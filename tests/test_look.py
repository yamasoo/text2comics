"""步驟 2：分段卡片（sections）、按鏡頭選段、出圖指紋與過期清單（D1／D2／D4）。

用 examples/sample_comic 當底：把「林曉雨」換成分段卡片，其餘（周子浩）維持舊的 look_en，
順便驗相容層。測試資料就在 tests/data/sections_card.md。
執行：python -m pytest tests/test_look.py
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import bible, compile as t2c_compile, look, stale, workspace  # noqa: E402
from t2c.compile import compile_chapter  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"
SECTIONS_CARD = ROOT / "tests" / "data" / "sections_card.md"


@pytest.fixture()
def proj(tmp_path):
    """從範例複製一份，把 lin 的卡片換成 sections 版本（其餘卡片照舊：相容層）。"""
    copy = tmp_path / "comic"
    shutil.copytree(SAMPLE, copy, ignore=shutil.ignore_patterns("renders", "pages", "build", "out", "picks"))
    (copy / "bible" / "characters" / "lin.md").write_text(SECTIONS_CARD.read_text(encoding="utf-8"), encoding="utf-8")
    return workspace.open_project(str(copy))


def job_of(jobs, panel_id):
    return next(j for j in jobs if j["id"] == panel_id)


def test_sections_card_loads_and_legacy_card_still_works(proj):
    """有 sections 讀得起來、look_en 由五段接起來；只有 look_en 的舊卡片照舊。"""
    lin = proj.characters["lin"]
    assert look.has_sections(lin) and "look_en" not in lin
    text = look.look_en(lin)
    assert text.startswith("A 19-year-old East Asian young woman") and "long legs" in text
    hao = proj.characters["hao"]
    assert not look.has_sections(hao) and hao["look_en"].startswith("A 20-year-old East Asian young man")


def test_shot_decides_which_sections_are_pasted(proj):
    """特寫只貼頭部；中景加上上半身與飾品；大遠景連下半身與下著都貼。"""
    jobs = compile_chapter(proj, proj.load_storyboard(1))
    wide = json.dumps(job_of(jobs, "p001_k1")["layout"], ensure_ascii=False).lower()      # extreme_wide：[lin]
    medium = json.dumps(job_of(jobs, "p001_k4")["layout"], ensure_ascii=False).lower()    # medium：[lin]
    close = json.dumps(job_of(jobs, "p001_k5")["layout"], ensure_ascii=False).lower()     # close：[hao, lin]
    assert "large determined eyes" in close and "long legs" not in close and "pleated skirt" not in close
    assert "narrow shoulders" in medium and "white t-shirt" in medium
    assert "long legs" not in medium and "pleated skirt" not in medium
    assert "long legs" in wide and "pleated skirt" in wide and "hair clip" in wide
    # 舊卡片（hao）不受 shot 影響：整段 look_en 都貼上（k3 是 hao 的中景）
    hao_medium = json.dumps(job_of(jobs, "p001_k3")["layout"], ensure_ascii=False).lower()
    assert "tall lanky build" in close and "tall lanky build" in hao_medium


def test_fingerprint_records_each_part(proj):
    """指紋記的是「這一格用了哪幾段」，所以改下著只會動到全身與遠景。"""
    lin = proj.characters["lin"]
    assert set(look.fingerprint(lin, "close")) == {"head", "accessory"}          # 特寫不貼服裝
    assert "lower" in look.fingerprint(lin, "full") and "outfits.default.bottom" in look.fingerprint(lin, "full")
    before = look.fingerprint(lin, "close")
    lin["sections"]["lower"] = ["very long legs"]                                    # 改「下著」以外的一段
    assert look.fingerprint(lin, "close") == before
    assert look.fingerprint(lin, "full")["lower"] != before.get("lower")


def test_stale_lists_only_the_panels_that_used_that_part(proj):
    """改下半身：只有大遠景／全身那幾格過期，特寫與中景不動（收貨條件）。"""
    jobs = compile_chapter(proj, proj.load_storyboard(1))
    build = proj.out_dir("build", "ch001")
    for job in jobs:                                                                  # 假裝每一格都出過圖
        (build / ("%s.prompt.json" % job["id"])).write_text(
            json.dumps({"id": job["id"], "fingerprint": job["fingerprint"], "explore": job["explore"]}, ensure_ascii=False),
            encoding="utf-8")
    path = proj.root / "bible" / "characters" / "lin.md"
    path.write_text(path.read_text(encoding="utf-8").replace("long legs", "very long legs"), encoding="utf-8")
    reopened = workspace.open_project(str(proj.root))
    panels = stale.chapter(reopened, 1)
    assert [p["id"] for p in panels] == ["p001_k1"]                                   # 只有大遠景（extreme_wide）用到 lower
    assert panels[0]["reasons"][0]["source"] == "lower"
    assert "下半身" in panels[0]["reasons"][0]["message"]


def test_style_change_makes_every_panel_stale(proj):
    """換畫風＝整章過期（D1 的帳單表）。"""
    jobs = compile_chapter(proj, proj.load_storyboard(1))
    old = job_of(jobs, "p001_k4")["fingerprint"]
    proj.config["style_preset"] = "color"
    new = job_of(compile_chapter(proj, proj.load_storyboard(1)), "p001_k4")["fingerprint"]
    reasons = stale.compare(old, new)
    assert any(r["source"] == "style" and "畫風" in r["message"] for r in reasons)


def test_explore_panel_is_skipped_by_stale(proj):
    """探索用（缺卡）不列入過期清單：沒有指紋可比，也沒有東西能重畫成定案。"""
    board = proj.load_storyboard(1)
    panel = next(p for p in board["pages"][0]["panels"] if p["id"] == "p001_k4")
    panel["characters"].append({"id": "nobody", "box": [0.55, 0.1, 0.9, 0.95]})
    jobs = compile_chapter(proj, board)
    job = job_of(jobs, "p001_k4")
    assert job["explore"] == ["nobody"]
    build = proj.out_dir("build", "ch001")
    (build / "p001_k4.prompt.json").write_text(
        json.dumps({"id": "p001_k4", "fingerprint": job["fingerprint"], "explore": job["explore"]}), encoding="utf-8")
    proj.root.joinpath("storyboard", "ch001.json").write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
    assert stale.chapter(workspace.open_project(str(proj.root)), 1) == []


def test_apply_sections_rewrites_frontmatter_and_keeps_body(proj):
    """分段編輯器存檔：frontmatter 換成分段、本文（人看的說明）逐字保留。"""
    before = (proj.root / "bible" / "characters" / "hao.md").read_text(encoding="utf-8")
    body = before.split("---", 2)[2].strip()
    result = bible.apply_sections(proj, "character", "hao",
                                  sections={"head": ["A 20-year-old East Asian young man", "messy short black hair"],
                                            "body": ["a tall lanky build"], "accessory": ["thin rectangular glasses"]},
                                  outfits={"default": {"top": ["a loose hooded sweatshirt"], "bottom": ["cargo pants"]}})
    assert result["issues"] == []
    text = result["text"]
    assert "sections:" in text and "look_en" not in text and "thin rectangular glasses" in text
    assert body.splitlines()[0] in text                                              # 本文還在
    reopened = workspace.open_project(str(proj.root))
    hao = reopened.characters["hao"]
    assert look.has_sections(hao) and look.outfit(hao, "default")["parts"]["bottom"] == ("cargo pants",)
