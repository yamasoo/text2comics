"""M1 修正：M-2（對話框閱讀順序）與 L-1–L-6。M-1 在 test_offscreen.py、M-3 在 test_portable.py、
L-7 在 test_ui.py（範例沒有出圖時）。
執行：python -m pytest tests/test_m1_fixes.py
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

from t2c import check, layout, letter, prompts, script as sc, workspace  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"
PAGES = layout.load_pages()


@pytest.fixture
def comic(tmp_path):
    root = tmp_path / "comic"
    for sub in ("bible", "storyboard", "script", "source"):
        shutil.copytree(SAMPLE / sub, root / sub)
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    renders = root / "renders" / "ch001"
    renders.mkdir(parents=True)
    for slot in range(1, 6):
        Image.new("L", (1000, 800), 120).save(renders / ("p001_k%d_s11.png" % slot))
    project = Project(root)
    return project, project.load_storyboard(1)


def settings_or_skip():
    try:
        return letter.Settings.from_config({})
    except letter.LetterError:
        pytest.skip("這台電腦找不到中文字型")


# ---- M-2 閱讀順序 -------------------------------------------------------------------------------

@pytest.mark.parametrize("first, later, bad", [
    ([600, 100, 800, 300], [300, 120, 500, 320], False),   # 後一個在左邊、差不多高：對
    ([600, 100, 800, 300], [600, 400, 800, 600], False),   # 在正下方：對
    ([300, 100, 500, 300], [650, 300, 850, 500], False),   # 在右下方、起頭低很多：不算（讀者多半先往左）
    ([300, 300, 500, 500], [600, 100, 800, 300], True),    # 跑到右上方
    ([300, 120, 500, 320], [600, 100, 800, 300], True),    # 差不多高、整個在右邊
    ([300, 500, 500, 700], [350, 100, 450, 300], True),    # 整個在上面
])
def test_order_conflict(first, later, bad):
    assert letter.order_conflict(first, later, 1000, 800) is bad


def test_lettering_keeps_reading_order_even_when_anchors_are_reversed(comic):
    """anchor 顛倒（後一句放右上）：自動擺位要照右翻順序，不壓到臉。"""
    project, board = comic
    board = copy.deepcopy(board)
    k4 = board["pages"][0]["panels"][3]
    k4["bubbles"] = [{"kind": "speech", "speaker": "lin", "text": "第一句。", "anchor": [0.12, 0.2]},
                     {"kind": "speech", "speaker": "lin", "text": "第二句。", "anchor": [0.88, 0.1]}]
    plan = letter.plan_page(project, 1, board["pages"][0], PAGES, {}, {}, settings_or_skip())
    panel = next(p for p in plan["panels"] if p["id"] == "p001_k4")
    a, b = panel["bubbles"]
    w, h = panel["rect"][2] - panel["rect"][0], panel["rect"][3] - panel["rect"][1]

    def box(item):
        ox, oy = letter.outer_axes(item["kind"], item["rx"], item["ry"])
        return [item["center"][0] - ox, item["center"][1] - oy, item["center"][0] + ox, item["center"][1] + oy]
    assert not letter.order_conflict(box(a), box(b), w, h)
    assert b["order_issue"] is None
    assert not [x for x in plan["warnings"] if "先讀到" in x]


def test_lettering_warns_when_manual_positions_break_the_order(comic):
    project, board = comic
    board = copy.deepcopy(board)
    k4 = board["pages"][0]["panels"][3]
    k4["bubbles"] = [{"kind": "speech", "speaker": "lin", "text": "第一句。\n好", "anchor": [0.5, 0.5]},
                     {"kind": "speech", "speaker": "lin", "text": "第二句。", "anchor": [0.5, 0.5]}]
    letters = {"p001_k4": {"faces": [], "bubbles": [{"center": [0.15, 0.7]}, {"center": [0.85, 0.2]}], "sfx": []}}
    plan = letter.plan_page(project, 1, board["pages"][0], PAGES, {}, letters, settings_or_skip())
    panel = next(p for p in plan["panels"] if p["id"] == "p001_k4")
    assert panel["bubbles"][1]["order_issue"] == 1
    warn = [x for x in plan["warnings"] if "先讀到" in x]
    assert len(warn) == 1 and "第 1 頁第 4 格" in warn[0] and "⏎" in warn[0] and "\n" not in warn[0]


def test_storyboard_check_warns_on_reversed_anchors(comic):
    project, board = comic
    panel = copy.deepcopy(board["pages"][0]["panels"][4])                # 範例 k5：hao 右上、lin 左上，順序對
    assert not [i for i in check.check_panel(project, 1, panel) if "anchor 在" in i.message]
    panel["bubbles"][1]["anchor"] = [0.97, 0.0]                           # 第二句跑到右上
    issues = [i for i in check.check_panel(project, 1, panel) if "anchor 在" in i.message]
    assert len(issues) == 1 and issues[0].level == "warn" and "第 2 個" in issues[0].message


# ---- L-1 外觀字 ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text, level", [
    ("A young man with dark hair waits.", "error"),
    ("Tousled hair falling over his eyes", "error"),
    ("pushes up his glasses", "error"),
    ("A bearded man nods.", "error"),
    ("A bald man nods.", "error"),
    ("A young man in a navy uniform", "error"),
    ("She stands in a red dress.", "error"),
    ("She has twin tails.", "error"),
    ("He wears a jacket.", "error"),
    ("dressed in black", "error"),
    ("Takes off his lab coat", "warn"),                   # 衣物是動作的對象：只提醒
    ("One arm still stuck in his jacket sleeve", "warn"),
    ("Wearing a headset, listening", None),               # 道具放行
    ("wearing a backpack", None),
    ("Pours two glasses of water", None),
    ("Pressing a headset to his ear", None),
])
def test_appearance_words(text, level):
    issues = []
    check._appearance(text, "scene", "w", issues)
    assert (issues[0].level if issues else None) == level, [str(i) for i in issues]


# ---- L-2 重複的格 id、頁碼 -------------------------------------------------------------------------

def test_save_storyboard_rejects_duplicate_ids_and_pages(comic):
    project, board = comic
    dup = copy.deepcopy(board)
    dup["pages"][0]["panels"][1]["id"] = "p001_k1"
    with pytest.raises(workspace.WorkspaceError, match="p001_k1.*重複"):
        workspace.save_storyboard(project, 1, dup)
    two = copy.deepcopy(board)
    two["pages"].append(copy.deepcopy(two["pages"][0]))
    with pytest.raises(workspace.WorkspaceError, match="第 1 頁出現兩次"):
        workspace.save_storyboard(project, 1, two)
    workspace.save_storyboard(project, 1, board)                              # 原本的照樣能存


# ---- L-3 忠實度：兩句併成一個對話框 ------------------------------------------------------------------

def test_fidelity_accepts_merged_quotes_but_not_rewrites():
    source = "「報名排的。」阿海說。「你排了嗎？」\n「意思是，我知道這件事。」\n「標星號的是我試過的。」\n「好。」他說，「等一下。」"
    page, _ = sc.parse_page("## 第 1 頁（模板 1）\n\n**1 格**｜中景｜畫面。\n"
                            "- 阿海：報名排的。你排了嗎？\n- 周遠：意思是，我知道這件事。……是我。\n- 周遠：好。等一下。")
    report = sc.fidelity(source, [page])
    assert report["dialogue_found"] == 2
    assert report["not_in_source"] == ["意思是，我知道這件事。……是我。"]     # 「是我」是子字串，但不是原著的任何一句


# ---- L-4 規劃的原著依據 ---------------------------------------------------------------------------

def test_plan_source_must_be_in_the_original(comic):
    project, _ = comic
    source = project.load_source(1)
    quote = next(q for q in sc.source_quotes(source) if len(sc.normalize(q)) >= 6)
    plan = {"title": "t", "pages": [{"page": 1, "template": "1", "purpose": "p", "panels": [
        {"slot": 1, "beat": "b", "source": "原著依據：「%s」" % quote}]}]}
    assert not [i for i in check.check_plan(project, plan, PAGES, source=source) if "原著依據" in i.message]
    plan["pages"][0]["panels"][0]["source"] = "他把整座城市都燒了"
    issues = [i for i in check.check_plan(project, plan, PAGES, source=source) if "原著依據" in i.message]
    assert len(issues) == 1 and issues[0].level == "warn"
    plan["pages"][0]["panels"][0]["source"] = quote[:5] + "……" + quote[-5:]   # 用刪節號省略中間：可以
    assert not [i for i in check.check_plan(project, plan, PAGES, source=source) if "原著依據" in i.message]
    assert not [i for i in check.check_plan(project, plan, PAGES) if "原著依據" in i.message]   # 沒給原著就不比


# ---- L-5 提示詞只放卡片本文第一段 ------------------------------------------------------------------

def test_card_summary_takes_first_paragraph_only():
    body = ("\n曙光站通訊官，句子快。\n會逼人選邊。\n\n## 待確認（請人工看過再確認入庫）\n- 補上的：髮型\n\n"
            "## 登場章節\n第 1 章\n\n## 原文依據\n- 第 3 章｜外觀")
    assert prompts.card_summary(body) == "曙光站通訊官，句子快。 會逼人選邊。"
    assert prompts.card_summary("# 林曉雨\n\n大學二年級。\n") == "大學二年級。"
    assert prompts.card_summary("- 只有清單") == ""


def test_bible_block_has_no_card_headings(comic):
    project, _ = comic
    card = project.characters["lin"]
    path = Path(card["_path"])
    path.write_text(path.read_text(encoding="utf-8") + "\n## 待確認\n- 補上的：XYZZY\n", encoding="utf-8")
    project = Project(project.root)
    text = prompts.bible_block(project)
    assert "待確認" not in text and "XYZZY" not in text


# ---- L-6 錯誤訊息裡的換行 -----------------------------------------------------------------------

def test_messages_show_newlines_as_return_symbol(comic):
    project, board = comic
    page, _ = sc.parse_page("## 第 1 頁（模板 1）\n\n**3 格**｜中景｜畫面。\n- 阿浩：對不起！排隊排到一半")
    panel = copy.deepcopy(board["pages"][0]["panels"][2])
    panel["sfx"] = []
    issues = [str(i) for i in check.check_against_script(project, 1, [panel], page) if i.level == "error"]
    assert issues and all("\n" not in i for i in issues)
    assert any("⏎" in i for i in issues)
    long = check.column_issues("一二三四五六七八九十一二三四\n短", "speech", "w")
    assert long and "\n" not in str(long[0])
    assert check.shown("a\nb") == "a⏎b" and check.shown("x" * 20, 5) == "xxxxx…"
