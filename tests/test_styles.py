"""畫風預設集（N5）：黑白／彩色／美式三組，style／meta／提示詞描述同一個來源。不需要 GPU。"""
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import styles, workspace  # noqa: E402
from t2c.compile import CompileError, compile_chapter  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"
BANNED = ("black and white", "black-and-white", "black ink", "黑白")


def color_project(tmp_path, preset="color"):
    """範例專案複本，project.yaml 拿掉寫死的 style／meta，改用預設集。"""
    root = tmp_path / "comic"
    shutil.copytree(SAMPLE, root)
    cfg = yaml.safe_load((root / "project.yaml").read_text(encoding="utf-8"))
    for key in ("style", "meta"):
        cfg.pop(key, None)
    cfg["style_preset"] = preset
    (root / "project.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return Project(root)


# ---- 預設集本身 ------------------------------------------------------------------

def test_three_presets():
    assert styles.names() == ["american", "color", "mono"]
    assert styles.default_name() == "mono"
    for name in styles.names():
        preset = styles.preset(name)
        for field in styles.FIELDS:
            assert str(preset[field]).strip(), "%s 缺 %s" % (name, field)
        assert isinstance(preset["meta"], list) and preset["meta"]


def test_mono_is_the_black_and_white_one():
    mono = styles.resolve({})
    assert mono["preset"] == "mono"
    assert "black and white" in mono["style"].lower()
    assert "black and white" in " ".join(mono["meta"]).lower()
    assert "黑白" in mono["look"]


@pytest.mark.parametrize("preset", ["color", "american"])
def test_color_presets_carry_no_black_and_white(preset):
    resolved = styles.resolve({"style_preset": preset})
    text = " ".join([resolved["style"], resolved["look"], resolved["sfx"]] + resolved["meta"]).lower()
    for word in BANNED:
        assert word not in text, "%s 不該提到 %s" % (preset, word)


def test_explicit_fields_win_over_preset():
    resolved = styles.resolve({"style_preset": "color", "style": "my own style", "meta": ["only this"]})
    assert resolved["preset"] == "color"
    assert resolved["style"] == "my own style"
    assert resolved["meta"] == ["only this"]
    assert resolved["look"] == "彩色日式頁漫"          # 沒明寫的欄位仍由預設集來


def test_unknown_preset_lists_names():
    with pytest.raises(styles.StylesError) as error:
        styles.resolve({"style_preset": "watercolor"})
    message = str(error.value)
    assert "watercolor" in message and "mono" in message and "american" in message


def test_preset_copy_is_not_mutated():
    got = styles.preset("mono")
    got["meta"].append("oops")
    assert "oops" not in styles.preset("mono")["meta"]


# ---- 接到生圖提示詞 --------------------------------------------------------------

def test_color_project_prompt_has_no_black_and_white(tmp_path):
    project = color_project(tmp_path)
    jobs = compile_chapter(project, project.load_storyboard(1))
    assert jobs
    for job in jobs:
        prompt = job["prompt"].lower()
        for word in BANNED:
            assert word not in prompt, "%s 的提示詞出現 %s" % (job["id"], word)
        assert json.loads(job["prompt"])["summary"]["meta"] == ["manga panel", "full color", "cel shading"]


def test_mono_project_without_style_uses_preset(tmp_path):
    project = color_project(tmp_path, preset="mono")
    jobs = compile_chapter(project, project.load_storyboard(1))
    assert "black and white" in jobs[0]["prompt"].lower()


def test_sample_project_still_compiles_with_its_own_style():
    project = Project(SAMPLE)
    jobs = compile_chapter(project, project.load_storyboard(1))
    assert [job["id"] for job in jobs] == ["p001_k1", "p001_k2", "p001_k3", "p001_k4", "p001_k5"]
    assert "Black and white Japanese manga artwork" in jobs[0]["prompt"]


def test_missing_style_everywhere_is_reported(tmp_path, monkeypatch):
    project = color_project(tmp_path)
    project.config.pop("style_preset", None)
    monkeypatch.setattr(styles, "resolve", lambda cfg=None: {"preset": "empty", "name": "", "look": "",
                                                             "style": "", "meta": [], "sfx": ""})
    with pytest.raises(CompileError) as error:
        compile_chapter(project, project.load_storyboard(1))
    assert "style" in str(error.value)


# ---- 新建專案 --------------------------------------------------------------------

def test_create_project_writes_preset(tmp_path):
    project = workspace.create_project(str(tmp_path / "a"), "新作品")
    assert project.config["style_preset"] == "mono"
    assert "style_preset: mono" in (Path(project.root) / "project.yaml").read_text(encoding="utf-8")
    assert styles.resolve(project.config)["preset"] == "mono"


def test_create_project_with_color_preset(tmp_path):
    project = workspace.create_project(str(tmp_path / "b"), "彩色作品", preset="color")
    assert project.config["style_preset"] == "color"
    assert "color" in project.config["style_preset"]


def test_create_project_rejects_unknown_preset(tmp_path):
    with pytest.raises(workspace.WorkspaceError) as error:
        workspace.create_project(str(tmp_path / "c"), "x", preset="watercolor")
    assert "watercolor" in str(error.value) and "mono" in str(error.value)


def test_created_project_yaml_has_no_duplicate_style(tmp_path):
    path = Path(workspace.create_project(str(tmp_path / "d"), "新作品").root) / "project.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.count("style_preset: mono") == 1
    assert "\nstyle:" not in text            # 沒明寫就不該有 style 鍵（只有註解）
