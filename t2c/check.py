"""LLM 輸出的驗證（S5）：改編規劃、分鏡頁。

目的是把「問題」變成一份**完整、寫得出是哪一頁哪一格**的清單，回給 LLM 修。`compile_chapter()` 只回報第一個錯誤、
遇到結構亂掉的 JSON 還會丟出一般例外，不適合直接拿來回修；所以這裡先把能事先擋掉的都擋掉（編譯失敗的原因幾乎都涵蓋），
`compile_chapter()` 留作最後一道關卡（見 adapt.py）。

只用標準函式庫，不依賴 FastAPI／fekit。
"""
import re

from . import layout
from .compile import ANGLE, BUBBLE_KINDS, SHOT, side_of_frame
from .script import Issue, MAX_BUBBLES, resolve_speaker

CJK = re.compile(r"[㐀-鿿豈-﫿　-〿＀-￯]")
# 外觀只能來自視覺聖經（CLAUDE.md 規則 3），scene／pose／expression 不准重寫外觀
APPEARANCE = [
    (re.compile(r"\b(wears?|wearing|dressed in)\b", re.I), "服裝"),
    (re.compile(r"\b(black|brown|blond|blonde|white|silver|gr[ae]y|red|pink|blue|green|long|short|messy|curly|straight|wavy)[ -](haired|hair|eyes)\b", re.I), "髮型或眼睛"),
    (re.compile(r"\b(bangs|ponytail|pigtails|braids?)\b", re.I), "髮型"),
]

PANEL_KEYS = {"slot", "id", "shot", "angle", "location", "scene", "characters", "objects", "sfx", "bubbles", "seeds"}
CHAR_KEYS = {"id", "outfit", "pose", "expression", "box"}
BUBBLE_KEYS = {"kind", "speaker", "text", "anchor"}

VOICE_KINDS = {"speech", "shout", "whisper"}   # 劇本沒標語氣的台詞，分鏡可以在這三種裡選
COLUMN_CHARS = 12            # 對話框每一行（直排是每一欄）最多幾個字；超過要加 \n
COLUMN_CHARS_NARRATION = 16
HEAD_CHARS = 8               # 第一行（欄）建議的上限，只做提醒


def _where(page, slot):
    return "第 %s 頁第 %s 格" % (page, slot)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _box(value, label, where, issues):
    try:
        return layout.check_box(value, label)
    except layout.LayoutError as error:
        issues.append(Issue("error", where, "%s：%s" % (label, error)))
        return None


def _english(value, label, where, issues):
    if not isinstance(value, str) or not value.strip():
        issues.append(Issue("error", where, "%s 不能是空的，要寫一句英文" % label))
        return
    if CJK.search(value):
        issues.append(Issue("error", where, "%s 要寫英文（生圖提示詞用英文），目前含有中文：「%s」" % (label, value[:40])))


def _appearance(value, label, where, issues):
    if not isinstance(value, str):
        return
    for pattern, kind in APPEARANCE:
        m = pattern.search(value)
        if m:
            issues.append(Issue("error", where, "%s 裡的「%s」像是在描述角色%s。外觀只能由視覺聖經提供，這裡只寫動作與畫面，人物用 the young woman／the young man 之類的代稱" % (label, m.group(0), kind)))
            return


def column_issues(text, kind, where):
    """直排台詞每欄字數：一整句超過上限、又沒有 \\n 時，嵌字的自動斷欄沒有中文斷詞，會把詞拆開。"""
    limit = COLUMN_CHARS_NARRATION if kind == "narration" else COLUMN_CHARS
    out = []
    for seg in str(text).split("\n"):
        n = len(re.sub(r"\s", "", seg))
        if n > limit:
            out.append(Issue("error", where, "台詞「%s…」有一行 %d 個字，超過 %d 字。請在詞與詞之間加換行 \\n（例如「對不起！\\n排隊排到一半\\n被教授抓去搬東西！」），每行 %d 字左右" % (seg[:8], n, limit, HEAD_CHARS + 2)))
            break
    return out


def _iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def check_panel(project, page_no, panel):
    """一格分鏡的結構與內容檢查。"""
    issues = []
    slot = panel.get("slot") if isinstance(panel, dict) else None
    where = _where(page_no, slot)
    if not isinstance(panel, dict):
        return [Issue("error", where, "每一格要是物件 {...}")]
    for key in sorted(set(panel) - PANEL_KEYS):
        issues.append(Issue("warn", where, "多餘的欄位「%s」已忽略" % key))
    if not isinstance(slot, int) or isinstance(slot, bool):
        issues.append(Issue("error", where, "slot 要是整數"))
    shot, angle = panel.get("shot", "medium"), panel.get("angle", "eye")
    if shot not in SHOT:
        issues.append(Issue("error", where, "shot「%s」不認得（可用：%s）" % (shot, "、".join(SHOT))))
    if angle not in ANGLE:
        issues.append(Issue("error", where, "angle「%s」不認得（可用：%s）" % (angle, "、".join(ANGLE))))
    loc = panel.get("location")
    if loc and loc not in project.locations:
        issues.append(Issue("error", where, "地點「%s」不在 bible/locations（現有：%s）；沒有合適的地點就省略 location" % (loc, "、".join(project.locations) or "無")))
    _english(panel.get("scene"), "scene", where, issues)
    _appearance(panel.get("scene"), "scene", where, issues)

    chars = panel.get("characters", [])
    cast, boxes = [], []
    if not isinstance(chars, list):
        issues.append(Issue("error", where, "characters 要是陣列（沒有人就給 []）"))
        chars = []
    for entry in chars:
        if not isinstance(entry, dict):
            issues.append(Issue("error", where, "characters 的每一項要是物件 {id, pose, expression, box}"))
            continue
        cid = entry.get("id")
        for key in sorted(set(entry) - CHAR_KEYS):
            issues.append(Issue("warn", where, "角色「%s」多餘的欄位「%s」已忽略" % (cid, key)))
        if cid not in project.characters:
            issues.append(Issue("error", where, "角色「%s」不在 bible/characters（現有：%s）" % (cid, "、".join(project.characters) or "無")))
            continue
        if cid in cast:
            issues.append(Issue("error", where, "角色「%s」在同一格出現兩次" % cid))
        cast.append(cid)
        outfit = entry.get("outfit") or "default"
        outfits = project.characters[cid].get("outfits") or {}
        if outfit != "default" and outfit not in outfits:
            issues.append(Issue("error", where, "角色「%s」沒有服裝「%s」（現有：%s）" % (cid, outfit, "、".join(["default"] + list(outfits)))))
        for field_name in ("pose", "expression"):
            if entry.get(field_name):
                _english(entry[field_name], "%s 的 %s" % (cid, field_name), where, issues)
                _appearance(entry[field_name], "%s 的 %s" % (cid, field_name), where, issues)
        if "box" in entry:
            b = _box(entry["box"], "角色「%s」的 box" % cid, where, issues)
            if b:
                boxes.append((cid, b))
    if len(boxes) >= 2:
        sides = [side_of_frame(b) for _, b in boxes]
        if len(set(sides)) == 1:
            issues.append(Issue("warn", where, "同一格的角色框中心都在畫面「%s」，嵌字與生圖的左右位置會不明確，建議左右分開" % sides[0]))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _iou(boxes[i][1], boxes[j][1]) > 0.5:
                    issues.append(Issue("warn", where, "角色「%s」與「%s」的框重疊過半" % (boxes[i][0], boxes[j][0])))

    objects = panel.get("objects", [])
    if not isinstance(objects, list):
        issues.append(Issue("error", where, "objects 要是陣列"))
        objects = []
    for obj in objects:
        if not isinstance(obj, dict) or "caption" not in obj or "box" not in obj:
            issues.append(Issue("error", where, "objects 的每一項要是 {caption: 英文, box: [x0,y0,x1,y1]}"))
            continue
        _english(obj["caption"], "objects.caption", where, issues)
        _box(obj["box"], "物件的 box", where, issues)

    sfx = panel.get("sfx", [])
    if not isinstance(sfx, list):
        issues.append(Issue("error", where, "sfx 要是陣列"))
        sfx = []
    for item in sfx:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip() or "box" not in item:
            issues.append(Issue("error", where, "sfx 的每一項要是 {text: 狀聲詞原文, box: [x0,y0,x1,y1]}"))
            continue
        _box(item["box"], "狀聲詞「%s」的 box" % item["text"], where, issues)

    bubbles = panel.get("bubbles", [])
    if not isinstance(bubbles, list):
        issues.append(Issue("error", where, "bubbles 要是陣列"))
        bubbles = []
    if len(bubbles) > MAX_BUBBLES:
        issues.append(Issue("error", where, "對話框有 %d 個，一格最多 %d 個" % (len(bubbles), MAX_BUBBLES)))
    for b in bubbles:
        if not isinstance(b, dict):
            issues.append(Issue("error", where, "bubbles 的每一項要是物件 {kind, speaker, text, anchor}"))
            continue
        for key in sorted(set(b) - BUBBLE_KEYS):
            issues.append(Issue("warn", where, "對話框多餘的欄位「%s」已忽略" % key))
        kind, text = b.get("kind", "speech"), b.get("text")
        if kind not in BUBBLE_KINDS:
            issues.append(Issue("error", where, "對話框種類「%s」不認得（可用：%s）" % (kind, "、".join(sorted(BUBBLE_KINDS)))))
        if not isinstance(text, str) or not text.strip():
            issues.append(Issue("error", where, "對話框的 text 不能是空的"))
        else:
            issues += column_issues(text, kind, where)
        speaker = b.get("speaker")
        if kind == "narration":
            if speaker:
                issues.append(Issue("error", where, "旁白不要寫 speaker"))
        elif not speaker:
            issues.append(Issue("error", where, "「%s」缺少 speaker（角色 id）" % str(text)[:12]))
        elif speaker not in project.characters:
            issues.append(Issue("error", where, "說話的角色「%s」不在 bible/characters" % speaker))
        elif speaker not in cast:
            issues.append(Issue("error", where, "「%s」說話，但 %s 不在這一格的 characters 裡。請把他加進 characters（不在畫面中央也可以，框放在畫面邊緣）" % (str(text)[:12], speaker)))
        anchor = b.get("anchor")
        if not (isinstance(anchor, (list, tuple)) and len(anchor) == 2 and all(_is_num(v) and 0 <= v <= 1 for v in anchor)):
            issues.append(Issue("error", where, "anchor 要是 [x, y]，兩個 0–1 的比例，目前是 %r" % (anchor,)))
    return issues


def check_page_panels(project, page_no, template_key, panels, pages_data):
    """一頁的格數、slot 與每一格的檢查。"""
    issues = []
    tpl = pages_data["templates"].get(str(template_key))
    if tpl is None:
        return [Issue("error", "第 %s 頁" % page_no, "沒有這個格子模板「%s」" % template_key)]
    if not isinstance(panels, list):
        return [Issue("error", "第 %s 頁" % page_no, "panels 要是陣列")]
    want = list(range(1, len(tpl["panels"]) + 1))
    got = [p.get("slot") if isinstance(p, dict) else None for p in panels]
    if got != want:
        issues.append(Issue("error", "第 %s 頁" % page_no, "模板「%s」有 %d 格，panels 的 slot 要依序是 %s，目前是 %s" % (template_key, len(want), want, got)))
    for panel in panels:
        issues += check_panel(project, page_no, panel)
    return issues


def check_against_script(project, page_no, panels, script_page):
    """分鏡的對話框、狀聲詞必須和劇本逐字相同（只允許加 \\n）；種類、說話者、順序也要一致。"""
    issues = []
    by_slot = {p.get("slot"): p for p in panels if isinstance(p, dict)}
    for sp in script_page.panels:
        panel = by_slot.get(sp.slot)
        if panel is None:
            continue
        where = _where(page_no, sp.slot)
        want = [l for l in sp.lines if l.kind != "sfx"]
        have = [b for b in (panel.get("bubbles") or []) if isinstance(b, dict)]
        if len(want) != len(have):
            issues.append(Issue("error", where, "劇本這一格有 %d 個對話框（含旁白），分鏡有 %d 個。對話框要和劇本一一對應，不增不減" % (len(want), len(have))))
        for i, (w, h) in enumerate(zip(want, have), 1):
            kind = h.get("kind", "speech")
            free = w.kind == "speech" and kind in VOICE_KINDS          # 劇本沒標語氣：分鏡可以判斷成喊叫或小聲
            if kind != w.kind and not free:
                want_kind = w.kind if w.kind != "speech" else "speech、shout 或 whisper 其中之一"
                issues.append(Issue("error", where, "第 %d 個對話框：劇本是「%s」，kind 要是 %s（目前是 %s）" % (i, w.text[:12], want_kind, kind)))
            if w.speaker:
                cid = resolve_speaker(project, w.speaker)
                if cid and h.get("speaker") != cid:
                    issues.append(Issue("error", where, "第 %d 個對話框：劇本由「%s」說，speaker 要是 %s（目前是 %s）" % (i, w.speaker, cid, h.get("speaker"))))
            a, b = re.sub(r"\s+", "", w.text), re.sub(r"\s+", "", str(h.get("text") or ""))
            if a != b:
                issues.append(Issue("error", where, "第 %d 個對話框的台詞和劇本不同。劇本：「%s」；分鏡：「%s」。台詞必須逐字照劇本，只能加換行 \\n" % (i, w.text, h.get("text"))))
        want_sfx = [l.text for l in sp.lines if l.kind == "sfx"]
        have_sfx = [str(s.get("text")) for s in (panel.get("sfx") or []) if isinstance(s, dict)]
        if want_sfx != have_sfx:
            issues.append(Issue("error", where, "狀聲詞要和劇本一致：劇本是 %s，分鏡是 %s" % (want_sfx or "沒有", have_sfx or "沒有")))
        # 鏡頭詞只是提示，不一致時提醒就好
        if sp.shots:
            from .script import SHOT_WORDS
            expect = SHOT_WORDS[sp.shots[0]]
            if panel.get("shot", "medium") != expect:
                issues.append(Issue("warn", where, "劇本鏡頭是「%s」（%s），分鏡 shot 是 %s" % (sp.shots[0], expect, panel.get("shot", "medium"))))
    return issues


# ---------------------------------------------------------------------------
# 改編規劃
# ---------------------------------------------------------------------------
MAX_PAGES = 60


def check_plan(project, plan, pages_data, want_pages=None):
    """改編規劃（plan/chNNN.json）。"""
    issues = []
    if not isinstance(plan, dict) or not isinstance(plan.get("pages"), list) or not plan["pages"]:
        return [Issue("error", "", "最外層要是 {\"title\":…, \"pages\":[…]}，而且 pages 不能是空的")]
    n = len(plan["pages"])
    if want_pages is not None and n != want_pages:
        issues.append(Issue("error", "", "要求共 %d 頁，目前規劃了 %d 頁" % (want_pages, n)))
    if n > MAX_PAGES:
        issues.append(Issue("error", "", "一章最多 %d 頁，目前 %d 頁" % (MAX_PAGES, n)))
    for index, page in enumerate(plan["pages"], 1):
        where = "第 %d 頁" % index
        if not isinstance(page, dict):
            issues.append(Issue("error", where, "每一頁要是物件"))
            continue
        if page.get("page") != index:
            issues.append(Issue("error", where, "page 要依序是 %d，目前是 %r" % (index, page.get("page"))))
        key = str(page.get("template"))
        tpl = pages_data["templates"].get(key)
        if tpl is None:
            issues.append(Issue("error", where, "沒有這個格子模板「%s」（可用：%s）" % (key, "、".join(pages_data["templates"]))))
            continue
        panels = page.get("panels")
        if not isinstance(panels, list):
            issues.append(Issue("error", where, "panels 要是陣列"))
            continue
        slots = [p.get("slot") if isinstance(p, dict) else None for p in panels]
        if slots != list(range(1, len(tpl["panels"]) + 1)):
            issues.append(Issue("error", where, "模板「%s」有 %d 格，panels 的 slot 要依序是 1–%d，目前是 %s" % (key, len(tpl["panels"]), len(tpl["panels"]), slots)))
        if not str(page.get("purpose") or "").strip():
            issues.append(Issue("error", where, "缺少 purpose（這一頁在章裡的作用）"))
        for p in panels:
            if not isinstance(p, dict):
                continue
            w = "%s第 %s 格" % (where, p.get("slot"))
            if not str(p.get("beat") or "").strip():
                issues.append(Issue("error", w, "缺少 beat（這一格發生什麼）"))
            for cid in p.get("characters") or []:
                if cid not in project.characters:
                    issues.append(Issue("error", w, "角色「%s」不在 bible/characters（現有：%s）；原著有但聖經沒有的人物請列在最外層的 unlisted_characters，不要放進格子" % (cid, "、".join(project.characters) or "無")))
            loc = p.get("location")
            if loc and loc not in project.locations:
                issues.append(Issue("error", w, "地點「%s」不在 bible/locations；沒有合適的地點就省略" % loc))
    return issues
