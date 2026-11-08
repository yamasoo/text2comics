"""最小的 ComfyUI API 客戶端（只用標準函式庫）。

workflow 用 API 格式（ComfyUI 選單 Export (API)），預設是 workflows/moss_layout.api.json。
要改的節點從 KSampler 往回追：positive／negative 的 CLIPTextEncode、latent 的寬高、seed；
模型檔名照 config.json 的 comfy.models 覆蓋。其他參數（步數、CFG、取樣器）照 workflow。

之後併入 Novel Studio 時，改用它的 studio/comfy.py（功能較完整：LoRA、Upsampler、錯誤說明）。
這裡刻意保持小，只為了獨立工具能先跑起來。
"""
import copy
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKFLOW = ROOT / "workflows" / "moss_layout.api.json"
LOADERS = {"UNETLoader": "unet_name", "CLIPLoader": "clip_name", "VAELoader": "vae_name"}
MODEL_KEYS = {"UNETLoader": "unet", "CLIPLoader": "clip", "VAELoader": "vae"}


class ComfyError(Exception):
    """給人看的錯誤訊息。"""


def _req(base, path, data=None, timeout=30, raw=False):
    url = base.rstrip("/") + path
    body = None if data is None else json.dumps(data).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:800]
        raise ComfyError("ComfyUI 回應 %d：%s" % (error.code, detail))
    except (urllib.error.URLError, OSError) as error:
        raise ComfyError("連不到 ComfyUI（%s）：%s。ComfyUI 有開嗎？" % (base, error))
    return payload if raw else json.loads(payload.decode("utf-8") or "{}")


def load_workflow(path=None):
    return json.loads(Path(path or DEFAULT_WORKFLOW).read_text(encoding="utf-8"))


def _sampler(wf):
    found = [nid for nid, node in wf.items() if node.get("class_type") == "KSampler"]
    if len(found) != 1:
        raise ComfyError("workflow 要剛好有一個 KSampler（目前 %d 個）" % len(found))
    return found[0]


def prepare(wf, positive, negative, seed, width, height, models=None, prefix="text2comics/panel"):
    """回傳 (修改後的 workflow, 輸出節點 id)。不改動傳入的 wf。"""
    wf = copy.deepcopy(wf)
    sid = _sampler(wf)
    ins = wf[sid]["inputs"]
    ins["seed"] = int(seed)
    for key, text in (("positive", positive), ("negative", negative)):
        nid = ins[key][0]
        node = wf[nid]
        if node["class_type"] == "CLIPTextEncode":
            node["inputs"]["text"] = text
        elif node["class_type"] != "ConditioningZeroOut":   # CFG 1 時負向可以換成 ConditioningZeroOut
            raise ComfyError("KSampler 的 %s 要接 CLIPTextEncode（目前是 %s）" % (key, node["class_type"]))
    latent = wf[ins["latent_image"][0]]["inputs"]
    latent["width"], latent["height"] = int(width), int(height)
    if "batch_size" in latent:
        latent["batch_size"] = 1
    for node in wf.values():
        cls = node.get("class_type")
        name = (models or {}).get(MODEL_KEYS.get(cls, ""), "")
        if cls in LOADERS and name:
            node["inputs"][LOADERS[cls]] = name
        if cls in LOADERS and not node["inputs"].get(LOADERS[cls]):
            raise ComfyError("%s 沒有設定模型檔名（config.json 的 comfy.models）" % cls)
    outputs = [nid for nid, node in wf.items() if node.get("class_type") in ("SaveImage", "PreviewImage")]
    if not outputs:
        raise ComfyError("workflow 裡沒有 SaveImage／PreviewImage")
    wf[outputs[0]]["inputs"]["filename_prefix"] = prefix
    if wf[outputs[0]]["class_type"] == "PreviewImage":
        wf[outputs[0]]["inputs"].pop("filename_prefix")
    return wf, outputs[0]


def run(base, wf, out_id, should_stop=lambda: False, timeout=1800):
    """送出並等待，回傳第一張圖的 bytes。"""
    result = _req(base, "/prompt", {"prompt": wf, "client_id": uuid.uuid4().hex})
    if result.get("node_errors"):
        raise ComfyError("workflow 有錯：%s" % json.dumps(result["node_errors"], ensure_ascii=False)[:800])
    pid = result.get("prompt_id")
    if not pid:
        raise ComfyError("ComfyUI 沒有回傳任務編號")
    start = time.time()
    while True:
        if should_stop():
            _req(base, "/interrupt", {"prompt_id": pid})
            raise ComfyError("已停止")
        entry = _req(base, "/history/" + urllib.parse.quote(pid), timeout=10).get(pid)
        if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                messages = [m[1] for m in status.get("messages") or [] if m and m[0] == "execution_error"]
                detail = messages[0].get("exception_message", "") if messages else ""
                raise ComfyError("ComfyUI 執行失敗：%s" % detail)
            images = ((entry.get("outputs") or {}).get(out_id) or {}).get("images") or []
            if images:
                image = images[0]
                query = urllib.parse.urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""),
                                                "type": image.get("type", "output")})
                return _req(base, "/view?" + query, timeout=60, raw=True)
            if status.get("completed"):
                raise ComfyError("ComfyUI 完成了，但沒有輸出圖片")
        if time.time() - start > timeout:
            raise ComfyError("等太久了（超過 %d 分鐘）" % (timeout // 60))
        time.sleep(1.0)
