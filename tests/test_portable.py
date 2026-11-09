"""M1 修正 M-3：`t2c/` 要能整包搬走（I1／I3 會把它複製進 Novel Studio、t2vn）。
只複製 t2c/ 到一個不相干的資料夾，所有模組都要能 import、讀得到格子模板與 MOSS workflow、能編譯一章；
設定檔與範例的位置由呼叫端給，t2c 不假設上一層資料夾是什麼。
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import comfy, layout, settings  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"

SCRIPT = r"""
import importlib, json, pkgutil, sys
sys.path.insert(0, sys.argv[1])
import t2c
mods = sorted(m.name for m in pkgutil.iter_modules(t2c.__path__))
for name in mods:
    importlib.import_module("t2c." + name)
from t2c import comfy, layout, settings
from t2c.compile import compile_chapter
from t2c.project import Project
pages = layout.load_pages()
wf = comfy.load_workflow()
project = Project(sys.argv[2])
jobs = compile_chapter(project, project.load_storyboard(1))
try:
    settings.load()
    no_root = "loaded"
except ValueError as error:
    no_root = "ValueError"
print(json.dumps({"modules": mods, "templates": sorted(pages["templates"]), "workflow_nodes": len(wf),
                  "jobs": len(jobs), "settings_without_root": no_root,
                  "builtin_workflow": str(comfy.workflow_path({"comfy": {"workflow": ""}}))}))
"""


def test_t2c_works_when_copied_alone(tmp_path):
    lib = tmp_path / "somewhere_else" / "vendor"
    shutil.copytree(ROOT / "t2c", lib / "t2c", ignore=shutil.ignore_patterns("__pycache__"))
    comic = tmp_path / "comic"
    comic.mkdir()
    for part in ("project.yaml", "bible", "storyboard"):
        src = SAMPLE / part
        (shutil.copytree if src.is_dir() else shutil.copy)(src, comic / part)
    runner = tmp_path / "run.py"
    runner.write_text(SCRIPT, encoding="utf-8")
    out = subprocess.run([sys.executable, str(runner), str(lib), str(comic)], cwd=str(tmp_path),
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert "letter" in result["modules"] and "workspace" in result["modules"]
    assert "5a" in result["templates"] and result["workflow_nodes"] > 0
    assert result["jobs"] == 5
    assert result["settings_without_root"] == "ValueError"
    assert Path(result["builtin_workflow"]).is_relative_to(lib / "t2c")


def test_no_module_looks_above_the_package():
    """t2c 裡不准用 parent.parent 找工具資料夾（上一層是什麼由整合的專案決定）。"""
    for path in sorted((ROOT / "t2c").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"parent\.parent|\.\./", text), path.name


def test_workflow_path_rules(tmp_path):
    builtin = comfy.DEFAULT_WORKFLOW
    assert builtin.is_file() and builtin.parent == layout.DATA
    assert comfy.workflow_path({}) == builtin
    assert comfy.workflow_path({"comfy": {"workflow": "workflows/moss_layout.api.json"}}) == builtin    # 舊的 config.json
    assert comfy.workflow_path({"comfy": {"workflow": "workflows\\moss_layout.api.json"}}) == builtin
    mine = tmp_path / "wf" / "mine.json"
    mine.parent.mkdir()
    mine.write_text("{}", encoding="utf-8")
    cfg = {"comfy": {"workflow": "wf/mine.json"}, "_path": str(tmp_path / "config.json")}
    assert comfy.workflow_path(cfg) == mine                                                         # 相對於 config.json
    with pytest.raises(comfy.ComfyError, match="找不到 workflow"):
        comfy.workflow_path({"comfy": {"workflow": "nope.json"}, "_path": str(tmp_path / "config.json")})


def test_settings_load_needs_a_location(tmp_path):
    with pytest.raises(ValueError):
        settings.load()
    (tmp_path / "config.example.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert settings.load(root=tmp_path)["a"] == 1
    (tmp_path / "config.json").write_text(json.dumps({"a": 2}), encoding="utf-8")
    assert settings.load(root=tmp_path)["a"] == 2
    assert settings.load(ROOT / "config.example.json")["_path"].endswith("config.example.json")


def test_old_data_folders_are_gone():
    """layouts/、workflows/ 已搬進 t2c/data/；留著舊檔會讓人改錯地方。"""
    for old in (ROOT / "layouts" / "pages.json", ROOT / "workflows" / "moss_layout.api.json"):
        assert not old.exists(), "%s 已搬到 t2c/data/，請刪掉舊檔（git rm）" % old.relative_to(ROOT)
