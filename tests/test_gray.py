"""組版要不要轉灰階：預設保留原色，只有 project.yaml 明寫 output.gray: true 才轉（1.12.2）。

1.12.1 曾經「依畫風預設集自動轉灰階」，但沒寫 style_preset 的舊專案會被當成 mono，
出圖彩色、頁面變黑白。現在改成所見即所出。
執行：python -m pytest tests/test_gray.py -q
"""
import json
import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import compose, styles  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"


@pytest.fixture
def comic(tmp_path):
    root = tmp_path / "comic"
    for sub in ("bible", "storyboard"):
        shutil.copytree(SAMPLE / sub, root / sub)
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    renders = root / "renders" / "ch001"
    renders.mkdir(parents=True)
    for slot in range(1, 6):
        Image.new("RGB", (1000, 800), (200, 60, 60)).save(renders / ("p001_k%d_s11.png" % slot))
    project = Project(root)
    return project, project.load_storyboard(1)


def page_mode(project, board, **kwargs):
    written, _ = compose.compose_chapter(project, 1, board, **kwargs)
    return Image.open(written[0][1]).mode


def test_presets_still_document_a_suggested_gray():
    assert styles.resolve({"style_preset": "mono"})["gray"] is True
    assert styles.resolve({"style_preset": "color"})["gray"] is False


def test_pages_keep_the_renders_colour_by_default(comic):
    """沒寫 output.gray 就保留原色——即使專案沒有 style_preset（舊專案的常見情況）。"""
    project, board = comic
    assert "style_preset" not in project.config
    assert compose.auto_gray(project) is False
    assert page_mode(project, board) == "RGB"


def test_color_preset_does_not_gray_pages(comic):
    project, board = comic
    project.config["style_preset"] = "color"
    assert page_mode(project, board) == "RGB"


def test_output_gray_turns_pages_grayscale(comic):
    """黑白頁漫想讓 PDF 小一點：明寫 output.gray: true。"""
    project, board = comic
    project.config["output"] = {"gray": True}
    assert compose.auto_gray(project) is True
    assert page_mode(project, board) == "L"


def test_explicit_gray_argument_still_wins(comic):
    project, board = comic
    assert page_mode(project, board, gray=True) == "L"
    project.config["output"] = {"gray": True}
    assert page_mode(project, board, gray=False) == "RGB"


def test_broken_gray_field_is_reported(tmp_path, monkeypatch):
    """styles.json 的 gray 不是布林就報錯，不要當成 false 靜默吃掉。"""
    bad = json.loads(styles.DATA.read_text(encoding="utf-8"))
    bad["presets"]["mono"]["gray"] = "yes"
    path = tmp_path / "styles.json"
    path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(styles, "DATA", path)
    styles._cache.clear()
    try:
        with pytest.raises(styles.StylesError) as error:
            styles.resolve({})
        assert "gray" in str(error.value)
    finally:
        styles._cache.clear()
