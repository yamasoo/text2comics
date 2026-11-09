"""專案與章節：總覽、新建、環境檢查、原著／規劃／劇本／分鏡的讀寫、圖片、選圖。"""
import threading
from collections import OrderedDict
from io import BytesIO

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, Response
from PIL import Image

from fekit import ApiError

from t2c import compose, export, gpu, layout, llm, workspace

from .common import body_project, chapter, config, guard
from .common import project as open_project

router = APIRouter()

IMAGE_DIRS = {"renders", "pages", "build"}
IMAGE_EXT = {".png", ".jpg", ".jpeg"}
_THUMBS = OrderedDict()
_THUMBS_MAX = 400
_LOCK = threading.Lock()


# ---- 專案 ------------------------------------------------------------------------

@router.get("/api/project")
def project_overview(project: str = ""):
    proj = _open(project)
    with guard():
        return workspace.overview(proj)


def _open(path):
    return open_project(path)


@router.post("/api/project/create")
def project_create(body: dict = Body(...)):
    with guard("create_failed"):
        proj = workspace.create_project(body.get("path"), str(body.get("title") or ""), str(body.get("style") or ""),
                                        from_sample=bool(body.get("from_sample")), sample_renders=bool(body.get("sample_renders")))
        return {"root": str(proj.root), "overview": workspace.overview(proj)}


@router.get("/api/env")
def env():
    """環境檢查：ComfyUI、各 provider 的金鑰與本機伺服器、出圖預設、字型。"""
    cfg = config()
    comfy_cfg = cfg.get("comfy") or {}
    stats = gpu.comfy_stats(comfy_cfg.get("url") or "http://127.0.0.1:8188")
    stages = {}
    for stage in ("adapt", "script", "storyboard", "bible"):
        prov = gpu.stage_provider(cfg, stage)
        stages[stage] = prov.get("id") if prov else ""
    providers = []
    for prov in cfg.get("providers") or []:
        if not isinstance(prov, dict):
            continue
        local = gpu.is_local(prov)
        providers.append({"id": prov.get("id"), "name": prov.get("name") or prov.get("id"), "model": prov.get("model") or "",
                          "local": local, "needs_key": bool(prov.get("key_env")) and not local,
                          "has_key": bool(llm.api_key(prov)) if prov.get("key_env") else True,
                          "key_env": prov.get("key_env") or "",
                          "running": gpu.llm_running(prov, 1.0) if local else None})
    table, default = _presets(cfg)
    return {"config_path": cfg.get("_path", ""),
            "comfy": {"url": comfy_cfg.get("url", ""), "ok": stats is not None, "vram": gpu.vram_summary(stats)},
            "providers": providers, "stages": stages, "presets": table, "default_preset": default}


def _presets(cfg):
    comfy_cfg = cfg.get("comfy") or {}
    table = [k for k in (comfy_cfg.get("presets") or {}) if not k.startswith("_")]
    return table, comfy_cfg.get("default_preset") or (table[0] if table else "")


# ---- 圖片 ------------------------------------------------------------------------

def _image_path(proj, rel):
    rel = str(rel or "").replace("\\", "/").strip("/")
    parts = rel.split("/")
    if not rel or parts[0] not in IMAGE_DIRS or ".." in parts:
        raise ApiError(400, "只能讀專案的 renders/、pages/、build/ 裡的圖", "bad_path")
    path = (proj.root / rel).resolve()
    if proj.root not in path.parents or path.suffix.lower() not in IMAGE_EXT:
        raise ApiError(400, "只能讀專案裡的 PNG／JPEG", "bad_path")
    if not path.is_file():
        raise ApiError(404, "找不到圖：%s" % rel, "not_found")
    return path


@router.get("/api/image")
def image(project: str = "", path: str = "", w: int = 0):
    """專案裡的圖；w > 0 時回傳寬 w 的 JPEG 縮圖（記憶體快取，原圖改了就重做）。"""
    proj = _open(project)
    src = _image_path(proj, path)
    if w <= 0:
        return FileResponse(src, headers={"Cache-Control": "no-cache"})
    w = max(64, min(int(w), 1600))
    key = (str(src), src.stat().st_mtime_ns, w)
    with _LOCK:
        data = _THUMBS.get(key)
        if data is not None:
            _THUMBS.move_to_end(key)
    if data is None:
        try:
            with Image.open(src) as img:
                img.draft("RGB", (w, w * 4))
                img = img.convert("RGB")
                img.thumbnail((w, w * 4), Image.LANCZOS)
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                data = buffer.getvalue()
        except OSError as error:
            raise ApiError(400, "讀不了圖 %s（%s）" % (src.name, error), "bad_image")
        with _LOCK:
            _THUMBS[key] = data
            while len(_THUMBS) > _THUMBS_MAX:
                _THUMBS.popitem(last=False)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ---- 原著 ------------------------------------------------------------------------

@router.get("/api/chapter/source")
def source_get(project: str = "", chapter_no: int = Query(1, alias="chapter")):
    proj, n = _open(project), chapter(chapter_no)
    with guard():
        data = workspace.read_source(proj, n)
    data["chars"] = len(workspace.source_body(data["text"]))
    data["tokens"] = llm.estimate_tokens(workspace.source_body(data["text"]))
    return data


@router.post("/api/chapter/source")
def source_save(body: dict = Body(...)):
    proj, n = body_project(body), chapter(body.get("chapter"))
    with guard("save_failed"):
        if body.get("path"):
            path = workspace.import_source_file(proj, n, body["path"])
        else:
            path = workspace.save_source(proj, n, body.get("text"))
    return {"path": str(path)}


# ---- 規劃 ------------------------------------------------------------------------

@router.get("/api/chapter/plan")
def plan_get(project: str = "", chapter_no: int = Query(1, alias="chapter")):
    proj, n = _open(project), chapter(chapter_no)
    with guard():
        data = workspace.read_plan(proj, n)
    data["templates"] = {k: {"name": t.get("name", k), "panels": len(t["panels"])} for k, t in layout.load_pages()["templates"].items()}
    return data


@router.post("/api/chapter/plan")
def plan_save(body: dict = Body(...)):
    proj, n = body_project(body), chapter(body.get("chapter"))
    with guard("save_failed"):
        path, issues = workspace.save_plan(proj, n, body.get("plan"))
    return {"path": str(path), "issues": issues}


# ---- 劇本 ------------------------------------------------------------------------

@router.get("/api/chapter/script")
def script_get(project: str = "", chapter_no: int = Query(1, alias="chapter")):
    proj, n = _open(project), chapter(chapter_no)
    with guard():
        return workspace.read_script(proj, n)


@router.post("/api/chapter/script")
def script_save(body: dict = Body(...)):
    proj, n = body_project(body), chapter(body.get("chapter"))
    with guard("save_failed"):
        path, issues = workspace.save_script(proj, n, body.get("text"))
    return {"path": str(path), "issues": issues}


# ---- 分鏡 ------------------------------------------------------------------------

def _vocab(proj):
    """分鏡編輯器要的選單：角色（含服裝）、地點、模板、鏡頭、角度、對話框種類。"""
    from t2c.compile import ANGLE, BUBBLE_KINDS, SHOT
    pages_data = layout.load_pages()
    return {
        "characters": [{"id": cid, "name": c.get("name", cid), "outfits": list((c.get("outfits") or {"default": ""}).keys())}
                       for cid, c in proj.characters.items()],
        "locations": [{"id": lid, "name": c.get("name", lid)} for lid, c in proj.locations.items()],
        "templates": {k: {"name": t.get("name", k), "panels": t["panels"]} for k, t in pages_data["templates"].items()},
        "page": {k: pages_data["page"][k] for k in ("width_mm", "height_mm")},
        "shots": list(SHOT), "angles": list(ANGLE),
        "bubble_kinds": ["speech", "thought", "shout", "whisper", "narration"] if BUBBLE_KINDS else [],
    }


@router.get("/api/chapter/storyboard")
def storyboard_get(project: str = "", chapter_no: int = Query(1, alias="chapter")):
    proj, n = _open(project), chapter(chapter_no)
    with guard():
        data = workspace.read_storyboard(proj, n)
    data["vocab"] = _vocab(proj)
    return data


@router.post("/api/chapter/storyboard")
def storyboard_save(body: dict = Body(...)):
    proj, n = body_project(body), chapter(body.get("chapter"))
    with guard("save_failed"):
        path, board, issues = workspace.save_storyboard(proj, n, body.get("storyboard"))
    return {"path": str(path), "storyboard": board, "issues": issues}


@router.post("/api/chapter/prompt")
def panel_prompt(body: dict = Body(...)):
    """編譯一格（可以是還沒存的分鏡），回傳送給 MOSS 的 layout 與生圖尺寸。"""
    proj, n = body_project(body), chapter(body.get("chapter"))
    with guard("compile_failed"):
        job = workspace.compile_one(proj, n, str(body.get("panel") or ""), body.get("storyboard"))
    return {"id": job["id"], "width": job["width"], "height": job["height"], "layout": job["layout"],
            "negative": job["negative"], "seeds": job["seeds"], "rect_px": job["rect_px"]}


# ---- 出圖與選圖 --------------------------------------------------------------------

@router.get("/api/chapter/panels")
def panels(project: str = "", chapter_no: int = Query(1, alias="chapter")):
    proj, n = _open(project), chapter(chapter_no)
    with guard():
        data = workspace.panels_status(proj, n)
    cfg = config()
    data["presets"], data["default_preset"] = _presets(cfg)
    data["renders"] = "renders/%s" % compose.chapter_name(n)
    return data


@router.post("/api/chapter/pick")
def pick(body: dict = Body(...)):
    proj, n = body_project(body), chapter(body.get("chapter"))
    with guard("pick_failed"):
        entry = workspace.set_pick(proj, n, str(body.get("panel") or ""), image=body.get("image"), focus=body.get("focus"),
                                   zoom=body.get("zoom"), clear=bool(body.get("clear")))
    return {"pick": entry}


@router.get("/api/chapter/crop.jpg")
def crop_preview(project: str = "", chapter_no: int = Query(1, alias="chapter"), panel: str = "", image: str = "", fx: float = 0.5, fy: float = 0.5,
                 zoom: float = 1.0, w: int = 480):
    """一格裁切後的樣子（調焦點、放大時預覽；不寫檔）。"""
    proj, n = _open(project), chapter(chapter_no)
    with guard("crop_failed"):
        job = workspace.compile_one(proj, n, panel)
        entry = compose.check_pick(panel, {"image": image, "focus": [fx, fy], "zoom": zoom})
    src = _image_path(proj, "renders/%s/%s" % (compose.chapter_name(n), entry["image"]))
    rect = job["rect_px"]
    cell = (rect[2] - rect[0], rect[3] - rect[1])
    w = max(64, min(int(w), 1200))
    size = (w, max(1, round(w * cell[1] / cell[0])))
    with Image.open(src) as img:
        tile = compose.crop_cover(img.convert("L"), size, entry["focus"], entry["zoom"])
    buffer = BytesIO()
    tile.save(buffer, format="JPEG", quality=85)
    return Response(buffer.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/api/chapter/pages")
def pages(project: str = "", chapter_no: int = Query(1, alias="chapter")):
    """頁面分頁：每頁的模板、格數、已輸出的 PNG。"""
    proj, n = _open(project), chapter(chapter_no)
    with guard():
        board = proj.load_storyboard(n)
    out_dir = compose.pages_dir(proj, n)
    rows = []
    for page in board.get("pages") or []:
        png = out_dir / ("p%03d.png" % int(page["page"]))
        rows.append({"page": int(page["page"]), "template": page.get("template"), "panels": len(page.get("panels") or []),
                     "png": "pages/%s/%s" % (compose.chapter_name(n), png.name) if png.is_file() else "",
                     "mtime": png.stat().st_mtime if png.is_file() else 0})
    size = layout.page_size(layout.load_pages()["page"])
    return {"pages": rows, "size": list(size), "export": _export_status(proj, n)}


def _export_status(proj, n):
    """能不能下載 PDF／CBZ：頁面 PNG 要齊；PNG 比分鏡、選圖或嵌字舊就列提醒。"""
    try:
        _, warnings = export.chapter_pages(proj, n)
    except export.ExportError as error:
        return {"ready": False, "message": str(error), "warnings": []}
    return {"ready": True, "message": "", "warnings": warnings}


@router.get("/api/chapter/export")
def export_download(project: str = "", chapter_no: int = Query(1, alias="chapter"), format: str = "pdf", page: int = 0,
                    quality: int = 0, lossless: bool = False, single: bool = False):
    """下載整章（或 page 這一頁）的 PDF／CBZ（右翻）。同時存一份在專案的 out/。"""
    proj, n = _open(project), chapter(chapter_no)
    with guard("export_failed"):
        path, _ = export.export_chapter(proj, n, format, page=page or None, spread=not single,
                                        quality=None if lossless else (quality or export.DEFAULT_QUALITY))
    media = "application/pdf" if path.suffix == ".pdf" else "application/vnd.comicbook+zip"
    return FileResponse(path, media_type=media, filename=path.name, headers={"Cache-Control": "no-store"})
