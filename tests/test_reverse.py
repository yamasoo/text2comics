"""N5 反推排程層：分批、預算、斷點續跑、累積、草稿。模型用腳本化的假回覆，不連外網。
執行：python -m pytest tests/test_reverse.py
"""
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import bible, llm, reverse  # noqa: E402
from t2c.compile import compile_chapter  # noqa: E402
from t2c.project import Project, read_front_matter  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"

CH1 = """---
title: 雨
---
阿杰把濕透的帽T掛在椅背上，揉了揉那頭亂翹的短髮。小晴戴著黑框眼鏡，從拱廊盡頭的書店探出頭來：「又忘了帶傘？」
"""
CH2 = "阿杰撐著折疊傘走進拱廊，小晴把書店的鐵捲門拉到一半。紙燈籠的光落在濕地板上。\n"
CH3 = "阿杰站在拱廊口，沒有帶傘。小晴把一本書塞給他，紙燈籠在風裡搖。\n"
CH4 = "雨停了。阿杰和小晴一起離開拱廊。\n"
CH1_BOSS = CH1 + "老闆娘在櫃台後面擦杯子。\n"


def js(obj):
    return json.dumps(obj, ensure_ascii=False)


JIE = {"name": "阿杰", "aliases": [], "role": "淋濕了跑進拱廊",
       "looks": [{"en": "unruly short hair", "quote": "那頭亂翹的短髮"}],
       "outfits": [{"label": "帽T", "en": "a soaked hooded sweatshirt", "quote": "濕透的帽T"}]}
QING = {"name": "小晴", "aliases": [], "role": "探頭調侃",
        "looks": [{"en": "black-rimmed glasses", "quote": "戴著黑框眼鏡"}], "outfits": []}
ARCADE1 = {"name": "拱廊", "aliases": [], "role": "碰面",
           "looks": [{"en": "a narrow covered arcade", "quote": "拱廊盡頭"}]}
ARCADE2 = {"name": "拱廊", "aliases": [], "role": "紙燈籠",
           "looks": [{"en": "paper lantern light on a wet floor", "quote": "紙燈籠的光落在濕地板上"}]}
ARCADE3 = {"name": "拱廊", "aliases": [], "role": "紙燈籠在風裡搖",
           "looks": [{"en": "paper lanterns swaying", "quote": "紙燈籠在風裡搖"}]}

SCAN1 = {"characters": [JIE, QING], "locations": [ARCADE1], "mentioned_only": []}
SCAN1_BOSS = dict(SCAN1, characters=SCAN1["characters"] + [
    {"name": "老闆娘", "aliases": [], "role": "櫃台後面擦杯子", "looks": [], "outfits": []}])
SCAN2 = {"characters": [dict(JIE, looks=[], outfits=[]), dict(QING, looks=[])], "locations": [ARCADE2], "mentioned_only": []}
SCAN3 = {"characters": [dict(JIE, looks=[], outfits=[]), dict(QING, looks=[])], "locations": [ARCADE3], "mentioned_only": []}
SCAN4 = {"characters": [{"name": "阿杰", "aliases": [], "role": "離開", "looks": [], "outfits": []},
                        {"name": "小晴", "aliases": [], "role": "離開", "looks": [], "outfits": []}],
         "locations": [{"name": "拱廊", "aliases": [], "role": "離開", "looks": []}], "mentioned_only": []}

CARD_JIE = {"id": "jie", "name": "阿杰", "aliases": [],
            "look_en": "A 22-year-old East Asian man with short, unruly black hair, a square jaw and a lean build",
            "outfits": {"default": "He wears a faded gray hooded sweatshirt over a white T-shirt, dark jeans and worn sneakers.",
                        "rain": "He wears a soaked yellow raincoat over dark trousers."},
            "outfit_notes": {"default": "日常", "rain": "下雨天"}, "summary": "愛逞強的大學生。",
            "invented": ["年齡與種族（原文沒寫）"], "conflicts": []}
CARD_QING = {"id": "qing", "name": "小晴", "aliases": ["晴"],
             "look_en": "A 21-year-old East Asian woman with a black bob, black-rimmed glasses and a slim build",
             "outfits": {"default": "She wears a green apron over a white blouse and a long gray skirt."},
             "outfit_notes": {"default": "書店制服"}, "summary": "書店的店員。", "invented": [], "conflicts": []}
CARD_ARCADE = {"id": "arcade", "name": "拱廊", "aliases": [],
               "look_en": "A narrow covered shopping arcade with a glass roof, small shuttered shops on both sides and hanging paper lanterns",
               "summary": "老商店街。", "invented": [], "conflicts": []}

# 假回覆用提示詞裡的「## 本章：第NN章」和「名字：…」來挑，和呼叫順序無關（續跑、--force、不同 --upto 都接得上）
SCANS = [("## 本章：第%02d章" % n, scan) for n, scan in ((1, SCAN1), (2, SCAN2), (3, SCAN3), (4, SCAN4))]
CARDS = [("名字：阿杰", CARD_JIE), ("名字：小晴", CARD_QING), ("名字：拱廊", CARD_ARCADE)]


class Fake:
    """依提示詞內容回覆（掃描看章號、成卡看證據裡的名字）；記下每次的 messages。"""

    def __init__(self, scans=None, cards=None):
        self.scans, self.cards = scans or SCANS, cards or CARDS
        self.calls = []

    def reply(self, messages):
        prompt = messages[1]["content"] if len(messages) > 1 else ""
        table = self.scans if "## 本章：" in prompt else self.cards
        for marker, value in table:
            if marker in prompt:
                return value
        raise AssertionError("假 provider 沒有對應的回覆：%s" % prompt[-120:])

    def chat_json(self, prov, messages, **kw):
        self.calls.append(json.loads(json.dumps(messages)))
        text = js(self.reply(messages))
        return llm.parse_json(text), llm.Reply(text=text, usage={"prompt_tokens": 100, "completion_tokens": 50},
                                               finish="stop")


def make_project(tmp_path, chapters, name="comic"):
    root = tmp_path / name
    (root / "bible" / "characters").mkdir(parents=True)
    (root / "bible" / "locations").mkdir(parents=True)
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    source = root / "source"
    source.mkdir()
    for n, text in chapters:
        (source / ("第%02d章.md" % n)).write_text(text, encoding="utf-8")
    return Project(root)


@pytest.fixture
def proj(tmp_path):
    return make_project(tmp_path, ((1, CH1), (2, CH2), (3, CH3), (4, CH4)))


@pytest.fixture
def one_chapter(tmp_path):
    return make_project(tmp_path, ((1, CH1),), name="one")


@pytest.fixture
def two_chapters(tmp_path):
    return make_project(tmp_path, ((1, CH1_BOSS), (2, CH2)), name="two")


def reverser(proj, fake=None, **kw):
    fake = fake or Fake()
    return reverse.Reverser(proj, prov={"id": "fake"}, chat_json=fake.chat_json, **kw), fake


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def chapter_sources(count=7, chars=100):
    return [{"n": n, "label": "ch%03d" % n, "text": "字" * chars} for n in range(1, count + 1)]


# ---- 分批與預算 --------------------------------------------------------------------
def test_plan_batches_caps_at_three_chapters():
    sources = chapter_sources()
    assert reverse.MAX_PER_BATCH == 3
    assert reverse.plan_batches(sources) == [[1, 2, 3], [4, 5, 6], [7]]
    assert reverse.plan_batches(sources, upto=4) == [[1, 2, 3], [4]]
    assert reverse.plan_batches(sources, start=5) == [[5, 6, 7]]
    assert reverse.plan_batches(sources, upto=3, start=9) == []


def test_plan_batches_splits_by_budget_and_never_returns_empty_batches():
    sources = chapter_sources(chars=100)                      # 100 個中文字 ≈ 120 token
    two = reverse.plan_batches(sources, budget=250, out_reserve=0)
    assert two == [[1, 2], [3, 4], [5, 6], [7]]
    tiny = reverse.plan_batches(sources, budget=1, out_reserve=8192)   # 可用的輸入空間是負的
    assert tiny == [[n] for n in range(1, 8)] and all(batch for batch in tiny)


# ---- 跑一輪：抽取 → 累積 → 草稿 -----------------------------------------------------
def test_run_extracts_accumulates_and_writes_batch_files(proj):
    rev, fake = reverser(proj)
    result = rev.run()
    assert result == {"chapters": 4, "batches": 2, "scanned": 4, "skipped": 0,
                      "drafts": ["jie", "qing", "arcade"], "rare": []}
    assert len(fake.calls) == 7

    batch = read_json(proj.root / "build" / "reverse" / "batches" / "第001-003章.json")
    assert batch["chapters"] == [1, 2, 3] and [s["chapter"] for s in batch["scans"]] == [1, 2, 3]
    assert (proj.root / "build" / "reverse" / "batches" / "第004-004章.json").is_file()

    acc = read_json(rev.accumulated_path())
    assert acc["chapters"] == [1, 2, 3, 4]
    assert acc["characters"]["阿杰"]["chapters"] == [1, 2, 3, 4]
    assert "unruly short hair" in acc["characters"]["阿杰"]["looks"]
    assert acc["characters"]["小晴"]["looks"] == ["black-rimmed glasses"]
    assert acc["locations"]["拱廊"]["chapters"] == [1, 2, 3, 4]

    state = read_json(rev.state_path())
    assert state["batches"] == 2 and state["scanned"] == 4 and state["skipped"] == 0
    assert state["stopped"] is False and state["chapters"] == [1, 2, 3, 4]


def test_drafts_have_english_look_en_and_pass_lint(proj):
    rev, _ = reverser(proj)
    rev.run()
    meta, body = read_front_matter(proj.root / "bible" / "drafts" / "characters" / "jie.md")
    assert meta["id"] == "jie" and meta["name"] == "阿杰" and meta["status"] == "draft"
    assert meta["look_en"] == CARD_JIE["look_en"]
    assert not re.search(r"[\u4e00-\u9fff]", meta["look_en"])          # look_en 是英文
    assert meta["outfits"]["default"].startswith("He wears") and meta["outfits"]["rain"] == CARD_JIE["outfits"]["rain"]
    assert "待確認" in body and "那頭亂翹的短髮" in body
    assert (proj.root / "bible" / "drafts" / "locations" / "arcade.md").is_file()
    assert not list((proj.root / "bible" / "characters").glob("*.md"))   # 沒寫進 bible/characters
    assert "jie" not in Project(proj.root).characters
    assert [i for _, _, issues in bible.lint(proj) for i in issues if i.level == "error"] == []


def test_run_upto_stops_at_that_chapter(proj):
    rev, fake = reverser(proj)
    result = rev.run(upto=2)
    assert result["chapters"] == 2 and result["batches"] == 1 and result["scanned"] == 2
    assert len(fake.calls) == 5                                        # 2 次掃描 ＋ 3 張卡
    assert read_json(rev.accumulated_path())["chapters"] == [1, 2]
    assert (proj.root / "build" / "reverse" / "batches" / "第001-002章.json").is_file()


# ---- 續跑 --------------------------------------------------------------------------
def test_rerun_skips_completed_chapters_without_model_calls(proj):
    rev, fake = reverser(proj)
    rev.run()
    assert len(fake.calls) == 7
    rev2, fake2 = reverser(proj)
    result = rev2.run()
    assert fake2.calls == []
    assert result == {"chapters": 4, "batches": 0, "scanned": 0, "skipped": 4, "drafts": [], "rare": []}
    assert read_json(rev2.state_path())["skipped"] == 4


def test_run_rescans_only_the_chapter_whose_scan_cache_is_missing(proj):
    """中間那一章的掃描快取不見了：不能因為「後面的章完成了」就永遠跳過它。"""
    rev, fake = reverser(proj)
    rev.run()
    (proj.root / "build" / "bible" / "scan" / "ch003.json").unlink()
    rev2, fake2 = reverser(proj)
    result = rev2.run()
    assert result == {"chapters": 4, "batches": 1, "scanned": 1, "skipped": 3, "drafts": [], "rare": []}
    assert len(fake2.calls) == 1 and "## 本章：第03章" in fake2.calls[0][1]["content"]
    assert read_json(rev2.accumulated_path())["chapters"] == [1, 2, 3, 4]
    assert (proj.root / "build" / "reverse" / "batches" / "第003-003章.json").is_file()


def test_third_run_after_everything_is_done_stays_a_noop(proj):
    rev, _ = reverser(proj)
    rev.run()
    rev2, _ = reverser(proj)
    rev2.run()
    rev3, fake3 = reverser(proj)
    assert rev3.run() == {"chapters": 4, "batches": 0, "scanned": 0, "skipped": 4, "drafts": [], "rare": []}
    assert fake3.calls == []
    assert sorted(p.name for p in (proj.root / "build" / "reverse" / "batches").glob("*.json")) == [
        "第001-003章.json", "第004-004章.json"]


def test_should_stop_after_first_batch_returns_partially_and_resumes(proj):
    flag = {"stop": False}

    def on_event(event):
        if event["kind"] == "saved" and "chapters" in event:          # 自己存的批次檔，不是 scan 的 entities.json
            flag["stop"] = True

    rev, fake = reverser(proj, should_stop=lambda: flag["stop"], on_event=on_event)
    result = rev.run()                                                # 不丟例外
    assert result == {"chapters": 4, "batches": 1, "scanned": 3, "skipped": 0, "drafts": [], "rare": []}
    assert len(fake.calls) == 3
    assert read_json(rev.accumulated_path())["chapters"] == [1, 2, 3]
    assert read_json(rev.state_path())["stopped"] is True
    assert not list((proj.root / "bible" / "drafts" / "characters").glob("*.md"))

    rev2, fake2 = reverser(proj)                                      # 從第 2 批接上
    result2 = rev2.run()
    assert result2 == {"chapters": 4, "batches": 1, "scanned": 1, "skipped": 3,
                       "drafts": ["jie", "qing", "arcade"], "rare": []}
    assert len(fake2.calls) == 4                                      # 第 4 章一次掃描 ＋ 3 張卡
    assert read_json(rev2.accumulated_path())["chapters"] == [1, 2, 3, 4]


def test_force_rescans_everything_and_redrafts(proj):
    rev, _ = reverser(proj)
    rev.run()
    rev2, fake2 = reverser(proj, force=True)
    result = rev2.run()
    assert result == {"chapters": 4, "batches": 2, "scanned": 4, "skipped": 0,
                      "drafts": ["jie", "qing", "arcade"], "rare": []}
    assert len(fake2.calls) == 7
    assert read_json(rev2.accumulated_path())["chapters"] == [1, 2, 3, 4]


# ---- 成卡門檻：單章專案也要有卡片 ------------------------------------------------------
def test_single_chapter_project_still_drafts_cards(one_chapter):
    """只有 1 章的專案：門檻降到 1，不然所有角色都會落進 rare，什麼草稿都沒有。"""
    rev, fake = reverser(one_chapter)
    result = rev.run()
    assert result["chapters"] == 1 and result["batches"] == 1 and result["scanned"] == 1
    assert result["drafts"] == ["jie", "qing", "arcade"] and result["rare"] == []
    assert len(fake.calls) == 4                                        # 1 次掃描 ＋ 3 張卡
    meta, _ = read_front_matter(one_chapter.root / "bible" / "drafts" / "characters" / "jie.md")
    assert meta["look_en"] == CARD_JIE["look_en"] and meta["outfits"]["default"].startswith("He wears")
    assert [i for _, _, issues in bible.lint(one_chapter) for i in issues if i.level == "error"] == []


def test_two_chapters_keep_the_two_chapter_rule(two_chapters):
    """2 章以上仍照既有規則：只出現 1 章的角色列進 rare、不成卡。"""
    rev, fake = reverser(two_chapters, Fake(scans=[("## 本章：第01章", SCAN1_BOSS), ("## 本章：第02章", SCAN2)]))
    result = rev.run()
    assert result["chapters"] == 2 and result["batches"] == 1 and result["scanned"] == 2
    assert result["drafts"] == ["jie", "qing", "arcade"]               # 兩章都出現的照樣成卡
    assert result["rare"] == ["老闆娘"]                                # 只出現在第 1 章 → 不成卡
    assert len(fake.calls) == 5                                        # 2 次掃描 ＋ 3 張卡（沒有老闆娘的卡）
    assert sorted(x.stem for x in (two_chapters.root / "bible" / "drafts" / "characters").glob("*.md")) == ["jie", "qing"]


def test_min_chapters_flag_lets_one_chapter_characters_become_cards(two_chapters):
    """造卡捷徑（D1）：--min-chapters 1 讓只出現一章的配角也成卡（預設仍要 2 章）。"""
    boss_card = {"id": "laobanniang", "name": "老闆娘", "aliases": [],
                 "sections": {"head": ["A 45-year-old East Asian woman", "short permed black hair"],
                              "body": ["a sturdy build"]},
                 "outfits": {"default": {"top": ["a red apron over a white shirt"], "bottom": ["dark trousers"]}},
                 "summary": "小吃店老闆娘。", "invented": ["年齡（原文沒寫）"], "conflicts": []}
    fake = Fake(scans=[("## 本章：第01章", SCAN1_BOSS), ("## 本章：第02章", SCAN2)],
                cards=CARDS + [("老闆娘", boss_card)])
    rev, fake = reverser(two_chapters, fake)
    result = rev.run(min_chapters=1)
    assert result["drafts"] == ["jie", "qing", "laobanniang", "arcade"] and result["rare"] == []
    assert len(fake.calls) == 6                                        # 2 次掃描 ＋ 4 張卡（多了老闆娘）
    names = sorted(x.stem for x in (two_chapters.root / "bible" / "drafts" / "characters").glob("*.md"))
    assert "laobanniang" in names                                      # 只出現第 1 章的老闆娘也成卡了


# ---- 草稿 → 定案 → 編譯 -------------------------------------------------------------
def test_accepted_drafts_compile_into_a_one_panel_page(proj):
    rev, _ = reverser(proj)
    rev.run()
    moved = bible.accept(proj, ["jie", "arcade"])
    assert [cid for _kind, cid, _path in moved] == ["jie", "arcade"]
    project = Project(proj.root)
    storyboard = {"pages": [{"page": 1, "template": "1", "panels": [{
        "slot": 1, "shot": "medium", "location": "arcade", "scene": "A young man stands under the lanterns.",
        "characters": [{"id": "jie", "outfit": "rain", "pose": "Closing a folding umbrella",
                        "expression": "Annoyed", "box": [0.2, 0.1, 0.8, 1]}]}]}]}
    job = compile_chapter(project, storyboard)[0]
    caption = job["layout"]["items"][1]["caption"]
    assert CARD_JIE["look_en"] + "." in caption and "soaked yellow raincoat" in caption


# ---- CLI ---------------------------------------------------------------------------
@pytest.fixture
def cli():
    spec = importlib.util.spec_from_file_location("tools_reverse", ROOT / "tools" / "reverse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_dry_run_prints_the_plan_and_calls_no_model(proj, cli, capsys):
    assert cli.main([str(proj.root), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "分成 2 批" in out and "第 1 批：第 1～3 章" in out and "第 2 批：第 4 章" in out
    assert not (proj.root / "build").exists()                         # 沒有寫任何檔案


def test_cli_dry_run_json_is_one_parseable_line(proj, cli, capsys):
    assert cli.main([str(proj.root), "--dry-run", "--upto", "3", "--json"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["ok"] is True and data["mode"] == "dry-run" and data["batches"] == [[1, 2, 3]]
    assert data["upto"] == 3 and data["chapters"] == 4


def test_cli_bad_project_exits_2_with_a_chinese_message(tmp_path, cli, capsys):
    code = cli.main([str(tmp_path / "沒有這個專案")])
    captured = capsys.readouterr()
    assert code == 2
    assert "錯誤：" in captured.err and "不是漫畫專案資料夾" in captured.err
    assert "Traceback" not in captured.err and "Traceback" not in captured.out


def test_cli_bad_project_json_exits_2_with_one_json_line(tmp_path, cli, capsys):
    assert cli.main([str(tmp_path / "沒有這個專案"), "--json"]) == 2
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1 and json.loads(lines[0])["ok"] is False
    assert "找不到" in captured.err or "不是漫畫專案資料夾" in captured.err
