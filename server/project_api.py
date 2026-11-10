"""專案與章節：總覽、新建、環境檢查、原著／規劃／劇本／分鏡的讀寫、圖片、選圖。"""
import threading
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, Response
from PIL import Image

from fekit import ApiError

from t2c import comfy, compose, export, gpu, importer, layout, llm, render, stale, styles, workspace

from .common import SAMPLE, body_project, chapter, config, guard
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
    """新建專案。style_preset 是畫風預設集（mono／color／american）；style 是舊的自訂畫風字串。"""
    params = {}
    if str(body.get("style_preset") or "").strip():
        params["preset"] = str(body["style_preset"]).strip()
    with guard("create_failed"):
        proj = workspace.create_project(body.get("path"), str(body.get("title") or ""), str(body.get("style") or ""),
                                        sample=SAMPLE if body.get("from_sample") else None,
                                        sample_renders=bool(body.get("sample_renders")), **params)
        return {"root": str(proj.root), "overview": workspace.overview(proj)}


@router.get("/api/styles")
def style_presets():
    """畫風預設集清單（畫風只有 t2c/data/styles.json 這一份來源）。"""
    with guard("no_styles"):
        return {"presets": [{"name": name, "label": styles.preset(name)["name"]} for name in styles.names()],
                "default": styles.default_name()}


@router.post("/api/project/style")
def project_style(body: dict = Body(...)):
    """換這部作品的畫風：改 project.yaml 的 style_preset，並拿掉明寫的 style／meta（會蓋掉預設集）。"""
    proj = body_project(body)
    with guard("style_failed"):
        result = workspace.set_style_preset(proj, body.get("preset"))
    proj = _open(str(proj.root))
    with guard():
        resolved = styles.resolve(proj.config)
        return {"path": result["path"], "preset": resolved["preset"], "dropped": result["dropped"],
                "resolved": {"name": resolved["name"], "style": resolved["style"], "meta": resolved["meta"]},
                "overview": workspace.overview(proj)}


# ---- 整本匯入切章（N2 的核心，介面入口在 N7） ----------------------------------------

def _import_paths(body):
    raw = body.get("paths") if isinstance(body.get("paths"), list) else [body.get("path")]
    paths = [Path(str(p)) for p in raw if str(p or "").strip()]
    if not paths:
        raise ApiError(400, "請先選要匯入的檔案（.txt／.md／.docx）", "bad_path")
    return paths


_IMPORT_OPTIONS = ("mode", "lang", "numbering", "start", "preface_as_chapter", "preface_title", "convert", "conflict")


def _import_opts(body):
    return {key: body[key] for key in _IMPORT_OPTIONS if key in body and body[key] not in (None, "")}


@router.post("/api/import/plan")
def import_plan(body: dict = Body(...)):
    """整本匯入：先切章預覽，不寫任何檔案。"""
    with guard("import_failed"):
        return importer.preview(_import_paths(body), _import_opts(body))


@router.post("/api/import/commit")
def import_commit(body: dict = Body(...)):
    """整本匯入：寫進專案的 source/chNNN.txt（conflict＝skip／overwrite，覆寫前會備份）。"""
    proj = body_project(body)
    with guard("import_failed"):
        result = importer.commit(proj, _import_paths(body), _import_opts(body))
    result["overview"] = workspace.overview(_open(str(proj.root)))
    return result


@router.get("/api/env")
def env(project: str = "", profile: str = ""):
    """環境檢查：ComfyUI、各 provider 的金鑰與本機伺服器、出圖預設、字型。

    presets／default_preset 跟著「這一章的 profile」（project.yaml 的 comfy_profile →
    config.json 的 default_profile）；沒有 comfy.profiles 的舊設定才用頂層的 presets。
    專案路徑壞掉時當成沒開專案（設定頁與環境檢查不該因此打不開）。
    """
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
    prof = _chapter_profile(cfg, _maybe_project(project))
    if str(profile or "").strip():                 # 介面換 profile 時，presets 也要跟著換
        try:
            prof = comfy.resolve_profile(cfg, name=profile)
        except comfy.ComfyError as error:
            raise ApiError(400, str(error), "bad_profile")
    table, default = _presets(cfg, prof)
    comfy_block = {"url": comfy_cfg.get("url", ""), "ok": stats is not None, "vram": gpu.vram_summary(stats),
                   "profiles": _profile_info(cfg), "default_profile": _default_profile(cfg),
                   "profile": (prof or {}).get("name", ""), "kind": (prof or {}).get("kind", ""),
                   "unet": ((prof or {}).get("models") or {}).get("unet", "")}
    return {"config_path": cfg.get("_path", ""), "comfy": comfy_block,
            "providers": providers, "stages": stages, "presets": table, "default_preset": default}


def _maybe_project(path):
    """沒開專案、或路徑壞掉就回 None（當成使用 config.json 的 default_profile）。"""
    if not str(path or "").strip():
        return None
    try:
        return open_project(path)
    except ApiError:
        return None


def _chapter_profile(cfg, proj):
    """這一章要用哪一組 profile；設定壞掉回 None（呼叫端退回舊的頂層 presets）。"""
    try:
        return comfy.resolve_profile(cfg, project_config=(proj.config if proj is not None else None))
    except comfy.ComfyError:
        return None


def _profile_info(cfg):
    """出圖 profile 清單（含 kind 與 unet 檔名）：[{"name","kind","unet"}]。

    沒有 comfy.profiles 的舊設定也回一組 moss，介面不用分兩種情況。
    """
    try:
        names = list(comfy.profile_table(cfg)) or [comfy.LEGACY_PROFILE]
    except comfy.ComfyError:
        return []
    rows = []
    for name in names:
        try:
            prof = comfy.resolve_profile(cfg, name=name)
        except comfy.ComfyError:
            rows.append({"name": name, "kind": "", "unet": ""})
            continue
        rows.append({"name": name, "kind": prof["kind"], "unet": (prof.get("models") or {}).get("unet", "")})
    return rows


def _presets(cfg, profile=None):
    """出圖預設的清單與預設名稱（來自 profile，N4）；設定壞掉時退回舊的頂層 presets，讓介面還開得起來。"""
    try:
        prof = profile if profile is not None else comfy.resolve_profile(cfg)
        table = list(prof["presets"])
        return table, prof["default_preset"] or (table[0] if table else "")
    except comfy.ComfyError:
        comfy_cfg = cfg.get("comfy") or {}
        table = [k for k in (comfy_cfg.get("presets") or {}) if not k.startswith("_")]
        return table, comfy_cfg.get("default_preset") or (table[0] if table else "")


def _profile_names(cfg):
    try:
        return list(comfy.profile_table(cfg))
    except comfy.ComfyError:
        return []


def _default_profile(cfg):
    try:
        return comfy.default_profile_name(cfg)
    except comfy.ComfyError:
        return ""


def _project_profile(cfg, proj):
    """這一章要用哪一組 profile（project.yaml 的 comfy_profile → config.json 的 default_profile）。"""
    try:
        return comfy.resolve_profile(cfg, project_config=proj.config)
    except comfy.ComfyError as error:
        raise ApiError(400, str(error), "bad_profile")


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


# ---- 切對話（N3／步驟 3）--------------------------------------------------------

@router.get("/api/chapter/scenes")
def scenes_get(project: str = "", chapter_no: int = Query(1, alias="chapter")):
    """scenes/chNNN.json 與忠實度報告（build/adapt/chNNN_scenes_fidelity.md）。沒有就是 scenes: null。"""
    proj, n = _open(project), chapter(chapter_no)
    with guard():
        doc = proj.load_scenes(n)
        path = proj.scenes_path(n)
    report = proj.root / "build" / "adapt" / ("ch%03d_scenes_fidelity.md" % n)
    text = report.read_text(encoding="utf-8") if report.is_file() else ""
    return {"path": str(path), "scenes": doc, "fidelity": text, "exists": doc is not None}


# ---- 規劃 ------------------------------------------------------------------------

@router.get("/api/chapter/plan")
def plan_get(project: str = "", chapter_no: int = Query(1, alias="chapter")):
    proj, n = _open(project), chapter(chapter_no)
    with guard():
        data = workspace.read_plan(proj, n)
    data["templates"] = {k: {"name": t.get("name", k), "panels": len(t["panels"])} for k, t in proj.pages()["templates"].items()}
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
    pages_data = proj.pages()
    info = proj.layout_info()
    from_project = set(info.get("templates") or [])
    return {
        "characters": [{"id": cid, "name": c.get("name", cid), "outfits": list((c.get("outfits") or {"default": ""}).keys())}
                       for cid, c in proj.characters.items()],
        "locations": [{"id": lid, "name": c.get("name", lid)} for lid, c in proj.locations.items()],
        "templates": {k: {"name": t.get("name", k), "panels": t["panels"], "source": "project" if k in from_project else "builtin"}
                      for k, t in pages_data["templates"].items()},
        "layout": info,
        "page": {k: pages_data["page"][k] for k in ("width_mm", "height_mm")},
        "shots": list(SHOT), "angles": list(ANGLE),
        "bubble_kinds": ["speech", "thought", "shout", "whisper", "radio", "narration"] if BUBBLE_KINDS else [],
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


@router.post("/api/chapter/character/remap")
def character_remap(body: dict = Body(...)):
    """「對應到既有卡片」：只動這一章（D10）；remember_alias 時順便記進卡片的別名（D11）。"""
    proj, n = body_project(body), chapter(body.get("chapter"))
    with guard("bad_character"):
        return workspace.remap_character(proj, n, body.get("from"), body.get("to"),
                                         remember_alias=body.get("remember_alias") is True)


@router.post("/api/chapter/character/extra")
def character_extra(body: dict = Body(...)):
    """「標為臨時角色」：分鏡寫 extra: true（D9），這一格就能出圖與選圖，不佔聖經的位置。"""
    proj, n = body_project(body), chapter(body.get("chapter"))
    with guard("bad_character"):
        return workspace.mark_extra(proj, n, body.get("from"))


@router.post("/api/chapter/character/drop")
def character_drop(body: dict = Body(...)):
    """「從這一格移除」：拿掉 characters[]，他說的對話框改成旁白。"""
    proj, n = body_project(body), chapter(body.get("chapter"))
    with guard("bad_character"):
        return workspace.drop_character(proj, n, body.get("from"))


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
def panels(project: str = "", chapter_no: int = Query(1, alias="chapter"), profile: str = ""):
    """出圖分頁的資料。profile 指定時，presets／default_preset 換成那一組的（介面臨時換 profile 用），
    project_profile 仍然是這一章的預設（project.yaml 的 comfy_profile → config.json 的 default_profile）。

    每一格多兩個欄位（步驟 2）：explore 是這一格用到、但還沒有卡片的角色 id；stale 是這一格在過期清單裡。"""
    proj, n = _open(project), chapter(chapter_no)
    with guard():
        data = workspace.panels_status(proj, n)
        jobs = render.chapter_jobs(proj, n)
        stale_ids = {row["id"] for row in stale.chapter(proj, n, jobs=jobs)}
    explore = {job["id"]: list(job.get("explore") or []) for job in jobs}
    unresolved = {job["id"]: list(job.get("unresolved") or []) for job in jobs}
    data["panels"] = [dict(row, explore=explore.get(row["id"], []),
                           unresolved=unresolved.get(row["id"], []), stale=row["id"] in stale_ids)
                      for row in data["panels"]]
    cfg = config()
    chapter_profile = _project_profile(cfg, proj)
    viewed = chapter_profile
    if str(profile or "").strip():
        try:
            viewed = comfy.resolve_profile(cfg, name=profile)
        except comfy.ComfyError as error:
            raise ApiError(400, str(error), "bad_profile")
    data["presets"], data["default_preset"] = _presets(cfg, viewed)
    data["profiles"] = _profile_names(cfg) or [viewed["name"]]
    data["default_profile"] = _default_profile(cfg)
    data["project_profile"] = chapter_profile["name"]
    data["profile"] = viewed["name"]
    data["kind"] = viewed["kind"]
    data["profile_info"] = _profile_info(cfg)
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
    size = layout.page_size(proj.pages()["page"])
    return {"pages": rows, "size": list(size), "layout": proj.layout_info(), "export": _export_status(proj, n)}


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
