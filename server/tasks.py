"""背景任務：LLM 三階段、出圖、輸出頁面、整章批次、視覺聖經的抽取與定裝圖。

每個任務函式的第一個參數是 fekit 的 Job；停止靠 job.stopping／job.checkpoint()。
任務的 result 帶 {"text", "refresh", "project", "chapter"}，頁面用來決定要不要重新載入（docs/05_介面設計.md 第 6 節）。
VRAM 排程（第 4 節）：呼叫本機 LLM 前請 ComfyUI 卸下模型；出圖前若本機 LLM 還在執行就暫停詢問。
"""
import shutil

from fastapi import APIRouter, Body

from fekit import ApiError, JobError, JobStopped

from t2c import adapt, bible, comfy, compose, gpu, layout, letter, llm, render, reverse, stale, workspace
from t2c.compile import CompileError
from t2c.project import ProjectError

from .common import CORE_ERRORS, body_project, chapter, config, runner
from .common import project as open_project

router = APIRouter()

STAGE_LABEL = {"annotate": "切對話", "plan": "改編規劃", "script": "劇本", "storyboard": "分鏡", "scan": "掃描", "card": "成卡"}
STAGES = ("annotate", "plan", "script", "storyboard", "render", "pages")   # 批次依這個順序跑
LLM_STAGES = ("annotate", "plan", "script", "storyboard")
STAGE_KEY = {"annotate": "annotate", "plan": "adapt", "script": "script", "storyboard": "storyboard"}


# ---------------------------------------------------------------------------
# 共用
# ---------------------------------------------------------------------------
class Reporter:
    """核心的 on_event／on_delta → 任務面板（模型輸出一段一個區塊，回修與重試寫進日誌）。"""

    def __init__(self, job):
        self.job, self.seg, self.count, self.streaming = job, None, 0, False

    def close(self):
        if self.seg:
            self.job.end(self.seg)
            self.seg = None

    def delta(self, text):
        if self.seg:
            if not self.streaming:
                self.streaming = True
                self.job.set(phase="streaming")
            self.job.write(self.seg, text)

    def event(self, ev):
        job, kind = self.job, ev.get("kind")
        if kind == "call":
            self.close()
            self.count += 1
            self.seg = "m%d" % self.count
            label = "%s %s%s" % (STAGE_LABEL.get(ev.get("stage"), ev.get("stage")), ev.get("label", ""),
                                 "（第 %d 次回修）" % ev["attempt"] if ev.get("attempt") else "")
            job.begin(self.seg, label)
            self.streaming = False
            job.set(phase="waiting", note=label)
        elif kind == "fix":
            self.close()
            errs = ev.get("errors") or []
            job.say("驗證沒過（%d 個問題），回給模型修：" % len(errs), "warn")
            for e in errs[:8]:
                job.say("  - %s" % e, "warn")
            if len(errs) > 8:
                job.say("  …還有 %d 個" % (len(errs) - 8), "warn")
        elif kind == "retry":
            job.say("重試 %d：%s（等 %.0f 秒）" % (ev["attempt"], ev["error"], ev["wait"]), "warn")
        elif kind == "page":
            self.close()
            job.say("✓ %s 第 %d 頁通過" % (STAGE_LABEL.get(ev["stage"], ev["stage"]), ev["page"]))
        elif kind == "saved":
            self.close()
            job.say("已存檔：%s" % ev["path"])
        elif kind == "cached":
            job.say("○ %s 已掃描過（原文沒變），沿用" % ev["label"], "dim")
        elif kind == "scanned":
            self.close()
            job.say("✓ %s：%d 個角色、%d 個地點" % (ev["label"], ev["characters"], ev["locations"]))
        elif kind == "drafted":
            self.close()
            job.say("✓ %s → %s" % (ev["label"], ev["path"]))


def _fail(error):
    raise JobError(str(error))


def _stopped_or(job, error):
    """核心收到停止要求時丟的 Cancelled → JobStopped；其他錯誤 → JobError。"""
    if job.stopping:
        raise JobStopped()
    _fail(error)


def free_for_llm(job, cfg, stage_keys):
    """要用本機 LLM：先請 ComfyUI 卸下模型。"""
    local = [p for p in (gpu.stage_provider(cfg, k) for k in stage_keys) if p and gpu.is_local(p)]
    if not local:
        return
    if gpu.comfy_free((cfg.get("comfy") or {}).get("url") or "http://127.0.0.1:8188"):
        job.say("已請 ComfyUI 卸下模型，讓出 VRAM 給本機 LLM（%s）" % "、".join(p.get("name") or p["id"] for p in local))


def wait_llm_released(job, cfg):
    """出圖前：本機 LLM 還在執行就暫停詢問（llama-server 沒有通用的卸載 API）。"""
    running = gpu.running_local_llms(cfg)
    while running:
        names = "、".join(p.get("name") or p.get("id") for p in running)
        job.set(phase="waiting", note="等待釋放 VRAM")
        answer = job.ask("本機 LLM（%s）還在執行，可能佔著 VRAM；和 ComfyUI 同時用 GPU 會很慢甚至記憶體不足。\n"
                         "請先關掉 llama-server（或卸載模型），再按「已關閉，繼續」。" % names,
                         options=[("retry", "已關閉，繼續"), ("anyway", "照樣出圖"), ("stop", "停止")], allow_text=False)
        if answer == "stop":
            raise JobStopped()
        if answer == "anyway":
            job.say("本機 LLM 仍在執行，照樣出圖", "warn")
            return
        running = gpu.running_local_llms(cfg)
        if running:
            job.say("還偵測得到 %s" % "、".join(p.get("name") or p.get("id") for p in running), "warn")


def _result(text, proj, n=None, refresh=()):
    return {"text": text, "project": str(proj.root), "chapter": n, "refresh": list(refresh)}


# ---------------------------------------------------------------------------
# 文字端（S5）
# ---------------------------------------------------------------------------
def run_adapt(job, proj, n, stage, cfg, want_pages=None, title="", only_pages=None, force=False, reporter=None):
    """跑一個 LLM 階段。回傳摘要文字。"""
    rep = reporter or Reporter(job)
    ad = adapt.Adapter(proj, prov_for=lambda key: llm.find_provider(cfg, stage=key), should_stop=lambda: job.stopping,
                       on_event=rep.event, on_delta=rep.delta)
    prov = llm.find_provider(cfg, stage=STAGE_KEY[stage])
    job.say("%s：模型 %s（%s）" % (STAGE_LABEL[stage], prov.get("name") or prov["id"], prov.get("model") or "預設"))
    try:
        if stage == "annotate":
            _, report = ad.run_annotate(n, title, force)
            text = ("切對話：段落 %d／%d（%d%%）、對話逐字 %d／%d、引號台詞 %d／%d"
                    % (report["paragraphs_used"], report["paragraphs"],
                       round(100.0 * report["paragraphs_used"] / (report["paragraphs"] or 1)),
                       report["dialogue_found"], report["dialogue_lines"],
                       report["source_quotes_kept"], report["source_quotes"]))
        elif stage == "plan":
            plan = ad.run_plan(n, want_pages, title, force)
            text = "規劃《%s》%d 頁；聖經缺少的人物：%s" % (plan["title"], len(plan["pages"]), "、".join(plan["unlisted_characters"]) or "無")
        elif stage == "script":
            _, report = ad.run_script(n, only_pages, force)
            text = "劇本：台詞 %d 句，%d 句能在原著找到；原著引號內台詞 %d 句，%d 句進了劇本" % (
                report["dialogue_lines"], report["dialogue_found"], report["source_quotes"], report["source_quotes_kept"])
        else:
            board = ad.run_storyboard(n, only_pages, force)
            text = "分鏡 %d 頁，已通過編譯檢查" % len(board["pages"])
    except llm.Cancelled:
        rep.close()
        job.checkpoint()
        raise JobStopped()
    except (adapt.AdaptError, llm.LLMError, ProjectError, CompileError) as error:
        rep.close()
        _fail(error)
    rep.close()
    for w in ad.warnings[:20]:
        job.say("提醒：%s" % w, "warn")
    if len(ad.warnings) > 20:
        job.say("…還有 %d 則提醒" % (len(ad.warnings) - 20), "warn")
    u = ad.usage
    job.say("呼叫 %d 次，約 %d 個輸入／%d 個輸出 token" % (u["calls"], u["prompt_tokens"], u["completion_tokens"]), "dim")
    return text


def adapt_task(job, root, n, stage, want_pages=None, title="", page=None, force=False):
    proj = workspace.open_project(root)
    cfg = config_or_fail()
    free_for_llm(job, cfg, [STAGE_KEY[stage]])
    text = run_adapt(job, proj, n, stage, cfg, want_pages, title, [page] if page else None, force)
    return _result(text, proj, n, [stage])


def config_or_fail():
    try:
        return config()
    except ApiError as error:
        raise JobError(error.message)


@router.post("/api/task/adapt")
def start_adapt(body: dict = Body(...)):
    proj, n = body_project(body), chapter(body.get("chapter"))
    stage = body.get("stage")
    if stage not in LLM_STAGES:
        raise ApiError(400, "stage 要是 %s 其中之一" % "、".join(LLM_STAGES), "bad_stage")
    pages = int(body["pages"]) if body.get("pages") else None
    page = int(body["page"]) if body.get("page") else None
    title = "第 %d 章：%s%s" % (n, STAGE_LABEL[stage], "（第 %d 頁）" % page if page else "")
    return runner.start(adapt_task, str(proj.root), n, stage, pages, str(body.get("title") or ""), page, bool(body.get("force")),
                        kind="adapt", title=title).summary()


# ---------------------------------------------------------------------------
# 反推設定（N5／步驟 4）：整本掃描 → 成卡草稿，斷點續跑
# ---------------------------------------------------------------------------
def reverse_task(job, root, upto=None, min_chapters=None, budget=None, force=False):
    proj = workspace.open_project(root)
    cfg = config_or_fail()
    free_for_llm(job, cfg, ["bible"])
    rep = Reporter(job)

    def on_event(ev):
        kind = ev.get("kind")
        if kind == "plan":
            job.say("① 計畫：%d 章、%d 批%s" % (ev.get("chapters") or 0, ev.get("batches") or 0,
                                         "（已完成 %d 章，這次跳過）" % ev["skipped"] if ev.get("skipped") else ""))
            job.set(progress=(0, max(1, ev.get("batches") or 1)))
        elif kind == "batch":
            job.set(phase="streaming", progress=(ev.get("index", 0) - 1, max(1, ev.get("total") or 1)),
                    note="掃描 %s" % (ev.get("label") or ""))
            job.say("② 第 %d／%d 批：%s" % (ev.get("index") or 0, ev.get("total") or 0, ev.get("label") or ""))
        elif kind == "saved" and ev.get("chapters"):
            job.say("　存檔：%s" % ev.get("path"), "dim")
        elif kind == "drafts":
            rare = ev.get("rare") or []
            job.say("③ 草稿 %d 張%s" % (ev.get("total") or 0, "；出現章數太少沒成卡：%s" % "、".join(rare) if rare else ""))
        elif kind == "stopped":
            job.say("已停止（這次掃描 %d 章）" % (ev.get("scanned") or 0), "warn")
        else:
            rep.event(ev)                    # call／delta／fix 由 Reporter 顯示
        job.checkpoint()

    rev = reverse.Reverser(proj, prov_for=lambda key: llm.find_provider(cfg, stage=key),
                           should_stop=lambda: job.stopping, on_event=on_event, budget=budget or 32768,
                           force=force, min_chapters=min_chapters)
    try:
        result = rev.run(upto)
    except llm.Cancelled:
        rep.close()
        job.checkpoint()
        raise JobStopped()
    except (reverse.ReverseError, bible.BibleError, llm.LLMError, ProjectError) as error:
        rep.close()
        _fail(error)
    rep.close()
    u = rev.usage
    text = "反推：掃描 %d 章、跳過 %d 章、草稿 %d 張%s" % (
        result["scanned"], result["skipped"], len(result["drafts"]),
        "；沒成卡：%s" % "、".join(result["rare"]) if result.get("rare") else "")
    job.say("呼叫 %d 次，約 %d 個輸入／%d 個輸出 token" % (u["calls"], u["prompt_tokens"], u["completion_tokens"]), "dim")
    return {"text": text, "project": str(proj.root), "refresh": ["bible"], "reverse": result}


@router.post("/api/task/reverse")
def start_reverse(body: dict = Body(...)):
    proj = body_project(body)
    upto = int(body["upto"]) if body.get("upto") else None
    min_chapters = int(body["min_chapters"]) if body.get("min_chapters") else None
    budget = int(body["budget"]) if body.get("budget") else None
    return runner.start(reverse_task, str(proj.root), upto, min_chapters, budget, bool(body.get("force")),
                        kind="bible", title="反推設定：掃描原著＋成卡草稿").summary()


@router.get("/api/bible/reverse")
def reverse_state(project: str = ""):
    """反推的進度（build/reverse/state.json）與目前累積到的章數、草稿數。"""
    proj = open_project(project)
    folder = proj.root / "build" / "reverse"
    state, accumulated = {}, {}
    try:
        import json as _json
        if (folder / "state.json").is_file():
            state = _json.loads((folder / "state.json").read_text(encoding="utf-8"))
        if (folder / "accumulated.json").is_file():
            accumulated = _json.loads((folder / "accumulated.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state, accumulated = {}, {}
    drafts = bible.list_drafts(proj)
    return {"state": state, "chapters": list(accumulated.get("chapters") or []),
            "batches": sorted(p.name for p in (folder / "batches").glob("*.json")) if (folder / "batches").is_dir() else [],
            "drafts": sorted(drafts), "folder": str(folder)}


# ---------------------------------------------------------------------------
# 出圖
# ---------------------------------------------------------------------------
def run_render(job, proj, n, cfg, jobs, preset=None, force=False, profile=None):
    """送 ComfyUI；每格一個 item、整體進度。回傳 (新出的張數, 略過的張數)。"""
    seeds_of = {j["id"]: (j["run_seeds"] if "run_seeds" in j else j["seeds"]) for j in jobs}
    for j in jobs:
        job.item(j["id"], label="%s（%d 張）" % (j["id"], len(seeds_of[j["id"]])), state="pending")
    counts = {"render": 0, "skip": 0}
    left = {pid: len(s) for pid, s in seeds_of.items()}

    def on_event(ev):
        kind = ev["kind"]
        if kind == "start":
            job.item(ev["id"], state="running")
            job.set(phase="streaming", note="%s seed %d（%d×%d）" % (ev["id"], ev["seed"], *ev["size"]))
            return
        counts[kind] = counts.get(kind, 0) + 1
        left[ev["id"]] -= 1
        job.set(progress=(ev["done"], ev["total"]))
        if kind == "skip":
            job.say("略過（已存在）%s" % ev["file"], "dim")
        else:
            job.say("✓ %s" % ev["file"])
        if left[ev["id"]] <= 0:
            job.item(ev["id"], state="done")

    total = sum(len(s) for s in seeds_of.values())
    job.set(progress=(0, total))
    try:
        render.render_jobs(proj, n, jobs, cfg, preset_name=preset, force=force, should_stop=lambda: job.stopping, on_event=on_event,
                           profile_name=profile)
    except render.Cancelled:
        raise JobStopped()
    except CORE_ERRORS as error:
        _stopped_or(job, error)
    for j in jobs:
        if not seeds_of[j["id"]]:
            job.item(j["id"], state="skipped")
    return counts["render"], counts["skip"]


def _backup_candidates(proj, n, jobs, preset, default_preset, profile, default_profile):
    """覆蓋前把會被蓋掉的候選圖複製到 build/render/backup/<章>/（build/ 不進版控；同名就覆蓋舊備份）。

    只備份這次真的要畫的 seed 所對應的檔名，其他預設／profile 的候選不動。回傳備份張數。
    """
    source_dir = compose.renders_dir(proj, n)
    if not source_dir.is_dir():
        return 0
    target_dir = proj.out_dir("build", "render", "backup", compose.chapter_name(n))
    saved = 0
    for job in jobs:
        for seed in (job["run_seeds"] if "run_seeds" in job else job["seeds"]):
            name = comfy.render_name(job["id"], seed, preset, default_preset, profile, default_profile)
            source = source_dir / name
            if source.is_file():
                shutil.copy2(source, target_dir / name)
                saved += 1
    return saved


def render_task(job, root, n, page=None, panel=None, more=0, seed=None, preset=None, force=None, profile=None, stale_only=False):
    """出圖。force=None 表示呼叫端沒指定：一般出圖維持原本的「已存在的候選不覆蓋」，
    只重畫過期格時預設覆蓋同一批 seed（卡片改了，這批圖就是要換成新的；picks 指到的檔名不變）。"""
    proj = workspace.open_project(root)
    cfg = config_or_fail()
    overwrite = bool(force)
    try:
        prof = render.resolve_profile(cfg, proj, profile)
        default_profile = comfy.default_profile_name(cfg)
        jobs = render.chapter_jobs(proj, n, page=page, panel=panel)
        if stale_only:                   # 只留過期的格（t2c/stale.py）
            wanted = {row["id"] for row in stale.chapter(proj, n)}
            jobs = [j for j in jobs if j["id"] in wanted]
        chosen, _, default = render.resolve_preset(cfg, preset, prof)
        explicit_add = bool(more) or seed is not None      # 呼叫端明確要加畫／指定 seed：照他的意思
        if more:                         # 加畫 N 張：新 seed、新檔名，舊的候選留著
            render.plan_more(proj, n, jobs, int(more), chosen, default, prof["name"], default_profile)
        elif seed is not None:
            for j in jobs:
                j["run_seeds"] = [int(seed)]
            overwrite = True
        if stale_only and force is None and not explicit_add:
            overwrite = True             # 只說 stale：用同一批 seed 覆蓋（舊圖先備份）
    except CORE_ERRORS as error:
        _fail(error)
    if stale_only and not jobs:
        job.say("沒有過期的格，不用重畫")
        return _result("沒有過期的格，不用重畫", proj, n, ["panels"])
    if stale_only and overwrite:
        saved = _backup_candidates(proj, n, jobs, chosen, default, prof["name"], default_profile)
        if saved:
            job.say("舊候選先備份：build/render/backup/%s/（%d 張）" % (compose.chapter_name(n), saved), "dim")
    job.say("出圖 profile：%s（%s）；出圖預設：%s" % (prof["name"], prof["kind"], chosen or "（workflow 預設）"))
    wait_llm_released(job, cfg)
    done, skipped = run_render(job, proj, n, cfg, jobs, chosen, overwrite, prof["name"])
    if stale_only and overwrite:
        return _result("重畫 %d 格（%d 張，舊候選備份在 build/render/backup/%s/）"
                       % (len(jobs), done, compose.chapter_name(n)), proj, n, ["panels"])
    return _result("新出 %d 張，略過 %d 張（已存在）" % (done, skipped), proj, n, ["panels"])


@router.post("/api/task/render")
def start_render(body: dict = Body(...)):
    proj, n = body_project(body), chapter(body.get("chapter"))
    page = int(body["page"]) if body.get("page") else None
    panel = str(body.get("panel") or "") or None
    more = max(0, min(int(body.get("more") or 0), 8))
    seed = int(body["seed"]) if body.get("seed") not in (None, "") else None
    stale_only = bool(body.get("stale"))
    force = None if body.get("force") is None else bool(body.get("force"))   # 沒指定就讓 render_task 自己決定
    what = panel or ("第 %d 頁" % page if page else "整章")
    title = "第 %d 章出圖：%s%s%s" % (n, what, "（只重畫過期的格）" if stale_only else "",
                                     "（加畫 %d 張）" % more if more else "（重畫 seed %d）" % seed if seed is not None else "")
    return runner.start(render_task, str(proj.root), n, page, panel, more, seed, body.get("preset") or None, force,
                        str(body.get("profile") or "") or None, stale_only, kind="render", title=title).summary()


# ---------------------------------------------------------------------------
# 輸出頁面
# ---------------------------------------------------------------------------
def run_pages(job, proj, n, cfg, page=None):
    """組版＋嵌字 → pages/chNNN/pNNN.png。回傳 (頁數, 警告)。"""
    try:
        storyboard = proj.load_storyboard(n)
        numbers = [int(p["page"]) for p in storyboard.get("pages") or [] if page is None or int(p["page"]) == int(page)]
        if not numbers:
            raise workspace.WorkspaceError("分鏡裡沒有第 %s 頁" % page)
        lettering = letter.Settings.from_config(cfg.get("lettering"))
        for note in lettering.notes:
            job.say(note, "dim")
        picks = compose.load_picks(proj, n)
        letters = letter.load_letters(proj, n)
        pages_data = proj.pages()
    except CORE_ERRORS as error:
        _fail(error)
    warnings = []
    job.set(progress=(0, len(numbers)))
    for i, no in enumerate(numbers, 1):
        job.checkpoint()
        job.set(note="第 %d 頁" % no)
        try:
            written, warns = compose.compose_chapter(proj, n, storyboard, pages_data, only_page=no, picks=picks,
                                                     lettering=lettering, letters=letters)
        except CORE_ERRORS as error:
            _fail(error)
        for w in warns:
            job.say("提醒：%s" % w, "warn")
        warnings += warns
        for _, path in written:
            job.say("第 %d 頁 → %s" % (no, path))
        job.set(progress=(i, len(numbers)))
    return len(numbers), warnings


def pages_task(job, root, n, page=None):
    proj = workspace.open_project(root)
    cfg = config_or_fail()
    count, warnings = run_pages(job, proj, n, cfg, page)
    return _result("輸出 %d 頁%s" % (count, "（%d 則提醒）" % len(warnings) if warnings else ""), proj, n, ["pages"])


@router.post("/api/task/pages")
def start_pages(body: dict = Body(...)):
    proj, n = body_project(body), chapter(body.get("chapter"))
    page = int(body["page"]) if body.get("page") else None
    return runner.start(pages_task, str(proj.root), n, page, kind="pages",
                        title="第 %d 章輸出頁面%s" % (n, "（第 %d 頁）" % page if page else "")).summary()


# ---------------------------------------------------------------------------
# 整章批次
# ---------------------------------------------------------------------------
BATCH_LABEL = {"annotate": "切對話", "plan": "改編規劃", "script": "劇本", "storyboard": "分鏡", "render": "出圖", "pages": "輸出頁面"}


def batch_task(job, root, n, stages, force=False, preset=None, want_pages=None, profile=None):
    """規劃 → 劇本 → 分鏡（LLM）→ 釋放 VRAM → 出圖 → 輸出頁面。已有的檔案跳過（force 時重做 LLM 階段；出圖永遠只補沒畫過的）。"""
    proj = workspace.open_project(root)
    cfg = config_or_fail()
    for stage in stages:
        job.item(stage, label=BATCH_LABEL[stage], state="pending")
    job.set(progress=(0, len(stages)))
    llm_todo = [s for s in stages if s in LLM_STAGES]
    paths = {"annotate": proj.scenes_path(n), "plan": proj.plan_path(n), "script": proj.script_path(n),
             "storyboard": proj.storyboard_path(n)}
    need_llm = [s for s in llm_todo if force or not paths[s].is_file()]
    if need_llm:
        free_for_llm(job, cfg, [STAGE_KEY[s] for s in need_llm])
    if llm_todo and "plan" in stages and proj.source_path(n) is None and not paths["plan"].is_file():
        raise JobError("第 %d 章還沒有原著（source/ch%03d.txt）" % (n, n))
    rep = Reporter(job)
    summary = []
    for index, stage in enumerate(stages, 1):
        job.checkpoint()
        job.item(stage, state="running")
        if stage in LLM_STAGES:
            if paths[stage].is_file() and not force:
                job.say("%s已存在，略過（要重做請勾「重做已有的」）" % BATCH_LABEL[stage], "dim")
                job.item(stage, state="skipped", note="已存在")
            else:
                text = run_adapt(job, proj, n, stage, cfg, want_pages if stage == "plan" else None, "", None, force, rep)
                summary.append(text)
                job.item(stage, state="done")
        elif stage == "render":
            try:
                prof = render.resolve_profile(cfg, proj, profile)
                default_profile = comfy.default_profile_name(cfg)
                jobs = render.chapter_jobs(proj, n)
                chosen, _, default = render.resolve_preset(cfg, preset, prof)
            except CORE_ERRORS as error:
                _fail(error)
            folder = compose.renders_dir(proj, n)
            if all((folder / comfy.render_name(j["id"], s, chosen, default, prof["name"], default_profile)).exists()
                   for j in jobs for s in j["seeds"]):
                job.say("每一格的候選圖都已經有了，略過出圖", "dim")
                job.item(stage, state="skipped", note="都已出圖")
            else:
                wait_llm_released(job, cfg)
                done, skipped = run_render(job, proj, n, cfg, jobs, chosen, False, prof["name"])
                summary.append("出圖：新出 %d 張，略過 %d 張" % (done, skipped))
                job.item(stage, state="done")
        elif stage == "pages":
            count, warnings = run_pages(job, proj, n, cfg)
            summary.append("輸出 %d 頁" % count)
            job.item(stage, state="done", note="%d 則提醒" % len(warnings) if warnings else "")
        job.set(progress=(index, len(stages)), note="")
    return _result("；".join(summary) or "全部階段都已經完成，沒有要做的", proj, n, list(stages))


@router.post("/api/task/batch")
def start_batch(body: dict = Body(...)):
    proj, n = body_project(body), chapter(body.get("chapter"))
    stages = [s for s in STAGES if s in (body.get("stages") or STAGES)]
    if not stages:
        raise ApiError(400, "至少要選一個階段", "bad_stage")
    pages = int(body["pages"]) if body.get("pages") else None
    return runner.start(batch_task, str(proj.root), n, stages, bool(body.get("force")), body.get("preset") or None, pages,
                        str(body.get("profile") or "") or None,
                        kind="batch", title="第 %d 章整章批次：%s" % (n, "→".join(BATCH_LABEL[s] for s in stages))).summary()


# ---------------------------------------------------------------------------
# 視覺聖經（S6）
# ---------------------------------------------------------------------------
def bible_extract_task(job, root, min_chapters=2, only=None, force=False, notes=None):
    proj = workspace.open_project(root)
    cfg = config_or_fail()
    free_for_llm(job, cfg, ["bible"])
    rep = Reporter(job)
    builder = bible.Builder(proj, prov_for=lambda key: llm.find_provider(cfg, stage=key), should_stop=lambda: job.stopping,
                            on_event=rep.event, on_delta=rep.delta)
    try:
        sources = bible.load_sources([], proj)
        job.say("① 掃描 %d 章" % len(sources))
        entities = builder.scan(sources, force=force, notes_inputs=notes or [])
        rep.close()
        job.say("角色 %d、地點 %d；只被提到沒出場：%s" % (len(entities["characters"]), len(entities["locations"]),
                                                "、".join(entities.get("mentioned_only") or []) or "無"))
        job.say("② 成卡")
        report = builder.draft(only=only or None, min_chapters=min_chapters, notes=bible.load_notes(notes or []), force=force)
    except llm.Cancelled:
        rep.close()
        raise JobStopped()
    except (bible.BibleError, llm.LLMError, ProjectError) as error:
        rep.close()
        _fail(error)
    rep.close()
    if report["known"]:
        job.say("已有定案卡片，略過：%s" % "、".join(report["known"]), "dim")
    if report["has_draft"]:
        job.say("已有草稿，略過（要重做請勾「覆蓋已有的草稿」）：%s" % "、".join(report["has_draft"]), "dim")
    if report["rare"]:
        job.say("出現不到 %d 章，略過：%s" % (min_chapters, "、".join(report["rare"])), "dim")
    return _result("草稿 %d 份，請到視覺聖經頁確認" % len(report["drafted"]), proj, None, ["bible"])


@router.post("/api/task/bible_extract")
def start_bible_extract(body: dict = Body(...)):
    proj = body_project(body)
    only = [str(x).strip() for x in body.get("only") or [] if str(x).strip()]
    notes = [str(x).strip() for x in body.get("notes") or [] if str(x).strip()]
    return runner.start(bible_extract_task, str(proj.root), max(1, int(body.get("min_chapters") or 2)), only,
                        bool(body.get("force")), notes, kind="bible", title="視覺聖經：掃描原著＋成卡").summary()


def bible_sheet_task(job, root, ids=None, views=("full",), candidates=None, preset=None, force=False, more=0, profile=None):
    proj = workspace.open_project(root)
    cfg = config_or_fail()
    try:
        prof = render.resolve_profile(cfg, proj, profile)
        default_profile = comfy.default_profile_name(cfg)
        jobs, manifest = bible.sheet_jobs(proj, ids=ids or None, views=tuple(views), candidates=candidates)
        chosen, _, default = bible.resolve_preset(cfg, preset, prof)
        if more:
            folder = bible.renders_dir(proj)
            want_profile = render.file_profile(prof["name"], default_profile)
            for j in jobs:
                have = set()
                for path in folder.glob(j["id"] + "_s*.png") if folder.is_dir() else []:
                    m = bible.RENDER_RE.match(path.name)
                    if m and m.group("job") == j["id"] and (m.group("preset") or "") == (chosen if chosen != default else "") \
                            and (m.group("profile") or "") == want_profile:
                        have.add(int(m.group("seed")))
                j["seeds"] = workspace.next_seeds(j, int(more), have, proj.config.get("seed_base", 0))
    except CORE_ERRORS as error:
        _fail(error)
    if not jobs:
        raise JobError("沒有定案的角色或地點可以出定裝圖（草稿要先確認入庫）")
    wait_llm_released(job, cfg)
    total = sum(len(j["seeds"]) for j in jobs)
    job.set(progress=(0, total))
    for j in jobs:
        job.item(j["id"], label=j["id"], state="pending")

    def on_event(ev):
        job.set(progress=(ev["done"], ev["total"]))
        pid = ev["file"].rsplit("_s", 1)[0]
        job.item(pid, state="done")
        job.say(("略過（已存在）%s" if ev["kind"] == "skip" else "✓ %s") % ev["file"], "dim" if ev["kind"] == "skip" else "info")

    try:
        written = bible.render_sheets(proj, jobs, manifest, cfg, preset_name=preset, force=force, profile_name=prof["name"],
                                      should_stop=lambda: job.stopping, on_event=on_event)
    except llm.Cancelled:
        raise JobStopped()
    except CORE_ERRORS as error:
        _stopped_or(job, error)
    return _result("定裝圖：新出 %d 張" % len(written), proj, None, ["bible"])


@router.post("/api/task/bible_sheet")
def start_bible_sheet(body: dict = Body(...)):
    proj = body_project(body)
    ids = [str(x) for x in body.get("ids") or [] if str(x).strip()]
    views = [v for v in (body.get("views") or ["full"]) if v in bible.VIEWS] or ["full"]
    candidates = int(body["candidates"]) if body.get("candidates") else None
    more = max(0, min(int(body.get("more") or 0), 8))
    title = "定裝圖：%s%s" % ("、".join(ids) if ids else "全部", "（加畫 %d 張）" % more if more else "")
    return runner.start(bible_sheet_task, str(proj.root), ids, views, candidates, body.get("preset") or None,
                        bool(body.get("force")), more, str(body.get("profile") or "") or None, kind="bible", title=title).summary()
