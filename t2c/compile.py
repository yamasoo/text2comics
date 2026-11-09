"""分鏡 JSON → 每一格的 MOSS-Image layout prompt。

設計重點（依據見 docs/01_架構與流程.md）：
1. 一格一張圖。整頁一次生成時角色容易跑錯格，解析度也被壓縮。
2. 角色外觀只從視覺聖經取，**逐字**貼進該格；LLM 寫分鏡時只寫角色 id，不寫外觀。
3. 每格的 summary 只描述這一格，並寫明這格有幾個人；不在場的角色完全不出現。
4. 台詞、旁白預設不交給 MOSS 畫（之後由嵌字程式疊上）；狀聲詞可選擇交給 MOSS（sfx_mode = "moss"）。
5. 比例座標只在這裡換成 MOSS 的 bbox（見 layout.to_moss_bbox）。
"""
import hashlib
import json
import re

from . import layout

SHOT = {
    "extreme_wide": "extreme wide establishing shot",
    "wide": "wide shot",
    "full": "full body shot",
    "medium": "medium shot",
    "close": "close-up shot",
    "extreme_close": "extreme close-up shot",
}
ANGLE = {
    "eye": "eye-level view",
    "high": "high-angle view looking down",
    "low": "low-angle view looking up",
    "bird": "bird's-eye view from directly above",
    "dutch": "tilted dutch angle",
    "over_shoulder": "over-the-shoulder view",
}
BUBBLE_KINDS = {"speech", "thought", "shout", "whisper", "radio", "narration"}
OFFSCREEN_KINDS = {"speech", "shout", "whisper", "radio"}   # 可以 offscreen 的種類（M1 修正）
SFX_MODES = {"overlay", "moss"}
NUMBERS = {1: "one person", 2: "two people", 3: "three people", 4: "four people", 5: "five people"}


class CompileError(Exception):
    """給人看的錯誤訊息（會列出是哪一頁哪一格）。"""


def _sentence(text):
    text = " ".join(str(text or "").split())
    if text and text[-1] not in ".!?":
        text += "."
    return text[:1].upper() + text[1:]


def _seed(panel_id, index, base=0):
    """同一格同一個候選編號永遠得到同一個 seed，重跑結果可重現。"""
    digest = hashlib.sha256(("%s#%d" % (panel_id, index)).encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) + int(base)) % 2_147_483_647


def cast_sentence(count):
    if count == 0:
        return "There are no people in this panel."
    who = NUMBERS.get(count, "%d people" % count)
    return "This panel shows exactly %s, and each person appears only once." % who


NO_FRAME = "The image has no border or frame."
NO_LETTERING = "The artwork has no speech bubbles, captions or lettering."


def side_of_frame(box):
    """比例框的水平位置：left／center／right（以中心點判斷）。"""
    center = (box[0] + box[2]) / 2.0
    if center < 0.4:
        return "left"
    if center > 0.6:
        return "right"
    return "center"


def _subject(card):
    """從 look_en 判斷用 She／He／This character（S1 實測：多角色時要寫明左右，見 docs/qa/S1_出圖實測.md）。"""
    words = set(re.findall(r"[a-z]+", str(card.get("look_en", "")).lower()))
    if words & {"woman", "girl", "female", "lady"}:
        return "She"
    if words & {"man", "boy", "male", "guy"}:
        return "He"
    return "This character"


def side_sentence(card, side):
    where = "in the center of the frame" if side == "center" else "on the %s side of the frame" % side
    return "%s is %s." % (_subject(card), where)


def character_caption(card, entry, side=None):
    """角色 item 的 caption：（多角色時的左右位置）＋聖經的 look_en（逐字）＋服裝＋這一格的姿勢、表情。"""
    parts = [side_sentence(card, side)] if side else []
    parts.append(_sentence(card["look_en"]))
    outfits = card.get("outfits") or {}
    outfit_id = entry.get("outfit") or "default"
    outfit = outfits.get(outfit_id)
    if outfit_id != "default" and outfit is None:
        raise KeyError("服裝「%s」不在角色「%s」的 outfits 裡" % (outfit_id, card["id"]))
    if outfit:
        parts.append(_sentence(outfit))          # 聖經裡寫成完整句子，例如 "She wears a navy school blazer."
    if entry.get("pose"):
        parts.append(_sentence(entry["pose"]))
    if entry.get("expression"):
        parts.append(_sentence("Facial expression: " + entry["expression"]))
    return " ".join(p for p in parts if p)


def bubble_error(project, bubble, cast):
    """對話框與這一格角色的一致性（不合就丟 KeyError）。cast：這一格 characters 的 id。
    說話者必須在這一格；`offscreen: true` 時反過來，必須是聖經角色、而且**不在**這一格（資料格式第 5 節）。"""
    kind = bubble.get("kind", "speech")
    if kind not in BUBBLE_KINDS:
        raise KeyError("對話框種類「%s」不認得（可用：%s）" % (kind, "、".join(sorted(BUBBLE_KINDS))))
    speaker, offscreen = bubble.get("speaker"), bubble.get("offscreen", False)
    if not isinstance(offscreen, bool):
        raise KeyError("offscreen 只能是 true 或 false")
    if offscreen:
        if kind not in OFFSCREEN_KINDS:
            raise KeyError("%s 的對話框不能 offscreen（可以的種類：%s）" % (kind, "、".join(sorted(OFFSCREEN_KINDS))))
        if not speaker:
            raise KeyError("offscreen 的對話框也要寫 speaker")
        if speaker not in project.characters:
            raise KeyError("說話的角色「%s」不在 bible/characters" % speaker)
        if speaker in cast:
            raise KeyError("「%s」標了 offscreen，但他列在這一格的 characters（會被畫出來）；畫面外就從 characters 拿掉" % speaker)
    elif speaker and speaker not in cast and kind != "narration":
        raise KeyError("說話的角色「%s」不在這一格（人在畫面外或透過通訊說話，對話框加 \"offscreen\": true）" % speaker)


def compile_panel(project, page, panel, template_box, settings):
    """回傳一格的生圖工作：{id, page, slot, width, height, layout, prompt, negative, seeds}。"""
    pid = panel.get("id") or "p%03d_k%d" % (page["page"], panel["slot"])
    where = "第 %s 頁第 %s 格（%s）" % (page["page"], panel.get("slot"), pid)
    try:
        page_cfg = settings["page"]
        rect = layout.panel_rect_px(page_cfg, template_box)
        aspect = (rect[2] - rect[0]) / float(rect[3] - rect[1])
        width, height = layout.gen_size(aspect, settings.get("megapixels", 1.0))

        chars = panel.get("characters") or []
        caption = [
            _sentence(settings["style"]),
            _sentence("%s, %s" % (SHOT.get(panel.get("shot"), SHOT["medium"]), ANGLE.get(panel.get("angle"), ANGLE["eye"]))),
        ]
        location = None
        if panel.get("location"):
            card = project.locations.get(panel["location"])
            if card is None:
                raise KeyError("地點「%s」不在 bible/locations" % panel["location"])
            location = card
            caption.append(_sentence("Setting: " + card["look_en"]))
        caption.append(_sentence(panel.get("scene", "")))
        caption.append(cast_sentence(len(chars)))
        caption.append(NO_FRAME)
        caption.append(NO_LETTERING)

        items = []
        if location is not None:
            items.append({"label": "object", "caption": _sentence(location["look_en"]) + " Background of the whole panel.",
                          "bbox": layout.to_moss_bbox([0, 0, 1, 1], width, height)})
        seen = set()
        for entry in chars:
            cid = entry.get("id")
            card = project.characters.get(cid)
            if card is None:
                raise KeyError("角色「%s」不在 bible/characters" % cid)
            if cid in seen:
                raise KeyError("角色「%s」在同一格出現兩次" % cid)
            seen.add(cid)
            box = entry.get("box", [0.25, 0.1, 0.75, 1])
            side = side_of_frame(layout.check_box(box)) if len(chars) >= 2 else None
            items.append({"label": "character", "caption": character_caption(card, entry, side),
                          "bbox": layout.to_moss_bbox(box, width, height)})
        for obj in panel.get("objects") or []:
            items.append({"label": "object", "caption": _sentence(obj["caption"]),
                          "bbox": layout.to_moss_bbox(obj["box"], width, height)})
        if settings.get("sfx_mode") == "moss":
            for sfx in panel.get("sfx") or []:
                items.append({"label": "text", "caption": "Bold hand-drawn manga sound effect lettering in black ink.",
                              "text": sfx["text"], "bbox": layout.to_moss_bbox(sfx["box"], width, height)})
        for bubble in panel.get("bubbles") or []:
            bubble_error(project, bubble, seen)
    except (KeyError, layout.LayoutError) as error:
        raise CompileError("%s：%s" % (where, error.args[0] if error.args else error))

    doc = {
        "summary": {"meta": list(settings.get("meta", ["manga panel"])), "caption": " ".join(c for c in caption if c)},
        "items": items,
        "bbox_coord_space": layout.MOSS_COORD_SPACE,
        "bbox_format": layout.MOSS_BBOX_FORMAT,
    }
    count = int(settings.get("candidates", 1))
    seeds = list(panel.get("seeds") or [])[:count]
    seeds += [_seed(pid, i, settings.get("seed_base", 0)) for i in range(len(seeds), count)]
    return {
        "id": pid, "page": page["page"], "slot": panel["slot"],
        "rect_px": list(rect), "width": width, "height": height,
        "layout": doc, "prompt": json.dumps(doc, ensure_ascii=False),
        "negative": settings.get("negative", ""), "seeds": seeds,
    }


def compile_chapter(project, storyboard, pages_data=None, only_page=None, overrides=None):
    """整章（或 only_page 指定的那一頁）→ 生圖工作清單。"""
    pages_data = pages_data or layout.load_pages()
    cfg = project.config
    settings = {
        "page": pages_data["page"],
        "style": cfg.get("style", ""),
        "meta": cfg.get("meta", ["manga panel", "black and white"]),
        "megapixels": cfg.get("megapixels", 1.0),
        "negative": cfg.get("negative", ""),
        "sfx_mode": cfg.get("sfx_mode", "overlay"),
        "candidates": cfg.get("candidates", 1),
        "seed_base": cfg.get("seed_base", 0),
    }
    settings.update(overrides or {})
    if settings["sfx_mode"] not in SFX_MODES:
        raise CompileError("sfx_mode 只能是 %s" % "、".join(sorted(SFX_MODES)))
    if not str(settings["style"]).strip():
        raise CompileError("project.yaml 缺少 style（整部作品共用的畫風描述）")

    jobs = []
    for page in storyboard.get("pages") or []:
        if only_page is not None and int(page["page"]) != int(only_page):
            continue
        tpl = pages_data["templates"].get(str(page.get("template")))
        if tpl is None:
            raise CompileError("第 %s 頁：沒有這個格子模板「%s」（見 t2c/data/pages.json）" % (page.get("page"), page.get("template")))
        boxes = tpl["panels"]
        slots = [p.get("slot") for p in page.get("panels") or []]
        if sorted(slots) != list(range(1, len(boxes) + 1)):
            raise CompileError("第 %s 頁：模板「%s」有 %d 格，分鏡的 slot 要剛好是 1–%d，目前是 %s"
                               % (page["page"], page["template"], len(boxes), len(boxes), slots))
        for panel in sorted(page["panels"], key=lambda p: p["slot"]):
            jobs.append(compile_panel(project, page, panel, boxes[panel["slot"] - 1], settings))
    if only_page is not None and not jobs:
        raise CompileError("分鏡裡沒有第 %s 頁" % only_page)
    return jobs


def save_job(build_dir, job):
    """把一格的工作寫成 build/<章>/<格>.prompt.json（layout 已展開，方便人看；prompt 字串不重複存）。"""
    path = build_dir / ("%s.prompt.json" % job["id"])
    path.write_text(json.dumps({k: v for k, v in job.items() if k != "prompt"}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path
