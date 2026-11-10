"""步驟 2：分段編輯器存檔端點 POST /api/bible/card/sections 與相容層。

用 examples/sample_comic（舊格式 look_en 的卡片）當底，確認：
1. 存一次分段就把舊卡片轉成分段、本文照舊；
2. 定案卡片的分段有錯要擋（不要寫壞的卡片）；
3. 草稿可以先存，錯誤列成提醒；
4. GET /api/bible 的清單對分段卡片回得出整段外觀（look.look_en 接起來）。
執行：python -m pytest tests/test_sections_api.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ui import client, post, sample_project  # noqa: E402
from t2c import workspace  # noqa: E402


def sections_body(root, **extra):
    body = {
        "project": root, "kind": "character", "id": "hao", "draft": False,
        "sections": {"head": ["A 20-year-old East Asian young man", "messy short black hair"],
                     "body": ["a tall lanky build"], "upper": [], "lower": [],
                     "accessory": ["thin rectangular glasses"]},
        "outfits": {"default": {"top": ["a loose hooded sweatshirt"], "bottom": ["cargo pants"], "set": [],
                                "notes": "日常"}},
    }
    body.update(extra)
    return body


def card_text(root):
    path = Path(root) / "bible" / "characters" / "hao.md"
    return path.read_text(encoding="utf-8")


def test_sections_save_converts_legacy_card_and_keeps_body(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    before = card_text(root)
    body_line = before.split("---", 2)[2].strip().splitlines()[0]
    saved = post("/api/bible/card/sections", sections_body(root))
    assert saved.status_code == 200, saved.json()
    data = saved.json()
    assert data["issues"] == [] and data["stale"] is False
    text = card_text(root)
    assert "sections:" in text and "look_en" not in text and "thin rectangular glasses" in text
    assert body_line in text                                    # 本文（人看的說明）照舊
    card = client.get("/api/bible/card", params={"project": root, "kind": "character", "id": "hao"}).json()
    assert card["text"] == text
    listed = client.get("/api/bible", params={"project": root}).json()["cards"]
    hao = next(c for c in listed if c["id"] == "hao")
    assert hao["look_en"].startswith("A 20-year-old East Asian young man")   # 相容層：分段接回整段


def test_sections_save_blocks_a_broken_confirmed_card(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    before = card_text(root)
    bad = sections_body(root)
    bad["sections"]["head"] = ["A 20-year-old young man wearing a red coat"]     # 服裝寫進 head：規則擋
    refused = post("/api/bible/card/sections", bad)
    assert refused.status_code == 400 and "服裝" in refused.json()["error"]
    assert card_text(root) == before                                            # 壞的沒寫進去


def test_sections_save_allows_drafts_with_issues(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    draft = post("/api/bible/new", {"project": root, "kind": "character", "id": "mei", "name": "小美"})
    assert draft.status_code == 200
    empty = post("/api/bible/card/sections", {"project": root, "kind": "character", "id": "mei", "draft": True,
                                              "sections": {"head": []}, "outfits": {"default": {"top": []}}})
    assert empty.status_code == 200, empty.json()                              # 草稿可以先存
    assert any(i["level"] == "error" for i in empty.json()["issues"])           # 但會列出錯誤


def test_sections_save_refuses_unknown_section_name(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    bad = sections_body(root, sections={"eyes": ["green eyes"]})
    refused = post("/api/bible/card/sections", bad)
    assert refused.status_code == 400 and "不認得的段名" in refused.json()["error"]

def test_all_skipped_render_does_not_update_fingerprints(tmp_path, monkeypatch):
    """force=False 且檔案都在：一張都不畫，就**不要**更新指紋。
    否則舊圖還在、GET /api/bible/stale 卻回 0 格（圖沒重畫，系統說已經跟上新卡片）。"""
    from t2c import comfy, render, settings, stale, workspace
    from test_ui import CFG, SAMPLE

    monkeypatch.setattr(settings, "load", lambda path=None, root=None: dict(CFG, _path="test"))
    monkeypatch.setattr(comfy, "run", lambda base, wf, out, should_stop=None, timeout=1800: b"PNG-DATA")
    proj = workspace.create_project(str(tmp_path / "c"), "", sample=SAMPLE)
    (proj.root / "renders" / "ch001").mkdir(parents=True, exist_ok=True)
    render.render_jobs(proj, 1, render.chapter_jobs(proj, 1), CFG)                  # 第一次：真的畫
    build = proj.root / "build" / "ch001"
    before = {p.name: p.read_bytes() for p in build.glob("*.prompt.json")}
    assert len(before) == 5
    card = proj.root / "bible" / "characters" / "lin.md"
    card.write_text(card.read_text(encoding="utf-8").replace("large determined eyes", "large calm eyes"), encoding="utf-8")
    reopened = workspace.open_project(str(proj.root))
    assert stale.chapter(reopened, 1), "改了卡片，這幾格應該過期"
    written = render.render_jobs(reopened, 1, render.chapter_jobs(reopened, 1), CFG)  # force=False：全部略過
    assert written == []
    after = {p.name: p.read_bytes() for p in build.glob("*.prompt.json")}
    assert after == before                                                            # 指紋沒有被偷改
    assert stale.chapter(reopened, 1), "沒有真的重畫，過期清單不能變成空的"

def test_split_endpoint_proposes_sections_without_writing(tmp_path):
    """舊卡片（只有 look_en）→ 分段草稿：回 sections／outfits，但**不寫檔**（人看過才按儲存）。"""
    proj = sample_project(tmp_path)
    root = str(proj.root)
    before = card_text(root)
    reply = post("/api/bible/card/split", {"project": root, "kind": "character", "id": "hao"})
    assert reply.status_code == 200, reply.json()
    data = reply.json()
    assert data["sections"]["head"] and any("hair" in p for p in data["sections"]["head"])
    assert data["sections"]["body"] and "build" in " ".join(data["sections"]["body"])
    assert data["sections"]["accessory"] and "glasses" in " ".join(data["sections"]["accessory"])
    assert data["outfits"]["default"]["bottom"] and "pants" in " ".join(data["outfits"]["default"]["bottom"])
    assert "規則" in data["note"]
    assert card_text(root) == before                                  # 只有建議，沒有寫檔

