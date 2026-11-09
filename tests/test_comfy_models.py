"""N6：ComfyUI 現在掛了哪些模型（t2c/comfy.py 的 object_info／model_lists／guess_models）
與設定頁的 GET /api/comfy/models（server/settings_api.py）。

ComfyUI 用本機假伺服器（ThreadingHTTPServer 綁 127.0.0.1:0），不連外網、不需要 GPU。
設定一律用 monkeypatch 換掉，不讀也不寫 repo 的 config.json。
執行：python -m pytest tests/test_comfy_models.py
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
from t2c import comfy, settings  # noqa: E402

client = TestClient(app_module.app, base_url="http://127.0.0.1")


def token():
    html = client.get("/").text
    return re.search(r'name="fe-token" content="([^"]+)"', html).group(1)


def post(path, body):
    return client.post(path, json=body, headers={"X-FE-Token": token()})


# ComfyUI 的 /object_info：CLIPLoader、LoraLoaderModelOnly、KSampler.scheduler 是新版
# ["COMBO", {"options": [...]}]，其餘是舊版 [[...]]。兩種都要讀得到。
OBJECT_INFO = {
    "UNETLoader": {"input": {"required": {"unet_name": [["moss_image_sft_v2.0.safetensors",
                                                         "anima_v4.safetensors",
                                                         "Illustrious-XL.safetensors"]]}}},
    "CLIPLoader": {"input": {"required": {"clip_name": ["COMBO", {"options": ["qwen3.5_9b_base.safetensors",
                                                                          "qwen_3_06b_base.safetensors"]}]}}},
    "VAELoader": {"input": {"required": {"vae_name": [["flux2-vae.safetensors", "qwen_image_vae.safetensors"]]}}},
    "LoraLoaderModelOnly": {"input": {"required": {"lora_name": ["COMBO", {"options": ["ANIMA/style.safetensors"]}]}}},
    "KSampler": {"input": {"required": {"sampler_name": [["euler", "dpmpp_2m", "dpmpp_2m_sde"]],
                                        "scheduler": ["COMBO", {"options": ["simple", "beta", "normal"]}]}}},
}


class Handler(BaseHTTPRequestHandler):
    """假 ComfyUI：GET /object_info 回 OBJECT_INFO，其他路徑 404。"""

    info = OBJECT_INFO
    hits = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.hits.append(self.path)
        if self.path == "/object_info":
            body = json.dumps(Handler.info).encode("utf-8")
            self.send_response(200)
        else:
            body = b"{}"
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def comfy_server():
    Handler.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


@pytest.fixture
def models_cfg(monkeypatch, comfy_server):
    """設定頁讀到的設定：comfy.url 指向假 ComfyUI（settings.load 換掉，不碰真的 config.json）。"""
    cfg = {"comfy": {"url": comfy_server}, "lettering": {}}
    monkeypatch.setattr(settings, "load", lambda path=None, root=None: dict(cfg, _path="test"))
    return cfg


# ---- t2c/comfy.py：object_info／model_lists ----------------------------------------

def test_model_lists_reads_old_and_new_combo_formats(comfy_server):
    """object_info 的兩種 Combo 格式都要讀成清單，六個鍵都要有。"""
    lists = comfy.model_lists(comfy.object_info(comfy_server))
    assert Handler.hits == ["/object_info"]
    assert lists == {
        "unet": ["moss_image_sft_v2.0.safetensors", "anima_v4.safetensors", "Illustrious-XL.safetensors"],
        "clip": ["qwen3.5_9b_base.safetensors", "qwen_3_06b_base.safetensors"],
        "vae": ["flux2-vae.safetensors", "qwen_image_vae.safetensors"],
        "lora": ["ANIMA/style.safetensors"],
        "sampler": ["euler", "dpmpp_2m", "dpmpp_2m_sde"],
        "scheduler": ["simple", "beta", "normal"],
    }
    assert comfy.available_models(comfy_server) == lists


def test_choices_tolerates_missing_nodes_and_empty_lists():
    """節點不在、欄位不是 Combo、清單是空的：回空清單，不丟錯。"""
    assert comfy.model_lists({}) == {key: [] for key in ("unet", "clip", "vae", "lora", "sampler", "scheduler")}
    assert comfy.model_lists({"KSampler": {"input": {"required": {"sampler_name": []}}}})["sampler"] == []
    assert comfy.model_lists({"KSampler": {"input": {}}})["sampler"] == []
    assert comfy.model_lists({"UNETLoader": {"input": {"required": {"unet_name": "字串"}}}})["unet"] == []


def test_available_models_reports_a_dead_server():
    """連不上 ComfyUI 丟 ComfyError（訊息寫出網址與「有開嗎」）。"""
    with pytest.raises(comfy.ComfyError, match="連不到 ComfyUI"):
        comfy.available_models("http://127.0.0.1:1")


# ---- t2c/comfy.py：guess_models ---------------------------------------------------

def test_guess_models_picks_by_filename():
    """依 GUESS 的關鍵字挑檔名（不分大小寫）；猜不到回空字串，kind 不認得回空物件。"""
    lists = comfy.model_lists(OBJECT_INFO)
    assert comfy.guess_models("anima", lists) == {"unet": "anima_v4.safetensors",
                                                  "clip": "qwen_3_06b_base.safetensors",
                                                  "vae": "qwen_image_vae.safetensors"}
    assert comfy.guess_models("moss", lists) == {"unet": "moss_image_sft_v2.0.safetensors",
                                                 "clip": "qwen3.5_9b_base.safetensors",
                                                 "vae": "flux2-vae.safetensors"}
    assert comfy.guess_models("anima", {}) == {"unet": "", "clip": "", "vae": ""}
    assert comfy.guess_models("anima", {"unet": ["UnstableAnima-Art-V4.safetensors"]})["unet"] == "UnstableAnima-Art-V4.safetensors"
    assert comfy.guess_models("anima", {"unet": ["moss.safetensors"]}) == {"unet": "", "clip": "", "vae": ""}
    assert comfy.guess_models("moss2", lists) == {}
    assert comfy.guess_models("", lists) == {}


# ---- GET /api/comfy/models --------------------------------------------------------

def test_comfy_models_api_lists_and_guesses(models_cfg):
    """ComfyUI 有開：ok:true 加六份清單；帶 kind 多回 guessed 的三個鍵。"""
    data = client.get("/api/comfy/models").json()
    assert data["ok"] is True and data["message"] == ""
    assert data["unet"] == ["moss_image_sft_v2.0.safetensors", "anima_v4.safetensors", "Illustrious-XL.safetensors"]
    assert data["clip"] == ["qwen3.5_9b_base.safetensors", "qwen_3_06b_base.safetensors"]
    assert data["vae"] == ["flux2-vae.safetensors", "qwen_image_vae.safetensors"]
    assert data["lora"] == ["ANIMA/style.safetensors"]
    assert data["sampler"] == ["euler", "dpmpp_2m", "dpmpp_2m_sde"]
    assert data["scheduler"] == ["simple", "beta", "normal"]
    assert "guessed" not in data                                     # 沒帶 kind 就不猜

    guessed = client.get("/api/comfy/models", params={"kind": "anima"}).json()
    assert set(guessed["guessed"]) == {"unet", "clip", "vae"}
    assert guessed["guessed"] == {"unet": "anima_v4.safetensors",
                                  "clip": "qwen_3_06b_base.safetensors",
                                  "vae": "qwen_image_vae.safetensors"}
    assert guessed["unet"] == data["unet"]                            # 清單本身不受 kind 影響


def test_comfy_models_api_says_when_comfy_is_off(monkeypatch):
    """ComfyUI 沒開：HTTP 還是 200，ok:false 加一句話，六份清單都是空的（介面直接顯示那句話）。"""
    monkeypatch.setattr(settings, "load", lambda path=None, root=None: {
        "comfy": {"url": "http://127.0.0.1:1"}, "lettering": {}, "_path": "test"})
    response = client.get("/api/comfy/models", params={"kind": "anima"})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False and data["message"]
    assert "ComfyUI" in data["message"]
    for key in ("unet", "clip", "vae", "lora", "sampler", "scheduler"):
        assert data[key] == []
