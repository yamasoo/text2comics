"""微5：角色解析的三個一鍵動作（D9、D10、D11）與探索用的資訊。

POST /api/chapter/character/remap｜extra｜drop；GET /api/chapter/panels 的 unresolved。
用 examples/sample_comic 的影本，先把 lin 的寫法改成對不上的 hynesen 當症狀。
執行：python -m pytest tests/test_character_api.py -q
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ui import client, post, sample_project  # noqa: E402
from t2c import cast, workspace  # noqa: E402


def board_path(root):
    return Path(root) / "storyboard" / "ch001.json"


def board(root):
    return json.loads(board_path(root).read_text(encoding="utf-8"))


def rename_to_bogus(root, old="lin", new="hynesen"):
    """模擬症狀：分鏡把角色的寫法換成對不上的英文拼法（卡片是 lin）。"""
    doc = board(root)
    for page in doc.get("pages") or []:
        for panel in page.get("panels") or []:
            for entry in panel.get("characters") or []:
                if entry.get("id") == old:
                    entry["id"] = new
            for bubble in panel.get("bubbles") or []:
                if bubble.get("speaker") == old:
                    bubble["speaker"] = new
    board_path(root).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return new


def panels(root):
    return client.get("/api/chapter/panels", params={"project": root, "chapter": 1}).json()["panels"]


def test_unresolved_shows_up_in_explore_and_panels(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    rename_to_bogus(root)
    rows = panels(root)
    row = next(p for p in rows if "hynesen" in p["explore"])
    assert row["unresolved"] == [{"id": "hynesen", "suggest": []}]      # 沒有相近的卡片：不亂建議


def test_remap_fixes_the_panel_and_records_the_alias(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    rename_to_bogus(root)
    res = post("/api/chapter/character/remap",
               {"project": root, "chapter": 1, "from": "hynesen", "to": "lin", "remember_alias": True})
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["card"] == "lin" and data["how"] == "id"
    assert data["changed"] and data["aliases"] == ["hynesen"] and data["other_chapters"] == []
    assert all(not p["explore"] for p in panels(root))                  # 不再探索用：可以選圖
    reloaded = workspace.open_project(root)
    assert cast.resolve(reloaded, "hynesen") == ("lin", "alias")        # 別名寫進卡片，下一章也對得上


def test_remap_accepts_a_name_and_refuses_an_unknown_card(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    rename_to_bogus(root)
    assert post("/api/chapter/character/remap",
                {"project": root, "chapter": 1, "from": "hynesen", "to": "nobody"}).status_code == 400
    ok = post("/api/chapter/character/remap",
              {"project": root, "chapter": 1, "from": "hynesen", "to": "林曉雨"})
    assert ok.status_code == 200 and ok.json()["card"] == "lin"


def test_extra_unlocks_the_panel_without_a_card(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    rename_to_bogus(root)
    res = post("/api/chapter/character/extra", {"project": root, "chapter": 1, "from": "hynesen"})
    assert res.status_code == 200, res.json()
    assert res.json()["changed"], "要標到至少一格"
    assert all(not p["explore"] for p in panels(root))
    entries = [entry for page in board(root)["pages"] for panel in page["panels"]
               for entry in panel.get("characters") or [] if entry.get("id") == "hynesen"]
    assert entries and all(entry.get("extra") is True for entry in entries)


def test_extra_refuses_a_character_that_has_a_card(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    res = post("/api/chapter/character/extra", {"project": root, "chapter": 1, "from": "hao"})
    assert res.status_code == 400 and "已經有卡片" in res.json()["error"]


def test_drop_removes_the_character_and_turns_its_lines_into_narration(tmp_path):
    proj = sample_project(tmp_path)
    root = str(proj.root)
    rename_to_bogus(root)
    res = post("/api/chapter/character/drop", {"project": root, "chapter": 1, "from": "hynesen"})
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["changed"] and data["narration"], "改了角色，也把台詞改成旁白"
    doc = board(root)
    assert not [entry for page in doc["pages"] for panel in page["panels"]
                for entry in panel.get("characters") or [] if entry.get("id") == "hynesen"]
    turned = [b for page in doc["pages"] for panel in page["panels"] for b in panel.get("bubbles") or []
              if b.get("kind") == "narration" and not b.get("speaker")]
    assert turned, "說話的對話框要改成旁白（拿掉 speaker、offscreen）"
    assert all(not p["explore"] for p in panels(root))                  # 移除後那一格照樣編譯得過


def test_extra_panel_uses_the_generic_look_and_a_constant_fingerprint(tmp_path):
    """標了 extra 的那一格：通用外觀（不猜長相）、指紋記成常數（不會永遠算過期）。"""
    from t2c.compile import compile_chapter

    proj = sample_project(tmp_path)
    root = str(proj.root)
    rename_to_bogus(root)
    assert post("/api/chapter/character/extra", {"project": root, "chapter": 1, "from": "hynesen"}).status_code == 200
    reloaded = workspace.open_project(root)
    jobs = {job["id"]: job for job in compile_chapter(reloaded, reloaded.load_storyboard(1))}
    job = jobs["p001_k1"]
    assert job["explore"] == [] and job["unresolved"] == []
    captions = [item["caption"] for item in job["layout"]["items"] if item["label"] == "character"]
    assert captions and all("plain generic appearance" in caption for caption in captions)
    assert "extra:hynesen" in job["fingerprint"]["characters"]
    assert job["fingerprint"]["characters"]["extra:hynesen"]["parts"] == {"extra": ""}
