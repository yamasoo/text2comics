"""N5：文字端提示詞的畫風由 styles.resolve(...)["look"] 決定——黑白專案的輸出必須與去硬編碼前逐字相同。

不需要 GPU、不連外網。執行：python -m pytest tests/test_prompts_look.py
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import layout, prompts, styles  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"
BANNED = ("black and white", "black-and-white", "black-", "黑白")

# 去硬編碼前的 system（git HEAD:t2c/prompts.py 第 22–26 行）。mono 專案必須與它逐字相同。
MONO_SYSTEM = (
    "你是日本漫畫的責任編輯兼分鏡師，負責把小說改編成日式黑白頁漫（由右往左閱讀）。"
    "你的輸出會被程式直接讀取，所以格式必須完全照指示；不要加前言、說明、結語，也不要用 ``` 圍欄。"
    "用繁體中文（台灣用語）；指定要寫英文的欄位才寫英文。"
)

PLAN = {"title": "測試章", "summary": "一句話", "omitted": [], "unlisted_characters": [],
        "pages": [{"page": 1, "template": "5a", "purpose": "建立場景", "hook": "",
                   "panels": [{"slot": i, "beat": "第 %d 格" % i, "characters": ["lin"]} for i in range(1, 6)]}]}


def project_with(preset=None):
    """範例專案的 Project；preset 有給就把 style_preset 換掉（只改記憶體裡的設定）。"""
    project = Project(SAMPLE)
    if preset is None:
        project.config.pop("style_preset", None)      # 預設就是 mono
    else:
        project.config["style_preset"] = preset
    return project


def all_messages(project):
    """四個 builder 產生的每一則 message（system＋user）。"""
    pages_data = layout.load_pages()
    source = project.load_source(1)
    plan_page = PLAN["pages"][0]
    script_page = (SAMPLE / "script" / "ch001.md").read_text(encoding="utf-8")
    batches = [
        prompts.annotate_messages(project, ["十二點四十分。", "「又不接。」"], "天台的便當"),
        prompts.plan_messages(project, source, pages_data, want_pages=2),
        prompts.script_messages(project, source, PLAN, plan_page, pages_data),
        prompts.storyboard_messages(project, script_page, 1, "5a", pages_data),
    ]
    return [message for batch in batches for message in batch]


def joined(project):
    return "\n".join(message["content"] for message in all_messages(project))


# ---- mono：與去硬編碼前逐字相同 ---------------------------------------------------

def test_system_without_look_is_the_mono_one():
    assert prompts.system() == MONO_SYSTEM
    assert "日式黑白頁漫" in prompts.system()


def test_mono_project_system_is_verbatim():
    for message in all_messages(project_with(None)):
        if message["role"] == "system":
            assert message["content"] == MONO_SYSTEM


def test_mono_project_plan_rules_keep_the_black_and_white_wording():
    project = project_with(None)
    text = prompts.plan_messages(project, project.load_source(1), layout.load_pages())[1]["content"]
    assert text.startswith("# 任務：改編規劃\n把下面這一章小說規劃成日式黑白頁漫。")


def test_system_follows_the_given_look():
    text = prompts.system("美式彩色漫畫")
    assert "美式彩色漫畫" in text and "日式黑白頁漫" not in text
    assert text != MONO_SYSTEM


# ---- 彩色／美式：不得出現任何黑白字樣 ---------------------------------------------

@pytest.mark.parametrize("preset,look", [("color", "彩色日式頁漫"), ("american", "美式彩色漫畫")])
def test_color_presets_have_no_black_and_white(preset, look):
    project = project_with(preset)
    assert styles.resolve(project.config)["look"] == look          # 前提：look 真的換了
    text = joined(project)
    lowered = text.lower()
    for word in BANNED:
        assert word not in lowered, "%s 專案的提示詞出現「%s」" % (preset, word)
    assert look in text


def test_every_builder_system_line_follows_the_preset():
    project = project_with("color")
    systems = [message["content"] for message in all_messages(project) if message["role"] == "system"]
    assert len(systems) == 4                                       # 四個 builder 各一則
    assert all("彩色日式頁漫" in content for content in systems)
