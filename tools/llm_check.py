"""檢查 LLM 連線：對 config.json 的 provider 各問一次，要求回 JSON；也可以測試按停止。

  python tools/llm_check.py                       # 檢查所有 provider
  python tools/llm_check.py --provider llamacpp   # 只查一個
  python tools/llm_check.py --stop-after 5        # 收到 5 個字就按停止，確認會中斷（長一點的回答才看得出來）
  python tools/llm_check.py --models              # 列出伺服器提供的模型名稱

DeepSeek 要先設環境變數 DEEPSEEK_API_KEY；llama.cpp 要先啟動 llama-server。
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from t2c import llm, settings  # noqa: E402

PROMPT = [
    {"role": "system", "content": "你是測試用的助手。只輸出 JSON，不要加說明。"},
    {"role": "user", "content": '請輸出 JSON：{"ok": true, "say": "<用繁體中文說一句問候>", "numbers": [1, 2, 3]}'},
]
LONG_PROMPT = [{"role": "user", "content": "請用繁體中文寫一段至少 500 字的故事，主題是下雨天的車站。"}]


def check(prov, stop_after, show_models):
    name = "%s（%s）" % (prov.get("name") or prov["id"], prov.get("model") or "預設模型")
    print("== %s" % name)
    if show_models:
        try:
            print("   模型：%s" % ("、".join(llm.list_models(prov)) or "（沒有）"))
        except llm.LLMError as err:
            print("   ✗ %s" % err)
        return False
    t0 = time.monotonic()
    if stop_after:
        got = []
        stop = {"flag": False}

        def on_delta(text):
            got.append(text)
            if len("".join(got)) >= stop_after:
                stop["flag"] = True

        try:
            llm.chat(prov, LONG_PROMPT, on_delta=on_delta, should_stop=lambda: stop["flag"], max_tokens=800)
        except llm.Cancelled:
            print("   ✓ 已中斷：收到 %d 字後停止，花 %.1f 秒" % (len("".join(got)), time.monotonic() - t0))
            return True
        except llm.LLMError as err:
            print("   ✗ %s" % err)
            return False
        print("   ✗ 沒有被中斷：已經整段生成完了（%d 字）" % len("".join(got)))
        return False
    try:
        data, reply = llm.chat_json(prov, PROMPT, max_tokens=300,
                                    on_retry=lambda n, e, w: print("   重試 %d：%s（等 %.0f 秒）" % (n, e, w)))
    except llm.Cancelled:
        print("   已取消")
        return False
    except llm.LLMError as err:
        print("   ✗ %s" % err)
        return False
    print("   ✓ JSON：%s" % data)
    print("   用時 %.1f 秒；usage：%s；結束原因：%s" % (time.monotonic() - t0, reply.usage or "（伺服器沒回報）", reply.finish))
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", help="只檢查這個 id；預設全部")
    ap.add_argument("--config", help="設定檔路徑；預設 config.json")
    ap.add_argument("--stop-after", type=int, default=0, help="收到幾個字就按停止")
    ap.add_argument("--models", action="store_true", help="列出伺服器的模型名稱")
    args = ap.parse_args()
    cfg = settings.load(args.config)
    provs = [llm.find_provider(cfg, provider_id=args.provider)] if args.provider else cfg.get("providers", [])
    results = [check(p, args.stop_after, args.models) for p in provs]
    sys.exit(0 if args.models or all(results) else 1)


if __name__ == "__main__":
    main()
