"""N4：專案層版型（project.yaml 的 layout）。

檢查疊加（merge）、覆寫（replace）、page 的局部覆蓋、錯誤訊息寫出檔案與位置，
以及編譯、檢查、介面 API 都讀專案自己的版型（不是只讀套件內建那份）。
"""
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from t2c import layout, settings, workspace  # noqa: E402
from t2c.compile import compile_chapter  # noqa: E402
from t2c.project import Project, ProjectError  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"
CLIENT = TestClient(app_module.app, base_url="http://127.0.0.1")

BUILTIN = layout.load_pages()
SOLO = {"templates": {"solo": {"name": "自訂一格", "panels": [[0.1, 0.2, 0.9, 0.8]]}}}


def make_project(tmp_path, name="comic"):
    root = tmp_path / name
    shutil.copytree(SAMPLE, root, ignore=shutil.ignore_patterns("renders", "pages", "build", "picks"))
    return Project(root)


def write_pages(project, data, name="pages.json"):
    path = project.root / name
    path.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def set_layout(project, spec):
    """在 project.yaml 尾巴加 layout 區塊；spec 是 dict 或檔名字串。"""
    text = (project.root / "project.yaml").read_text(encoding="utf-8").rstrip()
    if isinstance(spec, str):
        block = "layout: %s\n" % json.dumps(spec)
    elif isinstance(spec, dict):
        block = "layout:\n" + "".join("  %s: %s\n" % (key, json.dumps(value, ensure_ascii=False)) for key, value in spec.items())
    else:
        block = "layout: %s\n" % json.dumps(spec)
    (project.root / "project.yaml").write_text(text + "\n\n" + block, encoding="utf-8")
    return Project(project.root)


def with_pages(tmp_path, data, mode=None):
    project = make_project(tmp_path)
    write_pages(project, data)
    return set_layout(project, {"file": "pages.json"} if mode is None else {"file": "pages.json", "mode": mode})


# ---- 疊加與覆寫 ------------------------------------------------------------------

def test_project_without_layout_uses_the_builtin_pages(tmp_path):
    project = make_project(tmp_path)
    assert project.pages() == BUILTIN
    assert project.layout_info() == {"file": "", "mode": "", "templates": []}


def test_merge_keeps_builtin_templates_and_replaces_the_same_name(tmp_path):
    project = make_project(tmp_path)
    write_pages(project, {"_說明": "測試用", "templates": {
        "2h": {"name": "上下兩格（改）", "panels": [[0, 0, 1, 0.35], [0, 0.35, 1, 1]]},
        "7w": {"name": "新模板", "panels": [[0, 0, 1, 1]]}}})
    project = set_layout(project, {"file": "pages.json"})                  # mode 預設 merge
    pages = project.pages()
    assert list(pages["templates"]) == ["1", "2h", "3a", "4a", "5a", "6a", "7w"]   # 同名留在原位、新的排後面
    assert pages["templates"]["2h"]["name"] == "上下兩格（改）"
    assert pages["templates"]["1"] == BUILTIN["templates"]["1"]
    assert pages["page"] == BUILTIN["page"]
    info = project.layout_info()
    assert info["mode"] == "merge" and info["templates"] == ["2h", "7w"]
    assert info["file"].endswith("pages.json")


def test_replace_uses_only_the_project_templates_and_keeps_the_page(tmp_path):
    project = with_pages(tmp_path, SOLO, mode="replace")
    pages = project.pages()
    assert list(pages["templates"]) == ["solo"]
    assert pages["page"] == BUILTIN["page"]                                # page 沒給就沿用內建
    assert project.layout_info()["mode"] == "replace"


def test_page_fields_are_merged_one_level(tmp_path):
    project = with_pages(tmp_path, {"page": {"width_px": 1400, "gutter_px": 18}, "templates": {
        "solo": {"panels": [[0, 0, 1, 1]]}}}, mode="replace")
    page = project.pages()["page"]
    assert page["width_px"] == 1400 and page["gutter_px"] == 18
    assert page["width_mm"] == BUILTIN["page"]["width_mm"] and page["margin"] == BUILTIN["page"]["margin"]


def test_layout_accepts_a_file_name_only(tmp_path):
    project = make_project(tmp_path)
    write_pages(project, SOLO)
    project = set_layout(project, "pages.json")
    assert "solo" in project.pages()["templates"] and "1" in project.pages()["templates"]   # 沒寫 mode＝疊加
    assert project.layout_info()["mode"] == "merge" and project.layout_info()["templates"] == ["solo"]


# ---- 錯誤訊息 --------------------------------------------------------------------

@pytest.mark.parametrize("pages_text, spec, expected", [
    (None, {"file": "nope.json"}, "找不到版型檔"),
    ("{ 壞掉", {"file": "pages.json"}, "不是合法的 JSON"),
    (json.dumps({"_說明": "只有說明"}), {"file": "pages.json"}, "缺少 templates"),
    (json.dumps({"templates": {}}), {"file": "pages.json"}, "缺少 templates"),
    (json.dumps({"templates": {"solo": {"panels": [[0, 0, 2, 1]]}}}), {"file": "pages.json"}, "模板「solo」第 1 格"),
    (json.dumps({"templates": {"solo": {"panels": [[0, 0, 1]]}}}), {"file": "pages.json"}, "要是 [x0, y0, x1, y1] 四個數字"),
    (json.dumps({"templates": {"Big Key": {"panels": [[0, 0, 1, 1]]}}}), {"file": "pages.json"}, "只能用 a-z"),
    (json.dumps({"templates": {"solo": {"name": 3, "panels": [[0, 0, 1, 1]]}}}), {"file": "pages.json"}, "name 要是字串"),
    (json.dumps({"page": {"margin": [0.5, 0, 0.6, 0]}, "templates": {"solo": {"panels": [[0, 0, 1, 1]]}}}),
     {"file": "pages.json"}, "page.margin"),
    (json.dumps({"page": {"width_px": "big"}, "templates": {"solo": {"panels": [[0, 0, 1, 1]]}}}),
     {"file": "pages.json"}, "page.width_px 要是數字"),
    (json.dumps(SOLO), {"file": "pages.json", "mode": "overlay"}, "merge 或 replace"),
    (json.dumps(SOLO), {"mode": "merge"}, "少了 file"),
    (json.dumps(SOLO), 5, "要是版型檔的路徑"),
])
def test_layout_errors_say_what_and_where(tmp_path, pages_text, spec, expected):
    project = make_project(tmp_path)
    if pages_text is not None:
        write_pages(project, pages_text)
    project = set_layout(project, spec)
    with pytest.raises(ProjectError) as info:
        project.pages()
    assert expected in str(info.value)


def test_error_message_names_the_file_and_the_panel(tmp_path):
    project = make_project(tmp_path)
    path = write_pages(project, {"templates": {"solo": {"panels": [[0, 0, 2, 1]]}}})
    project = set_layout(project, {"file": "pages.json"})
    with pytest.raises(ProjectError) as info:
        project.pages()
    text = str(info.value)
    assert str(path) in text and "模板「solo」第 1 格" in text


def test_missing_file_error_names_the_yaml_key(tmp_path):
    project = set_layout(make_project(tmp_path), {"file": "layouts/mine.json"})
    with pytest.raises(ProjectError) as info:
        project.pages()
    text = str(info.value)
    assert "layout.file" in text and "mine.json" in text


# ---- 各處都讀專案的版型 -----------------------------------------------------------

def test_compile_uses_project_templates(tmp_path):
    project = with_pages(tmp_path, SOLO, mode="replace")
    board = {"pages": [{"page": 1, "template": "solo", "panels": [
        {"slot": 1, "id": "p001_k1", "shot": "medium", "angle": "eye", "scene": "A quiet room.", "characters": [], "bubbles": []}]}]}
    jobs = compile_chapter(project, board)
    assert jobs[0]["id"] == "p001_k1"
    assert list(jobs[0]["rect_px"]) == list(layout.panel_rect_px(project.pages()["page"], SOLO["templates"]["solo"]["panels"][0]))


def test_workspace_plan_check_uses_project_templates(tmp_path):
    project = with_pages(tmp_path, SOLO, mode="replace")
    plan = {"title": "測試", "pages": [{"page": 1, "template": "3a", "purpose": "讓讀者知道現在在哪",
                                      "panels": [{"slot": i, "beat": "事情發生", "characters": []} for i in (1, 2, 3)]}]}
    with pytest.raises(workspace.WorkspaceError) as info:
        workspace.save_plan(project, 1, plan)
    text = str(info.value)
    assert "沒有這個格子模板「3a」" in text and "solo" in text


def test_storyboard_checks_use_project_templates(tmp_path):
    project = with_pages(tmp_path, SOLO, mode="replace")
    board = {"pages": [{"page": 1, "template": "solo", "panels": [
        {"slot": 1, "id": "p001_k1", "shot": "medium", "angle": "eye", "scene": "A quiet room.",
         "characters": [], "bubbles": []}]}]}
    issues = workspace.storyboard_issues(project, 1, board)
    assert not [i for i in issues if "沒有這個格子模板" in str(i)]


def test_api_exposes_project_templates_and_page_size(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "load", lambda path=None, root=None: {"providers": [], "comfy": {"url": "http://127.0.0.1:1"},
                                                                       "lettering": {}, "_path": "test"})
    project = with_pages(tmp_path, {"page": {"width_px": 1400}, "templates": {
        "solo": {"name": "自訂一格", "panels": [[0.1, 0.2, 0.9, 0.8]]}}}, mode="replace")
    (project.root / "storyboard").mkdir(exist_ok=True)
    (project.root / "storyboard" / "ch001.json").write_text(json.dumps({"version": 1, "chapter": 1, "pages": [
        {"page": 1, "template": "solo", "panels": [
            {"slot": 1, "id": "p001_k1", "shot": "medium", "angle": "eye", "scene": "A quiet room.",
             "characters": [], "bubbles": []}]}]}, ensure_ascii=False), encoding="utf-8")
    params = {"project": str(project.root), "chapter": 1}

    vocab = CLIENT.get("/api/chapter/storyboard", params=params).json()["vocab"]
    assert list(vocab["templates"]) == ["solo"]
    assert vocab["templates"]["solo"]["source"] == "project"
    assert vocab["layout"]["file"].endswith("pages.json") and vocab["layout"]["mode"] == "replace"

    plan = CLIENT.get("/api/chapter/plan", params=params).json()
    assert list(plan["templates"]) == ["solo"]

    pages = CLIENT.get("/api/chapter/pages", params=params).json()
    assert pages["size"] == [1400, round(1400 * BUILTIN["page"]["height_mm"] / BUILTIN["page"]["width_mm"])]
    assert pages["layout"]["mode"] == "replace"
