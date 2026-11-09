"""頁面模板、格子尺寸、MOSS-Image 的 bbox 換算。

座標約定（整個專案都一樣）：
- 分鏡裡的位置一律是「比例」[x0, y0, x1, y1]，左上 (0,0)、右下 (1,1)。給 LLM 與人寫的都是這個。
- 只有送進 MOSS-Image 的那一刻才換成它的格式：像素、原點在畫布中心、順序 [y_min, x_min, y_max, x_max]
  （bbox_coord_space = "abs_centralized"、bbox_format = "yxyx"）。換算只在 to_moss_bbox() 做。
"""
import json
import math
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"      # 套件自帶的資料：整包搬走也讀得到（M1 修正 M-3）
PAGES_FILE = DATA / "pages.json"

MOSS_COORD_SPACE = "abs_centralized"
MOSS_BBOX_FORMAT = "yxyx"


class LayoutError(Exception):
    """給人看的錯誤訊息。"""


def load_pages(path=None):
    data = json.loads(Path(path or PAGES_FILE).read_text(encoding="utf-8"))
    for key, tpl in data["templates"].items():
        for i, box in enumerate(tpl["panels"], 1):
            check_box(box, "模板 %s 第 %d 格" % (key, i))
    return data


def check_box(box, label="位置"):
    """比例框：四個 0–1 的數字，而且 x0 < x1、y0 < y1。"""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise LayoutError("%s 要是 [x0, y0, x1, y1] 四個數字：%r" % (label, box))
    try:
        x0, y0, x1, y1 = (float(v) for v in box)
    except (TypeError, ValueError):
        raise LayoutError("%s 只能是數字：%r" % (label, box))
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise LayoutError("%s 要在 0–1 之間，而且左上小於右下：%r" % (label, box))
    return x0, y0, x1, y1


def page_size(page):
    """回傳組版用的整頁像素 (寬, 高)。"""
    width = int(page["width_px"])
    return width, int(round(width * page["height_mm"] / page["width_mm"]))


def inner_rect(page):
    """頁面內框的像素範圍 (left, top, right, bottom)，margin 是 [左, 上, 右, 下] 的比例。"""
    width, height = page_size(page)
    left, top, right, bottom = page.get("margin", [0, 0, 0, 0])
    return (width * left, height * top, width * (1 - right), height * (1 - bottom))


def panel_rect_px(page, box):
    """格子在整頁上的像素框，已扣掉一半的 gutter（相鄰兩格加起來剛好一個 gutter）。"""
    x0, y0, x1, y1 = check_box(box)
    left, top, right, bottom = inner_rect(page)
    half = page.get("gutter_px", 0) / 2
    w, h = right - left, bottom - top
    px0 = left + x0 * w + (half if x0 > 0 else 0)
    py0 = top + y0 * h + (half if y0 > 0 else 0)
    px1 = left + x1 * w - (half if x1 < 1 else 0)
    py1 = top + y1 * h - (half if y1 < 1 else 0)
    return (round(px0), round(py0), round(px1), round(py1))


def _round16(value):
    return max(16, int(round(value / 16.0)) * 16)


def gen_size(aspect, megapixels=1.0, min_aspect=1 / 3, max_aspect=3.0):
    """依格子的寬高比算出生圖尺寸：總像素約 megapixels、寬高都是 16 的倍數。
    太細長的格子先夾到 [min_aspect, max_aspect]，組版時再裁切成格子的形狀。"""
    if aspect <= 0:
        raise LayoutError("寬高比要大於 0：%r" % aspect)
    aspect = min(max(aspect, min_aspect), max_aspect)
    pixels = float(megapixels) * 1_000_000
    width = math.sqrt(pixels * aspect)
    return _round16(width), _round16(width / aspect)


def to_moss_bbox(box, width, height):
    """比例框 [x0, y0, x1, y1] → MOSS 的 [y_min, x_min, y_max, x_max]（像素、原點在中心）。"""
    x0, y0, x1, y1 = check_box(box)
    half_w, half_h = width / 2.0, height / 2.0
    return [
        int(round(y0 * height - half_h)),
        int(round(x0 * width - half_w)),
        int(round(y1 * height - half_h)),
        int(round(x1 * width - half_w)),
    ]


def from_moss_bbox(bbox, width, height):
    """to_moss_bbox 的反向（除錯、預覽框線用）。"""
    y0, x0, y1, x1 = bbox
    return [(x0 + width / 2.0) / width, (y0 + height / 2.0) / height,
            (x1 + width / 2.0) / width, (y1 + height / 2.0) / height]
