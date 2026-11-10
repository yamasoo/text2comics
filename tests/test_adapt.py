"""S5：文字端提示詞（改編規劃 → 劇本 → 分鏡）。模型用腳本化的假回覆，不連外網、不需要金鑰；
最後一項透過 test_llm 的假伺服器走一次真正的 llm.chat_json。
執行：python -m pytest tests/test_adapt.py
"""
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from t2c import adapt, check, layout, llm, prompts, script as sc  # noqa: E402
from t2c.compile import compile_chapter  # noqa: E402
from t2c.project import Project  # noqa: E402
from test_llm import ok_chunks, serve  # noqa: E402,F401  （serve 是 fixture）

SAMPLE = ROOT / "examples" / "sample_comic"
PAGES = layout.load_pages()


# ---- 共用資料 ----------------------------------------------------------------------
def sample_script_page():
    _, body = sc.split_front((SAMPLE / "script" / "ch001.md").read_text(encoding="utf-8"))
    return dict(sc.split_pages(body))[1]


def sample_panels():
    return json.loads((SAMPLE / "storyboard" / "ch001.json").read_text(encoding="utf-8"))["pages"][0]["panels"]


PLAN = {
    "title": "遲到的便當", "summary": "曉雨在頂樓等阿浩，阿浩遲到，帶著不要香菜的便當。",
    "pages": [
        {"page": 1, "template": "5a", "purpose": "建立場景與小衝突", "hook": "紙條",
         "panels": [{"slot": i, "beat": "第 %d 格" % i, "source": "原文", "characters": ["lin"], "location": "rooftop"} for i in range(1, 6)]},
        {"page": 2, "template": "1", "purpose": "收尾", "hook": "",
         "panels": [{"slot": 1, "beat": "兩人一起吃便當", "source": "原文", "characters": ["lin", "hao"]}]},
    ],
    "omitted": [], "unlisted_characters": [],
}

SCRIPT_P2 = """## 第 2 頁（模板 1：全頁大格）

**1 格**｜遠景、鳥瞰｜兩個人並肩坐在水塔陰影下，各自打開便當。阿浩在左、曉雨在右。
- 旁白：這一天的午餐，比平常晚了一點。"""

PANELS_P2 = [{"slot": 1, "shot": "wide", "angle": "bird", "location": "rooftop",
              "scene": "Two people sit side by side in the shadow of a water tank, each opening a lunch box.",
              "characters": [{"id": "hao", "pose": "Sitting cross-legged, opening a lunch box", "expression": "Relieved", "box": [0.1, 0.4, 0.4, 0.9]},
                             {"id": "lin", "pose": "Sitting with knees up, opening a lunch box", "expression": "Calm", "box": [0.6, 0.4, 0.9, 0.9]}],
              "bubbles": [{"kind": "narration", "text": "這一天的午餐，\n比平常晚了一點。", "anchor": [0.85, 0.1]}]}]


class ScriptedLLM:
    """replies：{stage_key: [回覆文字, …]}，依序取用。calls 記下每次的 (stage, messages)。"""

    def __init__(self, replies):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.calls = []

    def _next(self, kw, messages):
        self.calls.append((kw["stage"], copy.deepcopy(messages)))
        queue = self.replies[kw["stage"]]
        return queue.pop(0) if len(queue) > 1 else queue[0]     # 最後一則重複使用

    def chat_json(self, prov, messages, **kw):
        text = self._next(kw, messages)
        return llm.parse_json(text), llm.Reply(text=text, usage={"prompt_tokens": 100, "completion_tokens": 50}, finish="stop")

    def chat(self, prov, messages, **kw):
        return llm.Reply(text=self._next(kw, messages), usage={"prompt_tokens": 100, "completion_tokens": 50}, finish="stop")


def js(obj):
    return json.dumps(obj, ensure_ascii=False)


@pytest.fixture
def proj(tmp_path):
    """範例專案的複本（只有設定、聖經、原著），產出寫在暫存資料夾。"""
    root = tmp_path / "comic"
    root.mkdir()
    shutil.copy(SAMPLE / "project.yaml", root / "project.yaml")
    shutil.copytree(SAMPLE / "bible", root / "bible")
    shutil.copytree(SAMPLE / "source", root / "source")
    return Project(root)


def make(proj, fake, **kw):
    return adapt.Adapter(proj, {"id": "fake"}, chat=fake.chat, chat_json=fake.chat_json, **kw)


def good_replies():
    return {"adapt": [js(PLAN)], "script": [sample_script_page(), SCRIPT_P2],
            "storyboard": [js({"panels": sample_panels()}), js({"panels": PANELS_P2})]}


# ---- 劇本解析 ----------------------------------------------------------------------
def test_parse_sample_script():
    meta, pages, issues = sc.parse_script((SAMPLE / "script" / "ch001.md").read_text(encoding="utf-8"))
    assert meta["chapter"] == 1 and not issues
    page = pages[0]
    assert page.page == 1 and page.template == "5a" and [p.slot for p in page.panels] == [1, 2, 3, 4, 5]
    assert page.panels[0].shots == ["遠景"] and page.panels[0].angles == ["俯視"]
    assert [(l.kind, l.speaker) for l in page.panels[0].lines] == [("narration", ""), ("speech", "曉雨")]
    assert page.panels[1].lines == []                                  # （無台詞）
    assert [l.kind for l in page.panels[2].lines] == ["sfx", "speech"]
    assert page.panels[4].lines[1].kind == "thought"


def test_sample_script_page_passes_strict_check():
    project = Project(SAMPLE)
    page, issues = sc.parse_page(sample_script_page())
    assert not sc.errors(issues + sc.check_page(project, page, 1, "5a", 5, strict=True))


def test_script_marks_and_errors():
    project = Project(SAMPLE)
    raw = """## 第 1 頁（模板 2h）

**1 格**｜中景｜阿浩大喊。
- 阿浩（喊）：等一下！
- 曉雨（小聲）：笨蛋。
- 路人甲：誰啊？
- 曉雨（生氣）：哼。

**3 格**｜飛天景｜描述"""
    page, issues = sc.parse_page(raw)
    kinds = [l.kind for l in page.panels[0].lines]
    assert kinds[:2] == ["shout", "whisper"]
    text = "\n".join(str(i) for i in issues + sc.check_page(project, page, 1, "2h", 2))
    assert "生氣" in text                     # 不認得的語氣
    assert "路人甲" in text                   # 不在聖經
    assert "最多 3 個" in text                # 4 個對話框
    assert "1–2" in text                     # 格編號 1、3
    assert "飛天景" in text                   # 不認得的鏡頭詞


def test_resolve_speaker_by_name_alias_id():
    project = Project(SAMPLE)
    assert {sc.resolve_speaker(project, n) for n in ("林曉雨", "曉雨", "lin")} == {"lin"}
    assert sc.resolve_speaker(project, "阿浩") == "hao" and sc.resolve_speaker(project, "陌生人") is None


def test_fidelity_report():
    source = (SAMPLE / "source" / "ch001.txt").read_text(encoding="utf-8")
    _, pages, _ = sc.parse_script((SAMPLE / "script" / "ch001.md").read_text(encoding="utf-8"))
    rep = sc.fidelity(source, pages)
    assert rep["dialogue_lines"] == 5 and rep["dialogue_found"] == 5     # 範例劇本的台詞都來自原著（不計標點）
    assert rep["source_quotes_missing"] == ["您撥的電話暫時無人接聽"]        # 這句只在原著
    assert "原著有、劇本沒有" in sc.fidelity_markdown(rep)


# ---- 分鏡檢查 ----------------------------------------------------------------------
def test_sample_storyboard_passes_all_checks():
    project = Project(SAMPLE)
    panels = sample_panels()
    page, _ = sc.parse_page(sample_script_page())
    issues = check.check_page_panels(project, 1, "5a", panels, PAGES) + check.check_against_script(project, 1, panels, page)
    assert not sc.errors(issues), issues
    assert any("遠景" in str(i) for i in issues if i.level == "warn")     # 鏡頭不一致只提醒


def test_prompt_example_passes_its_own_rules(tmp_path):
    """提示詞裡的範例本身要能通過檢查，不然等於教模型犯錯。"""
    root = tmp_path / "ex"
    (root / "bible" / "characters").mkdir(parents=True)
    (root / "bible" / "locations").mkdir(parents=True)
    (root / "project.yaml").write_text("title: t\nstyle: manga\n", encoding="utf-8")
    for cid, name, look in (("jie", "阿杰", "A young man"), ("qing", "小晴", "A young woman")):
        (root / "bible" / "characters" / ("%s.md" % cid)).write_text("---\nid: %s\nname: %s\nlook_en: %s\n---\n" % (cid, name, look), encoding="utf-8")
    project = Project(root)
    page, issues = sc.parse_page(prompts.EXAMPLE_SCRIPT)
    assert not sc.errors(issues + sc.check_page(project, page, 3, "2h", 2))
    panels = prompts.EXAMPLE_STORYBOARD["panels"]
    found = check.check_page_panels(project, 3, "2h", panels, PAGES) + check.check_against_script(project, 3, panels, page)
    assert not found, found
    compile_chapter(project, {"pages": [{"page": 3, "template": "2h", "panels": panels}]}, PAGES)


def _bad(mutate):
    project = Project(SAMPLE)
    panels = sample_panels()
    mutate(panels)
    page, _ = sc.parse_page(sample_script_page())
    issues = check.check_page_panels(project, 1, "5a", panels, PAGES) + check.check_against_script(project, 1, panels, page)
    return "\n".join(str(i) for i in sc.errors(issues))


@pytest.mark.parametrize("mutate, expect", [
    (lambda p: p[0].__setitem__("scene", "曉雨坐在屋頂。"), "要寫英文"),
    (lambda p: p[0].__setitem__("scene", "A girl with long black hair sits."), "外觀只能由視覺聖經"),
    (lambda p: p[0]["characters"][0].__setitem__("pose", "She wears a red coat"), "服裝"),
    (lambda p: p[0]["characters"][0].__setitem__("outfit", "swimsuit"), "沒有服裝"),
    (lambda p: p[0]["characters"][0].__setitem__("box", [0.5, 0.5, 0.4, 0.9]), "左上小於右下"),
    (lambda p: p[0]["characters"][0].__setitem__("box", [100, 200, 300, 400]), "0–1"),
    (lambda p: p[0].__setitem__("location", "moon"), "bible/locations"),
    (lambda p: p[0].__setitem__("shot", "medium_wide"), "shot"),
    (lambda p: p[0]["bubbles"][1].__setitem__("anchor", [1.5, 0.2]), "anchor"),
    (lambda p: p[0]["bubbles"][1].__setitem__("kind", "yell"), "不認得"),
    (lambda p: p[0]["bubbles"][0].__setitem__("speaker", "lin"), "旁白不要寫 speaker"),
    (lambda p: p[4]["characters"].pop(1), "不在這一格的 characters"),
    (lambda p: p[2]["bubbles"][0].__setitem__("text", "抱歉！\n排隊排到一半\n被教授抓去搬東西！"), "逐字照劇本"),
    (lambda p: p[2]["bubbles"][0].__setitem__("text", "對不起！排隊排到一半被教授抓去搬東西！"), "加換行"),
    (lambda p: p[4]["bubbles"][1].__setitem__("kind", "speech"), "kind 要是 thought"),
    (lambda p: p[0]["bubbles"][0].__setitem__("kind", "speech"), "kind 要是 narration"),
    (lambda p: p[3]["bubbles"][0].__setitem__("kind", "thought"), "speech、shout 或 whisper"),
    (lambda p: p[4]["bubbles"].pop(), "一一對應"),
    (lambda p: p[2].__setitem__("sfx", []), "狀聲詞要和劇本一致"),
    (lambda p: p.pop(), "slot 要依序"),
    (lambda p: p[3].__setitem__("objects", [{"caption": "便當"}]), "objects"),
])
def test_storyboard_errors_are_reported(mutate, expect):
    assert expect in _bad(mutate)


def test_all_errors_reported_at_once():
    def many(p):
        p[0]["scene"] = "中文"
        p[3]["characters"][0]["outfit"] = "swimsuit"
        p[4]["bubbles"][0]["text"] = "改掉的台詞"
    text = _bad(many)
    assert "第 1 頁第 1 格" in text and "第 1 頁第 4 格" in text and "第 1 頁第 5 格" in text


def test_column_rule_allows_short_and_broken_lines():
    assert not check.column_issues("妳上次說的，不要香菜。", "speech", "x")
    assert not check.column_issues("對不起！\n排隊排到一半\n被教授抓去搬東西！", "shout", "x")
    assert check.column_issues("這是一句非常非常長而且完全沒有換行的台詞", "speech", "x")
    assert not check.column_issues("十二點四十分，天氣晴朗無雲。", "narration", "x")


def test_plan_check():
    project = Project(SAMPLE)
    assert not check.check_plan(project, PLAN, PAGES)
    assert "剛好" not in "".join(map(str, check.check_plan(project, PLAN, PAGES, want_pages=2)))
    bad = copy.deepcopy(PLAN)
    bad["pages"][0]["template"] = "9z"
    bad["pages"][1]["page"] = 5
    bad["pages"][1]["panels"][0]["characters"] = ["ghost"]
    text = "\n".join(map(str, check.check_plan(project, bad, PAGES, want_pages=3)))
    assert "9z" in text and "依序是 2" in text and "ghost" in text and "共 3 頁" in text


# ---- 提示詞 ------------------------------------------------------------------------
def test_template_catalog_lists_every_template_with_shapes():
    text = prompts.template_catalog(PAGES)
    for key, tpl in PAGES["templates"].items():
        assert "模板 %s" % key in text and "共 %d 格" % len(tpl["panels"]) in text
    assert "1 格 上右·" in text                      # 右翻：第 1 格在右上
    assert prompts.panel_shapes(PAGES, "1")[0][1] == "略直"   # B5 全頁格：寬 / 高 ≈ 0.8


def test_prompts_shape_and_cacheable_prefix(proj):
    source = proj.load_source(1)
    plan_msgs = prompts.plan_messages(proj, source, PAGES, want_pages=2)
    assert [m["role"] for m in plan_msgs] == ["system", "user"]
    assert "剛好 **2 頁**" in plan_msgs[1]["content"] and "又不接" in plan_msgs[1]["content"]
    s1 = prompts.script_messages(proj, source, PLAN, PLAN["pages"][0], PAGES)[1]["content"]
    s2 = prompts.script_messages(proj, source, PLAN, PLAN["pages"][1], PAGES, prev_script="上一頁")[1]["content"]
    cut = s1.index("## 本頁任務")
    assert s1[:cut] == s2[:cut]                      # 同階段的前綴一樣，快取才會生效
    assert "又不接" in s1 and "第 2 頁（模板 1：全頁大格）" in s2 and "上一頁" in s2
    sb = prompts.storyboard_messages(proj, sample_script_page(), 1, "5a", PAGES)[1]["content"]
    assert "又不接" in sb and "您撥的電話" not in sb   # 分鏡只看劇本，不看原著
    assert "look_en" not in sb and "shoulder-length" in sb        # 給外觀只供辨識
    for text in (plan_msgs[1]["content"], s1, sb):
        assert "像素" not in text or "不准寫像素" in text


def test_repair_message_lists_all_issues():
    msg = prompts.repair_message([sc.Issue("error", "第 1 頁第 2 格", "甲"), sc.Issue("error", "", "乙")])
    assert msg["role"] == "user" and "1. 第 1 頁第 2 格：甲" in msg["content"] and "2. 乙" in msg["content"]


def test_load_source_skips_front_matter(proj):
    (proj.root / "source" / "ch002.md").write_text("---\ntitle: x\n---\n正文。\n", encoding="utf-8")
    assert proj.load_source(2) == "正文。"
    with pytest.raises(Exception, match="找不到原著"):
        proj.load_source(9)


# ---- 流程 --------------------------------------------------------------------------
def test_full_pipeline_writes_compilable_storyboard(proj):
    fake = ScriptedLLM(good_replies())
    events = []
    ad = make(proj, fake, on_event=events.append)
    plan, text, report, sb = ad.run_all(1)
    assert proj.plan_path(1).is_file() and plan["title"] == "遲到的便當" and plan["chapter"] == 1
    meta, pages, issues = sc.parse_script(proj.script_path(1).read_text(encoding="utf-8"))
    assert meta["pages"] == 2 and meta["source"] == "source/ch001.txt" and [p.page for p in pages] == [1, 2] and not issues
    saved = proj.load_storyboard(1)
    assert saved == sb and [p["template"] for p in saved["pages"]] == ["5a", "1"]
    assert saved["pages"][1]["panels"][0]["id"] == "p002_k1"
    jobs = compile_chapter(proj, saved)
    assert len(jobs) == 6
    assert report["dialogue_found"] == report["dialogue_lines"]
    assert (proj.root / "build" / "adapt" / "ch001_fidelity.md").is_file()
    assert [c[0] for c in fake.calls] == ["adapt", "script", "script", "storyboard", "storyboard"]
    assert ad.usage["calls"] == 5 and ad.usage["prompt_tokens"] == 500
    assert sum(1 for e in events if e["kind"] == "saved") == 3
    # 第 2 頁的劇本提示詞帶了第 1 頁；第 2 頁分鏡帶了第 1 頁的畫面摘要
    assert "又不接" in fake.calls[2][1][1]["content"].split("## 本頁任務")[1]
    assert "Noon sunlight" in fake.calls[4][1][1]["content"].split("## 本頁任務")[1]


def test_storyboard_repair_round_sends_all_errors(proj):
    bad = sample_panels()
    bad[0]["scene"] = "曉雨坐在屋頂。"
    bad[2]["bubbles"][0]["text"] = "抱歉！"
    bad[4]["characters"].pop(1)
    bad[0]["id"] = "whatever"
    bad[0]["extra"] = 1
    replies = good_replies()
    replies["storyboard"] = [js({"panels": bad}), js({"panels": sample_panels()}), js({"panels": PANELS_P2})]
    fake = ScriptedLLM(replies)
    events = []
    ad = make(proj, fake, on_event=events.append)
    ad.run_plan(1)
    ad.run_script(1)
    sb = ad.run_storyboard(1)
    repair = fake.calls[4][1]
    assert [m["role"] for m in repair] == ["system", "user", "assistant", "user"]
    assert repair[2]["content"] == js({"panels": bad})
    for word in ("scene", "逐字照劇本", "不在這一格的 characters"):
        assert word in repair[3]["content"]
    assert sb["pages"][0]["panels"][0]["id"] == "p001_k1" and "extra" not in sb["pages"][0]["panels"][0]
    assert [e["kind"] for e in events].count("fix") == 1
    assert any("extra" in w for w in ad.warnings)


def test_script_repair_and_header_normalized(proj):
    bad_page = sample_script_page().replace("**5 格**", "**6 格**")
    fixed = sample_script_page().replace("## 第 1 頁（模板 5a：上二、中一、下二）", "## 第1頁")
    replies = good_replies()
    replies["script"] = ["```markdown\n" + bad_page + "\n```", fixed, SCRIPT_P2]
    fake = ScriptedLLM(replies)
    ad = make(proj, fake)
    ad.run_plan(1)
    text, _ = ad.run_script(1)
    assert "格編號要依序是 1–5" in fake.calls[2][1][-1]["content"]
    assert "## 第 1 頁（模板 5a：上二中一下二）" in text      # 標題行由程式統一


def test_gives_up_after_max_fix(proj):
    bad = sample_panels()
    bad[0]["scene"] = "中文"
    replies = good_replies()
    replies["storyboard"] = [js({"panels": bad})]
    fake = ScriptedLLM(replies)
    ad = make(proj, fake, max_fix=2)
    ad.run_plan(1)
    ad.run_script(1)
    with pytest.raises(adapt.AdaptError, match="修了 2 次仍有 1 個問題"):
        ad.run_storyboard(1)
    assert [c[0] for c in fake.calls].count("storyboard") == 3
    assert (proj.root / "build" / "adapt" / "ch001" / "storyboard_第 1 頁.txt").is_file()
    assert not proj.storyboard_path(1).exists()


def test_does_not_overwrite_without_force(proj):
    ad = make(proj, ScriptedLLM(good_replies()))
    ad.run_plan(1)
    with pytest.raises(adapt.AdaptError, match="已經存在"):
        ad.run_plan(1)
    ad.run_plan(1, force=True)


def test_missing_prerequisites(proj):
    ad = make(proj, ScriptedLLM(good_replies()))
    with pytest.raises(Exception, match="先執行 plan"):
        ad.run_script(1)
    with pytest.raises(adapt.AdaptError, match="先執行 script"):
        ad.run_storyboard(1)
    with pytest.raises(adapt.AdaptError, match="無法只重寫部分頁"):
        ad.plan_prompt(1) and ad.run_plan(1) and ad.run_script(1, only_pages=[2])


def test_regenerate_one_page_keeps_human_edits(proj):
    fake = ScriptedLLM(good_replies())
    ad = make(proj, fake)
    ad.run_all(1)
    path = proj.script_path(1)
    path.write_text(path.read_text(encoding="utf-8").replace("頂樓全景", "頂樓全景（人工修改）"), encoding="utf-8")
    fake.replies["script"] = [SCRIPT_P2.replace("比平常晚了一點", "比平常晚")]
    ad.run_script(1, only_pages=[2])
    text = path.read_text(encoding="utf-8")
    assert "人工修改" in text and "比平常晚。" in text and "比平常晚了一點" not in text
    # 分鏡也只重做第 2 頁；第 1 頁保持原樣
    before = proj.load_storyboard(1)["pages"][0]
    fake.replies["storyboard"] = [js({"panels": [dict(PANELS_P2[0], bubbles=[{"kind": "narration", "text": "這一天的午餐，\n比平常晚。", "anchor": [0.85, 0.1]}])]})]
    ad.run_storyboard(1, only_pages=[2])
    sb = proj.load_storyboard(1)
    assert sb["pages"][0] == before and sb["pages"][1]["panels"][0]["bubbles"][0]["text"].endswith("比平常晚。")


def test_storyboard_follows_human_edited_script(proj):
    """人改了劇本的台詞，分鏡若還用舊台詞就會被擋下來回修。"""
    fake = ScriptedLLM(good_replies())
    ad = make(proj, fake)
    ad.run_plan(1)
    ad.run_script(1)
    path = proj.script_path(1)
    path.write_text(path.read_text(encoding="utf-8").replace("我已經不餓了。", "我不餓。"), encoding="utf-8")
    new = sample_panels()
    new[3]["bubbles"][0]["text"] = "我不餓。"
    fake.replies["storyboard"] = [js({"panels": sample_panels()}), js({"panels": new}), js({"panels": PANELS_P2})]
    sb = ad.run_storyboard(1)
    assert sb["pages"][0]["panels"][3]["bubbles"][0]["text"] == "我不餓。"
    assert "我不餓。" in fake.calls[-2][1][-1]["content"]


def test_wrapped_output_is_tolerated(proj):
    replies = good_replies()
    replies["storyboard"] = [js({"pages": [{"page": 1, "panels": sample_panels()}]}), js(PANELS_P2)]
    ad = make(proj, ScriptedLLM(replies))
    ad.run_plan(1)
    ad.run_script(1)
    assert len(ad.run_storyboard(1)["pages"]) == 2


def test_stop_before_calling(proj):
    ad = make(proj, ScriptedLLM(good_replies()), should_stop=lambda: True)
    with pytest.raises(llm.Cancelled):
        ad.run_plan(1)


def test_stage_keys_pick_providers(proj):
    seen = []
    fake = ScriptedLLM(good_replies())
    ad = adapt.Adapter(proj, prov_for=lambda key: seen.append(key) or {"id": key}, chat=fake.chat, chat_json=fake.chat_json)
    ad.run_all(1)
    assert set(seen) == {"adapt", "script", "storyboard"}


def test_context_overflow_is_reported(proj):
    ad = adapt.Adapter(proj, {"id": "tiny", "context_tokens": 500, "max_output": 100},
                       chat=ScriptedLLM(good_replies()).chat, chat_json=ScriptedLLM(good_replies()).chat_json)
    with pytest.raises(llm.LLMError, match="提示詞太長"):
        ad.run_plan(1)


def test_plan_through_real_llm_client(proj, serve):  # noqa: F811
    """走一次真正的 llm.chat_json（假伺服器、SSE 串流），確認請求帶 JSON 模式、回覆能存成規劃。"""
    text = js(PLAN)
    f = serve([{"chunks": ok_chunks(text[:40], text[40:])}])
    p = {"id": "t", "base_url": f.url, "model": "m", "key_env": "", "context_tokens": 64000, "max_output": 4000, "json_mode": True}
    plan = adapt.Adapter(proj, p).run_plan(1)
    assert plan["pages"][1]["template"] == "1"
    body = f.requests[0][1]
    assert body["response_format"] == {"type": "json_object"} and "又不接" in body["messages"][1]["content"]
