"""設定頁（N1／N6）：讀寫工具設定 config.json、問 ComfyUI 有哪些模型、測 LLM 連線、把金鑰存進系統金鑰庫。

只寫白名單的鍵（t2c/settings.WRITABLE），寫之前備份成 config.json.bak。
金鑰不進檔案、也不從這裡出去：這裡只回報「環境變數有沒有設」與「金鑰庫有沒有這一筆」，
貼進來的金鑰只交給 keyring.set_password()（服務 novel-studio、帳號 = provider id）。
"""
import os
import time

from fastapi import APIRouter, Body

from fekit import ApiError

from t2c import comfy, llm, settings

from .common import ROOT, guard

router = APIRouter()


def settings_path():
    """設定檔位置（測試會換掉它）。"""
    return ROOT / "config.json"


def _cfg():
    path = settings_path()
    with guard("no_config"):
        return settings.load(path=path if path.is_file() else None, root=ROOT)


def _account(prov, fallback=""):
    """系統金鑰庫的帳號：provider 的 key_id，沒寫就用 id。"""
    return str(prov.get("key_id") or prov.get("id") or fallback)


def _keyring_status():
    """keyring 裝了沒有（沒裝時介面只顯示安裝提示，不給存）。"""
    available = llm.keyring_available()
    return {"available": available, "service": llm.KEYRING_SERVICE,
            "message": "" if available else
            "沒有安裝 keyring：請在 .venv 執行 pip install keyring，重啟伺服器之後才能在這裡存金鑰。"}


def _key_status(cfg):
    """每個 provider 的金鑰來源狀態：只說有沒有，不說內容。"""
    rows = []
    for prov in cfg.get("providers") or []:
        if not isinstance(prov, dict):
            continue
        env = str(prov.get("key_env") or "")
        rows.append({"id": prov.get("id"), "name": prov.get("name"), "key_env": env,
                     "env_set": bool(env and os.environ.get(env)),
                     "keyring": bool(env and llm.keyring_get(_account(prov)))})
    return rows


def _public(cfg):
    return {k: v for k, v in cfg.items() if not str(k).startswith("_")}


def _payload(cfg):
    path = settings_path()
    return {"path": str(path), "writable": list(settings.WRITABLE), "settings": _public(cfg),
            "keys": _key_status(cfg), "keyring": _keyring_status(), "stages": list(settings.STAGES),
            "backup": str(path.with_name(path.name + ".bak"))}


@router.get("/api/settings")
def settings_read():
    return _payload(_cfg())


@router.post("/api/settings")
def settings_write(body: dict = Body(...)):
    data = body.get("settings")
    if not isinstance(data, dict):
        raise ApiError(400, "缺少 settings", "bad_request")
    path = settings_path()
    try:
        cfg = settings.save(data, path=path)
    except ValueError as error:
        raise ApiError(400, str(error), "bad_settings")
    except OSError as error:
        raise ApiError(400, "寫不進設定檔：%s" % error, "write_failed")
    return _payload(cfg)


# ---- ComfyUI 現在有哪些模型（設定頁的下拉） ------------------------------------------

@router.get("/api/comfy/models")
def comfy_models(kind: str = ""):
    """ComfyUI 的 unet／clip／vae／lora／sampler／scheduler 清單。

    帶 kind（moss／anima）時多回 guessed：依檔名猜的三個模型檔名，給「依 kind 自動挑」用。
    ComfyUI 沒開回 ok:false 加一句話（HTTP 還是 200，介面直接把那句話顯示出來）。
    """
    cfg = _cfg()
    base = str((cfg.get("comfy") or {}).get("url") or "http://127.0.0.1:8188")
    empty = {"ok": False, "unet": [], "clip": [], "vae": [], "lora": [], "sampler": [], "scheduler": [], "message": ""}
    try:
        lists = comfy.available_models(base)
    except comfy.ComfyError as error:
        return dict(empty, message=str(error))
    data = dict(empty, ok=True, **lists)
    if str(kind or "").strip():
        data["guessed"] = comfy.guess_models(kind, lists)
    return data


# ---- LLM 連線探測與金鑰（設定頁） ----------------------------------------------------

@router.post("/api/llm/probe")
def llm_probe(body: dict = Body(...)):
    """測一個 provider 的連線：內部用 llm.list_models()，失敗也回 200（介面顯示 message）。"""
    cfg = _cfg()
    start = time.time()
    try:
        prov = llm.find_provider(cfg, str(body.get("provider") or "").strip() or None)
    except llm.LLMError as error:
        return {"ok": False, "models": [], "ms": 0, "message": str(error)}
    try:
        models = llm.list_models(prov)
    except llm.LLMError as error:
        return {"ok": False, "models": [], "ms": int((time.time() - start) * 1000), "message": str(error)}
    except Exception as error:                      # 探測端點不該因為任何原因回 500
        return {"ok": False, "models": [], "ms": int((time.time() - start) * 1000), "message": "測試失敗：%s" % error}
    return {"ok": True, "models": models, "ms": int((time.time() - start) * 1000), "message": ""}


@router.post("/api/llm/key")
def llm_key(body: dict = Body(...)):
    """把金鑰存進系統金鑰庫；這裡不寫任何檔案。存完就生效（列表／出圖的下一次呼叫就會讀到）。"""
    cfg = _cfg()
    key = str(body.get("key") or "").strip()
    if not key:
        raise ApiError(400, "金鑰是空的", "bad_key")
    try:
        prov = llm.find_provider(cfg, str(body.get("provider") or "").strip() or None)
    except llm.LLMError as error:
        raise ApiError(400, str(error), "bad_provider")
    account = _account(prov, str(body.get("provider") or ""))
    try:
        llm.keyring_set(account, key)
    except llm.LLMError as error:
        return {"ok": False, "stored": False, "message": str(error)}
    env = str(prov.get("key_env") or "")
    note = "（注意：環境變數 %s 優先，設了就以它為準）" % env if env else ""
    return {"ok": True, "stored": True,
            "message": "已存進系統金鑰庫（服務 %s、帳號 %s），不用重啟就生效%s。" % (llm.KEYRING_SERVICE, account, note)}
