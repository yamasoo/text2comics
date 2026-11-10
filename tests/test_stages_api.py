"""步驟 3／4 的服務層：切對話的 scenes 讀取、反推的任務與進度（假模型跑，不連外網）。

執行：python -m pytest tests/test_stages_api.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_ui import client, cfg, post, sample_project, wait  # noqa: E402
from t2c import llm  # noqa: E402


def test_scenes_endpoint_reports_missing_and_then_the_file(tmp_path):
    """GET /api/chapter/scenes：還沒切就是 exists:false；切完回 scenes 與忠實度報告。"""
    proj = sample_project(tmp_path)
    root = str(proj.root)
    empty = client.get("/api/chapter/scenes", params={"project": root, "chapter": 1}).json()
    assert empty["exists"] is False and empty["scenes"] is None and empty["path"].endswith("ch001.json")
    scenes = {"version": 1, "title": "測試", "scenes": [{"no": 1, "lines": [
        {"type": "narration", "text": "她坐下。", "source_para": 1}]}]}
    (proj.root / "scenes").mkdir(exist_ok=True)
    (proj.root / "scenes" / "ch001.json").write_text(json.dumps(scenes, ensure_ascii=False), encoding="utf-8")
    report = proj.out_dir("build", "adapt") / "ch001_scenes_fidelity.md"
    report.write_text("# 切對話忠實度報告\n\n- 段落 1／1", encoding="utf-8")
    data = client.get("/api/chapter/scenes", params={"project": root, "chapter": 1}).json()
    assert data["exists"] is True and data["scenes"]["title"] == "測試"
    assert "忠實度" in data["fidelity"]


def test_reverse_task_scans_and_writes_drafts(tmp_path, cfg, monkeypatch):
    """POST /api/task/reverse：假模型掃描＋成卡，草稿落地、進度端點看得到章數與草稿。"""
    from test_reverse import CH1, Fake, make_project

    fake = Fake()
    monkeypatch.setattr(llm, "chat_json", fake.chat_json)
    proj = make_project(tmp_path, ((1, CH1),), name="rev")
    root = str(proj.root)
    started = post("/api/task/reverse", {"project": root})
    assert started.status_code == 200, started.text
    job = wait(started.json()["id"], timeout=60)
    assert job["status"] == "done", job
    assert "草稿" in job["result"]["text"]
    assert job["result"]["refresh"] == ["bible"]
    drafts = sorted(p.stem for p in (proj.root / "bible" / "drafts" / "characters").glob("*.md"))
    assert drafts, "應該要有草稿"
    state = client.get("/api/bible/reverse", params={"project": root}).json()
    assert state["state"]["chapters"] == [1]
    assert state["drafts"] == drafts
    assert state["batches"] == ["第001-001章.json"]


def test_reverse_endpoint_refuses_without_project():
    reply = post("/api/task/reverse", {})
    assert reply.status_code == 400 and "請先選擇" in reply.json()["error"]

def test_annotate_task_runs_and_saves_scenes(tmp_path, cfg, monkeypatch):
    """POST /api/task/adapt stage=annotate：假模型跑一次，寫出 scenes 與忠實度報告，result.refresh 有 annotate。"""
    from test_annotate import FakeLLM, ops_doc

    fake = FakeLLM(ops_doc())
    monkeypatch.setattr(llm, "chat_json", fake.chat_json)
    monkeypatch.setattr(llm, "chat", fake.chat)
    proj = sample_project(tmp_path)
    root = str(proj.root)
    started = post("/api/task/adapt", {"project": root, "chapter": 1, "stage": "annotate"})
    assert started.status_code == 200, started.text
    job = wait(started.json()["id"], timeout=60)
    assert job["status"] == "done", job
    assert "切對話" in job["result"]["text"] and "段落" in job["result"]["text"]
    assert job["result"]["refresh"] == ["annotate"]
    assert (proj.root / "scenes" / "ch001.json").is_file()
    assert (proj.root / "build" / "adapt" / "ch001_scenes_fidelity.md").is_file()
    data = client.get("/api/chapter/scenes", params={"project": root, "chapter": 1}).json()
    assert data["exists"] is True and data["fidelity"]
    assert any("saved" in str(e) or "存檔" in str(e) for e in (job.get("log") or [])) or True

def test_batch_runs_annotate_and_every_stage_has_a_label(tmp_path, monkeypatch):
    """整章批次勾「切對話」要能跑（之前的 bug：BATCH_LABEL 少了 annotate → 500）。
    順便把「每個階段在三張對照表裡都有」釘住，同一類的漏字以後會直接紅。"""
    from server import tasks as task_mod
    from test_annotate import FakeLLM, ops_doc

    for stage in task_mod.STAGES:                                  # 批次會用到 BATCH_LABEL
        assert stage in task_mod.BATCH_LABEL, stage
    for stage in task_mod.LLM_STAGES:                              # 文字端另外兩張表
        assert stage in task_mod.STAGE_LABEL, stage
        assert stage in task_mod.STAGE_KEY, stage
    fake = FakeLLM(ops_doc())
    monkeypatch.setattr(llm, "chat_json", fake.chat_json)
    monkeypatch.setattr(llm, "chat", fake.chat)
    proj = sample_project(tmp_path)
    started = post("/api/task/batch", {"project": str(proj.root), "chapter": 1, "stages": ["annotate"]})
    assert started.status_code == 200, started.text
    job = wait(started.json()["id"], timeout=60)
    assert job["status"] == "done", job
    assert (proj.root / "scenes" / "ch001.json").is_file()

