"""小說一章 → 改編規劃 → 漫畫劇本 → 分鏡 JSON（S5）。

  python tools/adapt.py examples/sample_comic 1                    # 三個階段全跑
  python tools/adapt.py E:\\comics\\作品 3 --stage plan --pages 6    # 只做規劃，指定 6 頁
  python tools/adapt.py E:\\comics\\作品 3 --stage script           # 依 plan/ch003.json 寫劇本（之後可以手改 script/ch003.md）
  python tools/adapt.py E:\\comics\\作品 3 --stage storyboard       # 依劇本（含你改過的）產生分鏡
  python tools/adapt.py E:\\comics\\作品 3 --stage script --page 4  # 只重寫第 4 頁，其他頁維持原樣
  python tools/adapt.py E:\\comics\\作品 3 --stage storyboard --show-prompt --page 1   # 只印提示詞，不呼叫模型

原著放在 <專案>/source/chNNN.txt（或 .md）。已存在的輸出不會被覆蓋，要重做加 --force。
各階段用哪個模型：config.json 的 stage_providers（adapt／script／storyboard），或 --provider 指定。
DeepSeek 要先設環境變數 DEEPSEEK_API_KEY；llama.cpp 要先啟動 llama-server。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from t2c import adapt, llm, project, settings  # noqa: E402


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
    elif kind == "page":
        print("  ✓ %s 第 %d 頁通過" % (event["stage"], event["page"]), flush=True)
    elif kind == "saved":
        print("  ✔ 已存檔：%s" % event["path"], flush=True)


def print_prompt(messages):
    for m in messages:
        print("=" * 20, m["role"], "=" * 20)
        print(m["content"])
    print("=" * 50)
    print("（約 %d token）" % llm.estimate_messages(messages))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="漫畫專案資料夾")
    ap.add_argument("chapter", type=int, help="章編號（1 → source/ch001.txt）")
    ap.add_argument("--stage", choices=("plan", "script", "storyboard", "all"), default="all")
    ap.add_argument("--pages", type=int, help="（plan）指定總頁數；不給就由模型決定")
    ap.add_argument("--title", default="", help="（plan）章名；不給就由模型沿用原著")
    ap.add_argument("--page", type=int, action="append", help="（script／storyboard）只做這一頁，可重複；其他頁維持原樣")
    ap.add_argument("--provider", help="指定 provider id；預設依 stage_providers／default_provider")
    ap.add_argument("--config", help="設定檔路徑；預設 config.json")
    ap.add_argument("--max-fix", type=int, default=3, help="驗證沒過時最多回修幾次（預設 3）")
    ap.add_argument("--force", action="store_true", help="覆蓋已存在的輸出")
    ap.add_argument("--show-prompt", action="store_true", help="只印出提示詞（不呼叫模型、不需要金鑰）")
    ap.add_argument("--stream", action="store_true", help="即時顯示模型輸出（除錯用）")
    args = ap.parse_args()

    cfg = settings.load(args.config)
    proj = project.Project(args.project)
    stages = ("plan", "script", "storyboard") if args.stage == "all" else (args.stage,)
    first = stages[0]

    def prov_for(stage_key):
        return llm.find_provider(cfg, provider_id=args.provider, stage=stage_key)

    ad = adapt.Adapter(proj, prov_for=prov_for, on_event=show, max_fix=args.max_fix,
                       on_delta=(lambda t: print(t, end="", flush=True)) if args.stream else None)
    try:
        if args.show_prompt:
            if first == "plan":
                print_prompt(ad.plan_prompt(args.chapter, args.pages, args.title))
            elif first == "script":
                print_prompt(ad.script_prompt(args.chapter, (args.page or [1])[0]))
            else:
                print_prompt(ad.storyboard_prompt(args.chapter, (args.page or [1])[0]))
            return
        for key in dict.fromkeys(adapt.STAGE_KEY.get(s, s) for s in stages):
            prov = prov_for(key)
            print("%s 階段的模型：%s（%s）" % (key, prov.get("name") or prov["id"], prov.get("model") or "預設"))
        t0 = time.monotonic()
        if "plan" in stages:
            print("① 改編規劃")
            plan = ad.run_plan(args.chapter, args.pages, args.title, args.force)
            print("   《%s》%d 頁；刪減 %d 項；聖經缺少的人物：%s" % (plan["title"], len(plan["pages"]), len(plan["omitted"]), "、".join(plan["unlisted_characters"]) or "無"))
        if "script" in stages:
            print("② 漫畫劇本")
            _, report = ad.run_script(args.chapter, args.page, args.force)
            print("   台詞 %d 句，%d 句能在原著找到；原著引號內台詞 %d 句，%d 句進了劇本（細節：build/adapt/ch%03d_fidelity.md）"
                  % (report["dialogue_lines"], report["dialogue_found"], report["source_quotes"], report["source_quotes_kept"], args.chapter))
        if "storyboard" in stages:
            print("③ 分鏡")
            ad.run_storyboard(args.chapter, args.page, args.force)
            print("   已通過 compile_chapter 檢查")
    except llm.Cancelled:
        print("已取消")
        sys.exit(130)
    except (adapt.AdaptError, llm.LLMError, project.ProjectError) as err:
        print("✗ %s" % err)
        sys.exit(1)
    print("完成：呼叫 %d 次，約 %d 個輸入／%d 個輸出 token，用時 %.0f 秒" % (ad.usage["calls"], ad.usage["prompt_tokens"], ad.usage["completion_tokens"], time.monotonic() - t0))
    if ad.warnings:
        print("提醒（%d）：" % len(ad.warnings))
        for w in ad.warnings[:20]:
            print("  - %s" % w)


if __name__ == "__main__":
    main()
