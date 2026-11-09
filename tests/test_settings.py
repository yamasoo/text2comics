"""N1：設定頁——設定檔的寫入（白名單、備份、驗證）與 /api/settings。

執行：python -m pytest tests/test_settings.py
"""
import json
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from server import settings_api  # noqa: E402
from t2c import settings  # noqa: E402

client = TestClient(app_module.app, base_url="http://127.0.0.1")


def token():
    """fekit 的本機保護：POST／GET 都要帶頁面上的權杖（同 tests/test_ui.py）。"""
    html = client.get("/").text
    return re.search(r'name="fe-token" content="([^"]+)"', html).group(1)


def api_get(path):
    return client.get(path, headers={"X-FE-Token": token()})


def api_post(path, body):
    return client.post(path, json=body, headers={"X-FE-Token": token()})


def write_config(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def base_config():
    return {
        "_說明": "測試用",
        "providers": [{"id": "deepseek", "type": "openai", "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "key_env": "DEEPSEEK_API_KEY"}],
        "default_provider": "deepseek",
        "stage_providers": {"adapt": "", "script": "", "storyboard": "", "bible": ""},
        "comfy": {"url": "http://127.0.0.1:8188", "models": {"unet": "u", "clip": "c", "vae": "v"}, "default_preset": "final", "presets": {"final": {"steps": 25}}},
        "lettering": {"vertical": True, "dialogue_pt": 9, "narration_pt": 8.5},
    }


def test_save_writes_whitelisted_keys_and_keeps_the_rest(tmp_path):
    path = tmp_path / "config.json"
    write_config(path, base_config())
    saved = settings.save({"lettering": {"vertical": False}}, path=path)
    assert saved["_path"] == str(path)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["lettering"]["vertical"] is False              # 有送的有改
    assert on_disk["lettering"]["dialogue_pt"] == 9              # 沒送的保留（一層合併）
    assert on_disk["default_provider"] == "deepseek"          # 沒送的鍵保持原樣
    assert "_說明" not in on_disk and "_path" not in on_disk  # 底線開頭的不寫回


def test_save_merges_dict_sections_one_level(tmp_path):
    path = tmp_path / "config.json"
    write_config(path, base_config())
    saved = settings.save({"comfy": {"default_preset": "draft"}}, path=path)
    assert saved["comfy"]["default_preset"] == "draft"
    assert saved["comfy"]["models"]["unet"] == "u"        # 沒送的欄位還在
    assert saved["comfy"]["presets"] == {"final": {"steps": 25}}


def test_save_backs_up_the_old_file(tmp_path):
    path = tmp_path / "config.json"
    write_config(path, base_config())
    settings.save({"default_provider": "deepseek"}, path=path)
    backup = tmp_path / "config.json.bak"
    assert backup.is_file()
    assert json.loads(backup.read_text(encoding="utf-8"))["_說明"] == "測試用"


def test_save_rejects_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    write_config(path, base_config())
    with pytest.raises(ValueError) as error:
        settings.save({"_說明": "偷改", "comfy": {}}, path=path)
    assert "不能寫入" in str(error.value)


def test_save_rejects_provider_without_base_url(tmp_path):
    path = tmp_path / "config.json"
    write_config(path, base_config())
    with pytest.raises(ValueError) as error:
        settings.save({"providers": [{"id": "llamacpp", "type": "openai"}]}, path=path)
    assert "base_url" in str(error.value)


def test_save_rejects_duplicate_provider_id(tmp_path):
    path = tmp_path / "config.json"
    write_config(path, base_config())
    with pytest.raises(ValueError) as error:
        settings.save({"providers": [
            {"id": "a", "type": "openai", "base_url": "http://x"},
            {"id": "a", "type": "openai", "base_url": "http://y"}]}, path=path)
    assert "重複" in str(error.value)


def test_save_rejects_default_provider_not_in_list(tmp_path):
    path = tmp_path / "config.json"
    write_config(path, base_config())
    with pytest.raises(ValueError) as error:
        settings.save({"default_provider": "nope"}, path=path)
    assert "default_provider" in str(error.value)


def test_save_creates_file_from_example_when_missing(tmp_path):
    (tmp_path / "config.example.json").write_text(json.dumps(base_config(), ensure_ascii=False), encoding="utf-8")
    saved = settings.save({"default_provider": "deepseek"}, root=str(tmp_path))
    path = tmp_path / "config.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["comfy"]["default_preset"] == "final"
    assert saved["_path"] == str(path)


def test_api_settings_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    write_config(path, base_config())
    monkeypatch.setattr(settings_api, "settings_path", lambda: path)

    got = api_get("/api/settings")
    assert got.status_code == 200
    body = got.json()
    assert body["settings"]["default_provider"] == "deepseek"
    assert "_說明" not in body["settings"]
    assert body["writable"][0] == "providers"
    assert body["keys"][0]["id"] == "deepseek"

    changed = json.loads(json.dumps(body["settings"]))
    changed["comfy"]["default_preset"] = "draft"
    posted = api_post("/api/settings", {"settings": {"comfy": changed["comfy"]}})
    assert posted.status_code == 200
    assert json.loads(path.read_text(encoding="utf-8"))["comfy"]["default_preset"] == "draft"
    assert (tmp_path / "config.json.bak").is_file()


def test_api_settings_rejects_bad_payload(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    write_config(path, base_config())
    monkeypatch.setattr(settings_api, "settings_path", lambda: path)

    assert api_post("/api/settings", {}).status_code == 400
    bad = api_post("/api/settings", {"settings": {"providers": "不是陣列"}})
    assert bad.status_code == 400
    assert "providers" in bad.json()["error"] and bad.json()["code"] == "bad_settings"
