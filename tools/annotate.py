"""N3 切對話：小說一章 → 場 → 旁白／對話／演出（scenes/chNNN.json）＋忠實度報告。

  python tools/annotate.py examples/sample_comic 1                              # 呼叫模型切對話
  python tools/annotate.py E:\\comics\\作品 3 --title 大夜班                    # 指定章名
  python tools/annotate.py E:\\comics\\作品 3 --force                          # 覆蓋已存在的 scenes/ch003.json
  python tools/annotate.py E:\\comics\\作品 3 --no-repair                      # 不做漏句修補
  python tools/annotate.py E:\\comics\\作品 3 --show-prompt                    # 只印提示詞（不呼叫模型、不寫檔）
  python tools/annotate.py E:\\comics\\作品 3 --check                          # 不呼叫模型：驗證 scenes 檔與能不能編譯
  python tools/annotate.py E:\\comics\\作品 3 --to-storyboard                  # 讀 scenes 檔轉分鏡，印頁數與格數
  python tools/annotate.py E:\\comics\\作品 3 --to-storyboard --write-storyboard   # 另存 storyboard/ch003.from_scenes.json
  python tools/annotate.py E:\\comics\\作品 3 --json                           # stdout 只有一行 JSON（給程式接）

原著放在 <專案>/source/chNNN.txt（或 .md）。已存在的 scenes 檔不會被覆蓋，要重做加 --force。
切對話用哪個模型：config.json 的 stage_providers.annotate，或 --provider 指定。
DeepSeek 要先設環境變數 DEEPSEEK_API_KEY；llama.cpp 要先啟動 llama-server。
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import adapt, annotate, llm, project, settings  # noqa: E402

STAGE = "annotate"          # config.json 的 stage_providers 用的階段名稱


def show(event, out):
    """Adapter 的事件 → 一行進度（呼叫模型、回修、重試、存檔）。"""
    kind = event["kind"]
    if kind == "call":
        attempt = event["attempt"]
        print("  → 呼叫模型：%s %s%s" % (event["stage"], event["label"],
                                        "（第 %d 次回修）" % attempt if attempt else ""), file=out, flush=True)
    elif kind == "fix":
        print("  驗證沒過（%d 個問題），回給模型修：" % len(event["errors"]), file=out, flush=True)
        for error in event["errors"][:8]:
            print("      - %s" % error, file=out)
        if len(event["errors"]) > 8:
            print("      …還有 %d 個" % (len(event["errors"]) - 8), file=out)
    elif kind == "retry":
        print("  … 重試 %d：%s（等 %.0f 秒）" % (event["attempt"], event["error"], event["wait"]),
              file=out, flush=True)
    elif kind == "saved":
        print("  已存檔：%s" % event["path"], file=out, flush=True)


def print_prompt(messages, out):
    """--show-prompt：把 system＋user 原樣印出來，回傳估算的 token 數。"""
    for message in messages:
        print("=" * 20, message["role"], "=" * 20, file=out)
        print(message["content"], file=out)
    print("=" * 50, file=out)
    tokens = llm.estimate_messages(messages)
    print("（約 %d token）" % tokens, file=out)
    return tokens


def modes(args):
    """這一次要做哪幾件事；--check 與 --to-storyboard 可以一起給。"""
    if args.show_prompt:
        return ["show-prompt"]
    if args.check or args.to_storyboard or args.write_storyboard:
        return [name for name, on in (("check", args.check),
                                      ("storyboard", args.to_storyboard or args.write_storyboard)) if on]
    return [STAGE]


def chapter_label(chapter, title):
    return "第 %d 章%s" % (chapter, "《%s》" % title if title else "")


def panel_count(board):
    return sum(len(page.get("panels") or []) for page in board["pages"])


def report_row(report):
    """忠實度報告 → --json 的固定鍵（dialogue_total 就是 fidelity 的 dialogue_lines）。"""
    return {"paragraphs": report["paragraphs"],
            "paragraphs_used": report["paragraphs_used"],
            "dialogue_total": report["dialogue_lines"],
            "dialogue_found": report["dialogue_found"],
            "source_quotes_kept": report["source_quotes_kept"],
            "repaired": report["repaired"]}


def print_report(report, title, out):
    total = report["paragraphs"] or 1
    print("  《%s》%d 場；原著 %d 段，用到 %d 段（覆蓋 %d%%）"
          % (title or "未命名", report["scenes"], report["paragraphs"], report["paragraphs_used"],
             round(100.0 * report["paragraphs_used"] / total)), file=out)
    print("  對話 %d 句，%d 句能在原著逐字找到；原著引號台詞 %d 句，%d 句保留；漏句修補 %d 行"
          % (report["dialogue_lines"], report["dialogue_found"],
             report["source_quotes"], report["source_quotes_kept"], report["repaired"]), file=out)


def read_scenes(proj, chapter, path):
    """讀 scenes/chNNN.json；沒有就給一句看得懂的訊息（不要丟 traceback）。"""
    doc = proj.load_scenes(chapter)
    if doc is None:
        raise annotate.AnnotateError("找不到切對話檔案：%s（先執行 python tools/annotate.py \"%s\" %d）"
                                     % (path, proj.root, chapter))
    if not isinstance(doc, dict):
        raise annotate.AnnotateError("%s：最外層要是物件 {title, scenes: [ … ]}" % path)
    return doc


def run_offline(args, proj, out):
    """--check／--to-storyboard：完全不呼叫模型。"""
    scenes_path = proj.scenes_path(args.chapter)
    scene_doc = read_scenes(proj, args.chapter, scenes_path)
    scenes = [scene for scene in (scene_doc.get("scenes") or []) if isinstance(scene, dict)]
    title = str(scene_doc.get("title") or "")
    paragraphs = annotate.split_paragraphs(proj.load_source(args.chapter))
    print("讀 %s：%s，%d 場" % (scenes_path, chapter_label(args.chapter, title), len(scenes)), file=out)

    issues, board, compile_error = [], None, None
    if args.check:
        issues = list(annotate.validate(scene_doc, proj, paragraphs))
    try:
        board = annotate.to_storyboard(proj, scene_doc)
    except annotate.AnnotateError as error:
        compile_error = str(error)

    if args.check:
        errors = [issue for issue in issues if issue.level == "error"]
        print("  validate：%s" % ("沒有問題" if not issues else
                                  "%d 個問題（error %d、warn %d）" % (len(issues), len(errors), len(issues) - len(errors))),
              file=out)
        for issue in issues:
            print("    - [%s] %s" % (issue.level, issue), file=out)
        if compile_error:
            print("  compile_chapter：失敗", file=out)
            print("    - [error] %s" % compile_error, file=out)
        else:
            print("  compile_chapter：通過（%d 頁、%d 格）" % (len(board["pages"]), panel_count(board)), file=out)

    if not args.check:
        if compile_error:
            raise annotate.AnnotateError(compile_error)
        print("  轉分鏡：%d 頁、%d 格" % (len(board["pages"]), panel_count(board)), file=out)

    written = None
    if args.write_storyboard and board is not None:     # 轉不出分鏡時（board 是 None）不寫檔
        written = proj.out_dir("storyboard") / ("ch%03d.from_scenes.json" % args.chapter)
        if written.exists() and not args.force:
            raise adapt.AdaptError("%s 已經存在。要覆蓋請加 --force" % written)
        written.write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("  已存檔：%s" % written, file=out)

    rows = [{"level": issue.level, "where": issue.where, "message": issue.message} for issue in issues]
    if compile_error:
        rows.append({"level": "error", "where": "", "message": compile_error})
    result = {"ok": not [row for row in rows if row["level"] == "error"], "mode": "+".join(modes(args)),
              "chapter": args.chapter, "scenes": len(scenes), "title": title}
    if args.check:
        result["issues"] = rows
    if args.to_storyboard or args.write_storyboard:
        result["pages"] = len(board["pages"]) if board is not None else None
        result["panels"] = panel_count(board) if board is not None else None
        result["storyboard"] = str(written) if written else None
    return result


def run(args):
    out = sys.stderr if args.json else sys.stdout      # --json 時 stdout 只留最後一行 JSON
    cfg = settings.load(root=ROOT)
    proj = project.Project(args.project)

    def prov_for(stage_key):
        return llm.find_provider(cfg, provider_id=args.provider, stage=stage_key)

    if args.show_prompt:
        messages, paragraphs = adapt.Adapter(proj, prov_for=prov_for).annotate_prompt(args.chapter, args.title)
        tokens = print_prompt(messages, out)
        print("原著 %d 段（%s）" % (len(paragraphs), proj.source_path(args.chapter)), file=out)
        return {"ok": True, "mode": "show-prompt", "chapter": args.chapter, "scenes": 0,
                "paragraphs": len(paragraphs), "tokens": tokens}

    if args.check or args.to_storyboard or args.write_storyboard:
        return run_offline(args, proj, out)

    prov = prov_for(STAGE)
    print("切對話的模型：%s（%s）" % (prov.get("name") or prov["id"], prov.get("model") or "預設"), file=out)
    adapter = adapt.Adapter(proj, prov_for=prov_for, on_event=lambda event: show(event, out))
    started = time.monotonic()
    scene_doc, report = adapter.run_annotate(args.chapter, args.title, args.force, repair=not args.no_repair)
    print_report(report, str(scene_doc.get("title") or args.title), out)
    print("  報告：%s" % (proj.root / "build" / "adapt" / ("ch%03d_scenes_fidelity.md" % args.chapter)), file=out)
    print("  呼叫 %d 次，約 %d 個輸入／%d 個輸出 token，用時 %.0f 秒"
          % (adapter.usage["calls"], adapter.usage["prompt_tokens"], adapter.usage["completion_tokens"],
             time.monotonic() - started), file=out)
    if adapter.warnings:
        print("  提醒（%d）：" % len(adapter.warnings), file=out)
        for warning in adapter.warnings[:20]:
            print("    - %s" % warning, file=out)
    return {"ok": True, "mode": STAGE, "chapter": args.chapter,
            "scenes": len([scene for scene in (scene_doc.get("scenes") or []) if isinstance(scene, dict)]),
            "title": str(scene_doc.get("title") or ""),
            "files": {"scenes": str(proj.scenes_path(args.chapter)),
                      "fidelity": str(proj.root / "build" / "adapt" / ("ch%03d_scenes_fidelity.md" % args.chapter))},
            "report": report_row(report)}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="漫畫專案資料夾（有 project.yaml）")
    ap.add_argument("chapter", type=int, help="章編號（1 → source/ch001.txt、scenes/ch001.json）")
    ap.add_argument("--provider", help="指定 provider id；預設依 stage_providers.annotate／default_provider")
    ap.add_argument("--title", default="", help="章名；不給就由模型沿用原著")
    ap.add_argument("--force", action="store_true", help="覆蓋已存在的 scenes／分鏡檔")
    ap.add_argument("--no-repair", action="store_true", help="不做漏句修補（保留模型原本的輸出）")
    ap.add_argument("--show-prompt", action="store_true", help="只印出提示詞（不呼叫模型、不寫任何檔案）")
    ap.add_argument("--check", action="store_true",
                    help="不呼叫模型：驗證 scenes/chNNN.json 並試著編譯（有問題時 exit code 1）")
    ap.add_argument("--to-storyboard", action="store_true", help="讀 scenes/chNNN.json 轉分鏡，印出頁數與格數")
    ap.add_argument("--write-storyboard", action="store_true",
                    help="（--to-storyboard）另存 storyboard/chNNN.from_scenes.json")
    ap.add_argument("--json", action="store_true", help="stdout 只印一行 JSON 摘要（進度訊息改走 stderr）")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        result = run(args)
    except (annotate.AnnotateError, adapt.AdaptError, llm.LLMError, project.ProjectError, OSError) as error:
        print("錯誤：%s" % error, file=sys.stderr)
        if args.json:
            print(json.dumps({"ok": False, "mode": "+".join(modes(args)), "chapter": args.chapter,
                              "scenes": 0, "error": str(error)}, ensure_ascii=False))
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
