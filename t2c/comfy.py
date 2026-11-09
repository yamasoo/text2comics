"""最小的 ComfyUI API 客戶端（只用標準函式庫）。

workflow 用 API 格式（ComfyUI 選單 Export (API)），預設是套件自帶的 t2c/data/moss_layout.api.json（見 workflow_path）。
要改的節點從 KSampler 往回追：positive／negative 的 CLIPTextEncode、latent 的寬高、seed；
模型檔名照 config.json 的 comfy.models 覆蓋。步數、CFG、取樣器預設照 workflow；
傳入 preset（config.json 的 comfy.presets 其中一組）就覆蓋，並可在模型後面接一個 LoRA（見 apply_preset）。

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

DEFAULT_WORKFLOW = Path(__file__).resolve().parent / "data" / "moss_layout.api.json"
# 舊的 config.json 寫的是工具資料夾裡的相對路徑；那個檔案已搬進套件，照舊寫法也指到內建的
LEGACY_WORKFLOWS = {"workflows/moss_layout.api.json", "./workflows/moss_layout.api.json"}
LOADERS = {"UNETLoader": "unet_name", "CLIPLoader": "clip_name", "VAELoader": "vae_name"}
MODEL_KEYS = {"UNETLoader": "unet", "CLIPLoader": "clip", "VAELoader": "vae"}


PRESET_KEYS = {"steps": "steps", "cfg": "cfg", "sampler": "sampler_name", "scheduler": "scheduler"}
PRESET_OTHER = {"lora", "lora_strength", "note"}
LORA_NODE_ID = "t2c_lora"


class ComfyError(Exception):
    """給人看的錯誤訊息。"""


def apply_preset(wf, preset):
    """把出圖預設套到 workflow（就地修改）：steps、cfg、sampler、scheduler，以及可選的 lora。

    preset 例：{"steps": 4, "cfg": 1.0, "sampler": "euler", "scheduler": "simple",
                "lora": "ANIMA\\\\moss_image_sft_4step_v2.0.safetensors", "lora_strength": 1.0}
    lora 用 ComfyUI 列出的名稱（含子資料夾）；套用方式是在 KSampler 的 model 前面接一個 LoraLoaderModelOnly。
    """
    if not preset:
        return wf
    unknown = set(preset) - set(PRESET_KEYS) - PRESET_OTHER
    if unknown:
        raise ComfyError("出圖預設有不認得的欄位：%s（可用：%s）" % ("、".join(sorted(unknown)), "、".join(sorted(set(PRESET_KEYS) | PRESET_OTHER))))
    ins = wf[_sampler(wf)]["inputs"]
    try:
        for key, target in PRESET_KEYS.items():
            if key in preset:
                ins[target] = int(preset[key]) if key == "steps" else float(preset[key]) if key == "cfg" else str(preset[key])
    except (TypeError, ValueError):
        raise ComfyError("出圖預設的 steps 要是整數、cfg 要是數字：%r" % {k: preset[k] for k in ("steps", "cfg") if k in preset})
    if preset.get("lora"):
        wf[LORA_NODE_ID] = {"class_type": "LoraLoaderModelOnly", "_meta": {"title": "LoRA（出圖預設）"},
                            "inputs": {"model": ins["model"], "lora_name": str(preset["lora"]),
                                       "strength_model": float(preset.get("lora_strength", 1.0))}}
        ins["model"] = [LORA_NODE_ID, 0]
    return wf


def render_name(panel_id, seed, preset_name=None, default_preset=None):
    """出圖檔名：<格 id>_s<seed>.png；用的不是預設的出圖預設時，加 _<預設名>，避免同一個 seed 的草稿蓋掉定稿。"""
    suffix = "_%s" % preset_name if preset_name and preset_name != default_preset else ""
    return "%s_s%d%s.png" % (panel_id, int(seed), suffix)


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


def workflow_path(cfg):
    """工具設定（settings.load() 的結果）裡 comfy.workflow 指的檔案。
    空的、或舊寫法 workflows/moss_layout.api.json → 套件自帶的；相對路徑以 config.json 所在資料夾為準。"""
    spec = str(((cfg or {}).get("comfy") or {}).get("workflow") or "").strip()
    if not spec or spec.replace("\\", "/") in LEGACY_WORKFLOWS:
        return DEFAULT_WORKFLOW
    path = Path(spec).expanduser()
    if not path.is_absolute():
        base = Path(cfg["_path"]).resolve().parent if cfg.get("_path") else Path.cwd()
        path = base / path
    if not path.is_file():
        raise ComfyError("找不到 workflow：%s（config.json 的 comfy.workflow；留空就用內建的）" % path)
    return path


def config_workflow(cfg):
    """依工具設定載入 workflow。"""
    return load_workflow(workflow_path(cfg))


def _sampler(wf):
    found = [nid for nid, node in wf.items() if node.get("class_type") == "KSampler"]
    if len(found) != 1:
        raise ComfyError("workflow 要剛好有一個 KSampler（目前 %d 個）" % len(found))
    return found[0]


def prepare(wf, positive, negative, seed, width, height, models=None, prefix="text2comics/panel", preset=None):
    """回傳 (修改後的 workflow, 輸出節點 id)。不改動傳入的 wf。preset 見 apply_preset。"""
    wf = copy.deepcopy(wf)
    apply_preset(wf, preset)
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
