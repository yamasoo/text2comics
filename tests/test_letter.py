"""嵌字（t2c/letter.py）的檢查：排字禁則、標點、位置避臉、尾巴、微調檔、實際畫到頁面上。
需要一套中文字型（Noto CJK、思源、微軟正黑體…）；找不到就跳過需要畫字的項目。"""
import json
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from t2c import compose, layout, letter  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"


def settings_or_skip():
    try:
        return letter.Settings.from_config({})
    except letter.LetterError:
        pytest.skip("這台電腦找不到中文字型")


@pytest.fixture
def comic(tmp_path):
    """範例專案（設定、聖經、分鏡），renders 每格放一張 1000×800 的灰圖。"""
    root = tmp_path / "comic"
    for sub in ("bible", "storyboard"):
        shutil.copytree(SAMPLE / sub, root / sub)
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    renders = root / "renders" / "ch001"
    renders.mkdir(parents=True)
    for slot in range(1, 6):
        Image.new("L", (1000, 800), 120).save(renders / ("p001_k%d_s11.png" % slot))
    project = Project(root)
    return project, project.load_storyboard(1)


def plan_of(comic, letters=None, settings=None, picks=None):
    project, board = comic
    return letter.plan_page(project, 1, board["pages"][0], layout.load_pages(), picks or {}, letters or {},
                            settings or settings_or_skip())


def texts(lines):
    return ["".join(u[1] for u in line) for line in lines]


# ---- 排字 ---------------------------------------------------------------------------------------

def test_tokenize_kinds():
    units = letter.tokenize("「好！？」……12個ABC，")
    assert [u[0] for u in units] == ["r", "c", "t", "r", "r", "t", "c", "r", "p"]
    assert units[4] == ["r", "……", 2]                       # 刪節號整串不拆、佔兩格
    assert units[5] == ["t", "12", 1]                       # 兩位數縱中橫
    assert letter.tokenize("一\n二")[1][0] == "br"
    assert all(u[0] == "c" for u in letter.tokenize("「好」", vertical=False))


@pytest.mark.parametrize("text", [
    "對不起排隊排到一半，被教授抓去搬東西！", "妳上次說的，不要香菜。", "他說「明天見」然後走了。", "……記得這種事幹嘛。",
    "啊啊啊啊啊！？好痛好痛。。。",
])
@pytest.mark.parametrize("rows", [2, 3, 4, 5, 7])
def test_line_breaking_rules(text, rows):
    lines = letter.break_lines(letter.tokenize(text), rows)
    assert "".join(texts(lines)) == text.replace("\n", "")  # 不多不少
    for i, line in enumerate(lines):
        assert line, "不能有空欄"
        if i > 0:
            assert line[0][1][0] not in letter.NO_START, "欄首不能是 %r（%s）" % (line[0][1], texts(lines))
        if i < len(lines) - 1:
            assert line[-1][1][-1] not in letter.NO_END, "欄尾不能是 %r（%s）" % (line[-1][1], texts(lines))
        trailing_punct = all(u[1][:1] in letter.NO_START for u in line[-2:])
        assert letter._span(line) <= rows + 1 or trailing_punct      # 最多懸一格（整串標點例外）


def test_soft_break_after_punctuation_and_forced_newline():
    assert texts(letter.break_lines(letter.tokenize("妳上次說的，不要香菜。"), 6)) == ["妳上次說的，", "不要香菜。"]
    lines, *_ = letter.layout_text("speech", "對不起！\n排隊排到一半", 32, True, 2000, 2000)
    assert texts(lines) == ["對不起！", "排隊排到一半"]


def test_short_line_is_one_column_and_long_line_is_split():
    lines, rx, ry, fits = letter.layout_text("speech", "……又不接。", 32, True, 2000, 2000)
    assert len(lines) == 1 and fits and ry > rx
    lines, *_ = letter.layout_text("speech", "對不起排隊排到一半被教授抓去搬東西真的很抱歉", 32, True, 2000, 2000)
    assert 2 <= len(lines) <= 6


def test_bubble_contains_text_block():
    for kind in letter.KINDS:
        for tw, th in [(32, 300), (200, 120), (100, 100)]:
            rx, ry = letter.shape_axes(kind, tw, th, 32)
            if kind == "narration":
                assert rx >= tw / 2 and ry >= th / 2
            else:
                assert (tw / 2 / rx) ** 2 + (th / 2 / ry) ** 2 <= 0.93


def test_too_big_text_reports_not_fitting():
    *_, fits = letter.layout_text("speech", "字" * 200, 40, True, 300, 300)
    assert not fits


# ---- 幾何 -----------------------------------------------------------------------------------------

def test_map_box_follows_crop():
    assert letter.map_box([0.2, 0.2, 0.4, 0.6], [0, 0, 1, 1]) == [0.2, 0.2, 0.4, 0.6]
    zoomed = letter.map_box([0.5, 0.5, 0.75, 0.75], [0.5, 0.5, 1, 1])          # 只留右下四分之一
    assert zoomed == [0, 0, 0.5, 0.5]
    assert letter.map_box([0, 0, 0.2, 0.2], [0.5, 0.5, 1, 1]) is None         # 被裁掉
    assert compose.crop_window((1000, 1000), (100, 100), (1, 1), 2.0) == [0.5, 0.5, 1, 1]


def test_estimate_face_is_top_of_box_and_grows_with_shot():
    wide = letter.estimate_face([100, 100, 300, 700], "wide")
    close = letter.estimate_face([100, 100, 300, 700], "close")
    assert wide[1] == 100 and close[1] == 100
    assert close[3] - close[1] > wide[3] - wide[1]
    assert 100 <= wide[0] < wide[2] <= 300


def test_auto_tail_points_to_face_and_stops_outside_it():
    bubble = {"kind": "speech", "cx": 200, "cy": 200, "rx": 50, "ry": 100}
    face = [500, 250, 600, 350]
    tip = letter.auto_tail(bubble, face, [480, 250, 620, 900], 32)
    assert tip[0] > 250                                       # 往右（臉的方向）
    assert not (face[0] - 5 <= tip[0] <= face[2] + 5 and face[1] - 5 <= tip[1] <= face[3] + 5)
    assert ((tip[0] - 200) / 50) ** 2 + ((tip[1] - 200) / 100) ** 2 > 1   # 在框外
    assert letter.auto_tail(bubble, None, None, 32) is None


# ---- 排版計畫 ---------------------------------------------------------------------------------------

def test_sample_plan_keeps_bubbles_inside_panels_and_off_faces(comic):
    plan = plan_of(comic)
    assert plan["warnings"] == []
    for panel in plan["panels"]:
        rect = panel["rect"]
        for b in panel["bubbles"]:
            ox, oy = letter.outer_axes(b["kind"], b["rx"], b["ry"])
            assert rect[0] <= b["center"][0] - ox and b["center"][0] + ox <= rect[2]
            assert rect[1] <= b["center"][1] - oy and b["center"][1] + oy <= rect[3]
            shape = {"kind": b["kind"], "cx": b["center"][0], "cy": b["center"][1], "rx": b["rx"], "ry": b["ry"]}
            for face in panel["faces"]:
                assert letter.shape_overlap(shape, face) == 0, "%s 的對話框壓到臉" % panel["id"]
            if b["kind"] == "narration":
                assert b["tail"] is None
            elif b["speaker"]:
                assert b["tail"] is not None


def test_two_bubbles_do_not_overlap_and_keep_reading_order(comic):
    k5 = plan_of(comic)["panels"][4]
    first, second = k5["bubbles"]
    a = [first["center"][0] - first["rx"], first["center"][1] - first["ry"], first["center"][0] + first["rx"],
         first["center"][1] + first["ry"]]
    assert letter.shape_overlap({"kind": "speech", "cx": second["center"][0], "cy": second["center"][1],
                                 "rx": second["rx"], "ry": second["ry"]}, a) == 0
    assert not (second["center"][0] > first["center"][0] and second["center"][1] < first["center"][1])


def test_face_override_pushes_bubble_away(comic):
    k4 = plan_of(comic)["panels"][3]
    b = k4["bubbles"][0]
    rect = k4["rect"]
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    fx, fy = (b["center"][0] - rect[0]) / w, (b["center"][1] - rect[1]) / h
    face = [max(fx - 0.15, 0), max(fy - 0.15, 0), min(fx + 0.15, 1), min(fy + 0.15, 1)]     # 假裝臉就在原本的位置
    moved = plan_of(comic, {"p001_k4": letter.check_panel_letters("p001_k4", {"faces": [face]})})["panels"][3]
    assert moved["faces_auto"] is False and len(moved["faces"]) == 1
    nb = moved["bubbles"][0]
    assert letter.shape_overlap({"kind": "speech", "cx": nb["center"][0], "cy": nb["center"][1], "rx": nb["rx"],
                                 "ry": nb["ry"]}, moved["faces"][0]) == 0


def test_center_tail_scale_rows_overrides(comic):
    over = letter.check_panel_letters("p001_k1", {"bubbles": [
        {"center": [0.2, 0.3]},
        {"text": "舊的台詞", "center": [0.5, 0.5], "tail": None, "scale": 1.5, "rows": 2},
    ]})
    plan = plan_of(comic, {"p001_k1": over})
    narration, speech = plan["panels"][0]["bubbles"]
    rect = plan["panels"][0]["rect"]
    assert narration["auto_center"] is False
    assert abs(narration["center"][0] - (rect[0] + 0.2 * (rect[2] - rect[0]))) < 1
    assert speech["tail"] is None and speech["auto_tail"] is False
    assert speech["scale"] == 1.5 and speech["rows"] == 2 and len(speech["lines"]) >= 2
    base = plan_of(comic)["panels"][0]["bubbles"][1]
    assert speech["cell"] == pytest.approx(base["cell"] * 1.5, rel=0.01)
    assert any("台詞改過了" in w for w in plan["warnings"])
    manual = letter.check_panel_letters("p001_k1", {"bubbles": [{}, {"tail": [0.9, 0.9]}]})
    tip = plan_of(comic, {"p001_k1": manual})["panels"][0]["bubbles"][1]["tail"]
    assert tip == [round(rect[0] + 0.9 * (rect[2] - rect[0]), 1), round(rect[1] + 0.9 * (rect[3] - rect[1]), 1)]


def test_extra_override_entries_are_reported(comic):
    over = letter.check_panel_letters("p001_k4", {"bubbles": [{}, {"center": [0.5, 0.5]}]})
    assert any("多 1 個" in w for w in plan_of(comic, {"p001_k4": over})["warnings"])


def test_bubbles_follow_the_crop(comic):
    """zoom 2、焦點在右下：分鏡的 anchor 跟著換算，對話框位置會變。"""
    picks = {"p001_k4": {"image": "p001_k4_s11.png", "focus": [1.0, 1.0], "zoom": 2.0}}
    plain, zoomed = plan_of(comic)["panels"][3], plan_of(comic, picks=picks)["panels"][3]
    assert zoomed["window"][0] > plain["window"][0] + 0.2
    assert zoomed["bubbles"][0]["anchor"] != plain["bubbles"][0]["anchor"]


def test_sfx_overlay_and_moss_mode(comic):
    k3 = plan_of(comic)["panels"][2]
    assert len(k3["sfx"]) == 1 and k3["sfx"][0]["text"] == "碰！"
    project, board = comic
    project.config["sfx_mode"] = "moss"
    assert plan_of(comic)["panels"][2]["sfx"] == []


def test_plan_is_json_serializable(comic):
    json.dumps(plan_of(comic), ensure_ascii=False)


# ---- 微調檔 -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("entry", [
    "x", {"faces": "nope"}, {"faces": [[0.5, 0.5, 0.2, 0.9]]}, {"bubbles": {}}, {"bubbles": [{"center": [2, 0]}]},
    {"bubbles": [{"tail": "left"}]}, {"bubbles": [{"scale": 5}]}, {"bubbles": [{"rows": 0}]}, {"bubbles": [{"rows": 2.5}]},
    {"bubbles": [{"cneter": [0.5, 0.5]}]}, {"sfx": [{"angle": 90}]}, {"sfx": [{"vertical": "yes"}]}, {"oops": 1},
])
def test_bad_letters_are_rejected(entry):
    with pytest.raises(letter.LetterError):
        letter.check_panel_letters("p001_k1", entry)


def test_letters_round_trip_drops_empty_entries(comic):
    project, _ = comic
    data = {"p001_k1": letter.check_panel_letters("p001_k1", {"bubbles": [{}, {"center": [0.123456, 0.5], "tail": None}, {}]}),
            "p001_k2": letter.check_panel_letters("p001_k2", {"bubbles": [{}], "sfx": []}),
            "p001_k3": letter.check_panel_letters("p001_k3", {"faces": []})}
    path = letter.save_letters(project, 1, data)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["panels"] == {"p001_k1": {"bubbles": [{}, {"center": [0.1235, 0.5], "tail": None}]},
                               "p001_k3": {"faces": []}}
    loaded = letter.load_letters(project, 1)
    assert loaded["p001_k3"]["faces"] == [] and loaded["p001_k1"]["bubbles"][1]["tail"] is None


# ---- 字型 -----------------------------------------------------------------------------------------------

def test_font_errors_are_readable(tmp_path):
    with pytest.raises(letter.LetterError, match="lettering.dialogue_font"):
        letter.Settings.from_config({"dialogue_font": str(tmp_path / "nope.ttf")})
    with pytest.raises(letter.LetterError, match="找不到中文字型"):
        letter.Settings.from_config({}, dirs=[])
    with pytest.raises(letter.LetterError, match="dialogue_pt"):
        letter.Settings.from_config({"dialogue_pt": "big"})


def test_ttc_without_index_picks_traditional_chinese():
    settings = settings_or_skip()
    path, index = settings.fonts["dialogue"]
    if path.lower().endswith(".ttc"):
        name = " ".join(settings.font("dialogue", 20).getname())
        assert letter.TC_FACE.search(name), name


# ---- 畫 ------------------------------------------------------------------------------------------------

def _ink_box(img):
    return Image.eval(img, lambda v: 255 - v).getbbox()


def test_vertical_punctuation_is_centered_and_rotated():
    settings = settings_or_skip()
    font = settings.font("dialogue", 60)
    ink, mask = Image.new("L", (120, 120), 255), Image.new("L", (120, 120), 0)
    letter.draw_text(ink, mask, [[["p", "。", 1]]], 60, 60, 60, font)
    box = _ink_box(ink)
    assert abs((box[0] + box[2]) / 2 - 60) <= 3 and abs((box[1] + box[3]) / 2 - 60) <= 3     # 句號在字格正中
    ink = Image.new("L", (200, 200), 255)
    letter.draw_text(ink, Image.new("L", (200, 200), 0), [[["r", "…", 1]]], 100, 100, 60, font)
    box = _ink_box(ink)
    assert box[3] - box[1] > 2 * (box[2] - box[0])                                          # 刪節號轉成直的
    ink = Image.new("L", (200, 200), 255)
    letter.draw_text(ink, Image.new("L", (200, 200), 0), [[["c", "一", 1]], [["c", "二", 1]]], 100, 100, 60, font)
    assert ink.crop((100, 0, 200, 200)).getextrema()[0] < 100 and ink.crop((0, 0, 100, 200)).getextrema()[0] < 100
    first = Image.new("L", (200, 200), 255)
    letter.draw_text(first, Image.new("L", (200, 200), 0), [[["c", "一", 1]], []], 100, 100, 60, font)
    assert _ink_box(first)[0] > 100                                                          # 第一欄在右邊


@pytest.mark.parametrize("kind", letter.KINDS)
def test_each_bubble_kind_draws_white_inside_and_dark_text(kind):
    settings = settings_or_skip()
    canvas = Image.new("L", (600, 600), 120)
    lines, rx, ry, _ = letter.layout_text(kind, "測試台詞好", 32, True, 600, 600)
    bubble = {"kind": kind, "center": [250, 250], "rx": rx, "ry": ry, "tail": None if kind == "narration" else [480, 480],
              "cell": 32, "lines": lines, "vertical": True, "index": 0}
    letter.render_bubble(canvas, (0, 0, 600, 600), bubble, settings, "seed")
    inside = canvas.crop((int(250 - rx * 0.6), int(250 - ry * 0.9), int(250 + rx * 0.6), int(250 + ry * 0.9)))
    low, high = inside.getextrema()
    assert high == 255 and low < 60                          # 白底黑字
    assert canvas.getpixel((590, 10)) == 120                 # 框外不動
    if kind != "narration":
        assert canvas.crop((440, 440, 490, 490)).getextrema() != (120, 120)              # 尾巴伸到右下


def test_compose_with_lettering_writes_page_and_no_letter_does_not(comic):
    settings = settings_or_skip()
    project, board = comic
    written, warnings = compose.compose_chapter(project, 1, board, lettering=settings)
    lettered = Image.open(written[0][1])
    plan = plan_of(comic, settings=settings)
    for panel in plan["panels"]:
        for b in panel["bubbles"]:
            x, y = b["center"]
            region = lettered.crop((int(x - b["rx"] * 0.5), int(y - b["ry"] * 0.7), int(x + b["rx"] * 0.5),
                                    int(y + b["ry"] * 0.7)))
            extrema = region.convert("L").getextrema()          # 頁面可能是 RGB（預設保留原色）
            assert extrema[1] == 255 and extrema[0] < 80
    plain, _ = compose.compose_chapter(project, 1, board, out_dir=project.root / "plain")
    first = plan["panels"][0]["bubbles"][0]["center"]
    value = Image.open(plain[0][1]).getpixel(tuple(int(v) for v in first))
    assert (value[0] if isinstance(value, tuple) else value) == 120


def test_cli_letters_and_options(comic, capsys, tmp_path):
    settings_or_skip()
    import pages
    root = str(comic[0].root)
    assert pages.main([root, "1"]) == 0
    assert pages.main([root, "1", "--no-letter", "--out", str(tmp_path / "a")]) == 0
    assert pages.main([root, "1", "--guides", "--out", str(tmp_path / "b")]) == 0
    a, b = Image.open(tmp_path / "a" / "p001.png"), Image.open(tmp_path / "b" / "p001.png")
    assert a.size == b.size and a.tobytes() != b.tobytes()
    (comic[0].root / "letters").mkdir()
    (comic[0].root / "letters" / "ch001.json").write_text('{"version": 1, "panels": {"p001_k1": {"faces": 3}}}',
                                                          encoding="utf-8")
    assert pages.main([root, "1"]) == 2
    assert "faces" in capsys.readouterr().err
