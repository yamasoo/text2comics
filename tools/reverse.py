"""N5 反推：完成的稿子 → 視覺聖經草稿（bible/drafts/）。

  python tools/reverse.py examples/sample_comic --dry-run            # 只印批次計畫（不呼叫模型、不寫檔）
  python tools/reverse.py E:\\comics\\作品                             # 全部章節：逐章抽取 → 累積 → 卡片草稿
  python tools/reverse.py E:\\comics\\作品 --upto 30 --json            # 只跑到第 30 章；stdout 只有一行 JSON
  python tools/reverse.py E:\\comics\\作品 --from E:\\novels\\正文      # 原著不在專案 source/ 時指定
  python tools/reverse.py E:\\comics\\作品 --force                     # 全部重做（累積檔從頭開始）
  python tools/reverse.py E:\\comics\\作品 --budget 65536              # 加大模型上下文預算（每批可容納更多章）

原著預設讀 <專案>/source/（chNNN.txt、第 N 章.md）。抽到的角色與地點寫進 bible/drafts/，
人看過按「採用」才會搬進 bible/characters|locations/。做完的章記在 build/reverse/accumulated.json，
下一次只補新的章（--force 全部重做，中斷過就從斷掉的批次接）。
用哪個模型：config.json 的 stage_providers.bible，或 --provider 指定。DeepSeek 要先設環境變數 DEEPSEEK_API_KEY。
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import bible, llm, project, reverse, settings  # noqa: E402

STAGE = "bible"             # config.json 的 stage_providers／reasoning 用的階段名稱（和視覺聖經同一組）
OUT_RESERVE = 8192          # 輸出（一批的 JSON）預留的 token


def show(event, out):
    """Reverser／Builder 的事件 → 一行進度。"""
    kind = event["kind"]
    if kind == "plan":
        if event["batches"]:
            print("批次計畫：%d 章、%d 批（已完成 %d 章，從第 %d 章開始）"
                  % (event["chapters"], event["batches"], event["skipped"], event["start"]), file=out, flush=True)
        else:
            print("批次計畫：沒有要跑的批次（已完成 %d 章）" % event["skipped"], file=out, flush=True)
    elif kind == "batch":
        print("  第 %d／%d 批：%s" % (event["index"], event["total"], event["label"]), file=out, flush=True)
    elif kind == "call":
        attempt = event["attempt"]
        print("    → 呼叫模型：%s %s%s" % (event["stage"], event["label"],
                                          "（第 %d 次回修）" % attempt if attempt else ""), file=out, flush=True)
    elif kind == "cached":
        print("    第 %s 章：原文沒變，沿用掃描結果" % event["label"], file=out, flush=True)
    elif kind == "scanned":
        print("    第 %s 章：角色 %d 位、地點 %d 個" % (event["label"], event["characters"], event["locations"]),
              file=out, flush=True)
    elif kind == "fix":
        print("    驗證沒過（%d 個問題），回給模型修：" % len(event["errors"]), file=out, flush=True)
        for error in event["errors"][:8]:
            print("      - %s" % error, file=out)
        if len(event["errors"]) > 8:
            print("      …還有 %d 個" % (len(event["errors"]) - 8), file=out)
    elif kind == "retry":
        print("    … 重試 %d：%s（等 %.0f 秒）" % (event["attempt"], event["error"], event["wait"]), file=out, flush=True)
    elif kind == "saved":
        print("    已存檔：%s" % event["path"], file=out, flush=True)
    elif kind == "drafted":
        print("    卡片草稿：%s" % event["path"], file=out, flush=True)
    elif kind == "stopped":
        print("  收到停止：這次先停在這裡（已處理 %d 章），下次從下一批接" % event["scanned"], file=out, flush=True)


def source_label(args, proj):
    return str(Path(args.source_from) if args.source_from else proj.root / "source")


def print_plan(sources, batches, where, budget, out):
    """--dry-run：把批次計畫印成人看的形式（章號、估算的 token）。"""
    by_no = {int(s["n"]): s for s in sources}
    print("原著：%s（%d 章）" % (where, len(sources)), file=out)
    print("分成 %d 批（每批最多 %d 章；上下文預算 %d、輸出預留 %d）"
          % (len(batches), reverse.MAX_PER_BATCH, budget, OUT_RESERVE), file=out)
    for index, nos in enumerate(batches, 1):
        tokens = sum(llm.estimate_tokens((by_no[n].get("text") or "")) for n in nos)
        span = ("第 %d～%d 章" % (min(nos), max(nos))) if len(nos) > 1 else ("第 %d 章" % nos[0])
        print("  第 %d 批：%s（%d 章，約 %d token）" % (index, span, len(nos), tokens), file=out)


def run(args):
    out = sys.stderr if args.json else sys.stdout      # --json 時 stdout 只留最後一行 JSON
    if args.upto is not None and args.upto < 1:
        raise reverse.ReverseError("--upto 要是 1 以上（收到 %d）" % args.upto)
    proj = project.Project(args.project)
    sources = bible.load_sources([args.source_from] if args.source_from else [], proj)
    upto = min(args.upto, max(int(s["n"]) for s in sources)) if args.upto else max(int(s["n"]) for s in sources)
    where = source_label(args, proj)

    if args.dry_run:                                   # 只排批次：不呼叫模型、不寫任何檔案
        batches = reverse.plan_batches(sources, upto=args.upto, budget=args.budget, out_reserve=OUT_RESERVE)
        print_plan(sources, batches, where, args.budget, out)
        print("（--dry-run 不呼叫模型；去掉 --dry-run 才會真的抽取）", file=out)
        return {"ok": True, "mode": "dry-run", "source": where, "chapters": len(sources), "upto": upto,
                "budget": args.budget, "out_reserve": OUT_RESERVE, "batches": batches}

    cfg = settings.load(root=ROOT)

    def prov_for(stage_key):
        return llm.find_provider(cfg, provider_id=args.provider, stage=stage_key)

    prov = prov_for(STAGE)
    print("抽取用的模型：%s（%s）" % (prov.get("name") or prov.get("id"), prov.get("model") or "預設"), file=out)
    rev = reverse.Reverser(proj, prov_for=prov_for, sources=sources, budget=args.budget, out_reserve=OUT_RESERVE,
                           force=args.force, on_event=lambda event: show(event, out))
    started = time.monotonic()
    result = rev.run(args.upto, min_chapters=args.min_chapters)
    print("跑完：第 1～%d 章，%d 章、%d 批（這次掃描 %d 章，跳過 %d 章）"
          % (upto, result["chapters"], result["batches"], result["scanned"], result["skipped"]), file=out)
    if result["drafts"]:
        print("  卡片草稿 %d 份：%s" % (len(result["drafts"]), "、".join(result["drafts"])), file=out)
        print("  （放在 %s；看過按「採用」才會進 bible/characters|locations）" % (proj.root / "bible" / "drafts"), file=out)
    else:
        print("  沒有新草稿（已完成的章都跳過了；要重做加 --force）", file=out)
    if result["rare"]:
        print("  跳過 %d 位只出現在少數章節的角色／地點：%s（目前規則：出現 2 章以上才建卡）"
              % (len(result["rare"]), "、".join(result["rare"])), file=out)
    print("  呼叫 %d 次，約 %d 個輸入／%d 個輸出 token，用時 %.0f 秒"
          % (rev.usage["calls"], rev.usage["prompt_tokens"], rev.usage["completion_tokens"],
             time.monotonic() - started), file=out)
    return {"ok": True, "mode": "reverse", "source": where, "upto": upto,
            "chapters": result["chapters"], "batches": result["batches"], "scanned": result["scanned"],
            "skipped": result["skipped"], "drafts": result["drafts"], "rare": result["rare"],
            "calls": rev.usage["calls"],
            "files": {"state": str(rev.state_path()), "accumulated": str(rev.accumulated_path()),
                      "batches": str(rev.dir() / "batches"), "drafts": str(proj.root / "bible" / "drafts")}}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="漫畫專案資料夾（有 project.yaml）")
    ap.add_argument("--upto", type=int, default=None, help="只跑到第幾章（預設全部）")
    ap.add_argument("--budget", type=int, default=32768, help="模型的上下文 token 預算（預設 32768）")
    ap.add_argument("--force", action="store_true", help="全部重做：重新掃描每一章、重寫草稿（累積檔從頭開始）")
    ap.add_argument("--from", dest="source_from", metavar="路徑",
                    help="原著資料夾或檔案；預設讀專案的 source/")
    ap.add_argument("--dry-run", action="store_true", help="只印批次計畫，不呼叫模型、不寫任何檔案")
    ap.add_argument("--min-chapters", type=int, default=None, help="至少出現幾章才成卡（預設 min(2, 可用章數)；1＝只出現一章的配角也成卡）")
    ap.add_argument("--provider", help="指定 provider id；預設依 stage_providers.bible／default_provider")
    ap.add_argument("--json", action="store_true", help="stdout 只印一行 JSON 摘要（進度訊息改走 stderr）")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    mode = "dry-run" if args.dry_run else "reverse"
    try:
        result = run(args)
    except (reverse.ReverseError, bible.BibleError, llm.LLMError, project.ProjectError, FileNotFoundError) as error:
        print("錯誤：%s" % error, file=sys.stderr)
        if args.json:
            print(json.dumps({"ok": False, "mode": mode, "error": str(error)}, ensure_ascii=False))
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
