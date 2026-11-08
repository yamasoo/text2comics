"""S6：視覺聖經。模型用腳本化的假回覆，ComfyUI 用假的出圖函式，不連外網、不需要金鑰或 GPU。
執行：python -m pytest tests/test_bible.py
"""
import importlib.util
import io
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from t2c import bible, bible_check as bc, bible_prompts as bp, comfy, llm  # noqa: E402
from t2c.compile import compile_chapter  # noqa: E402
from t2c.project import Project, read_front_matter  # noqa: E402
from t2c.script import errors  # noqa: E402
from test_llm import ok_chunks, serve  # noqa: E402,F401  （serve 是 fixture）

SAMPLE = ROOT / "examples" / "sample_comic"

CH1 = """---
title: 雨
---
阿杰把濕透的帽T掛在椅背上，揉了揉那頭亂翹的短髮。小晴戴著黑框眼鏡，從拱廊盡頭的書店探出頭來：「又忘了帶傘？」
老闆娘在櫃台後面沒抬頭。
"""
CH2 = """阿杰撐著折疊傘走進拱廊，小晴把書店的鐵捲門拉到一半。她說：「你的傘壞了。」
阿杰沒回答，拱廊的紙燈籠在風裡搖。
"""


def js(obj):
    return json.dumps(obj, ensure_ascii=False)


SCAN1 = {"characters": [
    {"name": "阿杰", "aliases": [], "role": "淋濕了跑進拱廊", "looks": [{"en": "unruly short hair", "quote": "那頭亂翹的短髮"}],
     "outfits": [{"label": "帽T", "en": "a soaked hooded sweatshirt", "quote": "濕透的帽T"}]},
    {"name": "小晴", "aliases": [], "role": "探頭調侃", "looks": [{"en": "black-rimmed glasses", "quote": "戴著黑框眼鏡"}], "outfits": []},
    {"name": "老闆娘", "aliases": [], "role": "櫃台後面", "looks": [], "outfits": []}],
    "locations": [{"name": "拱廊", "aliases": [], "role": "碰面", "looks": []}], "mentioned_only": []}
SCAN2 = {"characters": [
    {"name": "阿杰", "aliases": ["杰"], "role": "撐傘回來", "looks": [], "outfits": [{"label": "帽T", "en": "a soaked hooded sweatshirt", "quote": "撐著折疊傘"}]},
    {"name": "小晴", "aliases": [], "role": "拉鐵捲門", "looks": [], "outfits": []}],
    "locations": [{"name": "拱廊", "aliases": [], "role": "紙燈籠", "looks": [{"en": "paper lanterns swaying in the wind", "quote": "紙燈籠在風裡搖"}]}],
    "mentioned_only": ["書店老闆"]}

CARD_JIE = {"id": "jie", "name": "阿杰", "aliases": [], "look_en": "A 22-year-old East Asian man with short, unruly black hair, a square jaw and a lean build",
            "outfits": {"default": "He wears a faded gray hooded sweatshirt over a white T-shirt, dark jeans and worn sneakers.",
                        "rain": "He wears a soaked yellow raincoat over dark trousers."},
            "outfit_notes": {"default": "日常", "rain": "下雨天（第 2 章）"}, "summary": "愛逞強的大學生。",
            "invented": ["年齡與種族（原文沒寫）"], "conflicts": []}
CARD_QING = {"id": "qing", "name": "小晴", "aliases": ["晴"], "look_en": "A 21-year-old East Asian woman with a black bob, black-rimmed glasses and a slim build",
             "outfits": {"default": "She wears a green apron over a white blouse and a long gray skirt."}, "outfit_notes": {"default": "書店制服"},
             "summary": "書店的店員。", "invented": [], "conflicts": []}
CARD_ARCADE = {"id": "arcade", "name": "拱廊", "aliases": [], "look_en": "A narrow covered shopping arcade with a glass roof, small shuttered shops on both sides and hanging paper lanterns",
               "summary": "老商店街。", "invented": ["玻璃屋頂（為了辨識度而補）"], "conflicts": []}


class Fake:
    """依序回覆；記下每次的 messages。最後一則重複使用。"""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat_json(self, prov, messages, **kw):
        self.calls.append(json.loads(json.dumps(messages)))
        text = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return llm.parse_json(text), llm.Reply(text=text, usage={"prompt_tokens": 100, "completion_tokens": 50}, finish="stop")


@pytest.fixture
def novel(tmp_path):
    folder = tmp_path / "novel" / "正文"
    folder.mkdir(parents=True)
    (folder / "第01章_雨.md").write_text(CH1, encoding="utf-8")
    (folder / "第02章_傘.md").write_text(CH2, encoding="utf-8")
    notes = tmp_path / "novel" / "設定"
    (notes / "角色").mkdir(parents=True)
    (notes / "草稿").mkdir()
    (notes / "角色" / "阿杰.md").write_text("---\n類型: 角色\n---\n# 阿杰\n- 外貌：一頭亂翹的短髮\n- 年齡：（正文未明確）\n<!-- 註解 -->\n", encoding="utf-8")
    (notes / "草稿" / "阿杰.md").write_text("草稿，不該被讀到", encoding="utf-8")
    return tmp_path / "novel"


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "comic"
    root.mkdir()
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    shutil.copytree(SAMPLE / "bible", root / "bible")
    return Project(root)


def builder(proj, replies, **kw):
    fake = Fake(replies)
    return bible.Builder(proj, {"id": "fake"}, chat_json=fake.chat_json, **kw), fake


# ---- 規則檢查 ----------------------------------------------------------------------
def test_sample_cards_and_prompt_examples_pass_lint():
    """範例卡、提示詞裡的範例都要通過自己的規則，否則等於教模型寫錯。"""
    project = Project(SAMPLE)
    for kind, cards in (("character", project.characters), ("location", project.locations)):
        for card in cards.values():
            assert not errors(bc.check_card(card, kind)), card["id"]
    assert not errors(bc.check_card(bp.EXAMPLE_CHARACTER, "character"))
    assert not errors(bc.check_card(bp.EXAMPLE_LOCATION, "location"))
    clean, issues = bc.normalize_scan(bp.SCAN_EXAMPLE, bp.SCAN_EXAMPLE_TEXT)
    assert not issues and clean["characters"][1]["name"] == "小晴"


@pytest.mark.parametrize("look, needle", [
    ("A 22-year-old East Asian man with a warm smile, short black hair and a lean build", "smile"),
    ("A 22-year-old East Asian man in a gray jacket with short black hair and a lean build", "jacket"),
    ("A 22-year-old East Asian man standing with short black hair and a lean build", "standing"),
    ("A 22-year-old East Asian person with short black hair and a lean build", "性別"),
    ("An East Asian man with short black hair and a lean build", "年齡"),
    ("A 22-year-old man", "太短"),
    ("一個二十二歲的男生，短黑髮，精瘦", "英文"),
])
def test_look_en_rules_reject(look, needle):
    msgs = [str(i) for i in errors(bc.check_character_look(look, "角色 x"))]
    assert any(needle in m for m in msgs), msgs


def test_look_en_allows_permanent_features_and_warns_without_hair():
    assert not errors(bc.check_character_look("A 45-year-old man with a scar across his right hand, round glasses and a stocky build", "x"))
    warns = [i for i in bc.check_character_look("A 45-year-old man with round glasses and a stocky build", "x") if i.level == "warn"]
    assert warns and "頭髮" in warns[0].message


def test_outfit_rules():
    look = "A 22-year-old East Asian man with short black hair and a lean build"
    assert not errors(bc.check_outfits({"default": "He wears a gray hoodie."}, look, "x"))
    bad = {"default": "A gray hoodie.", "rain": "She wears a raincoat.", "Bad Id": "He wears a hat.", "angry": "He wears a coat and is smiling."}
    msgs = " | ".join(str(i) for i in errors(bc.check_outfits(bad, look, "x")))
    assert "He wears" in msgs and "性別不一致" in msgs and "只能用 a-z" in msgs and "smiling" in msgs
    assert "default" in str(errors(bc.check_outfits({"rain": "He wears a coat."}, look, "x"))[0])
    assert "outfits" in str(errors(bc.check_outfits(None, look, "x"))[0])


def test_location_look_rules():
    assert not errors(bc.check_location_look("A narrow covered arcade with a glass roof and a worn tile floor", "x"))
    assert "不要有人" in str(errors(bc.check_location_look("A narrow arcade where a woman sells tea under a glass roof", "x"))[0])
    assert "英文" in str(errors(bc.check_location_look("一條有玻璃屋頂的老商店街", "x"))[0])


def test_check_card_ids_and_notes():
    card = dict(CARD_JIE, id="Bad Id", outfit_notes={"ghost": "x"})
    msgs = " | ".join(str(i) for i in bc.check_card(card))
    assert "id 只能用" in msgs and "ghost" in msgs


def test_scan_quotes_must_be_verbatim_and_names_present():
    bad = {"characters": [
        {"name": "阿杰", "looks": [{"en": "unruly short hair", "quote": "一頭亂翹的短髮"}]},                     # 原文是「那頭」
        {"name": "路人甲", "looks": []},                                                                     # 沒出現
        {"name": "小晴", "looks": [{"en": "glasses", "quote": "戴著黑框眼鏡"}, {"en": "a smiling face", "quote": "探出頭來"}],
         "outfits": [{"en": "a coat", "quote": "探出頭來"}]}],                                                  # looks 有表情、outfits 缺 label
        "locations": []}
    clean, issues = bc.normalize_scan(bad, CH1, "第01章")
    msgs = " | ".join(str(i) for i in issues)
    assert "找不到" in msgs and "路人甲" in msgs and "smiling" in msgs and "label" in msgs
    assert [c["name"] for c in clean["characters"]] == ["阿杰", "小晴"]


# ---- 讀原著與設定 ------------------------------------------------------------------
def test_load_sources_numbers_strips_frontmatter(novel):
    sources = bible.load_sources([novel / "正文"])
    assert [s["n"] for s in sources] == [1, 2] and sources[0]["label"] == "第01章_雨"
    assert sources[0]["text"].startswith("阿杰把") and "title:" not in sources[0]["text"]
    with pytest.raises(bible.BibleError, match="重複"):
        shutil.copy(novel / "正文" / "第01章_雨.md", novel / "正文" / "第1章_又一份.md")
        bible.load_sources([novel / "正文"])
    with pytest.raises(bible.BibleError, match="沒有原著"):
        bible.load_sources([], None)


def test_load_notes_skips_drafts_and_empty_lines_and_matches_by_name(novel):
    notes = bible.load_notes([novel / "設定"])
    assert [n["label"] for n in notes] == ["角色/阿杰.md"]
    assert "正文未明確" not in notes[0]["text"] and "註解" not in notes[0]["text"]
    assert bible.notes_for({"name": "阿杰", "aliases": []}, notes)[0][0] == "角色/阿杰.md"
    assert bible.notes_for({"name": "小晴", "aliases": []}, notes) == []


# ---- 合併 --------------------------------------------------------------------------
def test_merge_scans_joins_aliases_dedupes_and_marks_known(proj):
    s1, _ = bc.normalize_scan(SCAN1, CH1)
    s2, _ = bc.normalize_scan(SCAN2, CH2)
    merged = bible.merge_scans([(2, s2), (1, s1)], proj)
    names = {e["name"]: e for e in merged["characters"]}
    assert set(names) == {"阿杰", "小晴", "老闆娘"}
    jie = names["阿杰"]
    assert jie["chapters"] == [1, 2] and jie["aliases"] == ["杰"]
    assert len(jie["looks"]) == 1 and jie["looks"][0]["chapter"] == 1          # 重複的外觀只留最早的
    assert len(jie["outfits"]) == 1
    assert merged["mentioned_only"] == ["書店老闆"]
    assert merged["characters"][0]["chapters"] == [1, 2] and "outfits" not in merged["locations"][0]
    # 已有定案卡片（範例的 林曉雨）會被標成 known
    s3, _ = bc.normalize_scan({"characters": [{"name": "曉雨", "aliases": [], "role": "x", "looks": [], "outfits": []}]}, "曉雨來了")
    assert bible.merge_scans([(1, s3)], proj)["characters"][0]["known"] == "lin"


# ---- 流程：掃描 → 成卡 → 確認 ---------------------------------------------------------
def run_pipeline(proj, novel):
    bad_scan = dict(SCAN1, characters=[dict(SCAN1["characters"][0], looks=[{"en": "unruly short hair", "quote": "一頭亂翹的短髮"}])] + SCAN1["characters"][1:])
    bad_card = dict(CARD_JIE, look_en="A 22-year-old East Asian man with a warm smile, short black hair and a lean build")
    b, fake = builder(proj, [js(bad_scan), js(SCAN1), js(SCAN2), js(bad_card), js(CARD_JIE), js(CARD_QING), js(CARD_ARCADE)])
    sources = bible.load_sources([novel / "正文"])
    entities = b.scan(sources, inputs=[novel / "正文"], notes_inputs=[novel / "設定"])
    report = b.draft(min_chapters=2, notes=bible.load_notes([novel / "設定"]))
    return b, fake, entities, report


def test_scan_and_draft_end_to_end_with_repair(proj, novel):
    b, fake, entities, report = run_pipeline(proj, novel)
    # 掃描：第 1 章第一次引文不對 → 回修一次；之後一章一次
    assert fake.calls[0][0]["content"].startswith("你是日本漫畫的角色設計師")
    fix = fake.calls[1][-1]["content"]
    assert "找不到" in fix and "一頭亂翹的短髮" in fix and fake.calls[1][-2]["role"] == "assistant"
    assert entities["notes"] and (proj.root / "build" / "bible" / "entities.json").is_file()
    assert (proj.root / "build" / "bible" / "scan" / "ch001.json").is_file()
    # 成卡：老闆娘只出現一章 → 略過；阿杰第一次 look_en 有 smile → 回修
    assert report["rare"] == ["老闆娘"] and report["known"] == []
    assert [(k, i) for k, i, _ in report["drafted"]] == [("character", "jie"), ("character", "qing"), ("location", "arcade")]
    card_fix = fake.calls[4][-1]["content"]
    assert "smile" in card_fix and "表情或情緒" in card_fix
    # 作者設定只給有關的人，而且只有有資訊的行
    jie_prompt = fake.calls[3][1]["content"]
    assert "作者的設定檔" in jie_prompt and "一頭亂翹的短髮" in jie_prompt and "正文未明確" not in jie_prompt and "草稿，不該" not in jie_prompt
    assert "作者的設定檔" not in fake.calls[6][1]["content"]
    assert b.usage["calls"] == 7 and b.usage["prompt_tokens"] == 700

    # 草稿檔：frontmatter 讀得回來、待確認與依據寫在本文、Project 讀不到草稿
    draft = proj.root / "bible" / "drafts" / "characters" / "jie.md"
    meta, body = read_front_matter(draft)
    assert meta["status"] == "draft" and meta["name"] == "阿杰" and meta["aliases"] == ["杰"]
    assert meta["look_en"] == CARD_JIE["look_en"] and meta["outfits"] == CARD_JIE["outfits"] and meta["outfit_notes"]["rain"].startswith("下雨天")
    assert "待確認" in body and "年齡與種族" in body and "「那頭亂翹的短髮」→ unruly short hair" in body and "第 1、2 章" in body
    assert "jie" not in Project(proj.root).characters
    assert not errors([i for _, _, issues in bible.lint(proj) for i in issues])


def test_scan_cache_and_rescan_on_change(proj, novel):
    b, fake, _, _ = run_pipeline(proj, novel)
    sources = bible.load_sources([novel / "正文"])
    b2, fake2 = builder(proj, [js(SCAN1)])
    b2.scan(sources)
    assert fake2.calls == []                                           # 原文沒變：全部沿用
    (novel / "正文" / "第02章_傘.md").write_text(CH2 + "紙燈籠又亮了。\n", encoding="utf-8")
    b3, fake3 = builder(proj, [js(SCAN2)])
    b3.scan(bible.load_sources([novel / "正文"]))
    assert len(fake3.calls) == 1                                       # 只有改過的那章重掃
    b4, fake4 = builder(proj, [js(SCAN1), js(SCAN2)])
    b4.scan(bible.load_sources([novel / "正文"]), force=True)
    assert len(fake4.calls) == 2


def test_draft_gives_up_after_max_fix_and_reports_where(proj, novel):
    b, fake = builder(proj, [js(SCAN1), js(SCAN2)])
    b.scan(bible.load_sources([novel / "正文"]))
    bad = dict(CARD_JIE, look_en="He is smiling")
    b2, fake2 = builder(proj, [js(bad)], max_fix=2)
    with pytest.raises(bible.BibleError, match="修了 2 次") as exc:
        b2.draft(only=["阿杰"])
    assert "最後一次的輸出存在" in str(exc.value) and len(fake2.calls) == 3
    assert (proj.root / "build" / "bible" / "raw").is_dir()


def test_draft_id_collision_with_existing_card_is_repaired(proj, novel):
    b, _ = builder(proj, [js(SCAN1), js(SCAN2)])
    b.scan(bible.load_sources([novel / "正文"]))
    clash = dict(CARD_JIE, id="lin")                                   # 範例專案已有 lin
    b2, fake2 = builder(proj, [js(clash), js(CARD_JIE)])
    report = b2.draft(only=["阿杰"])
    assert "已經被用掉" in fake2.calls[1][-1]["content"] and report["drafted"][0][1] == "jie"


def test_draft_skips_existing_draft_and_force_replaces_it(proj, novel):
    b, _ = builder(proj, [js(SCAN1), js(SCAN2)])
    b.scan(bible.load_sources([novel / "正文"]))
    b1, _ = builder(proj, [js(CARD_JIE)])
    b1.draft(only=["阿杰"])
    b2, fake2 = builder(proj, [js(CARD_JIE)])
    assert b2.draft(only=["阿杰"])["has_draft"] == ["阿杰"] and fake2.calls == []
    renamed = dict(CARD_JIE, id="jie2")
    b3, _ = builder(proj, [js(renamed)])
    report = b3.draft(only=["阿杰"], force=True)
    assert report["drafted"][0][1] == "jie2"
    drafts = bible.list_drafts(proj)
    assert list(drafts) == ["jie2"]                                    # 舊 id 的草稿被換掉，不會留兩份


def test_accept_moves_draft_and_checks(proj, novel):
    run_pipeline(proj, novel)
    with pytest.raises(bible.BibleError, match="找不到"):
        bible.accept(proj, ["nobody"])
    moved = bible.accept(proj, ["阿杰", "arcade"])
    assert [(k, i) for k, i, _ in moved] == [("character", "jie"), ("location", "arcade")]
    project = Project(proj.root)
    assert project.characters["jie"]["status"] == "confirmed" and "arcade" in project.locations
    assert not (proj.root / "bible" / "drafts" / "characters" / "jie.md").exists()
    assert (proj.root / "bible" / "drafts" / "characters" / "qing.md").exists()
    # 草稿有錯誤時擋下
    path = proj.root / "bible" / "drafts" / "characters" / "qing.md"
    path.write_text(path.read_text(encoding="utf-8").replace("She wears a green apron", "A green apron"), encoding="utf-8")
    with pytest.raises(bible.BibleError, match="不能確認入庫"):
        bible.accept(proj, ["qing"])
    # 已經有定案卡片時不覆蓋
    (proj.root / "bible" / "drafts" / "characters").joinpath("jie.md").write_text(
        (proj.root / "bible" / "characters" / "jie.md").read_text(encoding="utf-8").replace("status: confirmed", "status: draft"), encoding="utf-8")
    with pytest.raises(bible.BibleError, match="已經存在"):
        bible.accept(proj, ["jie"])
    assert bible.accept(proj, ["jie"], force=True)


def test_accepted_card_compiles_with_verbatim_look(proj, novel):
    """定案的卡片真的能進分鏡編譯，而且 look_en、服裝逐字貼進該格。"""
    run_pipeline(proj, novel)
    bible.accept(proj, ["*"])
    project = Project(proj.root)
    storyboard = {"pages": [{"page": 1, "template": "1", "panels": [{
        "slot": 1, "shot": "medium", "location": "arcade", "scene": "The young man stands under the lanterns.",
        "characters": [{"id": "jie", "outfit": "rain", "pose": "Closing a folding umbrella", "expression": "Annoyed", "box": [0.2, 0.1, 0.8, 1]}]}]}]}
    job = compile_chapter(project, storyboard)[0]
    caption = job["layout"]["items"][1]["caption"]
    assert CARD_JIE["look_en"] + "." in caption and "soaked yellow raincoat" in caption
    assert "glass roof" in job["layout"]["summary"]["caption"]


# ---- 定裝圖 ------------------------------------------------------------------------
def test_sheet_jobs_shapes_and_captions(proj):
    jobs, manifest = bible.sheet_jobs(proj, views=("full", "bust"), candidates=2)
    ids = [j["id"] for j in jobs]
    assert ids == ["ref_c_hao_default_full", "ref_c_hao_default_bust", "ref_c_lin_default_full", "ref_c_lin_default_bust", "ref_l_rooftop"]
    assert manifest["ref_c_lin_default_bust"] == {"kind": "character", "id": "lin", "outfit": "default", "view": "bust"}
    full, loc = jobs[0], jobs[-1]
    assert (full["width"], full["height"]) == (864, 1152) and (loc["width"], loc["height"]) == (1152, 864)
    assert len(full["seeds"]) == 2 and full["seeds"][0] != full["seeds"][1]
    caption = full["layout"]["summary"]["caption"]
    assert "plain white background" in caption and "exactly one person" in caption
    assert "Facial expression: Neutral" in full["layout"]["items"][0]["caption"]
    assert "no people" in loc["layout"]["summary"]["caption"].lower() and loc["layout"]["items"][0]["label"] == "object"
    only, _ = bible.sheet_jobs(proj, ids=["林曉雨"], kinds=("character",))
    assert [j["id"] for j in only] == ["ref_c_lin_default_full"]
    with pytest.raises(bible.BibleError, match="找不到"):
        bible.sheet_jobs(proj, ids=["ghost"])
    with pytest.raises(bible.BibleError, match="視角"):
        bible.sheet_jobs(proj, views=("side",))


def test_sheet_jobs_one_per_outfit(proj):
    path = proj.root / "bible" / "characters" / "lin.md"
    path.write_text(path.read_text(encoding="utf-8").replace("---\n大學二年級", "  school: She wears a navy school blazer over a white shirt and a plaid skirt.\n---\n大學二年級"), encoding="utf-8")
    project = Project(proj.root)
    jobs, _ = bible.sheet_jobs(project, ids=["lin"], kinds=("character",))
    assert [j["id"] for j in jobs] == ["ref_c_lin_default_full", "ref_c_lin_school_full"]
    assert "navy school blazer" in jobs[1]["layout"]["items"][0]["caption"]
    assert [j["id"] for j in bible.sheet_jobs(project, ids=["lin"], outfits=["school"], kinds=("character",))[0]] == ["ref_c_lin_school_full"]


def png_bytes(color):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 80), color).save(buf, "PNG")
    return buf.getvalue()


CFG = {"comfy": {"url": "http://127.0.0.1:1", "workflow": "workflows/moss_layout.api.json",
                 "models": {"unet": "u.safetensors", "clip": "c.safetensors", "vae": "v.safetensors"},
                 "default_preset": "final", "presets": {"final": {"steps": 25}, "draft": {"steps": 4}}}}


@pytest.fixture
def fake_comfy(monkeypatch):
    calls = []

    def run(base, wf, out_id, should_stop=lambda: False, timeout=1800):
        calls.append(wf)
        return png_bytes((len(calls) * 20 % 255, 80, 160))
    monkeypatch.setattr(comfy, "run", run)
    return calls


def test_render_contact_pick_status_flow(proj, fake_comfy):
    jobs, manifest = bible.sheet_jobs(proj, candidates=2)
    events = []
    written = bible.render_sheets(proj, jobs, manifest, CFG, on_event=events.append)
    assert len(written) == 6 and len(fake_comfy) == 6 and written[0].startswith("ref_c_hao_default_full_s")
    assert fake_comfy[0]["8"]["inputs"]["steps"] == 25 and fake_comfy[0]["7"]["inputs"]["width"] == 864
    again = bible.render_sheets(proj, jobs, manifest, CFG, on_event=events.append)
    assert again == [] and len(fake_comfy) == 6 and events[-1]["kind"] == "skip"           # 已存在就跳過
    draft = bible.render_sheets(proj, jobs[:1], manifest, CFG, preset_name="draft")
    assert draft[0].endswith("_draft.png") and fake_comfy[-1]["8"]["inputs"]["steps"] == 4   # 非預設預設加後綴
    with pytest.raises(bible.BibleError, match="預設"):
        bible.render_sheets(proj, jobs, manifest, CFG, preset_name="nope")

    sheet = bible.contact_sheet(proj, "character", "lin")
    assert sheet.is_file() and sheet.name == "contact_character_lin.jpg"
    assert bible.contact_sheet(proj, "location", "ghost") is None

    lin_image = next(f for f, info, _ in bible.render_files(proj, "character", "lin") if not f.endswith("_draft.png"))
    with pytest.raises(bible.BibleError, match="不是「hao」"):
        bible.pick(proj, lin_image, cid="hao")
    with pytest.raises(bible.BibleError, match="不是定裝圖"):
        bible.pick(proj, "p001_k1_s1.png")
    assert bible.pick(proj, lin_image, cid="lin", outfit="default") == ("character", "lin", "default", "full")
    loc_image = bible.render_files(proj, "location", "rooftop")[0][0]
    bible.pick(proj, loc_image)
    picks = json.loads((proj.root / "bible" / "picks.json").read_text(encoding="utf-8"))
    assert picks["characters"]["lin"]["default"]["full"]["image"] == lin_image and picks["locations"]["rooftop"]["image"] == loc_image

    st = bible.status(proj)
    lin = next(r for r in st["characters"] if r["id"] == "lin")
    assert lin["outfits"][0]["state"] == "ok" and lin["outfits"][0]["image"] == lin_image
    assert next(r for r in st["characters"] if r["id"] == "hao")["outfits"][0]["state"] == "none"
    assert st["locations"][0]["state"] == "ok"
    # look_en 改了 → 已過期（要重畫重挑）
    path = proj.root / "bible" / "characters" / "lin.md"
    path.write_text(path.read_text(encoding="utf-8").replace("slim build", "very slim build"), encoding="utf-8")
    stale = next(r for r in bible.status(Project(proj.root))["characters"] if r["id"] == "lin")
    assert stale["outfits"][0]["state"] == "stale"


def test_status_usage_unlisted_and_matrix(proj):
    shutil.copytree(SAMPLE / "storyboard", proj.root / "storyboard")
    (proj.root / "plan").mkdir()
    (proj.root / "plan" / "ch001.json").write_text(js({"chapter": 1, "unlisted_characters": ["店長", "林曉雨", "阿浩"]}), encoding="utf-8")
    st = bible.status(proj)
    lin = next(r for r in st["characters"] if r["id"] == "lin")
    assert lin["outfits"][0]["used"] == {1: 3}
    assert list(st["unlisted"]) == ["店長"]                                   # 已有卡片的名字（含別名）不算缺
    text = bible.matrix_markdown(st)
    assert "| 林曉雨（lin） | default | － 未挑 |" in text and "第 1 章×3" in text and "店長（第 1 章）" in text
    # 分鏡用了卡片沒有的服裝
    sb = json.loads((proj.root / "storyboard" / "ch001.json").read_text(encoding="utf-8"))
    sb["pages"][0]["panels"][0]["characters"] = [{"id": "lin", "outfit": "ghost"}]
    (proj.root / "storyboard" / "ch001.json").write_text(js(sb), encoding="utf-8")
    lin = next(r for r in bible.status(proj)["characters"] if r["id"] == "lin")
    assert any(o["state"] == "missing" and o["id"] == "ghost" for o in lin["outfits"])


# ---- 走真正的 llm.chat_json（假伺服器）、命令列 ----------------------------------------
def test_scan_through_real_llm_client_uses_bible_stage(proj, novel, serve):  # noqa: F811
    text = js(SCAN1)
    f = serve([{"chunks": ok_chunks(text[:40], text[40:])}, {"chunks": ok_chunks(js(SCAN2))}])
    cfg = {"providers": [{"id": "other", "base_url": "http://127.0.0.1:1"},
                         {"id": "b", "base_url": f.url, "model": "m", "key_env": "", "context_tokens": 64000, "max_output": 4000, "json_mode": True}],
           "default_provider": "other", "stage_providers": {"bible": "b"}}
    b = bible.Builder(proj, prov_for=lambda key: llm.find_provider(cfg, stage=key))
    entities = b.scan(bible.load_sources([novel / "正文"]))
    assert len(entities["characters"]) == 3
    body = f.requests[0][1]
    assert body["response_format"] == {"type": "json_object"} and "又忘了帶傘" in body["messages"][1]["content"]


@pytest.fixture
def cli():
    spec = importlib.util.spec_from_file_location("tools_bible", ROOT / "tools" / "bible.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_check_accept_sheet_status_and_show_prompt(proj, novel, cli, capsys):
    run_pipeline(proj, novel)
    root = str(proj.root)
    assert cli.main(["check", root]) == 0
    out = capsys.readouterr().out
    assert "草稿" in out and "0 份有錯誤" in out
    assert cli.main(["accept", root, "--all"]) == 0
    assert cli.main(["accept", root, "nobody"]) == 1
    assert cli.main(["accept", root]) == 2
    assert cli.main(["sheet", root, "--only", "jie", "--views", "full,bust", "--candidates", "1"]) == 0
    assert (proj.root / "build" / "bible" / "ref_c_jie_rain_bust.prompt.json").is_file()
    assert cli.main(["sheet", root, "--only", "ghost"]) == 1
    assert cli.main(["contact", root]) == 0
    assert cli.main(["pick", root, "ref_c_jie_default_full_s1.png"]) == 1
    capsys.readouterr()
    assert cli.main(["status", root]) == 0
    assert "jie" in capsys.readouterr().out and (proj.root / "build" / "bible" / "matrix.md").is_file()
    # --show-prompt 不呼叫模型、不需要金鑰
    shutil.rmtree(proj.root / "build" / "bible" / "scan")
    cfg = proj.root.parent / "config.json"
    cfg.write_text(js({"providers": [{"id": "x", "base_url": "http://127.0.0.1:1", "key_env": "NO_SUCH_KEY"}]}), encoding="utf-8")
    assert cli.main(["scan", root, "--from", str(novel / "正文"), "--show-prompt", "--config", str(cfg)]) == 0
    assert "本章：第01章_雨" in capsys.readouterr().out
    assert cli.main(["draft", root, "--only", "小晴", "--show-prompt", "--config", str(cfg)]) == 0
    shown = capsys.readouterr().out
    assert "這個角色的證據" in shown and "戴著黑框眼鏡" in shown


def test_parse_chapters(cli):
    assert cli.parse_chapters("1-3,5") == {1, 2, 3, 5}
