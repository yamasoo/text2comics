"""N6：設定頁的 LLM 連線探測（POST /api/llm/probe）與存金鑰（POST /api/llm/key）。

用本機假 OpenAI 伺服器（ThreadingHTTPServer 綁 127.0.0.1:0），不連外網、不需要金鑰；
金鑰庫換成假的（不碰真的系統金鑰庫）。設定檔與 ROOT 一律用 tmp_path：跑完目錄裡只有
本來就寫進去的那個 config.json，內容一模一樣。
執行：python -m pytest tests/test_llm_probe.py
"""
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from server import settings_api  # noqa: E402
from t2c import llm, settings  # noqa: E402

client = TestClient(app_module.app, base_url="http://127.0.0.1")


def token():
    html = client.get("/").text
    return re.search(r'name="fe-token" content="([^"]+)"', html).group(1)


def post(path, body):
    return client.post(path, json=body, headers={"X-FE-Token": token()})


class Handler(BaseHTTPRequestHandler):
    """假 OpenAI 伺服器：GET /v1/models 回 Handler.models（status 不是 200 就回錯誤）。"""

    models = ["deepseek-chat", "deepseek-reasoner"]
    status = 200
    hits = []

    def log_message(self, *a):
        pass

    def _reply(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Handler.hits.append(self.path)
        if self.path != "/v1/models":
            self._reply(404, json.dumps({"error": {"message": "沒有這個路徑"}}).encode("utf-8"))
        elif Handler.status != 200:
            self._reply(Handler.status, json.dumps({"error": {"message": "伺服器壞掉了"}}).encode("utf-8"))
        else:
            self._reply(200, json.dumps({"data": [{"id": name} for name in Handler.models]}).encode("utf-8"))


@pytest.fixture
def llm_server():
    Handler.hits = []
    Handler.status = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


def make_cfg(base):
    """兩個 provider：本機的假模型（不用金鑰）、雲端的（要金鑰，測試裡不放行）。"""
    return {"providers": [
        {"id": "fake", "type": "openai", "name": "假模型", "base_url": base + "/v1", "model": "deepseek-chat",
         "key_env": "", "context_tokens": 200000, "max_output": 8000},
        {"id": "cloud", "type": "openai", "name": "雲端", "base_url": "https://api.deepseek.com/v1",
         "model": "deepseek-chat", "key_env": "T2C_PROBE_KEY"},
    ], "default_provider": "fake", "comfy": {"url": "http://127.0.0.1:1"}, "lettering": {}}


@pytest.fixture
def probe_config(tmp_path, monkeypatch, llm_server):
    """settings_path／ROOT 換成 tmp_path 裡的設定檔；跑完只應該剩這個檔案，內容不變。"""
    root = tmp_path / "root"
    root.mkdir()
    path = root / "config.json"
    path.write_text(json.dumps(make_cfg(llm_server), ensure_ascii=False, indent=2), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(settings_api, "settings_path", lambda: path)
    monkeypatch.setattr(settings_api, "ROOT", root)
    monkeypatch.delenv("T2C_PROBE_KEY", raising=False)
    monkeypatch.setattr(llm, "keyring_get", lambda account: "")         # 真的系統金鑰庫不碰
    return {"root": root, "path": path, "before": before, "cfg": make_cfg(llm_server)}


def assert_nothing_written(state):
    """沒有任何檔案被寫入：目錄裡只有原本那個 config.json，內容一模一樣。"""
    assert sorted(p.name for p in state["root"].iterdir()) == ["config.json"]
    assert state["path"].read_bytes() == state["before"]


# ---- POST /api/llm/probe ---------------------------------------------------------

def test_probe_lists_models_from_the_server(probe_config):
    """假 OpenAI 伺服器回兩個模型：ok:true、models 正確、有 ms，沒有寫任何檔案。"""
    response = post("/api/llm/probe", {"provider": "fake"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True and data["message"] == ""
    assert data["models"] == ["deepseek-chat", "deepseek-reasoner"]
    assert isinstance(data["ms"], int) and data["ms"] >= 0
    assert Handler.hits == ["/v1/models"]
    assert_nothing_written(probe_config)


def test_probe_reports_a_server_error(probe_config):
    """伺服器回 500：ok:false 加非空的訊息（不丟 500 給介面）。"""
    Handler.status = 500
    response = post("/api/llm/probe", {"provider": "fake"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False and data["message"] and data["models"] == []
    assert "500" in data["message"]
    assert_nothing_written(probe_config)


def test_probe_without_a_key_says_so(probe_config, monkeypatch):
    """要金鑰的 provider 沒有金鑰：ok:false，訊息說「沒有金鑰」並寫出環境變數名稱。"""
    monkeypatch.setattr(llm, "keyring_get", lambda account: "")
    data = post("/api/llm/probe", {"provider": "cloud"}).json()
    assert data["ok"] is False and data["models"] == []
    assert "沒有金鑰" in data["message"] and "T2C_PROBE_KEY" in data["message"]
    assert Handler.hits == []                                   # 沒金鑰就不連出去
    assert_nothing_written(probe_config)


def test_probe_unknown_provider(probe_config):
    """provider id 不存在：ok:false，訊息列出目前有哪些。"""
    data = post("/api/llm/probe", {"provider": "nope"}).json()
    assert data["ok"] is False and data["models"] == [] and data["ms"] == 0
    assert "nope" in data["message"] and "fake" in data["message"]
    assert_nothing_written(probe_config)


# ---- POST /api/llm/key -----------------------------------------------------------

def test_key_rejects_an_empty_key(probe_config):
    """空金鑰（含只有空白）回 400，什麼都不存。"""
    for empty in ("", "   "):
        response = post("/api/llm/key", {"provider": "cloud", "key": empty})
        assert response.status_code == 400 and "金鑰" in response.json()["error"]
    assert_nothing_written(probe_config)


def test_key_is_stored_in_the_keyring_and_read_back(probe_config, monkeypatch):
    """存金鑰：ok:true、stored:true、訊息含「系統金鑰庫」，而且 llm.api_key() 立刻讀得到；沒有寫任何檔案。"""
    store = {}
    monkeypatch.setattr(llm, "keyring_set", lambda account, secret: store.__setitem__(account, secret))
    monkeypatch.setattr(llm, "keyring_get", lambda account: store.get(account, ""))
    response = post("/api/llm/key", {"provider": "cloud", "key": " sk-test "})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True and data["stored"] is True
    assert "系統金鑰庫" in data["message"] and "cloud" in data["message"]
    assert store == {"cloud": "sk-test"}                       # 帳號是 provider id，前後空白去掉
    assert llm.api_key(llm.find_provider(probe_config["cfg"], provider_id="cloud")) == "sk-test"
    assert_nothing_written(probe_config)


def test_key_without_keyring_fails_clearly(probe_config, monkeypatch):
    """沒有裝 keyring（keyring_set 丟 LLMError）：ok:false，訊息含「keyring」，也沒有寫檔。"""
    def no_keyring(account, secret):
        raise llm.LLMError("沒有安裝 keyring：請在 Python 環境執行 pip install keyring（No module named 'keyring'）")
    monkeypatch.setattr(llm, "keyring_set", no_keyring)
    response = post("/api/llm/key", {"provider": "cloud", "key": "sk-test"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False and data["stored"] is False
    assert "keyring" in data["message"]
    assert_nothing_written(probe_config)


def test_key_for_an_unknown_provider_is_refused(probe_config, monkeypatch):
    """provider id 不存在：回 400（不是 500），也沒有寫檔。"""
    monkeypatch.setattr(llm, "keyring_set", lambda account, secret: pytest.fail("不該存"))
    response = post("/api/llm/key", {"provider": "nope", "key": "sk-test"})
    assert response.status_code == 400 and "nope" in response.json()["error"]
    assert_nothing_written(probe_config)
