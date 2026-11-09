#!/usr/bin/env python3
"""視覺聖經（S6）：從小說抽角色與地點 → look_en 草稿 → 人工確認 → 定裝圖 → 服裝矩陣。

  # ① 抽取（DeepSeek 或 llama.cpp；要先設環境變數 DEEPSEEK_API_KEY）
  python tools/bible.py extract E:\\comics\\作品 --from E:\\novel\\作品\\正文 --notes E:\\novel\\作品\\設定
  python tools/bible.py scan    E:\\comics\\作品 --from E:\\novel\\作品\\正文          # 只掃描：每章誰出場、原文寫了什麼外觀
  python tools/bible.py draft   E:\\comics\\作品 --min-chapters 2                    # 依掃描結果寫卡片草稿 → bible/drafts/
  python tools/bible.py draft   E:\\comics\\作品 --only 阿海 --only 老周             # 指定人物（不受章數限制）
  python tools/bible.py scan ... --show-prompt                                      # 只印提示詞，不呼叫模型

  # ② 檢查與確認（人看過草稿、改過 look_en 之後）
  python tools/bible.py check  E:\\comics\\作品                                      # 規則檢查全部卡片（定案＋草稿）
  python tools/bible.py accept E:\\comics\\作品 chen_jiahe su_yan                   # 草稿 → 定案（先過檢查）
  python tools/bible.py accept E:\\comics\\作品 --all

  # ③ 定裝圖（需要 ComfyUI；只能在你的 Windows 電腦上做）
  python tools/bible.py sheet   E:\\comics\\作品                                     # 只編譯，寫到 build/bible/
  python tools/bible.py sheet   E:\\comics\\作品 --render --candidates 3             # 出圖 → renders/bible/，並拼出比較表
  python tools/bible.py sheet   E:\\comics\\作品 --only su_yan --outfit default --views full,bust --render
  python tools/bible.py contact E:\\comics\\作品                                     # 重拼比較表 → build/bible/contact_*.jpg
  python tools/bible.py pick    E:\\comics\\作品 ref_c_su_yan_default_full_s123.png  # 選定一張，記進 bible/picks.json

  # ④ 服裝矩陣與現況
  python tools/bible.py status E:\\comics\\作品                                      # 寫 build/bible/matrix.md 並印出摘要

各階段用哪個模型：config.json 的 stage_providers.bible（沒填就用 default_provider），或 --provider 指定。
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import bible, llm, project as projmod, settings  # noqa: E402
from t2c.compile import CompileError  # noqa: E402


def parse_chapters(text):
    """'1-3,5' → {1, 2, 3, 5}"""
    out = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out |= set(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def show(event):
    kind = event["kind"]
    if kind == "call":
        print("  → 呼叫模型：%s %s%s" % (event["stage"], event["label"], "（第 %d 次回修）" % event["attempt"] if event["attempt"] else ""), flush=True)
    elif kind == "fix":
        print("  ✗ 驗證沒過（%d 個問題），回給模型修：" % len(event["errors"]), flush=True)
        for e in event["errors"][:8]:
            print("      - %s" % e)
        if len(event["errors"]) > 8:
            print("      …還有 %d 個" % (len(event["errors"]) - 8))
    elif kind == "retry":
        print("  … 重試 %d：%s（等 %.0f 秒）" % (event["attempt"], event["error"], event["wait"]), flush=True)
    elif kind == "cached":
        print("  ○ %s 已掃描過（原文沒變），沿用" % event["label"], flush=True)
    elif kind == "scanned":
        print("  ✓ %s：%d 個角色、%d 個地點" % (event["label"], event["characters"], event["locations"]), flush=True)
    elif kind == "drafted":
        print("  ✓ %s → %s" % (event["label"], event["path"]), flush=True)
    elif kind == "render":
        print("  [%d/%d] %s（%d×%d）" % (event["done"], event["total"], event["file"], *event["size"]), flush=True)
    elif kind == "skip":
        print("  [%d/%d] 略過（已存在）%s" % (event["done"], event["total"], event["file"]), flush=True)


def print_prompt(messages):
    for m in messages:
        print("=" * 20, m["role"], "=" * 20)
        print(m["content"])
    print("=" * 50)
    print("（約 %d token）" % llm.estimate_messages(messages))


def make_builder(args, proj):
    cfg = settings.load(args.config, root=ROOT)
    return bible.Builder(proj, prov_for=lambda key: llm.find_provider(cfg, provider_id=args.provider, stage=key),
                         on_event=show, max_fix=args.max_fix,
                         on_delta=(lambda t: print(t, end="", flush=True)) if getattr(args, "stream", False) else None), cfg


def do_scan(args, proj, builder):
    sources = bible.load_sources(args.sources, proj)
    only = parse_chapters(args.chapters) if args.chapters else None
    if only:
        sources_sel = [s for s in sources if s["n"] in only]
        if not sources_sel:
            raise bible.BibleError("沒有第 %s 章（有：%s）" % (args.chapters, "、".join(str(s["n"]) for s in sources)))
    if args.show_prompt:
        first = next(s for s in sources if not only or s["n"] in only)
        print_prompt(builder.scan_prompt(first))
        return None
    print("① 掃描 %d 章（模型：%s）" % (len(sources), builder._prov_for("bible").get("name") or builder._prov_for("bible")["id"]))
    entities = builder.scan(sources, force=args.force, only=only, inputs=[str(Path(s).resolve()) for s in args.sources],
                            notes_inputs=[str(Path(n).resolve()) for n in args.notes or []])
    print("   角色 %d、地點 %d（合併自各章）；只被提到沒出場：%s" % (len(entities["characters"]), len(entities["locations"]),
                                                      "、".join(entities["mentioned_only"]) or "無"))
    for e in entities["characters"]:
        mark = "（已有卡片 %s）" % e["known"] if e.get("known") else ""
        print("   · %s：出現 %d 章%s" % (e["name"], len(e["chapters"]), mark))
    return entities


def do_draft(args, proj, builder):
    notes_inputs = args.notes
    if not notes_inputs:
        try:
            notes_inputs = builder.load_entities().get("notes") or []
        except bible.BibleError:
            notes_inputs = []
    notes = bible.load_notes(notes_inputs)
    if args.show_prompt:
        entities = builder.load_entities()
        chosen, _, _ = builder.select(entities, args.only, args.min_chapters)
        if not chosen:
            raise bible.BibleError("沒有符合條件的角色或地點可以成卡")
        kind, entity = chosen[0]
        print_prompt(builder.card_prompt(kind, entity, notes))
        return
    print("② 成卡（設定檔 %d 份）" % len(notes))
    report = builder.draft(only=args.only, min_chapters=args.min_chapters, notes=notes, force=args.force)
    print("   草稿 %d 份 → %s" % (len(report["drafted"]), proj.root / "bible" / "drafts"))
    if report["known"]:
        print("   已有定案卡片，略過：%s" % "、".join(report["known"]))
    if report["has_draft"]:
        print("   已有草稿，略過（要重做加 --force）：%s" % "、".join(report["has_draft"]))
    if report["rare"]:
        print("   只出現 %d 章以下，略過（要成卡用 --only 名字，或調 --min-chapters）：%s" % (args.min_chapters - 1, "、".join(report["rare"])))
    if report["drafted"]:
        print("   下一步：打開草稿，看「待確認」清單，改 look_en；再 python tools/bible.py accept <專案> <id>")


def cmd_check(args, proj):
    rows = bible.lint(proj)
    bad = 0
    for kind, path, issues in rows:
        errs = [i for i in issues if i.level == "error"]
        mark = "✗" if errs else ("⚠" if issues else "✓")
        print("%s %s %s" % (mark, kind, path.relative_to(proj.root).as_posix()))
        for i in issues:
            print("    %s %s" % ("錯誤" if i.level == "error" else "提醒", i.message))
        bad += bool(errs)
    print("共 %d 份卡片，%d 份有錯誤" % (len(rows), bad))
    return 1 if bad else 0


def cmd_accept(args, proj):
    names = ["*"] if args.all else args.names
    if not names:
        print("錯誤：請指定要確認的 id，或加 --all", file=sys.stderr)
        return 2
    for kind, cid, path in bible.accept(proj, names, force=args.force):
        print("✔ %s %s → %s" % (kind, cid, path.relative_to(proj.root).as_posix()))
    return 0


def cmd_sheet(args, proj):
    views = [v.strip() for v in args.views.split(",") if v.strip()]
    kinds = tuple(k for k, flag in (("character", not args.locations_only), ("location", not args.characters_only)) if flag)
    jobs, manifest = bible.sheet_jobs(proj, ids=args.only, outfits=args.outfit, views=views, kinds=kinds,
                                      candidates=args.candidates, megapixels=args.megapixels)
    bible.save_sheet_jobs(proj, jobs, manifest)
    print("已編譯 %d 張定裝圖（%d 個角色視角、%d 個地點）→ %s" % (
        len(jobs), sum(1 for m in manifest.values() if m["kind"] == "character"), sum(1 for m in manifest.values() if m["kind"] == "location"),
        proj.root / "build" / "bible"))
    if not args.render:
        return 0
    cfg = settings.load(args.config, root=ROOT)
    chosen, preset, _ = bible.resolve_preset(cfg, args.preset)
    if chosen:
        print("出圖預設：%s%s" % (chosen, "（LoRA %s）" % preset["lora"] if preset and preset.get("lora") else ""))
    written = bible.render_sheets(proj, jobs, manifest, cfg, preset_name=args.preset, force=args.force, on_event=show,
                                  only_seeds=set(args.seed or []))
    print("完成：新出 %d 張 → %s" % (len(written), bible.renders_dir(proj)))
    return cmd_contact(argparse.Namespace(ids=args.only or []), proj)


def cmd_contact(args, proj):
    made = 0
    for kind, cards in (("character", proj.characters), ("location", proj.locations)):
        for cid in cards:
            if args.ids and cid not in args.ids:
                continue
            path = bible.contact_sheet(proj, kind, cid)
            if path:
                made += 1
                print("  比較表：%s" % path.relative_to(proj.root).as_posix())
    if not made:
        print("沒有定裝圖可以拼（先 sheet --render）")
    else:
        print("看完請用 pick 選定：python tools/bible.py pick <專案> <檔名>（檔名在比較表每張圖的下方有 服裝/視角 與 seed，檔案在 renders/bible/）")
    return 0


def cmd_pick(args, proj):
    kind, cid, outfit, view = bible.pick(proj, args.image, args.id, args.outfit)
    print("✔ 已選定：%s %s%s（%s）" % ("角色" if kind == "character" else "地點", cid, " 的服裝 " + outfit if outfit else "", view))
    return 0


def cmd_status(args, proj):
    st = bible.status(proj)
    text = bible.matrix_markdown(st)
    out = proj.out_dir("build", "bible") / "matrix.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print("（已寫入 %s）" % out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, llm_opts=False):
        p.add_argument("project", help="漫畫專案資料夾（有 project.yaml）")
        p.add_argument("--config", help="設定檔路徑；預設 config.json")
        if llm_opts:
            p.add_argument("--provider", help="指定 provider id；預設依 stage_providers.bible／default_provider")
            p.add_argument("--max-fix", type=int, default=3, help="驗證沒過時最多回修幾次（預設 3）")
            p.add_argument("--show-prompt", action="store_true", help="只印出提示詞（不呼叫模型、不需要金鑰）")
            p.add_argument("--stream", action="store_true", help="即時顯示模型輸出（除錯用）")
        return p

    def scan_opts(p):
        p.add_argument("--from", dest="sources", action="append", default=[], metavar="路徑", help="小說章節的資料夾或檔案（可重複）；省略就讀專案的 source/")
        p.add_argument("--notes", action="append", metavar="路徑", help="作者的設定檔資料夾或檔案（可重複）；成卡時優先參考")
        p.add_argument("--chapters", help="只掃這些章，例如 1-3,5（其餘沿用已有的掃描結果）")
        p.add_argument("--force", action="store_true", help="掃描：忽略快取全部重掃；成卡：覆蓋已有的草稿")

    def draft_opts(p):
        p.add_argument("--only", action="append", metavar="名字", help="只替這個人物或地點成卡（名字或別名；可重複）；不受章數限制")
        p.add_argument("--min-chapters", type=int, default=2, help="至少出現幾章才成卡（預設 2，擋掉只出現一次的路人）")

    p = common(sub.add_parser("extract", help="掃描＋成卡"), True)
    scan_opts(p)
    draft_opts(p)
    p = common(sub.add_parser("scan", help="① 掃描原著"), True)
    scan_opts(p)
    p = common(sub.add_parser("draft", help="② 依掃描結果寫卡片草稿"), True)
    p.add_argument("--notes", action="append", metavar="路徑", help="作者的設定檔（省略就用 scan 時記下的）")
    p.add_argument("--force", action="store_true", help="覆蓋已有的草稿")
    draft_opts(p)
    common(sub.add_parser("check", help="規則檢查全部卡片"))
    p = common(sub.add_parser("accept", help="草稿 → 定案"))
    p.add_argument("names", nargs="*", help="id 或名字")
    p.add_argument("--all", action="store_true", help="全部草稿")
    p.add_argument("--force", action="store_true", help="覆蓋已有的定案卡片（之後每一格的外觀都會變）")
    p = common(sub.add_parser("sheet", help="③ 定裝圖"))
    p.add_argument("--only", action="append", metavar="id", help="只做這個角色或地點（id 或名字；可重複）")
    p.add_argument("--outfit", action="append", metavar="服裝id", help="只做這套服裝（可重複）")
    p.add_argument("--views", default="full", help="角色視角，逗號分隔：full（全身）、bust（胸像）；預設 full")
    p.add_argument("--characters-only", action="store_true", help="不做地點")
    p.add_argument("--locations-only", action="store_true", help="不做角色")
    p.add_argument("--candidates", type=int, help="每張幾個 seed（覆蓋 project.yaml）")
    p.add_argument("--megapixels", type=float, help="生圖像素（百萬；覆蓋 project.yaml）")
    p.add_argument("--render", action="store_true", help="送 ComfyUI 出圖")
    p.add_argument("--preset", help="出圖預設名稱（config.json 的 comfy.presets）")
    p.add_argument("--seed", type=int, action="append", help="只畫這個 seed（可重複）")
    p.add_argument("--force", action="store_true", help="已經有的圖也重畫")
    p = common(sub.add_parser("contact", help="重拼比較表"))
    p.add_argument("ids", nargs="*", help="角色或地點 id；省略就全部")
    p = common(sub.add_parser("pick", help="選定一張定裝圖"))
    p.add_argument("image", help="renders/bible/ 裡的檔名")
    p.add_argument("--id", help="角色或地點 id（用來防呆）")
    p.add_argument("--outfit", help="服裝 id（用來防呆）")
    common(sub.add_parser("status", help="④ 服裝矩陣與現況"))
    args = ap.parse_args(argv)

    try:
        proj = projmod.Project(args.project)
        if args.cmd in ("scan", "draft", "extract"):
            builder, _ = make_builder(args, proj)
            t0 = time.monotonic()
            if args.cmd in ("scan", "extract"):
                if do_scan(args, proj, builder) is None and args.show_prompt:
                    return 0
            if args.cmd in ("draft", "extract"):
                do_draft(args, proj, builder)
                if args.show_prompt:
                    return 0
            print("完成：呼叫 %d 次，約 %d 個輸入／%d 個輸出 token，用時 %.0f 秒" % (builder.usage["calls"], builder.usage["prompt_tokens"],
                                                                      builder.usage["completion_tokens"], time.monotonic() - t0))
            if builder.warnings:
                print("提醒（%d）：" % len(builder.warnings))
                for w in builder.warnings[:20]:
                    print("  - %s" % w)
            return 0
        return {"check": cmd_check, "accept": cmd_accept, "sheet": cmd_sheet, "contact": cmd_contact, "pick": cmd_pick, "status": cmd_status}[args.cmd](args, proj)
    except llm.Cancelled:
        print("已取消")
        return 130
    except (bible.BibleError, llm.LLMError, projmod.ProjectError, CompileError) as error:
        print("✗ %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
