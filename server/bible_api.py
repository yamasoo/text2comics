"""視覺聖經：卡片（定案與草稿）的讀寫、確認入庫、定裝圖候選與挑選、過期清單。抽取與出圖任務在 tasks.py。"""
import re

from fastapi import APIRouter, Body, Query

from fekit import ApiError

from t2c import bible, bible_check, look, stale
from t2c.project import ID_RE, ProjectError, read_front_matter
from t2c.script import Issue, errors

from .common import body_project, guard
from .common import chapter as chapter_no
from .common import project as open_project

router = APIRouter()
KINDS = ("character", "location")
NEW_CARD = {
    "character": "---\nid: {id}\nname: {name}\naliases: []\nstatus: draft\nlook_en: >-\n  \noutfits:\n  default: >-\n    \n---\n\n"
                 "（手動新增的角色。look_en 寫固定的英文外觀：年齡、性別、髮型、臉、體型；服裝寫在 outfits，以 He/She wears 開頭。）\n",
    "location": "---\nid: {id}\nname: {name}\naliases: []\nstatus: draft\nlook_en: >-\n  \n---\n\n（手動新增的地點。look_en 寫固定的英文場景描述，不要寫人物。）\n",
}


def _kind(value):
    if value not in KINDS:
        raise ApiError(400, "kind 要是 character 或 location", "bad_kind")
    return value


def _issues(issues):
    return [{"level": i.level, "where": i.where, "message": i.message} for i in issues]


def _card_path(proj, kind, cid, draft):
    if not ID_RE.match(str(cid or "")):
        raise ApiError(400, "id 只能用 a-z、0-9、底線、連字號", "bad_id")
    return bible.cards_dir(proj, kind, drafts=draft) / ("%s.md" % cid)


@router.get("/api/bible")
def overview(project: str = ""):
    """全部卡片（定案＋草稿）的摘要與檢查結果、定裝圖狀態、規劃裡缺卡的人物。"""
    proj = open_project(project)
    cards = []
    with guard():
        for kind_label, path, issues in bible.lint(proj):
            kind = "character" if kind_label.startswith("character") else "location"
            draft = "草稿" in kind_label
            try:
                meta, body = read_front_matter(path)
            except ProjectError:
                meta, body = {}, ""
            cards.append({"kind": kind, "draft": draft, "id": str(meta.get("id") or path.stem), "file": path.stem,
                          "name": str(meta.get("name") or path.stem), "aliases": [str(a) for a in meta.get("aliases") or []],
                          "look_en": look.look_en(meta),
                          "outfits": {str(k): " ".join(str(v or "").split()) for k, v in (meta.get("outfits") or {}).items()},
                          "outfit_notes": {str(k): str(v) for k, v in (meta.get("outfit_notes") or {}).items()},
                          "pending": "## 待確認" in body, "issues": _issues(issues)})
        status = bible.status(proj)
    return {"cards": cards, "status": status}


@router.get("/api/bible/card")
def card_get(project: str = "", kind: str = "character", id: str = "", draft: bool = False):
    proj = open_project(project)
    path = _card_path(proj, _kind(kind), id, draft)
    if not path.is_file():
        raise ApiError(404, "找不到卡片：%s" % path, "not_found")
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    try:
        meta, body = read_front_matter(path)
        issues = bible_check.check_card(meta, kind)
    except ProjectError as error:
        meta, body, issues = {}, text, [Issue("error", path.name, str(error))]
    return {"path": str(path), "text": text, "body": body, "issues": _issues(issues),
            "signature_used": bool(not draft and _picked(proj, kind, id))}


def _picked(proj, kind, cid):
    picks = bible.load_picks(proj)
    return (picks["characters"] if kind == "character" else picks["locations"]).get(cid)


@router.post("/api/bible/card/sections")
def card_sections(body: dict = Body(...)):
    """分段編輯器存檔：只換 frontmatter 的 sections／outfits，本文（人看的說明）照舊。
    走 t2c/bible.apply_sections()，規則檢查與 card_save 同一套：定案卡片有 error 就擋。"""
    proj = body_project(body)
    kind = _kind(body.get("kind"))
    cid, draft = str(body.get("id") or ""), bool(body.get("draft"))
    sections = body.get("sections")
    outfits = body.get("outfits")
    if sections is None and outfits is None:
        raise ApiError(400, "沒有東西可以存：請帶 sections 或 outfits", "bad_card")
    if sections is not None and not isinstance(sections, dict):
        raise ApiError(400, "sections 要是 {段名: [英文短語…]}", "bad_card")
    if outfits is not None and not isinstance(outfits, dict):
        raise ApiError(400, "outfits 要是 {服裝 id: {top: […], bottom: […], set: […], notes: 中文}}", "bad_card")
    try:
        result = bible.apply_sections(proj, kind, cid, sections=sections, outfits=outfits, draft=draft, write=False)
    except bible.BibleError as error:
        raise ApiError(400, str(error), "bad_card")
    except ProjectError as error:
        raise ApiError(400, str(error), "bad_card")
    issues = result["issues"]
    if not draft:
        errs = errors(issues)
        if errs:
            raise ApiError(400, "定案卡片不能有錯誤（分鏡編譯要用）：\n%s" % "\n".join("  - %s" % e for e in errs), "bad_card")
    path = result["path"]
    text = result["text"]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text if text.endswith("\n") else text + "\n")
    return {"path": path, "text": text, "issues": _issues(issues), "stale": result["stale"]}


@router.post("/api/bible/card/split")
def card_split(body: dict = Body(...)):
    """舊卡片（只有 look_en／整句服裝）→ 分段草稿。**不寫檔**：只是把拆好的內容回給介面填進輸入框，
    人看過、改過再按「儲存分段」。文字規則寫在 t2c/bible.split_look()。"""
    proj = body_project(body)
    kind = _kind(body.get("kind"))
    cid, draft = str(body.get("id") or ""), bool(body.get("draft"))
    path = _card_path(proj, kind, cid, draft)
    if not path.is_file():
        raise ApiError(404, "找不到卡片：%s" % path, "not_found")
    if kind != "character":
        raise ApiError(400, "地點不分段：地點只有 look_en（空鏡）", "bad_kind")
    try:
        meta, _body = read_front_matter(path)
    except ProjectError as error:
        raise ApiError(400, str(error), "bad_card")
    return bible.split_look(meta)


@router.post("/api/bible/card")
def card_save(body: dict = Body(...)):
    """存一張卡片（整個 Markdown 檔）。frontmatter 讀不懂、id 被改掉就擋；其他規則檢查回傳成提醒（確認入庫時才擋）。"""
    proj = body_project(body)
    kind = _kind(body.get("kind"))
    cid, draft = str(body.get("id") or ""), bool(body.get("draft"))
    path = _card_path(proj, kind, cid, draft)
    text = str(body.get("text") or "").replace("\r\n", "\n")
    if not path.is_file():
        raise ApiError(404, "找不到卡片：%s（新卡片請用「新增」）" % path, "not_found")
    m = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.S)
    if not m:
        raise ApiError(400, "開頭要有 --- 包起來的 YAML frontmatter", "bad_card")
    import yaml
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as error:
        raise ApiError(400, "frontmatter 不是合法的 YAML：%s" % error, "bad_card")
    if not isinstance(meta, dict) or str(meta.get("id") or "") != cid:
        raise ApiError(400, "frontmatter 的 id 要維持「%s」（要換 id 請新增一張卡片）" % cid, "bad_card")
    issues = bible_check.check_card(meta, kind)
    if not draft:
        errs = errors(issues)
        if errs:
            raise ApiError(400, "定案卡片不能有錯誤（分鏡編譯要用）：\n%s" % "\n".join("  - %s" % e for e in errs), "bad_card")
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    stale = False
    if not draft and _picked(proj, kind, cid):                 # 定裝圖挑過之後又改了 look_en／服裝 → 過期，要重畫重挑
        with guard():
            st = bible.status(open_project(str(proj.root)))
        rows = st["characters"] if kind == "character" else st["locations"]
        row = next((r for r in rows if r["id"] == cid), {})
        stale = any(o["state"] == "stale" for o in row.get("outfits", [])) if kind == "character" else row.get("state") == "stale"
    return {"path": str(path), "issues": _issues(issues), "stale": stale}


@router.post("/api/bible/new")
def card_new(body: dict = Body(...)):
    """新增一張草稿卡片（例如規劃裡缺卡的人物）。"""
    proj = body_project(body)
    kind = _kind(body.get("kind"))
    cid, name = str(body.get("id") or "").strip(), str(body.get("name") or "").strip()
    if not name:
        raise ApiError(400, "請輸入名字", "bad_card")
    path = _card_path(proj, kind, cid, True)
    taken = set(proj.characters if kind == "character" else proj.locations) | set(bible.list_drafts(proj, kind))
    if cid in taken or path.exists():
        raise ApiError(400, "id「%s」已經有卡片了" % cid, "bad_card")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NEW_CARD[kind].format(id=cid, name=bible._q(name)), encoding="utf-8")
    return {"path": str(path), "id": cid}


@router.post("/api/bible/accept")
def accept(body: dict = Body(...)):
    proj = body_project(body)
    ids = [str(x) for x in body.get("ids") or [] if str(x).strip()]
    if not ids:
        raise ApiError(400, "請指定要確認的卡片", "bad_request")
    kind = body.get("kind")
    with guard("accept_failed"):
        moved = bible.accept(proj, ids, kind=_kind(kind) if kind else None, force=bool(body.get("force")))
    return {"moved": [{"kind": k, "id": cid, "path": str(p)} for k, cid, p in moved]}


@router.get("/api/bible/renders")
def renders(project: str = "", kind: str = "character", id: str = Query("")):
    """一個角色或地點的定裝圖候選：[{file, outfit, view, seed, picked}]。"""
    proj = open_project(project)
    kind = _kind(kind)
    got = _picked(proj, kind, id) or {}
    chosen = set()
    if kind == "character":
        for outfit in got.values():
            chosen |= {v.get("image") for v in outfit.values()}
    elif got:
        chosen.add(got.get("image"))
    files = [{"file": name, "path": "renders/bible/%s" % name, "outfit": info["outfit"], "view": info["view"], "seed": seed,
              "picked": name in chosen} for name, info, seed in bible.render_files(proj, kind, id)]
    return {"files": files}


@router.post("/api/bible/pick")
def pick(body: dict = Body(...)):
    proj = body_project(body)
    with guard("pick_failed"):
        kind, cid, outfit, view = bible.pick(proj, str(body.get("image") or ""))
    return {"kind": kind, "id": cid, "outfit": outfit, "view": view}


# ---- 過期清單（步驟 2：卡片改了哪幾格要重畫） --------------------------------------

def _chapter_stale(proj, n):
    """一章的過期清單：{"chapter", "title", "panels", "count"}。沒有過期的格也回傳（count 0）。"""
    panels = stale.chapter(proj, n)
    try:
        title = str(proj.load_storyboard(n).get("title") or "")
    except ProjectError:                       # 分鏡讀不懂：還能列出過期的格（標題空白）
        title = ""
    return {"chapter": n, "title": title, "panels": panels, "count": len(panels)}


@router.get("/api/bible/stale")
def stale_list(project: str = "", chapter: str = Query("")):
    """哪幾格過期（卡片或畫風改了，見 t2c/stale.py）：帶 chapter 只算那一章，不帶算整部。

    帶 chapter 時那一章一定在清單裡（count 0 就是「沒有過期的格」）；不帶時只列有過期的章。
    total 是清單裡所有章加起來的格數。
    """
    proj = open_project(project)
    with guard():
        if str(chapter or "").strip():
            rows = [_chapter_stale(proj, chapter_no(chapter))]
        else:
            rows = stale.project_chapters(proj)
    return {"chapters": rows, "total": sum(row["count"] for row in rows)}
