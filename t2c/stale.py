"""帳單軌（docs/reports/01_build_book_flow.md、docs/06 D1）：哪幾格因為卡片或畫風改了而過期。

出圖時 `compile` 把「這一格用了哪幾段、每段指紋」寫進 build/<章>/<格>.prompt.json（`save_job` 存的），
這裡拿它跟現在的卡片重算一次比對：不一樣就是過期，並說出是哪一個角色、哪一段。

規則（D2）：
- 已經沒有卡片、或當初就是探索用的格不列入（沒有指紋可比，也沒有東西能重畫成「定案」）。
- 沒出過圖的格不列入（沒有圖可以過期）。
- 分鏡改了（角色換人、新增角色、場景改寫）也算過期，理由寫「分鏡改了」。

只用標準函式庫。
"""
import json

from . import compose, look

SECTION_TEXT = look.SECTION_TEXT
OUTFIT_TEXT = look.OUTFIT_TEXT


def build_dir(project, chapter):
    return project.root / "build" / compose.chapter_name(chapter)


def stored(project, chapter):
    """這一章每一格出圖時記下的指紋：{格 id: {"fingerprint": …, "explore": […]}}。沒出過圖的格不會有。"""
    out = {}
    folder = build_dir(project, chapter)
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.prompt.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fp = data.get("fingerprint")
        if isinstance(fp, dict):
            out[str(data.get("id") or path.name.split(".")[0])] = {"fingerprint": fp, "explore": data.get("explore") or []}
    return out


def _part_text(source):
    """指紋的來源 → 給人看的那一段名字。"""
    if source in SECTION_TEXT:
        return SECTION_TEXT[source]
    if source == "look_en":
        return "整段外觀（舊格式）"
    if source.startswith("outfits."):
        bits = source.split(".")
        if len(bits) == 2:
            return "服裝「%s」" % bits[1]
        return "服裝「%s」的%s" % (bits[1], OUTFIT_TEXT.get(bits[2], bits[2]))
    return source


def compare(old, new):
    """兩份指紋 → 過期原因清單 [{"source", "level", "message"}]。空清單＝沒有過期。"""
    out = []
    if old.get("style") != new.get("style"):
        out.append({"source": "style", "level": "warn", "message": "畫風（style／meta／狀聲詞）換了：整章都要重畫"})
    if (old.get("location") or "") != (new.get("location") or ""):
        out.append({"source": "location", "level": "warn", "message": "地點的描述改了"})
    old_cards = old.get("characters") or {}
    new_cards = new.get("characters") or {}
    for cid in sorted(set(old_cards) | set(new_cards)):
        was, now = old_cards.get(cid), new_cards.get(cid)
        if was is None or now is None:
            out.append({"source": "characters", "level": "warn",
                        "message": "角色「%s」%s這一格" % (cid, "不在" if now is None else "新增到")})
            continue
        if was.get("outfit") != now.get("outfit"):
            out.append({"source": "outfits.%s" % cid, "level": "ok",
                        "message": "角色「%s」換了服裝（%s → %s）" % (cid, was.get("outfit"), now.get("outfit"))})
        old_parts, new_parts = was.get("parts") or {}, now.get("parts") or {}
        for source in sorted(set(old_parts) | set(new_parts)):
            if old_parts.get(source) == new_parts.get(source):
                continue
            level = "warn" if source in ("head", "look_en") else "ok"
            out.append({"source": source, "level": level,
                        "message": "角色「%s」的%s改了" % (cid, _part_text(source))})
    if not out and old.get("prompt") != new.get("prompt"):
        out.append({"source": "prompt", "level": "ok", "message": "分鏡或台詞改了，提示詞跟著變"})
    return out


def chapter(project, chapter_no, jobs=None):
    """這一章過期的格：
    [{"id", "page", "slot", "shot", "files", "reasons": [{"source", "level", "message"}]}]。
    jobs 可以傳已經編好的（compile_chapter 的結果），省一次重算。"""
    from .compile import compile_chapter
    jobs = jobs if jobs is not None else compile_chapter(project, project.load_storyboard(chapter_no))
    seen = stored(project, chapter_no)
    out = []
    for job in jobs:
        if job.get("explore"):
            continue
        mine = seen.get(job["id"])
        if mine is None or mine.get("explore"):
            continue
        reasons = compare(mine["fingerprint"], job["fingerprint"])
        if not reasons:
            continue
        out.append({"id": job["id"], "page": job["page"], "slot": job["slot"], "shot": job.get("fingerprint", {}).get("shot"),
                    "files": sorted(compose.candidates(project, chapter_no, job["id"])), "reasons": reasons})
    return out


def project_chapters(project, limit=None):
    """整部專案過期的格，依章分組：[{"chapter", "title", "panels": […], "count": n}]（只列有過期的章）。"""
    folder = project.root / "storyboard"
    numbers = sorted(int(p.stem[2:]) for p in folder.glob("ch*.json") if p.stem[2:].isdigit())
    if limit:
        numbers = numbers[:int(limit)]
    out = []
    for n in numbers:
        try:
            panels = chapter(project, n)
        except Exception as error:                     # 分鏡壞掉不要讓整份清單消失
            out.append({"chapter": n, "title": "", "panels": [], "count": 0, "error": str(error)})
            continue
        if panels:
            try:
                title = (project.load_storyboard(n).get("title") or "")
            except Exception:
                title = ""
            out.append({"chapter": n, "title": title, "panels": panels, "count": len(panels)})
    return out
