"""逐格出圖（S7）：compile_chapter 的工作 → ComfyUI → renders/chNNN/<格 id>_s<seed>.png。

命令列（tools/panels.py）與介面共用。停止靠 should_stop（回傳 True 時丟 Cancelled），進度靠 on_event：
    {"kind": "render"|"skip", "done", "total", "id", "seed", "file", "size"}
"""
from . import comfy, compose, workspace
from .compile import CompileError, compile_chapter
from .project import ProjectError


class RenderError(Exception):
    """給人看的錯誤訊息（寫出哪一格哪個 seed）。"""


class Cancelled(Exception):
    """使用者要求停止。"""


def presets(cfg):
    comfy_cfg = cfg.get("comfy") or {}
    return {k: v for k, v in (comfy_cfg.get("presets") or {}).items() if not k.startswith("_")}, comfy_cfg.get("default_preset") or None


def resolve_preset(cfg, name=None):
    """出圖預設：(名稱, 內容, 預設名稱)。和 tools/panels.py、bible.resolve_preset 同一套規則。"""
    table, default = presets(cfg)
    chosen = name or default
    if chosen and chosen not in table:
        raise RenderError("找不到出圖預設「%s」（config.json 的 comfy.presets 有：%s）" % (chosen, "、".join(table) or "無"))
    return chosen, table.get(chosen) if chosen else None, default


def chapter_jobs(project, chapter, page=None, panel=None, candidates=None):
    """要出圖的格：整章、某一頁，或某一格。"""
    try:
        storyboard = project.load_storyboard(chapter)
        overrides = {"candidates": candidates} if candidates else None
        jobs = compile_chapter(project, storyboard, only_page=page, overrides=overrides)
    except (ProjectError, CompileError) as error:
        raise RenderError(str(error))
    if panel:
        jobs = [j for j in jobs if j["id"] == panel]
        if not jobs:
            raise RenderError("分鏡裡沒有格「%s」" % panel)
    return jobs


def existing_seeds(project, chapter, panel_id, preset_name, default_preset):
    """這一格在同一個出圖預設下已經畫過的 seed。"""
    suffix = preset_name if preset_name and preset_name != default_preset else ""
    out = set()
    for name in compose.candidates(project, chapter, panel_id):
        info = workspace.candidate_info(name)
        if info["seed"] is not None and info["preset"] == suffix:
            out.add(info["seed"])
    return out


def plan_more(project, chapter, jobs, more, preset_name, default_preset):
    """「加畫 N 張」：每格各取 N 個還沒畫過的 seed（見 workspace.next_seeds），寫進 job["run_seeds"]。"""
    base = project.config.get("seed_base", 0)
    for job in jobs:
        have = existing_seeds(project, chapter, job["id"], preset_name, default_preset)
        job["run_seeds"] = workspace.next_seeds(job, more, have, base)
    return jobs


def render_jobs(project, chapter, jobs, cfg, preset_name=None, force=False, should_stop=None, on_event=None):
    """送 ComfyUI 出圖。job["run_seeds"] 有給就只畫那些（否則畫 job["seeds"]）。已存在的檔案跳過（force 就重畫）。
    回傳寫出的檔名清單。"""
    chosen, preset, default = resolve_preset(cfg, preset_name)
    comfy_cfg = cfg.get("comfy") or {}
    base = comfy_cfg.get("url") or "http://127.0.0.1:8188"
    workflow = comfy.config_workflow(cfg)
    folder = project.out_dir("renders", compose.chapter_name(chapter))
    build = project.out_dir("build", compose.chapter_name(chapter))
    todo = [(job, seed) for job in jobs for seed in (job["run_seeds"] if "run_seeds" in job else job["seeds"])]
    written = []
    stop = should_stop or (lambda: False)
    from .compile import save_job
    for job in jobs:
        save_job(build, job)
    for i, (job, seed) in enumerate(todo, 1):
        if stop():
            raise Cancelled()
        name = comfy.render_name(job["id"], seed, chosen, default)
        target = folder / name
        event = {"done": i, "total": len(todo), "id": job["id"], "seed": seed, "file": name, "size": (job["width"], job["height"])}
        if target.exists() and not force:
            if on_event:
                on_event(dict(event, kind="skip"))
            continue
        if on_event:
            on_event(dict(event, kind="start"))
        try:
            wf, out_id = comfy.prepare(workflow, job["prompt"], job["negative"], seed, job["width"], job["height"],
                                       models=comfy_cfg.get("models"), prefix="text2comics/%s" % compose.chapter_name(chapter), preset=preset)
            data = comfy.run(base, wf, out_id, should_stop=stop)
        except comfy.ComfyError as error:
            if stop():
                raise Cancelled()
            raise RenderError("%s（%s seed %d）" % (error, job["id"], seed))
        target.write_bytes(data)
        written.append(name)
        if on_event:
            on_event(dict(event, kind="render"))
    return written
