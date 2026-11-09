"""M1 修正 M-1：畫面外的說話者（`offscreen`）與通訊的電子音框（`radio`）。
格式見 docs/02_資料格式.md 第 4 節（劇本標記）、第 5 節「畫面外的說話者」。
執行：python -m pytest tests/test_offscreen.py
"""
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import adapt, check, compose, layout, letter, prompts, script as sc  # noqa: E402
from t2c.compile import CompileError, compile_chapter  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"
PAGES = layout.load_pages()


@pytest.fixture
def comic(tmp_path):
    root = tmp_path / "comic"
    for sub in ("bible", "storyboard", "script"):
        shutil.copytree(SAMPLE / sub, root / sub)
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    renders = root / "renders" / "ch001"
    renders.mkdir(parents=True)
    for slot in range(1, 6):
        Image.new("L", (1000, 800), 120).save(renders / ("p001_k%d_s11.png" % slot))
    project = Project(root)
    return project, project.load_storyboard(1)


def k4_with(board, bubble):
    """第 4 格（只有 lin 在場）加一個對話框。"""
    board = copy.deepcopy(board)
    board["pages"][0]["panels"][3]["bubbles"].append(bubble)
    return board


def errors_of(project, panel):
    return [str(i) for i in check.check_panel(project, 1, panel) if i.level == "error"]


# ---- 劇本標記 ----------------------------------------------------------------------------------

def parse_one(line):
    page, issues = sc.parse_page("## 第 1 頁（模板 1）\n\n**1 格**｜中景｜畫面。\n" + line)
    return page.panels[0].lines[0] if page.panels[0].lines else None, issues


@pytest.mark.parametrize("line, kind, offscreen", [
    ("- 阿浩（通訊）：在。", "radio", False),
    ("- 阿浩（電話）：在。", "radio", False),
    ("- 阿浩（畫面外）：在。", "speech", True),
    ("- 阿浩（畫面外、喊）：快跑！", "shout", True),
    ("- 阿浩（小聲、畫面外）：噓。", "whisper", True),
    ("- 阿浩（喊）：喂！", "shout", False),
])
def test_script_marks(line, kind, offscreen):
    item, issues = parse_one(line)
    assert not issues
    assert (item.kind, item.offscreen, item.speaker) == (kind, offscreen, "阿浩")


@pytest.mark.parametrize("line, words", [
    ("- 阿浩（通訊、喊）：快跑！", "通訊"),
    ("- 阿浩（畫面外、心聲）：……", "心聲"),
    ("- 阿浩（喊、小聲）：……", "只能標一個"),
    ("- 阿浩（手機）：……", "不認得的標記"),
])
def test_script_bad_marks(line, words):
    _, issues = parse_one(line)
    assert issues and words in str(issues[0])


# ---- 分鏡檢查 ----------------------------------------------------------------------------------

def test_offscreen_speaker_passes_check_and_compiles(comic):
    project, board = comic
    board = k4_with(board, {"kind": "radio", "speaker": "hao", "offscreen": True, "text": "在。", "anchor": [0.2, 0.2]})
    panel = board["pages"][0]["panels"][3]
    assert errors_of(project, panel) == []
    job = next(j for j in compile_chapter(project, board) if j["id"] == "p001_k4")
    caption = job["layout"]["summary"]["caption"]
    assert "exactly one person" in caption                   # 畫面外的人不算進人數
    assert [i["label"] for i in job["layout"]["items"]].count("character") == 1
    hao_look = project.characters["hao"]["look_en"]
    assert hao_look not in job["prompt"]                      # 也不會被畫出來（規則 3、4）
    assert "在。" not in job["prompt"]                         # 台詞不進生圖（規則 5）


def test_speaker_not_in_panel_without_offscreen_points_to_offscreen(comic):
    project, board = comic
    board = k4_with(board, {"kind": "speech", "speaker": "hao", "text": "在。", "anchor": [0.2, 0.2]})
    errs = errors_of(project, board["pages"][0]["panels"][3])
    assert len(errs) == 1 and "offscreen" in errs[0] and "第 1 頁第 4 格" in errs[0]
    with pytest.raises(CompileError, match="offscreen"):
        compile_chapter(project, board)


def test_offscreen_but_listed_in_characters_is_an_error(comic):
    project, board = comic
    board = k4_with(board, {"kind": "speech", "speaker": "lin", "offscreen": True, "text": "在。", "anchor": [0.2, 0.2]})
    errs = errors_of(project, board["pages"][0]["panels"][3])
    assert any("characters" in e and "offscreen" in e for e in errs)
    with pytest.raises(CompileError, match="第 1 頁第 4 格"):
        compile_chapter(project, board)


@pytest.mark.parametrize("bubble, words", [
    ({"kind": "thought", "speaker": "hao", "offscreen": True, "text": "唔。", "anchor": [0.2, 0.2]}, "不能 offscreen"),
    ({"kind": "narration", "offscreen": True, "text": "隔天。", "anchor": [0.2, 0.2]}, "旁白不要寫 offscreen"),
    ({"kind": "speech", "speaker": "nobody", "offscreen": True, "text": "唔。", "anchor": [0.2, 0.2]}, "不在 bible"),
    ({"kind": "speech", "speaker": "hao", "offscreen": "yes", "text": "唔。", "anchor": [0.2, 0.2]}, "true 或 false"),
])
def test_offscreen_bad_combinations(comic, bubble, words):
    project, board = comic
    board = k4_with(board, bubble)
    errs = errors_of(project, board["pages"][0]["panels"][3])
    assert any(words in e for e in errs), errs


def test_against_script_requires_offscreen_and_radio(comic):
    project, board = comic
    page, issues = sc.parse_page("## 第 1 頁（模板 1）\n\n**4 格**｜中景｜曉雨別過頭。\n"
                                 "- 曉雨：我已經不餓了。\n- 阿浩（通訊）：在。\n- 阿浩（畫面外）：真的？")
    assert not issues
    panels = copy.deepcopy(board["pages"][0]["panels"])
    k4 = panels[3]
    k4["bubbles"] += [{"kind": "speech", "speaker": "hao", "offscreen": True, "text": "在。", "anchor": [0.2, 0.2]},
                      {"kind": "speech", "speaker": "hao", "text": "真的？", "anchor": [0.2, 0.5]}]
    errs = [str(i) for i in check.check_against_script(project, 1, [k4], page) if i.level == "error"]
    assert any("radio" in e for e in errs)                      # 劇本（通訊）→ kind 要 radio
    assert any("（畫面外）" in e and "offscreen" in e for e in errs)
    k4["bubbles"][1]["kind"] = "radio"
    k4["bubbles"][2]["offscreen"] = True
    assert [i for i in check.check_against_script(project, 1, [k4], page) if i.level == "error"] == []


def test_radio_with_speaker_on_screen_is_allowed(comic):
    """通訊但說話者在畫面上（例如臉在螢幕上）：不寫 offscreen，列進 characters。"""
    project, board = comic
    board = k4_with(board, {"kind": "radio", "speaker": "lin", "text": "收到。", "anchor": [0.2, 0.2]})
    assert errors_of(project, board["pages"][0]["panels"][3]) == []
    compile_chapter(project, board)


def test_adapt_drops_default_offscreen():
    b = adapt.Adapter._strip({"kind": "speech", "speaker": "x", "text": "a", "anchor": [0.5, 0.5], "offscreen": False, "z": 1}, "bubbles")
    assert b == {"kind": "speech", "speaker": "x", "text": "a", "anchor": [0.5, 0.5]}


def test_prompt_example_shows_offscreen_and_rules_mention_it():
    bubbles = [b for p in prompts.EXAMPLE_STORYBOARD["panels"] for b in p.get("bubbles", [])]
    assert any(b.get("offscreen") for b in bubbles)
    assert "（畫面外" in prompts.EXAMPLE_SCRIPT
    assert "radio" in prompts.STORYBOARD_RULES and "offscreen" in prompts.STORYBOARD_RULES
    assert "（通訊）" in prompts.SCRIPT_RULES
    assert "框放在畫面邊緣" not in prompts.STORYBOARD_RULES     # 舊規則（把人畫在邊緣）已拿掉


# ---- 嵌字 -------------------------------------------------------------------------------------

def settings_or_skip():
    try:
        return letter.Settings.from_config({})
    except letter.LetterError:
        pytest.skip("這台電腦找不到中文字型")


def plan_k4(comic, bubble, letters=None):
    project, board = comic
    board = k4_with(board, bubble)
    plan = letter.plan_page(project, 1, board["pages"][0], PAGES, {}, letters or {}, settings_or_skip())
    return next(p for p in plan["panels"] if p["id"] == "p001_k4")


def test_offscreen_tail_leaves_the_frame(comic):
    panel = plan_k4(comic, {"kind": "speech", "speaker": "hao", "offscreen": True, "text": "在。", "anchor": [0.08, 0.5]})
    b = panel["bubbles"][-1]
    clip = b["clip"]
    assert b["offscreen"] and b["tail"] is not None and b["auto_tail"]
    assert b["tail"][0] < clip[0]                               # 最近的是左邊框：尖端伸出框外，畫的時候被框切掉
    assert clip[1] < b["tail"][1] < clip[3]


def test_offscreen_radio_has_no_tail_and_tail_override_still_works(comic):
    panel = plan_k4(comic, {"kind": "radio", "speaker": "hao", "offscreen": True, "text": "在。", "anchor": [0.1, 0.5]})
    assert panel["bubbles"][-1]["kind"] == "radio" and panel["bubbles"][-1]["tail"] is None
    over = {"p001_k4": {"faces": None, "bubbles": [{}, {"tail": [0.5, 0.9]}], "sfx": []}}
    panel = plan_k4(comic, {"kind": "radio", "speaker": "hao", "offscreen": True, "text": "在。", "anchor": [0.1, 0.5]}, over)
    assert panel["bubbles"][-1]["tail"] is not None and not panel["bubbles"][-1]["auto_tail"]


def test_radio_bubble_draws_jagged_outline(comic):
    project, board = comic
    settings = settings_or_skip()
    board = k4_with(board, {"kind": "radio", "speaker": "lin", "text": "收到。", "anchor": [0.15, 0.5]})
    canvas, _, warnings = compose.render_page(project, 1, board["pages"][0], PAGES, picks={}, lettering=settings, letters={})
    plan = letter.plan_page(project, 1, board["pages"][0], PAGES, {}, {}, settings)
    b = next(p for p in plan["panels"] if p["id"] == "p001_k4")["bubbles"][-1]
    assert b["tail"] is not None                                # 說話者在畫面上：尾巴照常指向他
    cx, cy = b["center"]
    rx = b["rx"]
    # 沿著框的左緣上下掃：鋸齒會讓黑白交替好幾次（平滑的橢圓只會碰到一次框線）
    gray = canvas.convert("L")
    x = int(cx - rx * 1.02)
    column = [gray.getpixel((x, int(cy - b["ry"] * 0.5 + i))) < 128 for i in range(int(b["ry"]))]
    flips = sum(1 for a, c in zip(column, column[1:]) if a != c)
    assert flips >= 4


def test_m1_chapter_style_page_letters_without_error(comic, tmp_path):
    """通訊對話的典型頁：陳嘉禾在走廊（畫面上）、周遠在通訊室（畫面外，radio）。"""
    project, board = comic
    board = copy.deepcopy(board)
    k1 = board["pages"][0]["panels"][0]
    k1["bubbles"] = [{"kind": "speech", "speaker": "lin", "text": "阿浩。", "anchor": [0.85, 0.1]},
                     {"kind": "radio", "speaker": "hao", "offscreen": True, "text": "在。", "anchor": [0.6, 0.1]},
                     {"kind": "shout", "speaker": "hao", "offscreen": True, "text": "快跑！", "anchor": [0.15, 0.3]}]
    compile_chapter(project, board)
    canvas, _, warnings = compose.render_page(project, 1, board["pages"][0], PAGES, picks={},
                                           lettering=settings_or_skip(), letters={})
    assert canvas.size[0] > 0
    assert not [w for w in warnings if "說話的角色" in w]
