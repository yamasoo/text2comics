"""S8：輸出（t2c/export.py、tools/export.py）。用合成的頁面 PNG，不需要 ComfyUI。
執行：python -m pytest tests/test_export.py
"""
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from t2c import compose, export  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"
GRAYS = {1: 30, 2: 120, 3: 220}              # 每頁一種灰階，輸出後用它認頁
SIZE = (364, 514)                            # B5 比例的小圖（真正的頁面是 1820×2570）


@pytest.fixture
def comic(tmp_path):
    """3 頁的專案（把範例的第 1 頁複製成 3 頁）；頁面 PNG 是合成的純色圖、dpi 254。"""
    root = tmp_path / "comic"
    root.mkdir()
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    shutil.copytree(SAMPLE / "bible", root / "bible")
    board = json.loads((SAMPLE / "storyboard" / "ch001.json").read_text(encoding="utf-8"))
    board["pages"] = [dict(board["pages"][0], page=n) for n in GRAYS]
    (root / "storyboard").mkdir()
    (root / "storyboard" / "ch001.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    pages = root / "pages" / "ch001"
    pages.mkdir(parents=True)
    for n, gray in GRAYS.items():
        Image.new("L", SIZE, gray).save(pages / ("p%03d.png" % n), dpi=(254, 254))
    return Project(root)


# ---- PDF ---------------------------------------------------------------------------

def parse_pdf(data):
    """很小的 PDF 讀取：驗證 xref 位移正確，回傳 {編號: 物件內容 bytes}。"""
    assert data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")
    start = int(re.search(rb"startxref\n(\d+)\n%%EOF", data).group(1))
    assert data[start:start + 4] == b"xref"
    count = int(re.match(rb"xref\n0 (\d+)\n", data[start:]).group(1))
    entries = re.findall(rb"(\d{10}) (\d{5}) ([nf]) \n", data[start:])
    assert len(entries) == count and entries[0][2] == b"f"
    objects = {}
    for number, (offset, _, kind) in enumerate(entries):
        if kind == b"f":
            continue
        head = b"%d 0 obj\n" % number
        assert data[int(offset):int(offset) + len(head)] == head, "第 %d 號物件的位移不對" % number
        end = data.index(b"\nendobj\n", int(offset))
        objects[number] = data[int(offset) + len(head):end]
    return objects


def pdf_pages(objects):
    """依 /Kids 的順序回傳每頁的 (MediaBox, 影像物件內容)。"""
    root = next(b for b in objects.values() if b"/Type /Catalog" in b)
    pages_obj = objects[int(re.search(rb"/Pages (\d+) 0 R", root).group(1))]
    kids = [int(k) for k in re.findall(rb"(\d+) 0 R", re.search(rb"/Kids \[(.*?)\]", pages_obj).group(1))]
    out = []
    for kid in kids:
        page = objects[kid]
        box = [float(v) for v in re.search(rb"/MediaBox \[([^\]]*)\]", page).group(1).split()]
        image = objects[int(re.search(rb"/Im0 (\d+) 0 R", page).group(1))]
        out.append((box, image))
    return root, out


def image_pixels(image_obj):
    """影像物件（Flate）→ (寬, 高, 第一個像素)。"""
    width = int(re.search(rb"/Width (\d+)", image_obj).group(1))
    height = int(re.search(rb"/Height (\d+)", image_obj).group(1))
    stream = image_obj.split(b"stream\n", 1)[1].rsplit(b"\nendstream", 1)[0]
    return width, height, zlib.decompress(stream)


def test_pdf_is_right_to_left_with_pages_in_order(comic):
    path, warnings = export.export_chapter(comic, 1, "pdf")
    assert warnings == [] and path == comic.root / "out" / "ch001.pdf"
    root, pages = pdf_pages(parse_pdf(path.read_bytes()))
    assert b"/ViewerPreferences << /Direction /R2L >>" in root           # 右翻
    assert b"/PageLayout /TwoPageRight" in root and b"/Lang (zh-TW)" in root
    assert len(pages) == 3
    for box in (b for b, _ in pages):                                      # 254 dpi → 364 px = 103.18 pt
        assert box[:2] == [0, 0] and abs(box[2] - 364 / 254 * 72) < 0.01 and abs(box[3] - 514 / 254 * 72) < 0.01


def test_pdf_lossless_keeps_pixels_and_order(comic):
    path, _ = export.export_chapter(comic, 1, "pdf", quality=None)
    _, pages = pdf_pages(parse_pdf(path.read_bytes()))
    assert [image_pixels(img)[2][0] for _, img in pages] == [GRAYS[1], GRAYS[2], GRAYS[3]]    # 第 1 頁在最前面
    width, height, raw = image_pixels(pages[0][1])
    assert (width, height) == SIZE and len(raw) == SIZE[0] * SIZE[1]
    assert b"/DeviceGray" in pages[0][1] and b"/FlateDecode" in pages[0][1]


def test_pdf_jpeg_is_default_and_smaller(comic):
    jpeg, _ = export.export_chapter(comic, 1, "pdf", out=comic.root / "out" / "a.pdf")
    flate, _ = export.export_chapter(comic, 1, "pdf", out=comic.root / "out" / "b.pdf", quality=None)
    _, pages = pdf_pages(parse_pdf(jpeg.read_bytes()))
    assert all(b"/DCTDecode" in img and b"/DeviceGray" in img for _, img in pages)
    assert export.DEFAULT_QUALITY == 90 and jpeg.stat().st_size > 0 and flate.stat().st_size > 0


def test_pdf_title_is_utf16_and_single_page_layout(comic):
    path, _ = export.export_chapter(comic, 1, "pdf", spread=False)
    objects = parse_pdf(path.read_bytes())
    info = next(b for b in objects.values() if b"/Producer" in b)
    title = bytes.fromhex(re.search(rb"/Title <FEFF([0-9A-F]+)>", info).group(1).decode())
    assert title.decode("utf-16-be") == "屋頂的便當　第 1 章　遲到的便當"
    assert b"/PageLayout /SinglePage" in next(b for b in objects.values() if b"/Type /Catalog" in b)


def test_pdf_deterministic(comic):
    a, _ = export.export_chapter(comic, 1, "pdf", out=comic.root / "out" / "a.pdf")
    b, _ = export.export_chapter(comic, 1, "pdf", out=comic.root / "out" / "b.pdf")
    assert a.read_bytes() == b.read_bytes()


def test_pdf_page_size_follows_png_dpi(comic):
    Image.new("L", SIZE, 99).save(comic.root / "pages" / "ch001" / "p001.png", dpi=(127, 127))     # 一半的 dpi → 兩倍大
    path, _ = export.export_chapter(comic, 1, "pdf", page=1)
    _, pages = pdf_pages(parse_pdf(path.read_bytes()))
    assert abs(pages[0][0][2] - 364 / 127 * 72) < 0.01
    assert b"/PageLayout /SinglePage" in parse_pdf(path.read_bytes())[1]                          # 只有一頁就用單頁


def test_pdf_rgb_page(comic):
    Image.new("RGB", SIZE, (200, 10, 10)).save(comic.root / "pages" / "ch001" / "p002.png", dpi=(254, 254))
    path, _ = export.export_chapter(comic, 1, "pdf", quality=None)
    _, pages = pdf_pages(parse_pdf(path.read_bytes()))
    assert b"/DeviceRGB" in pages[1][1] and b"/DeviceGray" in pages[0][1]
    assert image_pixels(pages[1][1])[2][:3] == bytes([200, 10, 10])


def test_pdf_opens_with_pypdf_if_available(comic):
    pypdf = pytest.importorskip("pypdf")
    path, _ = export.export_chapter(comic, 1, "pdf")
    reader = pypdf.PdfReader(str(path))
    assert len(reader.pages) == 3
    assert str(reader.trailer["/Root"]["/ViewerPreferences"]["/Direction"]) == "/R2L"


# ---- CBZ ---------------------------------------------------------------------------

def test_cbz_pages_comicinfo_and_right_to_left(comic):
    path, warnings = export.export_chapter(comic, 1, "cbz")
    assert warnings == [] and path == comic.root / "out" / "ch001.cbz"
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert names == ["p001.png", "p002.png", "p003.png", "ComicInfo.xml"]
        assert archive.read("p002.png") == (comic.root / "pages" / "ch001" / "p002.png").read_bytes()      # PNG 原封不動
        info = ET.fromstring(archive.read("ComicInfo.xml"))
    assert info.findtext("Manga") == "YesAndRightToLeft"
    assert info.findtext("Series") == "屋頂的便當" and info.findtext("Title") == "遲到的便當"
    assert info.findtext("Number") == "1" and info.findtext("PageCount") == "3"
    assert info.findtext("LanguageISO") == "zh-TW" and info.findtext("BlackAndWhite") == "Yes"
    pages = info.find("Pages").findall("Page")
    assert [p.get("Image") for p in pages] == ["0", "1", "2"] and pages[0].get("Type") == "FrontCover"
    assert pages[0].get("ImageWidth") == str(SIZE[0]) and pages[0].get("ImageHeight") == str(SIZE[1])


def test_cbz_deterministic_and_escapes_title(comic):
    (comic.root / "project.yaml").write_text(
        (comic.root / "project.yaml").read_text(encoding="utf-8").replace("title: 屋頂的便當", 'title: "A & B <1>"'), encoding="utf-8")
    comic = Project(comic.root)
    a, _ = export.export_chapter(comic, 1, "cbz", out=comic.root / "out" / "a.cbz")
    b, _ = export.export_chapter(comic, 1, "cbz", out=comic.root / "out" / "b.cbz")
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as archive:
        assert ET.fromstring(archive.read("ComicInfo.xml")).findtext("Series") == "A & B <1>"


def test_cbz_color_pages_are_not_black_and_white(comic):
    Image.new("RGB", SIZE, (1, 2, 3)).save(comic.root / "pages" / "ch001" / "p003.png", dpi=(254, 254))
    path, _ = export.export_chapter(comic, 1, "cbz")
    with zipfile.ZipFile(path) as archive:
        assert ET.fromstring(archive.read("ComicInfo.xml")).findtext("BlackAndWhite") == "No"


# ---- 整章、單頁、錯誤 -----------------------------------------------------------------

def test_single_page_and_out_locations(comic, tmp_path):
    path, _ = export.export_chapter(comic, 1, "cbz", page=2)
    assert path.name == "ch001_p002.cbz"
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["p002.png", "ComicInfo.xml"]
        assert ET.fromstring(archive.read("ComicInfo.xml")).findtext("PageCount") == "1"
    folder = tmp_path / "books"
    assert export.export_chapter(comic, 1, "pdf", out=folder)[0] == folder / "ch001.pdf"          # 資料夾（還不存在也行）
    assert export.export_chapter(comic, 1, "pdf", page=3, out=folder / "x.pdf")[0] == folder / "x.pdf"
    assert not list(folder.glob("*.tmp"))                                                          # 沒有留下暫存檔
    with pytest.raises(export.ExportError, match="副檔名"):
        export.export_chapter(comic, 1, "pdf", out=folder / "x.cbz")


def test_missing_pages_are_listed_together(comic):
    (comic.root / "pages" / "ch001" / "p002.png").unlink()
    (comic.root / "pages" / "ch001" / "p003.png").unlink()
    with pytest.raises(export.ExportError, match=r"第 2、3 頁還沒有輸出頁面"):
        export.export_chapter(comic, 1, "pdf")
    assert export.export_chapter(comic, 1, "pdf", page=1)[0].is_file()                              # 只輸出有的那頁沒問題


@pytest.mark.parametrize("kwargs, message", [
    ({"fmt": "epub"}, "格式要是"), ({"fmt": "pdf", "page": 9}, "沒有第 9 頁"),
    ({"fmt": "pdf", "quality": 0}, "品質"), ({"fmt": "pdf", "quality": 99}, "品質"),
])
def test_bad_arguments(comic, kwargs, message):
    with pytest.raises(export.ExportError, match=message):
        export.export_chapter(comic, 1, **kwargs)


def test_unreadable_page_image_is_an_error(comic):
    (comic.root / "pages" / "ch001" / "p002.png").write_bytes(b"not a png")
    for fmt in ("pdf", "cbz"):
        with pytest.raises(export.ExportError, match="p002.png"):
            export.export_chapter(comic, 1, fmt)


def test_stale_pages_warn(comic):
    picks = compose.save_picks(comic, 1, {"p001_k1": {"image": "x.png", "focus": [0.5, 0.5], "zoom": 1.0}})
    old, new = picks.stat().st_mtime - 100, picks.stat().st_mtime + 100
    for n, when in ((1, old), (2, new), (3, old)):                  # 只有第 2 頁是選圖之後才輸出的
        os.utime(comic.root / "pages" / "ch001" / ("p%03d.png" % n), (when, when))
    _, warnings = export.export_chapter(comic, 1, "pdf")
    assert len(warnings) == 1 and "第 1、3 頁" in warnings[0]


def test_empty_storyboard_is_an_error(comic):
    board = comic.load_storyboard(1)
    board["pages"] = []
    comic.storyboard_path(1).write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(export.ExportError, match="沒有任何頁"):
        export.export_chapter(comic, 1, "pdf")


# ---- 命令列 ------------------------------------------------------------------------

def test_cli(comic, capsys, tmp_path):
    import export as cli
    root = str(comic.root)
    assert cli.main([root, "1"]) == 0
    assert (comic.root / "out" / "ch001.pdf").is_file()
    assert cli.main([root, "1", "--format", "all", "--out", str(tmp_path / "o"), "--lossless", "--single"]) == 0
    assert (tmp_path / "o" / "ch001.pdf").is_file() and (tmp_path / "o" / "ch001.cbz").is_file()
    assert cli.main([root, "1", "--format", "cbz", "--page", "2"]) == 0
    assert (comic.root / "out" / "ch001_p002.cbz").is_file()
    assert "ch001.pdf" in capsys.readouterr().out
    assert cli.main([root, "1", "--format", "all", "--out", str(tmp_path / "f.pdf")]) == 2        # 兩種格式不能共用一個檔名
    assert cli.main([root, "1", "--page", "9"]) == 2
    assert cli.main([root, "1", "--quality", "100"]) == 2
    (comic.root / "pages" / "ch001" / "p001.png").unlink()
    assert cli.main([root, "1"]) == 2
    assert "還沒有輸出頁面" in capsys.readouterr().err


def test_real_sample_page_exports():
    """範例專案的真實頁面（有的話）：整頁 PDF 的尺寸是 B5。"""
    page = SAMPLE / "pages" / "ch001" / "p001.png"
    if not page.is_file():
        pytest.skip("範例還沒有輸出頁面")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = export.build_pdf([page], Path(tmp) / "x.pdf", {"title": "t"})
        _, pages = pdf_pages(parse_pdf(path.read_bytes()))
        assert abs(pages[0][0][2] - 182 / 25.4 * 72) < 1 and abs(pages[0][0][3] - 257 / 25.4 * 72) < 1
