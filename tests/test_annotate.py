"""N3 切對話：段落、逐字驗證、漏句修補、忠實度報告、轉分鏡（compile_chapter 端到端）。
執行：python -m pytest tests/test_annotate.py
"""
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import adapt, annotate as an, check, layout, llm, prompts, script as sc  # noqa: E402
from t2c.compile import compile_chapter  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"
M1 = ROOT / "work" / "m1_mars_ch1"
PAGES = layout.load_pages()
SOURCE = (SAMPLE / "source" / "ch001.txt").read_text(encoding="utf-8")
PARAGRAPHS = an.split_paragraphs(SOURCE)


@pytest.fixture
def project(tmp_path):
    """範例專案的複本（設定、聖經、原著）。"""
    root = tmp_path / "comic"
    root.mkdir()
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    shutil.copytree(SAMPLE / "bible", root / "bible")
    shutil.copytree(SAMPLE / "source", root / "source")
    return Project(root)


def ops_doc():
    """範例第 1 章的完整切對話：10 段全部用到，4 句對話、2 個角色、1 個演出。"""
    return {"scenes": [{
        "title": "天台的便當",
        "location": "rooftop",
        "setting_en": "The rooftop of a school club building at noon; a water tank casts a hard shadow.",
        "cast": [{"id": "lin", "expression": "annoyed"}, {"id": "hao", "expression": "out of breath"}],
        "ops": [
            {"k": "N", "p": 1},
            {"k": "n", "p": 2, "t": "林曉雨一個人坐在社辦大樓頂樓的水塔陰影下"},
            {"k": "d", "p": 3, "s": "lin", "m": "小聲", "t": "「……又不接。」"},
            {"k": "x", "shot": "wide", "angle": "high", "note": "An empty rooftop under the noon sun."},
            {"k": "N", "p": 4},
            {"k": "d", "p": 5, "s": "hao", "t": "「對不起！排隊排到一半，被教授抓去搬東西！」"},
            {"k": "N", "p": 6},
            {"k": "d", "p": 7, "s": "lin", "t": "「我已經不餓了。」"},
            {"k": "N", "p": 8},
            {"k": "d", "p": 9, "s": "hao", "t": "「妳上次說的，不要香菜。」"},
            {"k": "N", "p": 10},
        ]}]}


def expanded(project, doc=None):
    """展開並確認沒有 error（warn 例如「漏敘述」是給漏句修補處理的，不算失敗）。"""
    result = an.expand(doc if doc is not None else ops_doc(), project, 1, PARAGRAPHS, "天台的便當")
    assert [str(issue) for issue in result.issues if issue.level == "error"] == []
    return result


def scene_lines(doc):
    return [line for scene in doc["scenes"] for line in scene["lines"]]


# ---- 段落與斷句 --------------------------------------------------------------------
def test_split_paragraphs_numbers_from_one_and_skips_structure():
    text = "# 第 1 章 測試\n\n第一段。\n\n＊＊＊\n\n第二段。\n\n---\n\n第三段。"
    assert an.split_paragraphs(text) == ["第一段。", "第二段。", "第三段。"]
    assert an.chapter_title(text) == "第 1 章 測試"


def test_split_paragraphs_keeps_multiline_block():
    assert an.split_paragraphs("甲。\n乙。\n\n丙。") == ["甲。\n乙。", "丙。"]


def test_split_text_merges_short_and_splits_long():
    pieces = an.split_text("短句。")
    assert pieces == ["短句。"]
    long_text = "，".join(["這是一段很長的話"] * 30) + "。"
    pieces = an.split_text(long_text)
    assert len(pieces) > 1 and all(len(piece) <= an.HARD_LIMIT for piece in pieces)


# ---- 逐字比對 ----------------------------------------------------------------------
def test_unfaithful_clauses_allows_punctuation_and_pronoun():
    assert an.unfaithful_clauses("又不接", "「……又不接。」她小聲嘀咕。") == []
    assert an.unfaithful_clauses("她雙手抱胸", "雙手抱胸，把臉別向另一邊。") == []


def test_unfaithful_clauses_flags_rewrite():
    assert an.unfaithful_clauses("我不想吃", "「我已經不餓了。」") == ["我不想吃"]


def test_omitted_clauses_skips_speech_tags():
    assert an.omitted_clauses("她說，雨停了。", ["她說"]) == ["雨停了"]


def test_has_quoted_speech_ignores_sound_words():
    assert an.has_quoted_speech("「碰」的一聲撞開了。") is False
    assert an.has_quoted_speech("「我已經不餓了。」") is True


# ---- 展開 op -----------------------------------------------------------------------
def test_expand_builds_scene_graph(project):
    result = expanded(project)
    doc = result.scene_doc
    assert doc["source"] == {"file": "ch001.txt", "paragraphs": 10}
    assert len(doc["scenes"]) == 1
    scene = doc["scenes"][0]
    assert scene["scene_id"] == "ch001_sc01" and scene["location"] == "rooftop"
    kinds = [line["type"] for line in scene["lines"]]
    assert kinds.count("direction") == 1
    dialogue = [line for line in scene["lines"] if line["type"] == "dialogue"]
    assert [line["kind"] for line in dialogue] == ["whisper", "speech", "speech", "speech"]
    assert all(line["source_para"] in range(1, 11) for line in dialogue)


def test_expand_flags_missing_paragraph(project):
    doc = ops_doc()
    doc["scenes"][0]["ops"] = [op for op in doc["scenes"][0]["ops"] if op.get("p") != 10]
    result = an.expand(doc, project, 1, PARAGRAPHS)
    assert any("原著有 1 段沒用到：10" in str(issue) for issue in result.issues)


def test_expand_flags_rewritten_dialogue(project):
    doc = ops_doc()
    doc["scenes"][0]["ops"][7]["t"] = "「我不想吃。」"
    result = an.expand(doc, project, 1, PARAGRAPHS)
    assert any("不是段落 7 的原文" in str(issue) for issue in result.issues)


def test_expand_rejects_N_on_speech_paragraph(project):
    doc = ops_doc()
    doc["scenes"][0]["ops"][5] = {"k": "N", "p": 5}
    result = an.expand(doc, project, 1, PARAGRAPHS)
    assert any("N 會把台詞當旁白" in str(issue) for issue in result.issues)


def test_expand_flags_paragraph_order(project):
    doc = ops_doc()
    ops = doc["scenes"][0]["ops"]
    ops[1], ops[2] = ops[2], ops[1]
    result = an.expand(doc, project, 1, PARAGRAPHS)
    assert any("又回到前面的段落" in str(issue) for issue in result.issues)


def test_expand_flags_unknown_location_and_chinese_setting(project):
    doc = ops_doc()
    doc["scenes"][0]["location"] = "nowhere"
    doc["scenes"][0]["setting_en"] = "天台的水塔陰影。"
    result = an.expand(doc, project, 1, PARAGRAPHS)
    text = "／".join(str(issue) for issue in result.issues)
    assert "地點「nowhere」不在 bible/locations" in text
    assert "setting_en 要寫英文" in text


def test_expand_flags_unknown_speaker(project):
    doc = ops_doc()
    doc["scenes"][0]["ops"][7]["s"] = "nobody"
    result = an.expand(doc, project, 1, PARAGRAPHS)
    assert any("說話的角色「nobody」不在 bible/characters" in str(issue) for issue in result.issues)


def test_expand_adds_speaker_missing_from_cast(project):
    doc = ops_doc()
    doc["scenes"][0]["cast"] = [{"id": "lin", "expression": "annoyed"}]
    result = an.expand(doc, project, 1, PARAGRAPHS)
    assert [str(issue) for issue in result.issues if issue.level == "error"] == []
    assert [item["id"] for item in result.scene_doc["scenes"][0]["cast"]] == ["lin", "hao"]
    assert any("沒列在 cast" in warning for warning in result.warnings)


def test_expand_flags_bad_direction(project):
    doc = ops_doc()
    doc["scenes"][0]["ops"][3] = {"k": "x", "shot": "zoom"}
    result = an.expand(doc, project, 1, PARAGRAPHS)
    assert any("shot「zoom」不認得" in str(issue) for issue in result.issues)
    doc["scenes"][0]["ops"][3] = {"k": "x"}
    result = an.expand(doc, project, 1, PARAGRAPHS)
    assert any("演出至少要寫" in str(issue) for issue in result.issues)


def test_expand_marks_radio_and_offscreen(project):
    doc = ops_doc()
    doc["scenes"][0]["ops"][7] = {"k": "d", "p": 7, "s": "lin", "m": "通訊", "t": "「我已經不餓了。」"}
    line = [item for item in expanded(project, doc).scene_doc["scenes"][0]["lines"]
            if item["type"] == "dialogue" and item["source_para"] == 7][0]
    assert line["kind"] == "radio" and "offscreen" not in line
    doc["scenes"][0]["ops"][7] = {"k": "d", "p": 7, "s": "lin", "m": "心聲、畫面外", "t": "「我已經不餓了。」"}
    result = an.expand(doc, project, 1, PARAGRAPHS)
    assert any("心聲" in str(issue) and "畫面外" in str(issue) for issue in result.issues)


def test_validate_flags_unused_paragraph_and_unfaithful_line(project):
    doc = copy.deepcopy(expanded(project).scene_doc)
    doc["scenes"][0]["lines"] = [line for line in doc["scenes"][0]["lines"] if line.get("source_para") != 10]
    doc["scenes"][0]["lines"][1]["text"] = "林曉雨坐在社辦大樓頂樓"
    issues = an.validate(doc, project, PARAGRAPHS)
    text = "／".join(str(issue) for issue in issues)
    assert "沒用到：10" in text
    assert "不是段落" in text


def test_validate_flags_scene_over_paragraph_limit(project):
    paragraphs = ["第 %d 段的內容。" % index for index in range(1, 42)]
    doc = {"scenes": [{"scene_id": "ch001_sc01", "setting_en": "A long corridor.",
                       "cast": [{"id": "lin", "expression": "calm"}],
                       "lines": [{"type": "narration", "text": text, "source_para": index + 1}
                                 for index, text in enumerate(paragraphs)]}]}
    issues = an.validate(doc, project, paragraphs)
    assert any("上限 %d" % an.MAX_SCENE_PARAGRAPHS in str(issue) for issue in issues)


# ---- 漏句修補 ----------------------------------------------------------------------
def test_repair_omissions_puts_back_missing_narration(project):
    doc = copy.deepcopy(expanded(project).scene_doc)
    lines = doc["scenes"][0]["lines"]
    index = [i for i, line in enumerate(lines) if line.get("source_para") == 4][0]
    lines[index] = {"type": "narration", "text": "就在這時", "source_para": 4}
    added = an.repair_omissions(doc, an.paragraph_map(PARAGRAPHS))
    assert added >= 1
    texts = [line["text"] for line in lines if line.get("source_para") == 4]
    assert an.omitted_clauses(PARAGRAPHS[3], texts) == []
    assert an.validate(doc, project, PARAGRAPHS) == []
    paras = [line["source_para"] for line in lines if isinstance(line.get("source_para"), int)]
    assert paras == sorted(paras)


def test_repair_omissions_is_idempotent(project):
    doc = expanded(project).scene_doc
    first = an.repair_omissions(doc, an.paragraph_map(PARAGRAPHS))
    assert first >= 1                                  # 範例的 ops 只取了台詞，敘述要靠修補補回
    assert an.repair_omissions(doc, an.paragraph_map(PARAGRAPHS)) == 0
    report = an.fidelity(doc, SOURCE, first)
    assert report["omitted"] == [] and report["unfaithful"] == []
    assert [str(issue) for issue in an.validate(doc, project, PARAGRAPHS) if "漏掉敘述" in issue.message] == []


def test_repair_omissions_keeps_dialogue_verbatim(project):
    doc = copy.deepcopy(expanded(project).scene_doc)
    lines = doc["scenes"][0]["lines"]
    index = [i for i, line in enumerate(lines) if line.get("source_para") == 8][0]
    lines[index] = {"type": "narration", "text": "阿浩愣了一下", "source_para": 8}
    before = [line["text"] for line in lines if line["type"] == "dialogue"]
    an.repair_omissions(doc, an.paragraph_map(PARAGRAPHS))
    after = [line["text"] for line in lines if line["type"] == "dialogue"]
    assert before == after


# ---- 忠實度報告 --------------------------------------------------------------------
def test_fidelity_report_counts(project):
    report = an.fidelity(expanded(project).scene_doc, SOURCE, 0)
    assert report["paragraphs"] == 10 and report["paragraphs_used"] == 10
    assert report["dialogue_lines"] == 4 and report["dialogue_found"] == 4
    assert report["unfaithful"] == []
    assert report["source_quotes"] == 5 and report["source_quotes_kept"] == 4   # 電話錄音那句只取了前半段


def test_fidelity_report_flags_rewrite(project):
    doc = copy.deepcopy(expanded(project).scene_doc)
    doc["scenes"][0]["lines"][1]["text"] = "她坐在頂樓"
    report = an.fidelity(doc, SOURCE)
    assert "她坐在頂樓" in report["unfaithful"]
    assert "林曉雨一個人坐在社辦大樓頂樓的水塔陰影下" in report["omitted"]


def test_fidelity_markdown_has_numbers(project):
    text = an.fidelity_markdown(an.fidelity(expanded(project).scene_doc, SOURCE), "天台的便當")
    assert text.startswith("# 切對話忠實度報告：天台的便當")
    assert "原著段落 10 段，用到 10 段（覆蓋 100%）" in text


# ---- 轉分鏡 ------------------------------------------------------------------------
def test_to_storyboard_passes_compile_chapter(project):
    board = an.to_storyboard(project, expanded(project).scene_doc)
    jobs = compile_chapter(project, board)
    assert len(jobs) == sum(len(page["panels"]) for page in board["pages"])
    assert all(page["template"] in PAGES["templates"] for page in board["pages"])


def test_to_storyboard_panels_pass_checks(project):
    board = an.to_storyboard(project, expanded(project).scene_doc)
    for page in board["pages"]:
        issues = check.check_page_panels(project, page["page"], page["template"], page["panels"], PAGES)
        assert [str(issue) for issue in issues if issue.level == "error"] == []


def test_to_storyboard_keeps_dialogue_verbatim_and_columns(project):
    doc = expanded(project).scene_doc
    board = an.to_storyboard(project, doc)
    want = [line["text"] for line in scene_lines(doc) if line["type"] == "dialogue"]
    have = [bubble["text"] for page in board["pages"] for panel in page["panels"]
            for bubble in panel["bubbles"] if bubble["kind"] != "narration"]
    assert ["".join(text.split()) for text in have] == ["".join(text.split()) for text in want]
    for page in board["pages"]:
        for panel in page["panels"]:
            for bubble in panel["bubbles"]:
                limit = check.COLUMN_CHARS_NARRATION if bubble["kind"] == "narration" else check.COLUMN_CHARS
                assert all(len(column) <= limit for column in bubble["text"].split("\n"))


def test_to_storyboard_applies_direction_to_panels(project):
    board = an.to_storyboard(project, expanded(project).scene_doc)
    assert any(panel["shot"] == "wide" and panel["angle"] == "high"
               for page in board["pages"] for panel in page["panels"])


def test_to_storyboard_offscreen_bubble_not_drawn(project):
    doc = ops_doc()
    doc["scenes"][0]["ops"][5] = {"k": "d", "p": 5, "s": "hao", "m": "通訊",
                                  "t": "「對不起！排隊排到一半，被教授抓去搬東西！」"}
    board = an.to_storyboard(project, expanded(project, doc).scene_doc)
    panels = [panel for page in board["pages"] for panel in page["panels"]]
    offscreen = [bubble for panel in panels for bubble in panel["bubbles"] if bubble.get("offscreen")]
    assert len(offscreen) == 1 and offscreen[0]["kind"] == "radio"
    panel = next(panel for panel in panels if any(bubble.get("offscreen") for bubble in panel["bubbles"]))
    assert "hao" not in [item["id"] for item in panel["characters"]]


def test_to_storyboard_follows_plan_templates(project):
    doc = expanded(project).scene_doc
    plan = {"pages": [{"page": 1, "template": "1"}, {"page": 2, "template": "2h"}]}
    board = an.to_storyboard(project, doc, plan=plan)
    assert [page["template"] for page in board["pages"]][:2] == ["1", "2h"]
    assert len(board["pages"]) > 2                      # 頁數不夠時自動補頁
    assert compile_chapter(project, board)


def test_to_storyboard_rejects_empty_scenes(project):
    with pytest.raises(an.AnnotateError):
        an.to_storyboard(project, {"scenes": [{"setting_en": "A room.", "cast": [], "lines": []}]})


# ---- 提示詞 ------------------------------------------------------------------------
def test_annotate_prompt_has_numbered_paragraphs(project):
    messages = prompts.annotate_messages(project, PARAGRAPHS, "天台的便當")
    content = messages[1]["content"]
    assert "〔1〕十二點四十分。" in content and "〔10〕" in content
    assert "切對話" in content and "逐字" in content
    assert "id=lin" in content and "心聲" in content


def test_scenes_ledger_lists_lines_with_paragraphs(project):
    text = prompts.scenes_ledger(expanded(project).scene_doc)
    assert "- 旁白：十二點四十分。〔p1〕" in text
    assert "- lin（小聲）：「……又不接。」〔p3〕" in text


def test_script_prompt_includes_ledger(project):
    from t2c import layout as lay
    plan = {"title": "t", "summary": "s", "pages": [{"page": 1, "template": "1", "purpose": "p", "hook": "",
                                                     "panels": [{"slot": 1, "beat": "b"}]}]}
    page = plan["pages"][0]
    board = expanded(project).scene_doc
    without = prompts.script_messages(project, SOURCE, plan, page, lay.load_pages())
    with_ledger = prompts.script_messages(project, SOURCE, plan, page, lay.load_pages(), "", board)
    assert "切對話帳本" not in without[1]["content"]
    assert "切對話帳本" in with_ledger[1]["content"]
    assert "〔p3〕" in with_ledger[1]["content"]


# ---- 整條流程（假模型）------------------------------------------------------------
class FakeReply:
    def __init__(self, text):
        self.text = text
        self.usage = {"prompt_tokens": 100, "completion_tokens": 50}
        self.finish = "stop"


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat_json(self, prov, messages, **kw):
        self.calls.append((kw.get("stage"), copy.deepcopy(messages)))
        text = json.dumps(self.payload, ensure_ascii=False)
        return llm.parse_json(text), FakeReply(text)

    def chat(self, prov, messages, **kw):
        return FakeReply("")


def test_expand_warns_about_dropped_narration(project):
    result = expanded(project)
    assert any(issue.level == "warn" and "漏掉敘述" in issue.message for issue in result.issues)


def test_run_annotate_writes_scenes_and_report(project):
    fake = FakeLLM(ops_doc())
    adapter = adapt.Adapter(project, {"id": "fake"}, chat=fake.chat, chat_json=fake.chat_json)
    scenes, report = adapter.run_annotate(1, "天台的便當")
    assert fake.calls[0][0] == "annotate"
    assert project.scenes_path(1).is_file()
    assert project.load_scenes(1)["scenes"][0]["scene_id"] == "ch001_sc01"
    report_path = project.root / "build" / "adapt" / "ch001_scenes_fidelity.md"
    assert report_path.is_file() and "切對話忠實度報告" in report_path.read_text(encoding="utf-8")
    assert report["paragraphs_used"] == 10 and report["dialogue_found"] == 4
    assert report["repaired"] >= 1 and report["omitted"] == []    # 漏句修補在正式流程裡就跑過
    board = an.to_storyboard(project, scenes)
    assert compile_chapter(project, board)


def test_run_annotate_repairs_after_bad_reply(project):
    bad = ops_doc()
    bad["scenes"][0]["ops"][7]["t"] = "「我不想吃。」"
    fake = FakeLLM(bad)
    adapter = adapt.Adapter(project, {"id": "fake"}, chat=fake.chat, chat_json=fake.chat_json)
    adapter.max_fix = 1
    with pytest.raises(adapt.AdaptError):
        adapter.run_annotate(1)
    assert len(fake.calls) == 2                  # 一次退回、一次重寫
    assert not project.scenes_path(1).is_file()


def test_run_annotate_force_overwrites(project):
    fake = FakeLLM(ops_doc())
    adapter = adapt.Adapter(project, {"id": "fake"}, chat=fake.chat, chat_json=fake.chat_json)
    adapter.run_annotate(1)
    with pytest.raises(adapt.AdaptError):
        adapter.run_annotate(1)
    adapter.run_annotate(1, force=True)


# ---- 忠實度基準：用既有劇本反推 scenes，數字要重現舊報告 ---------------------------
def scenes_from_script(project, chapter):
    """把現成的劇本反推成 scenes（只有忠實度報告要用的欄位）。"""
    source = project.load_source(chapter)
    para_map = an.paragraph_map(an.split_paragraphs(source))
    _, pages, _ = sc.parse_script(project.script_path(chapter).read_text(encoding="utf-8"))
    attributed = []
    for page in pages:
        for panel in page.panels:
            for line in panel.lines:
                if line.kind == "sfx":
                    continue
                para = next((number for number in sorted(para_map) if not an.unfaithful_clauses(line.text, para_map[number])),
                            an.locate_clause(line.text, para_map) or (attributed[-1]["source_para"] if attributed else 1))
                attributed.append({"type": "narration" if line.kind == "narration" else "dialogue",
                                   "text": line.text, "source_para": para})
    blocks = {}
    for line in attributed:
        blocks.setdefault((line["source_para"] - 1) // 30, []).append(line)
    scenes = []
    for index, key in enumerate(sorted(blocks), 1):
        scenes.append({"scene_id": "ch%03d_sc%02d" % (int(chapter), index),
                       "setting_en": "The scene as described in the source text.",
                       "cast": [], "lines": blocks[key]})
    return {"version": 1, "chapter": int(chapter), "title": "", "scenes": scenes}


@pytest.mark.skipif(not (M1 / "script" / "ch001.md").is_file(), reason="work/m1_mars_ch1 不在（不進版控）")
def test_fidelity_baseline_matches_m1_report():
    """M1 的〈大夜班〉第 1 章：把現有劇本反推成 scenes，新的切對話報告要得到和劇本層報告一樣的數字，
    才叫做「不比現有水準差」。（build/adapt/ch001_fidelity.md 是 L-3 之前留下的 39/44；同一份劇本用現在的程式
    重算是 43/44，所以基準要在同一支測試裡即時算，不能抄檔案裡的舊數字。）"""
    project = Project(M1)
    source = project.load_source(1)
    _, pages, _ = sc.parse_script(project.script_path(1).read_text(encoding="utf-8"))
    old = sc.fidelity(source, pages)
    new = an.fidelity(scenes_from_script(project, 1), source)
    assert (new["dialogue_lines"], new["dialogue_found"]) == (old["dialogue_lines"], old["dialogue_found"])
    assert (new["source_quotes"], new["source_quotes_kept"]) == (old["source_quotes"], old["source_quotes_kept"])
    assert new["dialogue_found"] >= 43            # L-3 修正後的現況（39/44 是更早的版本）
    # 劇本層沒有段落覆蓋的觀念：同一章 83 段裡只有 40 段被用到。切對話要求全覆蓋，這是新的門檻。
    assert new["paragraphs"] == 83 and new["paragraphs_used"] == 40
