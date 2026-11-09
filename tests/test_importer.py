"""N2：整本小說匯入切章（t2c/importer.py、tools/import.py）。

執行：python -m pytest tests/test_importer.py
"""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import importer  # noqa: E402

SAMPLE = ROOT / "tests" / "data" / "n2_sample_six_chapters.txt"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_project(tmp_path, name="comic"):
    root = tmp_path / name
    root.mkdir()
    (root / "project.yaml").write_text("title: 測試\nstyle: test\n", encoding="utf-8")
    return root


def make_docx(path, paragraphs):
    body = "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % escape(p) for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (W, body))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


# ---------------------------------------------------------------------------
# 讀檔
# ---------------------------------------------------------------------------
def test_decode_utf8_bom_and_utf16():
    text, enc = importer.decode(b"\xef\xbb\xbf" + "第一章 雨夜".encode("utf-8"))
    assert (text, enc) == ("第一章 雨夜", "UTF-8")
    text, enc = importer.decode("第一章 雨夜".encode("utf-16"))
    assert text == "第一章 雨夜" and enc == "UTF-16"


def test_decode_big5():
    text, enc = importer.decode("這是一段用 Big5 存的中文測試。".encode("cp950"))
    assert text == "這是一段用 Big5 存的中文測試。"
    assert enc.startswith("Big5")


def test_read_source_txt_md_and_unsupported(tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("第一章 雨夜\n\n內容。\n", encoding="utf-8")
    assert importer.read_source(txt)[0].startswith("第一章")
    md = tmp_path / "b.MD"
    md.write_bytes("# 標題\n".encode("utf-8"))
    assert importer.read_source(md) == ("# 標題\n", "UTF-8")
    bad = tmp_path / "c.pdf"
    bad.write_bytes(b"%PDF")
    with pytest.raises(importer.ImporterError) as error:
        importer.read_source(bad)
    assert ".txt、.md、.docx" in str(error.value)
    with pytest.raises(importer.ImporterError) as error:
        importer.read_source(tmp_path / "nope.txt")
    assert "讀不到檔案" in str(error.value)


def test_read_docx_paragraphs_and_tabs(tmp_path):
    path = tmp_path / "book.docx"
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="%s"><w:body>'
           '<w:p><w:r><w:t>第一章 雨夜</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>第一段</w:t></w:r><w:r><w:tab/><w:t>接下去</w:t></w:r>'
           '<w:r><w:br/><w:t>換行</w:t></w:r></w:p>'
           '</w:body></w:document>' % W)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    expected = "第一章 雨夜\n\n第一段　接下去\n換行"
    assert importer.read_docx(path) == expected
    assert importer.read_docx(path.read_bytes()) == expected       # 也可以直接吃 bytes


def test_read_docx_rejects_broken_file(tmp_path):
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")
    with pytest.raises(importer.ImporterError) as error:
        importer.read_docx(path)
    assert ".docx" in str(error.value) and ".doc" in str(error.value)


# ---------------------------------------------------------------------------
# 切章
# ---------------------------------------------------------------------------
def test_split_text_chinese_english_and_special_headings():
    text = ("第一章　雨夜\n\n內容一。\n\n"
            "Chapter II The Letter\n\n內容二。\n\n"
            "第三章：天台\n\n內容三。\n\n"
            "序章\n\n很久以前。\n")
    preface, chunks = importer.split_text(text)
    assert [c["num"] for c in chunks] == [1, 2, 3, None]
    assert [c["title"] for c in chunks] == ["雨夜", "The Letter", "天台", "序章"]
    assert "內容三" in chunks[2]["body"]


def test_split_text_special_and_english_titles():
    _, chunks = importer.split_text("Chapter VI\nTHE CAPTAIN'S PAPERS\n\n內容。\n\nPrologue\n\n很久以前。\n")
    assert chunks[0]["num"] == 6 and chunks[0]["title"] == "THE CAPTAIN'S PAPERS"
    assert chunks[1]["num"] is None and chunks[1]["title"].startswith("Prologue")


def test_split_text_markdown_mode():
    _, chunks = importer.split_text("# 第一章 雨夜\n\n內容。\n\n## 某個段落\n\n### 更小的標題\n", mode="markdown")
    assert [(c["num"], c["title"]) for c in chunks] == [(1, "雨夜"), (None, "某個段落"), (None, "更小的標題")]


def test_sample_drops_toc_and_merges_duplicate_heading():
    stats = {}
    _, chunks = importer.split_text(SAMPLE.read_text(encoding="utf-8"), stats=stats)
    assert stats == {"toc": 6, "merged": 1}
    assert [c["num"] for c in chunks] == [1, 2, 3, 4, 5, 6]
    assert [c["title"] for c in chunks] == ["雨夜", "失約", "天台", "舊信", "車站", "晴天"]


def test_title_key_aligns_traditional_and_simplified(monkeypatch):
    """有 opencc 字表時，同一章名的繁簡寫法要算同一個（沒有 opencc 時只去標點與大小寫）。"""
    monkeypatch.setattr(importer, "_T2S", {ord("風"): ord("风"), ord("歸"): ord("归")})
    assert importer._title_key("《風雪夜歸》") == importer._title_key("「风雪夜归」")
    assert importer._title_key("風雪夜歸") != importer._title_key("風雪夜行")


def test_normalize_paragraphs_and_scene_break():
    text = "第一行\n第二行\n\n***\n\n第三行"
    assert importer.normalize(text) == "第一行第二行\n\n＊＊＊\n\n第三行"
    assert importer.normalize(text, lang="en") == "第一行第二行\n\n* * *\n\n第三行"
    assert "＊＊＊" not in importer.normalize(text, lang="ja")
    assert "***" in importer.normalize(text, lang="ja")


def test_count_text_counts_cjk_and_english_words():
    assert importer.count_text("一二三，ABC def") == 3      # 3 個漢字，比 2 個英文詞多
    assert importer.count_text("ABC def ghi") == 3         # 英文書算詞
    assert importer.count_text("# 第1章 雨夜\n\n本文") == 2  # 標題行不算


# ---------------------------------------------------------------------------
# plan／preview
# ---------------------------------------------------------------------------
def test_plan_sample_numbers_and_titles():
    result = importer.plan(SAMPLE)
    assert result["numbered_by_title"] is True
    assert [(c["no"], c["title"]) for c in result["chapters"]] == [
        (1, "雨夜"), (2, "失約"), (3, "天台"), (4, "舊信"), (5, "車站"), (6, "晴天")]
    assert result["sources"][0]["chapters"] == 6
    assert result["sources"][0]["encoding"] == "UTF-8"
    assert any("目錄" in w for w in result["warnings"])
    assert any("連寫了兩次" in w for w in result["warnings"])
    assert "＊＊＊" in result["chapters"][0]["text"]


def test_plan_sequential_renumbers_from_start():
    result = importer.plan(SAMPLE, {"numbering": "sequential", "start": 10})
    assert result["numbered_by_title"] is False
    assert [c["no"] for c in result["chapters"]] == [10, 11, 12, 13, 14, 15]


def test_plan_titles_rejects_non_increasing_numbers(tmp_path):
    path = tmp_path / "titles.txt"
    path.write_text("第二章 失約\n\n內容。\n\n第一章 雨夜\n\n內容。\n", encoding="utf-8")
    with pytest.raises(importer.ImporterError) as error:
        importer.plan(path, {"numbering": "titles"})
    assert "依順序重新編號" in str(error.value)


def test_plan_preface_as_chapter():
    result = importer.plan(SAMPLE, {"preface_as_chapter": True, "preface_title": "開場"})
    assert result["chapters"][0]["no"] == 1 and result["chapters"][0]["title"] == "開場"
    assert len(result["chapters"]) == 7
    assert result["preface"] == []


def test_plan_convert_without_opencc_warns_and_keeps_text(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "has_opencc", lambda: False)
    path = tmp_path / "simp.txt"
    path.write_text("第一章 雨夜\n\n这是一段简体文字，没有转繁。\n", encoding="utf-8")
    result = importer.plan(path, {"convert": True})
    assert any("OpenCC" in w for w in result["warnings"])
    assert "简体" in result["chapters"][0]["text"]


def test_plan_converts_when_opencc_is_injected(tmp_path, monkeypatch):
    monkeypatch.setattr(importer, "has_opencc", lambda: True)
    monkeypatch.setattr(importer, "to_traditional", lambda text: text.replace("简体", "簡體"))
    path = tmp_path / "convert.txt"
    path.write_text("第一章 雨夜\n\n这是简体。\n", encoding="utf-8")
    result = importer.plan(path, {"convert": True})
    assert "簡體" in result["chapters"][0]["text"]
    assert "简体" not in result["chapters"][0]["text"]


def test_preview_does_not_include_full_text():
    result = importer.preview(SAMPLE)
    chapter = result["chapters"][0]
    assert "text" not in chapter and chapter["head"].startswith("十二點四十分")
    assert len(chapter["head"]) <= 60


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------
def test_commit_writes_chapter_files(tmp_path):
    project = make_project(tmp_path)
    result = importer.commit(project, SAMPLE)
    assert [w["no"] for w in result["written"]] == [1, 2, 3, 4, 5, 6]
    assert result["skipped"] == [] and result["replaced"] == []
    assert result["chars"] == sum(w["chars"] for w in result["written"])
    first = (project / "source" / "ch001.txt").read_text(encoding="utf-8")
    assert first.startswith("# 第1章 雨夜\n\n十二點四十分")
    assert first.endswith("\n") and "＊＊＊" in first
    assert (project / "source" / "ch006.txt").read_text(encoding="utf-8").startswith("# 第6章 晴天")


def test_commit_skip_keeps_existing_file(tmp_path):
    project = make_project(tmp_path)
    source = project / "source"
    source.mkdir()
    (source / "ch001.txt").write_text("舊內容\n", encoding="utf-8")
    result = importer.commit(project, SAMPLE)
    assert result["skipped"] == [1] and result["replaced"] == []
    assert (source / "ch001.txt").read_text(encoding="utf-8") == "舊內容\n"
    assert (source / "ch002.txt").is_file()


def test_commit_overwrite_backs_up_old_file(tmp_path):
    project = make_project(tmp_path)
    source = project / "source"
    source.mkdir()
    (source / "ch001.txt").write_text("舊內容\n", encoding="utf-8")
    result = importer.commit(project, SAMPLE, {"conflict": "overwrite"})
    assert result["replaced"] == [1]
    assert (source / "ch001.txt").read_text(encoding="utf-8").startswith("# 第1章 雨夜")
    backup = project / "build" / "import" / "backup"
    assert [p.read_text(encoding="utf-8") for p in backup.glob("ch001.txt.*.bak")] == ["舊內容\n"]
    assert result["backups"][0]["files"][0].startswith("build/import/backup/")


def test_commit_overwrite_replaces_old_md(tmp_path):
    project = make_project(tmp_path)
    source = project / "source"
    source.mkdir()
    (source / "ch001.md").write_text("舊的 md\n", encoding="utf-8")
    result = importer.commit(project, SAMPLE, {"conflict": "overwrite"})
    assert result["replaced"] == [1]
    assert not (source / "ch001.md").exists()
    assert (source / "ch001.txt").is_file()
    backup = list((project / "build" / "import" / "backup").glob("ch001.md.*.bak"))
    assert backup and backup[0].read_text(encoding="utf-8") == "舊的 md\n"


def test_commit_requires_project_yaml(tmp_path):
    folder = tmp_path / "not_a_project"
    folder.mkdir()
    with pytest.raises(importer.ImporterError) as error:
        importer.commit(folder, SAMPLE)
    assert "project.yaml" in str(error.value)


def test_commit_rejects_unknown_conflict(tmp_path):
    project = make_project(tmp_path)
    with pytest.raises(importer.ImporterError) as error:
        importer.commit(project, SAMPLE, {"conflict": "merge"})
    assert "skip、overwrite" in str(error.value)


def test_commit_docx_end_to_end(tmp_path):
    project = make_project(tmp_path)
    docx = make_docx(tmp_path / "book.docx", [
        "第一章 雨夜", "十二點四十分，雨還在下。", "第二章 失約", "隔天放學，雨停了。", "第三章 天台", "第三天，她先到了天台。"])
    result = importer.commit(project, docx)
    assert [w["no"] for w in result["written"]] == [1, 2, 3]
    assert [w["chars"] for w in result["written"]] == [10, 7, 9]
    text = (project / "source" / "ch002.txt").read_text(encoding="utf-8")
    assert text.startswith("# 第2章 失約\n\n隔天放學，雨停了。")


# ---------------------------------------------------------------------------
# 命令列
# ---------------------------------------------------------------------------
def test_cli_previews_then_commits(tmp_path):
    project = make_project(tmp_path)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, str(ROOT / "tools" / "import.py"), str(project), str(SAMPLE)]

    preview = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", env=env)
    assert preview.returncode == 0, preview.stderr
    assert "（預覽，沒有寫入" in preview.stdout
    assert not (project / "source").exists()

    wrote = subprocess.run(cmd + ["--commit", "--json"], cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", env=env)
    assert wrote.returncode == 0, wrote.stderr
    result = json.loads(wrote.stdout)
    assert [w["no"] for w in result["written"]] == [1, 2, 3, 4, 5, 6]
    assert len(list((project / "source").glob("ch*.txt"))) == 6
