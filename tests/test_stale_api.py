"""步驟 2：過期清單與只重畫過期的格（docs/07_微調簡報.md）。

GET /api/bible/stale、POST /api/task/render 的 stale 參數、GET /api/chapter/panels 的
explore／stale 欄位。模型與 ComfyUI 都用假的（不連外網、不需要 GPU）。
執行：PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_stale_api.py -q
"""
import re
import sys
import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from t2c import comfy, settings, workspace  # noqa: E402

client = TestClient(app_module.app, base_url="http://127.0.0.1")
SAMPLE = ROOT / "examples" / "sample_comic"

CFG = {
    "providers": [{"id": "fake", "type": "openai", "name": "假模型", "base_url": "https://example.invalid", "model": "m",
                   "key_env": "", "context_tokens": 200000, "max_output": 8000}],
    "default_provider": "fake",
    "comfy": {"url": "http://127.0.0.1:1", "workflow": "workflows/moss_layout.api.json",
              "models": {"unet": "u.safetensors", "clip": "c.safetensors", "vae": "v.safetensors"},
              "default_preset": "final", "presets": {"final": {"steps": 25}, "draft": {"steps": 4}}},
    "lettering": {},
}
PANEL_KEYS = {"id", "page", "slot", "gen_size", "cell_size", "seeds", "scene", "characters", "lines", "candidates", "pick"}
STALE_PANEL_KEYS = {"id", "page", "slot", "shot", "files", "reasons"}


# ---- 工具 -------------------------------------------------------------------------

def token():
    html = client.get("/").text
    return re.search(r'name="fe-token" content="([^"]+)"', html).group(1)


def post(path, body):
    return client.post(path, json=body, headers={"X-FE-Token": token()})


def png_bytes(value=128, size=(1000, 800)):
    buffer = BytesIO()
    Image.new("L", size, value).save(buffer, format="PNG")
    return buffer.getvalue()


def wait(job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        data = client.get("/api/jobs/%s" % job_id).json()
        if data.get("status") in ("done", "error", "stopped"):
            return data
        time.sleep(0.05)
    raise AssertionError("任務沒有結束：%s" % job_id)


def render(root, **extra):
    return wait(post("/api/task/render", dict(project=root, chapter=1, **extra)).json()["id"])


def stale(root, chapter=None):
    params = {"project": root}
    if chapter is not None:
        params["chapter"] = chapter
    return client.get("/api/bible/stale", params=params)


def panel_rows(root):
    return {row["id"]: row for row in client.get("/api/chapter/panels", params={"project": root, "chapter": 1}).json()["panels"]}


def files_of(root, pid):
    return sorted(c["file"] for c in panel_rows(root)[pid]["candidates"])


def image_bytes(proj, name):
    return (proj.root / "renders" / "ch001" / name).read_bytes()


def backup_dir(proj):
    return proj.root / "build" / "render" / "backup" / "ch001"


def change_lin_outfit(proj, was="plain white T-shirt", now="plain black T-shirt"):
    """改林曉雨的服裝（卡片改了 → 用到她的格過期；畫風、地點、分鏡都沒動）。"""
    path = proj.root / "bible" / "characters" / "lin.md"
    text = path.read_text(encoding="utf-8")
    assert was in text
    path.write_text(text.replace(was, now), encoding="utf-8")


# ---- fixture ----------------------------------------------------------------------

@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(settings, "load", lambda path=None, root=None: dict(CFG, _path="test"))
    return CFG


@pytest.fixture
def fake_comfy(monkeypatch):
    calls = []

    def run(base, wf, out_id, should_stop=lambda: False, timeout=1800):
        calls.append(wf)
        return png_bytes(40 + len(calls) * 7 % 200)

    monkeypatch.setattr(comfy, "run", run)
    return calls


@pytest.fixture
def comic(tmp_path):
    """從範例新建的專案（不含出圖與 build/，所以還沒有指紋）。"""
    return workspace.create_project(str(tmp_path / "comic"), "", sample=SAMPLE)


# ---- GET /api/bible/stale ---------------------------------------------------------

def test_stale_endpoint_without_fingerprints(comic):
    """沒出過圖（沒有 build/*.prompt.json）＝沒有指紋可比，清單是空的，不是錯誤。"""
    root = str(comic.root)
    assert not (comic.root / "build").exists()
    one = stale(root, 1)
    assert one.status_code == 200
    assert one.json() == {"chapters": [{"chapter": 1, "title": "遲到的便當", "count": 0, "panels": []}], "total": 0}
    everything = stale(root)
    assert everything.status_code == 200 and everything.json() == {"chapters": [], "total": 0}   # 只列有過期的章


def test_stale_endpoint_rejects_bad_project_and_chapter(comic):
    empty = stale("")
    assert empty.status_code == 400 and "專案" in empty.json()["error"]
    missing = stale(str(comic.root.parent / "nope"), 1)
    assert missing.status_code == 400 and missing.json()["error"]
    assert stale(str(comic.root), "abc").status_code == 400
    assert "整數" in stale(str(comic.root), "abc").json()["error"]
    assert stale(str(comic.root), 9).status_code == 400                       # 分鏡裡沒有第 9 章


def test_stale_endpoint_after_render_and_card_change(comic, cfg, fake_comfy):
    """出圖後指紋一致 → 沒有過期；改了卡片 → 只列出用到那個角色的格，並說出改了哪一段。"""
    root = str(comic.root)
    assert render(root)["result"]["text"] == "新出 15 張，略過 0 張（已存在）"
    assert stale(root, 1).json()["total"] == 0
    change_lin_outfit(comic)

    data = stale(root, 1).json()
    assert data["total"] == 3
    row = data["chapters"][0]
    assert (row["chapter"], row["title"], row["count"]) == (1, "遲到的便當", 3)
    assert [p["id"] for p in row["panels"]] == ["p001_k1", "p001_k4", "p001_k5"]   # k2 沒有角色、k3 只有 hao
    first = row["panels"][0]
    assert set(first) == STALE_PANEL_KEYS
    assert (first["page"], first["slot"], first["shot"]) == (1, 1, "extreme_wide")
    assert first["files"] and all(f.startswith("p001_k1_s") and f.endswith(".png") for f in first["files"])
    reason = first["reasons"][0]
    assert reason["source"] == "outfits.default" and reason["level"] == "ok"
    assert "lin" in reason["message"] and "服裝" in reason["message"]
    whole = stale(root).json()
    assert whole["total"] == 3 and [c["chapter"] for c in whole["chapters"]] == [1]


# ---- POST /api/task/render 的 stale ------------------------------------------------

def test_render_stale_only_redraws_stale_panels(comic, cfg, fake_comfy):
    """只送 stale：過期的 3 格用同一批 seed 覆蓋（檔名不變、內容換新），舊圖先備份到 build/render/backup/。"""
    root = str(comic.root)
    assert render(root)["status"] == "done"
    before = {pid: files_of(root, pid) for pid in ("p001_k1", "p001_k2", "p001_k3", "p001_k4", "p001_k5")}
    assert all(len(files) == 3 for files in before.values())
    redrawn = ("p001_k1", "p001_k4", "p001_k5")
    untouched = ("p001_k2", "p001_k3")
    old = {(pid, name): image_bytes(comic, name) for pid, names in before.items() for name in names}
    change_lin_outfit(comic)

    done = render(root, stale=True)
    assert done["status"] == "done", done
    assert done["result"]["text"] == "重畫 3 格（9 張，舊候選備份在 build/render/backup/ch001/）"
    assert {item["key"] for item in done["items"]} == set(redrawn)
    assert len(fake_comfy) == 24                                              # 15 + 3 格 × 3 張
    assert [e["text"] for e in done["log"] if e["text"].startswith("✓ ")]      # 任務事件照既有格式
    after = {pid: files_of(root, pid) for pid in before}
    for pid in untouched:                                                     # 沒過期的格不動
        assert after[pid] == before[pid]
        assert all(image_bytes(comic, name) == old[(pid, name)] for name in before[pid])
    for pid in redrawn:                                                       # 檔名不變（picks 指到的還是同一個檔）
        assert after[pid] == before[pid]
        assert all(image_bytes(comic, name) != old[(pid, name)] for name in before[pid])   # 內容是新圖
    saved = sorted(p.name for p in backup_dir(comic).glob("*.png"))
    assert saved == sorted(name for pid in redrawn for name in before[pid])    # 舊圖先備份
    assert all((backup_dir(comic) / name).read_bytes() == old[(pid, name)] for pid in redrawn for name in before[pid])
    assert "舊候選先備份" in " ".join(entry["text"] for entry in done["log"])
    assert stale(root, 1).json()["total"] == 0                                 # 指紋跟著更新

    quiet = render(root, stale=True)                                          # 沒有過期的格：正常結束
    assert quiet["status"] == "done"
    assert quiet["result"]["text"] == "沒有過期的格，不用重畫"
    assert quiet["items"] == [] and len(fake_comfy) == 24
    assert any("沒有過期的格" in entry["text"] for entry in quiet["log"])


def test_render_stale_with_explicit_more(comic, cfg, fake_comfy):
    """呼叫端明確要「加畫 N 張」：照舊加新 seed，舊的候選留著、不備份。"""
    root = str(comic.root)
    assert render(root)["status"] == "done"
    before = {pid: files_of(root, pid) for pid in ("p001_k1", "p001_k2", "p001_k3")}
    old = {name: image_bytes(comic, name) for name in before["p001_k1"]}
    change_lin_outfit(comic)
    done = render(root, stale=True, more=1)
    assert done["status"] == "done", done
    assert done["result"]["text"] == "新出 3 張，略過 0 張（已存在）"
    assert len(fake_comfy) == 18
    after = {pid: files_of(root, pid) for pid in before}
    assert len(after["p001_k1"]) == 4 and set(before["p001_k1"]) <= set(after["p001_k1"])
    assert all(image_bytes(comic, name) == old[name] for name in before["p001_k1"])   # 沒有覆蓋
    assert after["p001_k2"] == before["p001_k2"] and after["p001_k3"] == before["p001_k3"]
    assert not backup_dir(comic).exists()                                     # 沒覆蓋就不用備份


def test_render_stale_with_force_false_follows_caller(comic, cfg, fake_comfy):
    """明確給 force: false：照呼叫端說的，一張都不覆蓋（全部略過）；檔案內容不變。"""
    root = str(comic.root)
    assert render(root)["status"] == "done"
    mine = render(root)                                                       # 沒帶 stale、檔案都在：全部略過（skip 事件）
    assert mine["result"]["text"] == "新出 0 張，略過 15 張（已存在）"
    assert any("略過（已存在）" in entry["text"] for entry in mine["log"])
    before = {pid: files_of(root, pid) for pid in ("p001_k1", "p001_k2", "p001_k3")}
    old = {name: image_bytes(comic, name) for name in before["p001_k1"]}
    change_lin_outfit(comic)
    done = render(root, stale=True, force=False)
    assert done["status"] == "done", done
    assert done["result"]["text"] == "新出 0 張，略過 9 張（已存在）"
    assert len(fake_comfy) == 15
    assert files_of(root, "p001_k1") == before["p001_k1"]
    assert all(image_bytes(comic, name) == old[name] for name in before["p001_k1"])
    assert not backup_dir(comic).exists()


# ---- GET /api/chapter/panels 的 explore／stale -------------------------------------

def test_panels_api_carries_explore_and_stale(comic, cfg, fake_comfy):
    root = str(comic.root)
    board = client.get("/api/chapter/storyboard", params={"project": root, "chapter": 1}).json()["storyboard"]
    board["pages"][0]["panels"][1]["characters"] = [{"id": "nobody"}]         # 還沒有卡片：探索用
    saved = post("/api/chapter/storyboard", {"project": root, "chapter": 1, "storyboard": board})
    assert saved.status_code == 200, saved.text
    assert any("探索用" in issue["message"] for issue in saved.json()["issues"])
    assert render(root)["result"]["text"] == "新出 15 張，略過 0 張（已存在）"

    rows = panel_rows(root)
    for row in rows.values():
        assert PANEL_KEYS <= set(row)                                        # 既有欄位一個都沒少
        assert isinstance(row["explore"], list) and isinstance(row["stale"], bool)
        assert row["stale"] is False
    assert rows["p001_k2"]["explore"] == ["nobody"] and rows["p001_k2"]["characters"] == ["nobody"]
    assert rows["p001_k1"]["explore"] == [] and rows["p001_k3"]["explore"] == []

    change_lin_outfit(comic)
    rows = panel_rows(root)
    flagged = {pid for pid, row in rows.items() if row["stale"]}
    assert flagged == {"p001_k1", "p001_k4", "p001_k5"}
    assert {p["id"] for p in stale(root, 1).json()["chapters"][0]["panels"]} == flagged   # 與過期清單一致
    assert rows["p001_k2"]["explore"] == ["nobody"] and rows["p001_k2"]["stale"] is False
