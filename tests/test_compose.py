"""組版（t2c/compose.py、tools/pages.py）的檢查：用合成的純色圖，不需要 ComfyUI。"""
import json
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from t2c import compose, layout  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"
GRAYS = {1: 20, 2: 60, 3: 100, 4: 140, 5: 180}        # 每個 slot 一種灰階，組版後用它認格子


@pytest.fixture
def comic(tmp_path):
    """範例專案（只複製設定、聖經、分鏡），renders 放每格 2 張合成圖。"""
    root = tmp_path / "comic"
    for sub in ("bible", "storyboard"):
        shutil.copytree(SAMPLE / sub, root / sub)
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    renders = root / "renders" / "ch001"
    renders.mkdir(parents=True)
    for slot, gray in GRAYS.items():
        Image.new("L", (1000, 800), gray).save(renders / ("p001_k%d_s11.png" % slot))
        Image.new("L", (1000, 800), 250).save(renders / ("p001_k%d_s22.png" % slot))
    project = Project(root)
    return project, project.load_storyboard(1)


def px(img, xy):
    """一個像素的亮度。頁面可能是 RGB（預設保留原色）或 L（output.gray: true）。"""
    value = img.getpixel(xy)
    return value[0] if isinstance(value, tuple) else value


def center(img, rect):
    return px(img, ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2))


def test_page_is_b5_ratio_with_dpi(comic):
    project, board = comic
    written, _ = compose.compose_chapter(project, 1, board)
    img = Image.open(written[0][1])
    data = layout.load_pages()["page"]
    assert img.size == layout.page_size(data)
    assert abs(img.size[0] / img.size[1] - 182 / 257) < 0.001
    assert img.mode == "RGB"                             # 預設保留原色；要灰階寫 output.gray: true
    assert round(img.info["dpi"][0]) == compose.page_dpi(data) == 254


def test_reading_order_and_grid(comic):
    """每一格的中心就是該 slot 的圖，且 slot 1 在右上、2 在左上（右翻）。"""
    project, board = comic
    picks = {"p001_k%d" % s: {"image": "p001_k%d_s11.png" % s, "focus": [0.5, 0.5], "zoom": 1.0} for s in GRAYS}
    written, warnings = compose.compose_chapter(project, 1, board, picks=picks)
    assert warnings == []
    img = Image.open(written[0][1])
    page = layout.load_pages()
    rects = [layout.panel_rect_px(page["page"], box) for box in page["templates"]["5a"]["panels"]]
    for slot, rect in enumerate(rects, 1):
        assert center(img, rect) == GRAYS[slot]
    assert rects[0][0] > rects[1][0] and rects[0][1] == rects[1][1]       # 1 在 2 的右邊、同一排
    assert rects[2][1] > rects[0][3]                                       # 3 在第一排下面


def test_frames_and_gutters(comic):
    project, board = comic
    written, _ = compose.compose_chapter(project, 1, board)
    img = Image.open(written[0][1])
    page = layout.load_pages()
    cfg = page["page"]
    rect = layout.panel_rect_px(cfg, page["templates"]["5a"]["panels"][0])
    assert px(img, (rect[0] + 1, (rect[1] + rect[3]) // 2)) == 0      # 框線是黑的
    assert px(img, (rect[0] + cfg["frame_px"] + 6, (rect[1] + rect[3]) // 2)) != 0   # 框內是圖
    assert px(img, (rect[0] - cfg["gutter_px"] // 4, (rect[1] + rect[3]) // 2)) == 255   # 格外是白邊
    assert px(img, (2, 2)) == 255                                      # 頁邊是白的


def test_pick_overrides_default(comic):
    project, board = comic
    picks = {"p001_k1": {"image": "p001_k1_s22.png", "focus": [0.5, 0.5], "zoom": 1.0}}
    written, warnings = compose.compose_chapter(project, 1, board, picks=picks)
    img = Image.open(written[0][1])
    rects = [layout.panel_rect_px(layout.load_pages()["page"], b) for b in layout.load_pages()["templates"]["5a"]["panels"]]
    assert center(img, rects[0]) == 250
    assert len(warnings) == 4 and all("沒有選圖紀錄" in w for w in warnings)      # 其餘 4 格暫用第一個候選


def test_missing_image_gets_placeholder_and_warning(comic):
    project, board = comic
    for f in (project.root / "renders" / "ch001").glob("p001_k3_*"):
        f.unlink()
    written, warnings = compose.compose_chapter(project, 1, board)
    assert any("p001_k3" in w and "沒有任何候選圖" in w for w in warnings)
    assert Image.open(written[0][1]).size[0] == 1820


def test_pick_pointing_to_missing_file_is_an_error(comic):
    project, board = comic
    picks = {"p001_k1": {"image": "nope.png"}}
    with pytest.raises(compose.ComposeError, match="p001_k1.*不存在"):
        compose.compose_chapter(project, 1, board, picks=picks)


@pytest.mark.parametrize("entry", [
    {"image": "../x.png"}, {"image": "a/b.png"}, {}, {"image": "a.png", "focus": [2, 0.5]},
    {"image": "a.png", "focus": [0.5]}, {"image": "a.png", "zoom": 0.5}, {"image": "a.png", "zoom": 9}, "a.png",
])
def test_bad_pick_entries_are_rejected(entry):
    with pytest.raises(compose.ComposeError):
        compose.check_pick("p001_k1", entry)


def test_crop_cover_focus_and_zoom():
    left_black = Image.new("L", (200, 100), 255)
    left_black.paste(0, (0, 0, 100, 100))                                  # 左半黑、右半白
    assert compose.crop_cover(left_black, (50, 50), focus=(0.0, 0.5)).getpixel((25, 25)) == 0
    assert compose.crop_cover(left_black, (50, 50), focus=(1.0, 0.5)).getpixel((25, 25)) == 255
    quad = Image.new("L", (100, 100), 0)
    quad.paste(255, (50, 50, 100, 100))                                    # 只有右下四分之一是白
    assert compose.crop_cover(quad, (40, 40), zoom=1.0).getpixel((5, 5)) == 0
    assert compose.crop_cover(quad, (40, 40), focus=(1.0, 1.0), zoom=4.0).getpixel((5, 5)) == 255   # 放大後只留右下角
    assert compose.crop_cover(quad, (40, 40), focus=(0, 0), zoom=4.0).getpixel((35, 35)) == 0


def test_crop_cover_fills_target_exactly():
    for size in [(300, 100), (100, 300), (123, 77)]:
        assert compose.crop_cover(Image.new("L", (640, 480), 9), size).size == size


def test_picks_round_trip_and_ignore_unknown(comic):
    project, board = comic
    picks = {"p001_k1": compose.check_pick("p001_k1", {"image": "p001_k1_s11.png", "zoom": 2}),
             "p009_k9": compose.check_pick("p009_k9", {"image": "x.png"})}
    path = compose.save_picks(project, 1, picks)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert compose.load_picks(project, 1) == picks
    _, warnings = compose.compose_chapter(project, 1, board)
    assert any("p009_k9" in w and "已忽略" in w for w in warnings)


def test_color_option_keeps_rgb(comic):
    project, board = comic
    written, _ = compose.compose_chapter(project, 1, board, gray=False)
    assert Image.open(written[0][1]).mode == "RGB"


def test_sample_picks_file_is_valid_and_matches_storyboard():
    project = Project(SAMPLE)
    picks = compose.load_picks(project, 1)
    ids = {p.get("id") or "p001_k%d" % p["slot"] for p in project.load_storyboard(1)["pages"][0]["panels"]}
    assert set(picks) == ids


def test_cli_pick_focus_list_and_compose(comic, capsys):
    import pages
    root = str(comic[0].root)
    assert pages.main([root, "1", "--pick", "p001_k1=22", "--focus", "p001_k1=0.2,0.7", "--zoom", "p001_k1=1.5"]) == 0
    saved = compose.load_picks(comic[0], 1)["p001_k1"]
    assert saved == {"image": "p001_k1_s22.png", "focus": [0.2, 0.7], "zoom": 1.5}
    assert (comic[0].root / "pages" / "ch001" / "p001.png").is_file()
    assert pages.main([root, "1", "--list"]) == 0
    out = capsys.readouterr().out
    assert "* p001_k1_s22.png" in out and "p001_k2  （未選）" in out
    assert pages.main([root, "1", "--pick", "p001_k1=999"]) == 2              # 圖不存在
    assert pages.main([root, "1", "--pick", "p999_k1=11"]) == 2               # 分鏡沒有這格
    assert pages.main([root, "1", "--focus", "p001_k2=0.5,0.5"]) == 2         # 還沒選圖就調焦點
    assert pages.main([root, "1", "--page", "7"]) == 2
