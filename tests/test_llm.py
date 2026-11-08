"""S4：LLM 連線。用本機假伺服器（OpenAI 相容的 SSE），不連外網、不需要金鑰。
執行：python -m pytest tests/test_llm.py
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import llm  # noqa: E402


class Fake:
    """script：每個請求依序取一項。項目是 dict：
    status／headers／json（整包回應）／chunks（SSE 事件 list，字串直接寫出）／delay（每段間隔）／drop（送完 chunks 就斷線，不送 [DONE]）"""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []        # (headers, body)
        self.disconnected = threading.Event()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                fake.requests.append((dict(self.headers), body))
                step = fake.script.pop(0) if fake.script else fake.script_last
                fake.script_last = step
                status = step.get("status", 200)
                if "json" in step or status != 200:
                    data = json.dumps(step.get("json", {"error": {"message": step.get("message", "壞掉了")}})).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    for k, v in (step.get("headers") or {}).items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for ch in step["chunks"]:
                        text = ch if isinstance(ch, str) else "data: %s\n\n" % json.dumps(ch)
                        self.wfile.write(text.encode("utf-8"))
                        self.wfile.flush()
                        time.sleep(step.get("delay", 0))
                    if not step.get("drop"):
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    fake.disconnected.set()

        self.script_last = {"chunks": []}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/v1" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def delta(text=None, finish=None, **extra):
    d = {}
    if text is not None:
        d["content"] = text
    d.update(extra)
    return {"choices": [{"delta": d, "finish_reason": finish}]}


def ok_chunks(*texts, usage=True):
    out = [delta(t) for t in texts] + [delta(finish="stop")]
    if usage:
        out.append({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    return out


@pytest.fixture
def serve():
    servers = []

    def make(script):
        f = Fake(script)
        servers.append(f)
        return f

    yield make
    for f in servers:
        f.close()


def prov(fake, **kw):
    p = {"id": "t", "type": "openai", "name": "測試", "base_url": fake.url, "model": "m1", "key_env": "",
         "context_tokens": 8000, "max_output": 1000, "temperature": 0.5, "json_mode": True}
    p.update(kw)
    return p


MSG = [{"role": "user", "content": "你好"}]


# --- 基本串流 ---------------------------------------------------------------
def test_streams_text_and_usage(serve):
    f = serve([{"chunks": ok_chunks("你", "好", "！")}])
    seen = []
    r = llm.chat(prov(f), MSG, on_delta=seen.append)
    assert r.text == "你好！" and seen == ["你", "好", "！"]
    assert r.usage["completion_tokens"] == 5 and r.finish == "stop" and r.attempts == 1


def test_request_body_and_auth(serve, monkeypatch):
    monkeypatch.setenv("T2C_TEST_KEY", "sk-abc")
    f = serve([{"chunks": ok_chunks("{}")}])
    llm.chat(prov(f, key_env="T2C_TEST_KEY"), MSG, json_mode=True, max_tokens=77)
    headers, body = f.requests[0]
    assert headers["Authorization"] == "Bearer sk-abc"
    assert body["model"] == "m1" and body["max_tokens"] == 77 and body["temperature"] == 0.5
    assert body["stream"] is True and body["response_format"] == {"type": "json_object"}


def test_json_mode_off_and_no_key_for_local(serve):
    f = serve([{"chunks": ok_chunks("x")}])
    llm.chat(prov(f, json_mode=False, key_env="T2C_NOT_SET"), MSG, json_mode=True)   # 本機服務不需要金鑰
    headers, body = f.requests[0]
    assert "response_format" not in body and "Authorization" not in headers


def test_key_from_env_then_keyring(monkeypatch):
    p = {"id": "deepseek", "key_env": "T2C_TEST_KEY2"}
    monkeypatch.delenv("T2C_TEST_KEY2", raising=False)
    asked = []
    monkeypatch.setattr(llm, "_keyring_get", lambda account: asked.append(account) or "sk-ring")
    assert llm.api_key(p) == "sk-ring" and asked == ["deepseek"]
    monkeypatch.setenv("T2C_TEST_KEY2", "sk-env")
    assert llm.api_key(p) == "sk-env" and asked == ["deepseek"]       # 環境變數優先，不去問金鑰庫
    asked.clear()
    assert llm.api_key({"id": "llamacpp", "key_env": ""}) == "" and asked == []   # 本機服務不查金鑰庫


def test_list_models_checks_key_first(monkeypatch):
    monkeypatch.setattr(llm, "_keyring_get", lambda account: "")
    p = {"id": "d", "base_url": "https://api.deepseek.com", "key_env": "T2C_NOT_SET_KEY"}
    with pytest.raises(llm.LLMError, match="沒有金鑰"):
        llm.list_models(p)


def test_missing_key_for_remote_is_clear_error(monkeypatch):
    monkeypatch.setattr(llm, "_keyring_get", lambda account: "")
    p = {"id": "d", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "key_env": "T2C_NOT_SET_KEY"}
    with pytest.raises(llm.LLMError, match="T2C_NOT_SET_KEY"):
        llm.chat(p, MSG)


def test_thinking_goes_to_callback_not_text(serve):
    f = serve([{"chunks": [delta(reasoning_content="想一下"), delta("答案"), delta(finish="stop")]}])
    think = []
    r = llm.chat(prov(f), MSG, on_thinking=think.append)
    assert r.text == "答案" and think == ["想一下"] and r.thinking == "想一下"


def test_non_streaming_server(serve):
    f = serve([{"json": {"choices": [{"message": {"content": "一次回完"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1}}}])
    seen = []
    r = llm.chat(prov(f), MSG, on_delta=seen.append)
    assert r.text == "一次回完" and seen == ["一次回完"]


# --- 重試 -------------------------------------------------------------------
def test_retries_429_then_succeeds(serve):
    f = serve([{"status": 429, "headers": {"Retry-After": "0"}}, {"status": 503}, {"chunks": ok_chunks("好")}])
    retries = []
    r = llm.chat(prov(f), MSG, backoff=0.01, on_retry=lambda n, e, w: retries.append((n, e.status)))
    assert r.text == "好" and r.attempts == 3 and retries == [(1, 429), (2, 503)] and len(f.requests) == 3


def test_gives_up_after_retries(serve):
    f = serve([{"status": 500}])
    with pytest.raises(llm.LLMError, match="HTTP 500"):
        llm.chat(prov(f), MSG, retries=2, backoff=0.01)
    assert len(f.requests) == 3


@pytest.mark.parametrize("status,hint", [(401, "金鑰"), (402, "餘額"), (404, "模型名稱")])
def test_does_not_retry_client_errors(serve, status, hint):
    f = serve([{"status": status}])
    with pytest.raises(llm.LLMError, match=hint) as e:
        llm.chat(prov(f), MSG, backoff=0.01)
    assert len(f.requests) == 1 and e.value.status == status and not e.value.retryable


def test_connection_refused_is_retried_then_reported():
    p = {"id": "x", "name": "沒開", "base_url": "http://127.0.0.1:9/v1", "model": ""}
    n = []
    with pytest.raises(llm.LLMError, match="連不上"):
        llm.chat(p, MSG, retries=1, backoff=0.01, on_retry=lambda *a: n.append(a))
    assert len(n) == 1


def test_drop_before_any_text_is_retried(serve):
    f = serve([{"chunks": [], "drop": True}, {"chunks": ok_chunks("後來好了")}])
    r = llm.chat(prov(f), MSG, backoff=0.01)
    assert r.text == "後來好了" and len(f.requests) == 2


def test_drop_after_text_is_not_retried(serve):
    f = serve([{"chunks": [delta("半")], "drop": True}])
    with pytest.raises(llm.LLMError, match="已收到") as e:
        llm.chat(prov(f), MSG, backoff=0.01)
    assert len(f.requests) == 1 and not e.value.retryable


# --- 取消 -------------------------------------------------------------------
def test_cancel_stops_stream_quickly_and_disconnects(serve):
    f = serve([{"chunks": [delta("字")] * 200, "delay": 0.05}])
    stop = threading.Event()
    got = []

    def on_delta(t):
        got.append(t)
        if len(got) == 3:
            stop.set()

    t0 = time.monotonic()
    with pytest.raises(llm.Cancelled):
        llm.chat(prov(f), MSG, on_delta=on_delta, should_stop=stop.is_set)
    assert time.monotonic() - t0 < 2 and len(got) < 20
    assert f.disconnected.wait(3)      # 伺服器那邊也知道客戶端走了（本機模型才會停止生成）


def test_cancel_while_waiting_for_first_byte(serve):
    f = serve([{"chunks": [delta("慢")], "delay": 0}])
    f.script.insert(0, {"chunks": [""], "delay": 5})       # 標頭已送出，但 5 秒內沒有任何資料
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    t0 = time.monotonic()
    with pytest.raises(llm.Cancelled):
        llm.chat(prov(f), MSG, should_stop=stop.is_set)
    assert time.monotonic() - t0 < 2


def test_cancel_first_byte_even_if_shutdown_is_ineffective(serve, monkeypatch):
    """Windows 上 socket.shutdown 不一定叫得醒卡在 recv 的讀取執行緒；取消不能因此等到伺服器下一次寫資料。"""
    import socket
    monkeypatch.setattr(socket.socket, "shutdown", lambda self, how: None)
    test_cancel_while_waiting_for_first_byte(serve)


def test_cancel_during_retry_wait(serve):
    f = serve([{"status": 503}])
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    t0 = time.monotonic()
    with pytest.raises(llm.Cancelled):
        llm.chat(prov(f), MSG, backoff=30, should_stop=stop.is_set)
    assert time.monotonic() - t0 < 2 and len(f.requests) == 1


# --- JSON -------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('好的，結果如下：\n{"a": [1, 2]}\n以上。', {"a": [1, 2]}),
    ('[{"a": 1}, {"a": 2}]', [{"a": 1}, {"a": 2}]),
    ('說明 [1, 2, 3] 完', [1, 2, 3]),
])
def test_parse_json_tolerant(text, expected):
    assert llm.parse_json(text) == expected


@pytest.mark.parametrize("text", ["", "沒有 JSON", '{"a": ', "{壞掉}"])
def test_parse_json_failures(text):
    with pytest.raises(llm.JSONParseError):
        llm.parse_json(text)


def test_chat_json_returns_data(serve):
    f = serve([{"chunks": ok_chunks('```json\n{"pages":', ' 3}\n```')}])
    data, reply = llm.chat_json(prov(f), MSG)
    assert data == {"pages": 3} and f.requests[0][1]["response_format"] == {"type": "json_object"}


def test_chat_json_repairs_once_with_error_fed_back(serve):
    f = serve([{"chunks": ok_chunks('{"pages": ')}, {"chunks": ok_chunks('{"pages": 3}')}])
    data, _ = llm.chat_json(prov(f), MSG)
    assert data == {"pages": 3}
    second = f.requests[1][1]["messages"]
    assert second[-2] == {"role": "assistant", "content": '{"pages": '} and "JSON" in second[-1]["content"]
    assert len(f.requests[0][1]["messages"]) == 1       # 沒有改到呼叫端的 messages
    assert MSG == [{"role": "user", "content": "你好"}]


def test_chat_json_gives_up(serve):
    f = serve([{"chunks": ok_chunks("不是 JSON")}])
    with pytest.raises(llm.JSONParseError):
        llm.chat_json(prov(f), MSG, fix_rounds=1)
    assert len(f.requests) == 2


def test_chat_json_truncated_output_is_not_retried(serve):
    f = serve([{"chunks": [delta('{"a":'), delta(finish="length")]}])
    with pytest.raises(llm.LLMError, match="截斷"):
        llm.chat_json(prov(f), MSG)
    assert len(f.requests) == 1


# --- providers／token／思考 ---------------------------------------------------
CFG = {"providers": [{"id": "deepseek"}, {"id": "llamacpp"}], "default_provider": "deepseek",
       "stage_providers": {"_說明": "x", "adapt": "", "script": "llamacpp"}}


def test_find_provider_order():
    assert llm.find_provider(CFG)["id"] == "deepseek"
    assert llm.find_provider(CFG, stage="adapt")["id"] == "deepseek"        # 空字串＝用預設
    assert llm.find_provider(CFG, stage="script")["id"] == "llamacpp"
    assert llm.find_provider(CFG, provider_id="llamacpp", stage="adapt")["id"] == "llamacpp"
    with pytest.raises(llm.LLMError, match="找不到"):
        llm.find_provider(CFG, provider_id="nope")
    with pytest.raises(llm.LLMError):
        llm.find_provider({"providers": []})


def test_example_config_providers_work():
    from t2c import settings
    cfg = settings.load(ROOT / "config.example.json")
    assert [llm.find_provider(cfg, provider_id=i)["id"] for i in ("deepseek", "llamacpp")] == ["deepseek", "llamacpp"]
    assert llm.find_provider(cfg, stage="storyboard")["id"] == cfg["default_provider"]


def test_estimate_tokens():
    ds = {"base_url": "https://api.deepseek.com"}
    local = {"base_url": "http://127.0.0.1:8080/v1"}
    assert llm.estimate_tokens("", ds) == 0
    assert llm.estimate_tokens("你好嗎" * 100, ds) == 180          # 300 字 × 0.6
    assert llm.estimate_tokens("你好嗎" * 100, local) == 360        # 保守的 1.2
    assert llm.estimate_tokens("你好嗎" * 100, dict(local, cjk_token_ratio=1.0)) == 300
    assert llm.estimate_tokens("hello world!", ds) == 3             # 12 字元 ÷ 4
    assert llm.estimate_tokens("，。！", ds) == 2                    # 全形標點算中日韓字


def test_context_check():
    p = {"base_url": "http://127.0.0.1/v1", "context_tokens": 1000, "max_output": 400, "cjk_token_ratio": 1.0}
    small = [{"role": "user", "content": "字" * 100}]
    big = [{"role": "user", "content": "字" * 700}]
    assert llm.check_context(p, small) == 1000 - 104 - 400
    with pytest.raises(llm.LLMError, match="太長"):
        llm.check_context(p, big)
    assert llm.check_context({"base_url": "x"}, big) is None        # 沒設定上下文就不檢查


def test_deepseek_reasoning_adapter():
    p = {"reasoning": {"adapter": "deepseek", "script": "high", "storyboard": "off", "adapt": "medium"}}
    body = {}
    llm.apply_reasoning(body, p, "script")
    assert body == {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    body = {}
    llm.apply_reasoning(body, p, "storyboard")
    assert body == {"thinking": {"type": "disabled"}}
    body = {}
    llm.apply_reasoning(body, p, "adapt")
    assert body["reasoning_effort"] == "high"                        # DeepSeek 沒有 medium
    body = {}
    llm.apply_reasoning(body, p, None)
    llm.apply_reasoning(body, {}, "script")
    assert body == {}
    q = {"reasoning": {"adapter": "qwen_template", "script": "off"}}
    llm.apply_reasoning(body, q, "script")
    assert body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_extra_params_override(serve):
    f = serve([{"chunks": ok_chunks("x")}])
    llm.chat(prov(f, extra={"top_p": 0.9, "temperature": 0.1}), MSG)
    body = f.requests[0][1]
    assert body["top_p"] == 0.9 and body["temperature"] == 0.1


def test_list_models(serve):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            data = json.dumps({"data": [{"id": "a"}, {"id": "b"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert llm.list_models({"base_url": "http://127.0.0.1:%d/v1" % srv.server_address[1]}) == ["a", "b"]
    finally:
        srv.shutdown()
