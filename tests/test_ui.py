"""S7：介面後端（server/）與它用的核心（t2c/workspace.py、render.py、gpu.py）。
模型與 ComfyUI 都用假的（不連外網、不需要 GPU）。執行：python -m pytest tests/test_ui.py
"""
import json
import shutil
import re
import sys
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app as app_module  # noqa: E402
from t2c import comfy, gpu, llm, render, settings, workspace  # noqa: E402
from t2c.compile import _seed  # noqa: E402
from test_adapt import ScriptedLLM, good_replies  # noqa: E402

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


def token():
    html = client.get("/").text
    return re.search(r'name="fe-token" content="([^"]+)"', html).group(1)


def post(path, body):
    return client.post(path, json=body, headers={"X-FE-Token": token()})


def png_bytes(value=128, size=(1000, 800)):
    buffer = BytesIO()
    Image.new("L", size, value).save(buffer, format="PNG")
    return buffer.getvalue()


def wait(job_id, timeout=30, answer=None):
    """等任務結束；answer 是遇到提問時要回覆的值。"""
    end = time.time() + timeout
    while time.time() < end:
        data = client.get("/api/jobs/%s" % job_id).json()
        if data.get("ask") and answer is not None:
            client.post("/api/jobs/%s/reply" % job_id, json={"ask_id": data["ask"]["id"], "text": answer},
                        headers={"X-FE-Token": token()})
            answer = None
        if data.get("status") in ("done", "error", "stopped"):
            return data
        time.sleep(0.05)
    raise AssertionError("任務沒有結束：%s" % job_id)


def need_font():
    from t2c import letter
    try:
        letter.Settings.from_config({})
    except letter.LetterError:
        pytest.skip("這台電腦找不到中文字型")


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(settings, "load", lambda path=None, root=None: dict(CFG, _path="test"))
    return CFG


@pytest.fixture
def fake_comfy(monkeypatch):
    calls = []

    def run(base, wf, out_id, should_stop=lambda: False, timeout=1800):
        calls.append(wf)
        return png_bytes(40 + len(calls) * 10 % 200)
    monkeypatch.setattr(comfy, "run", run)
    return calls


@pytest.fixture
def comic(tmp_path):
    """從範例新建的專案（不含出圖）。"""
    return workspace.create_project(str(tmp_path / "comic"), "測試作品", sample=SAMPLE)


# ---- 核心：workspace ---------------------------------------------------------------

def test_create_project_new_and_from_sample(tmp_path):
    proj = workspace.create_project(str(tmp_path / "new"), "新作品")
    assert proj.config["title"] == "新作品" and "manga" in proj.config["style"]
    assert (proj.root / "bible" / "characters").is_dir() and workspace.overview(proj)["chapters"] == []
    with pytest.raises(workspace.WorkspaceError):
        workspace.create_project(str(tmp_path / "new"), "又一次")                  # 不是空資料夾
    with pytest.raises(workspace.WorkspaceError):
        workspace.create_project("relative/path", "x")                              # 要完整路徑
    sample = workspace.create_project(str(tmp_path / "s"), "改名", sample=SAMPLE)
    assert sample.config["title"] == "改名" and not (sample.root / "renders").exists()
    ch = workspace.overview(sample)["chapters"][0]
    assert ch["chapter"] == 1 and ch["script_pages"] == 1 and ch["panels"] == 5 and ch["rendered"] == 0
    bare = tmp_path / "bare_sample"                                                 # 新 clone 的範例沒有 renders/（不進版控）
    shutil.copytree(SAMPLE, bare, ignore=shutil.ignore_patterns("renders", "pages", "build", "out"))
    assert not workspace.sample_has_renders(bare)
    with pytest.raises(workspace.WorkspaceError, match="範例沒有出圖"):
        workspace.create_project(str(tmp_path / "r0"), "", sample=bare, sample_renders=True)
    assert not (tmp_path / "r0").exists() or not any((tmp_path / "r0").iterdir())


@pytest.mark.skipif(not workspace.sample_has_renders(SAMPLE), reason="範例的出圖不進版控（examples/sample_comic/renders/），這台電腦沒有")
def test_create_project_from_sample_with_renders(tmp_path):
    with_renders = workspace.create_project(str(tmp_path / "r"), "", sample=SAMPLE, sample_renders=True)
    ch = workspace.overview(with_renders)["chapters"][0]
    assert ch["rendered"] == 5 and ch["picked"] == 5


def test_storyboard_save_blocks_compile_errors_only(comic):
    board = comic.load_storyboard(1)
    board["pages"][0]["panels"][0]["scene"] = "She wears a red dress and waits."                # 外觀字：提醒，不擋
    path, saved, issues = workspace.save_storyboard(comic, 1, board)
    assert any("wear" in i["message"] or "外觀" in i["message"] for i in issues)
    assert saved["pages"][0]["panels"][0]["id"] == "p001_k1" and json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    board["pages"][0]["panels"][1]["characters"] = [{"id": "nobody"}]                         # 編譯不了：擋
    with pytest.raises(workspace.WorkspaceError, match="第 1 頁第 2 格"):
        workspace.save_storyboard(comic, 1, board)


def test_script_and_plan_save(comic):
    text = (comic.script_path(1)).read_text(encoding="utf-8")
    _, issues = workspace.save_script(comic, 1, text.replace("曉雨：", "路人甲：", 1))
    assert any("路人甲" in i["message"] for i in issues)                                       # 照存，回報問題
    with pytest.raises(workspace.WorkspaceError):
        workspace.save_script(comic, 1, "沒有頁標題")
    with pytest.raises(workspace.WorkspaceError, match="規劃有"):
        workspace.save_plan(comic, 1, {"pages": [{"page": 2}]})


def test_next_seeds_are_reproducible_and_skip_existing():
    job = {"id": "p001_k1", "seeds": [_seed("p001_k1", 0), _seed("p001_k1", 1)]}
    first = workspace.next_seeds(job, 3, set())
    assert first == [_seed("p001_k1", i) for i in range(3)]
    assert workspace.next_seeds(job, 2, set(first)) == [_seed("p001_k1", 3), _seed("p001_k1", 4)]
    assert workspace.next_seeds({"id": "p001_k1", "seeds": [7]}, 2, set()) == [7, _seed("p001_k1", 0)]


# ---- 核心：gpu ---------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def _reply(self, code, body=b"{}"):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        Handler.hits.append(("GET", self.path))
        if self.path == "/health":
            self._reply(503)                                     # 模型載入中也算「在執行」
        elif self.path == "/system_stats":
            self._reply(200, json.dumps({"devices": [{"name": "GPU", "vram_total": 16 * 1024 ** 3, "vram_free": 4 * 1024 ** 3}]}).encode())
        else:
            self._reply(404)

    def do_POST(self):
        Handler.hits.append(("POST", self.path, self.rfile.read(int(self.headers.get("Content-Length") or 0))))
        self._reply(200)


@pytest.fixture
def local_server():
    Handler.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % server.server_address[1]
    server.shutdown()


def test_gpu_helpers(local_server):
    prov = {"id": "llamacpp", "base_url": local_server + "/v1"}
    assert gpu.is_local(prov) and gpu.llm_running(prov)
    assert not gpu.llm_running({"id": "x", "base_url": "http://127.0.0.1:1/v1"}, 0.5)
    assert not gpu.llm_running({"id": "ds", "base_url": "https://api.deepseek.com"})          # 雲端的不用管
    assert gpu.comfy_free(local_server) and json.loads(Handler.hits[-1][2]) == {"unload_models": True, "free_memory": True}
    assert not gpu.comfy_free("http://127.0.0.1:1", 0.5)
    assert "已用 12.0／共 16.0 GiB" in gpu.vram_summary(gpu.comfy_stats(local_server))


# ---- API：專案與章節 ---------------------------------------------------------------

def test_project_api_and_editing(tmp_path, cfg):
    root = str(tmp_path / "c")
    made = post("/api/project/create", {"path": root, "title": "介面測試", "from_sample": True}).json()
    assert made["overview"]["title"] == "介面測試"
    assert client.get("/api/project", params={"project": root}).json()["chapters"][0]["panels"] == 5
    assert client.get("/api/project", params={"project": str(tmp_path)}).status_code == 400

    src = client.get("/api/chapter/source", params={"project": root, "chapter": 2}).json()
    assert src["exists"] is False
    assert post("/api/chapter/source", {"project": root, "chapter": 2, "text": "第二章的原著。"}).status_code == 200
    assert client.get("/api/chapter/source", params={"project": root, "chapter": 2}).json()["chars"] == 7
    novel = tmp_path / "novel.txt"
    novel.write_bytes("﻿匯入的原著".encode("utf-8"))
    assert post("/api/chapter/source", {"project": root, "chapter": 3, "path": str(novel)}).status_code == 200
    assert [c["chapter"] for c in client.get("/api/project", params={"project": root}).json()["chapters"]] == [1, 2, 3]

    sb = client.get("/api/chapter/storyboard", params={"project": root, "chapter": 1}).json()
    assert sb["compile_error"] == "" and {c["id"] for c in sb["vocab"]["characters"]} == {"lin", "hao"}
    board = sb["storyboard"]
    board["pages"][0]["panels"][0]["shot"] = "full"
    saved = post("/api/chapter/storyboard", {"project": root, "chapter": 1, "storyboard": board}).json()
    assert saved["storyboard"]["pages"][0]["panels"][0]["shot"] == "full"
    prompt = post("/api/chapter/prompt", {"project": root, "chapter": 1, "panel": "p001_k1", "storyboard": board}).json()
    assert "Full body shot" in prompt["layout"]["summary"]["caption"] and prompt["width"] % 16 == 0
    board["pages"][0]["panels"][0]["location"] = "moon"
    bad = post("/api/chapter/storyboard", {"project": root, "chapter": 1, "storyboard": board})
    assert bad.status_code == 400 and "moon" in bad.json()["error"]

    script = client.get("/api/chapter/script", params={"project": root, "chapter": 1}).json()
    assert script["pages"] == [{"page": 1, "template": "5a", "panels": 5}] and script["issues"] == []
    env = client.get("/api/env").json()
    assert env["comfy"]["ok"] is False and env["providers"][0]["id"] == "fake" and env["default_preset"] == "final"


def test_render_pick_crop_and_pages(tmp_path, cfg, fake_comfy):
    need_font()
    root = str(workspace.create_project(str(tmp_path / "c"), "", sample=SAMPLE).root)
    first = post("/api/task/render", {"project": root, "chapter": 1, "page": 1}).json()
    done = wait(first["id"])
    assert done["status"] == "done", done
    assert len(fake_comfy) == 15 and "新出 15 張" in done["result"]["text"] and done["result"]["refresh"] == ["panels"]
    assert {i["state"] for i in done["items"]} == {"done"}

    more = wait(post("/api/task/render", {"project": root, "chapter": 1, "panel": "p001_k2", "more": 2}).json()["id"])
    assert more["status"] == "done" and len(fake_comfy) == 17
    panels = client.get("/api/chapter/panels", params={"project": root, "chapter": 1}).json()
    k2 = next(p for p in panels["panels"] if p["id"] == "p001_k2")
    assert len(k2["candidates"]) == 5 and k2["pick"] is None
    assert [c["seed"] for c in k2["candidates"]][:0] == [] and panels["default_preset"] == "final"

    draft = wait(post("/api/task/render", {"project": root, "chapter": 1, "panel": "p001_k3", "more": 1, "preset": "draft"}).json()["id"])
    assert draft["status"] == "done" and fake_comfy[-1]["8"]["inputs"]["steps"] == 4
    names = [c["file"] for c in client.get("/api/chapter/panels", params={"project": root, "chapter": 1}).json()["panels"][2]["candidates"]]
    assert any(n.endswith("_draft.png") for n in names)

    image = k2["candidates"][-1]["file"]
    picked = post("/api/chapter/pick", {"project": root, "chapter": 1, "panel": "p001_k2", "image": image}).json()["pick"]
    assert picked == {"image": image, "focus": [0.5, 0.5], "zoom": 1.0}
    moved = post("/api/chapter/pick", {"project": root, "chapter": 1, "panel": "p001_k2", "focus": [0.2, 0.7], "zoom": 1.5}).json()["pick"]
    assert moved["image"] == image and moved["zoom"] == 1.5
    assert post("/api/chapter/pick", {"project": root, "chapter": 1, "panel": "p001_k2", "zoom": 9}).status_code == 400
    assert post("/api/chapter/pick", {"project": root, "chapter": 1, "panel": "p001_k2", "image": "nope.png"}).status_code == 400

    crop = client.get("/api/chapter/crop.jpg", params={"project": root, "chapter": 1, "panel": "p001_k2", "image": image, "fx": 0.2, "fy": 0.7, "zoom": 1.5, "w": 300})
    assert crop.status_code == 200 and Image.open(BytesIO(crop.content)).size[0] == 300
    thumb = client.get("/api/image", params={"project": root, "path": "renders/ch001/%s" % image, "w": 200})
    assert thumb.headers["content-type"] == "image/jpeg" and Image.open(BytesIO(thumb.content)).size[0] == 200
    assert client.get("/api/image", params={"project": root, "path": "project.yaml"}).status_code == 400
    assert client.get("/api/image", params={"project": root, "path": "renders/../project.yaml"}).status_code == 400

    out = wait(post("/api/task/pages", {"project": root, "chapter": 1}).json()["id"])
    assert out["status"] == "done", out
    pages = client.get("/api/chapter/pages", params={"project": root, "chapter": 1}).json()
    assert pages["pages"][0]["png"] == "pages/ch001/p001.png" and (Path(root) / "pages" / "ch001" / "p001.png").is_file()


def test_export_status_and_download(tmp_path, cfg):
    """S8：頁面 PNG 還沒輸出時不能下載；輸出後 PDF／CBZ（整章與單頁）下載得到，且右翻。"""
    root = str(workspace.create_project(str(tmp_path / "c"), "", sample=SAMPLE).root)
    params = {"project": root, "chapter": 1}
    status = client.get("/api/chapter/pages", params=params).json()["export"]
    assert status["ready"] is False and "還沒有輸出頁面" in status["message"]
    refused = client.get("/api/chapter/export", params=dict(params, format="pdf"))
    assert refused.status_code == 400 and "還沒有輸出頁面" in refused.json()["error"]

    pages = Path(root) / "pages" / "ch001"
    pages.mkdir(parents=True, exist_ok=True)
    Image.new("L", (364, 514), 80).save(pages / "p001.png", dpi=(254, 254))
    status = client.get("/api/chapter/pages", params=params).json()["export"]
    assert status["ready"] is True and status["message"] == ""

    pdf = client.get("/api/chapter/export", params=dict(params, format="pdf"))
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert 'filename="ch001.pdf"' in pdf.headers["content-disposition"] and b"/Direction /R2L" in pdf.content
    assert (Path(root) / "out" / "ch001.pdf").read_bytes() == pdf.content                    # 同時存在專案的 out/
    cbz = client.get("/api/chapter/export", params=dict(params, format="cbz", page=1))
    assert cbz.status_code == 200 and 'filename="ch001_p001.cbz"' in cbz.headers["content-disposition"]
    with zipfile.ZipFile(BytesIO(cbz.content)) as archive:
        assert b"YesAndRightToLeft" in archive.read("ComicInfo.xml")
    lossless = client.get("/api/chapter/export", params=dict(params, format="pdf", lossless="true", single="true"))
    assert b"/FlateDecode" in lossless.content and b"/PageLayout /SinglePage" in lossless.content
    assert client.get("/api/chapter/export", params=dict(params, format="epub")).status_code == 400
    assert client.get("/api/chapter/export", params=dict(params, format="pdf", page=9)).status_code == 400


def test_adapt_task_streams_and_saves(tmp_path, cfg, monkeypatch):
    fake = ScriptedLLM(good_replies())
    monkeypatch.setattr(llm, "chat", fake.chat)
    monkeypatch.setattr(llm, "chat_json", fake.chat_json)
    proj = workspace.create_project(str(tmp_path / "c"), "", sample=SAMPLE)
    for sub in ("script", "storyboard"):
        for path in (proj.root / sub).glob("*"):
            path.unlink()
    root = str(proj.root)
    plan = wait(post("/api/task/adapt", {"project": root, "chapter": 1, "stage": "plan"}).json()["id"])
    assert plan["status"] == "done" and "2 頁" in plan["result"]["text"] and proj.plan_path(1).is_file()
    again = wait(post("/api/task/adapt", {"project": root, "chapter": 1, "stage": "plan"}).json()["id"])
    assert again["status"] == "error" and "已經存在" in again["error"]                       # 不加 force 不覆蓋
    batch = wait(post("/api/task/batch", {"project": root, "chapter": 1, "stages": ["plan", "script", "storyboard"]}).json()["id"])
    assert batch["status"] == "done", batch
    states = {i["key"]: i["state"] for i in batch["items"]}
    assert states == {"plan": "skipped", "script": "done", "storyboard": "done"}
    assert proj.storyboard_path(1).is_file() and len(proj.load_storyboard(1)["pages"]) == 2


def test_batch_render_waits_for_local_llm(tmp_path, cfg, fake_comfy, monkeypatch, local_server):
    need_font()
    local = {"id": "llamacpp", "name": "llama.cpp", "base_url": local_server + "/v1", "key_env": ""}
    monkeypatch.setattr(settings, "load", lambda path=None, root=None: dict(CFG, providers=CFG["providers"] + [local], _path="test"))
    root = str(workspace.create_project(str(tmp_path / "c"), "", sample=SAMPLE).root)
    stopped = wait(post("/api/task/batch", {"project": root, "chapter": 1, "stages": ["render"]}).json()["id"], answer="stop")
    assert stopped["status"] == "stopped" and fake_comfy == []
    done = wait(post("/api/task/batch", {"project": root, "chapter": 1, "stages": ["render", "pages"]}).json()["id"], answer="anyway")
    assert done["status"] == "done", done
    assert len(fake_comfy) == 15 and (Path(root) / "pages" / "ch001" / "p001.png").is_file()
    skip = wait(post("/api/task/batch", {"project": root, "chapter": 1, "stages": ["render"]}).json()["id"])
    assert {i["key"]: i["state"] for i in skip["items"]}["render"] == "skipped"                # 都畫過了：不用問也不出圖


def test_render_core_cancel(comic, fake_comfy):
    jobs = render.chapter_jobs(comic, 1, page=1)
    with pytest.raises(render.Cancelled):
        render.render_jobs(comic, 1, jobs, CFG, should_stop=lambda: True)
    assert fake_comfy == []


# ---- API：視覺聖經 ------------------------------------------------------------------

def test_bible_api(tmp_path, cfg, fake_comfy):
    root = str(workspace.create_project(str(tmp_path / "c"), "", sample=SAMPLE).root)
    data = client.get("/api/bible", params={"project": root}).json()
    assert {c["id"] for c in data["cards"] if c["kind"] == "character"} == {"lin", "hao"}
    assert post("/api/bible/new", {"project": root, "kind": "character", "id": "lin", "name": "重複"}).status_code == 400
    assert post("/api/bible/new", {"project": root, "kind": "character", "id": "mei", "name": "小美"}).status_code == 200
    card = client.get("/api/bible/card", params={"project": root, "kind": "character", "id": "mei", "draft": True}).json()
    assert any(i["level"] == "error" for i in card["issues"])                                  # 空的 look_en
    text = card["text"].replace("look_en: >-\n  \n", "look_en: >-\n  A young East Asian woman in her twenties with long black hair and a slim build\n")
    text = text.replace("default: >-\n    \n", "default: >-\n    She wears a white blouse and a dark skirt.\n")
    saved = post("/api/bible/card", {"project": root, "kind": "character", "id": "mei", "draft": True, "text": text}).json()
    assert [i for i in saved["issues"] if i["level"] == "error"] == []
    renamed = post("/api/bible/card", {"project": root, "kind": "character", "id": "mei", "draft": True, "text": text.replace("id: mei", "id: mai")})
    assert renamed.status_code == 400
    assert post("/api/bible/accept", {"project": root, "ids": ["mei"]}).json()["moved"][0]["id"] == "mei"

    sheet = wait(post("/api/task/bible_sheet", {"project": root, "ids": ["mei"], "candidates": 2}).json()["id"])
    assert sheet["status"] == "done" and len(fake_comfy) == 2
    files = client.get("/api/bible/renders", params={"project": root, "kind": "character", "id": "mei"}).json()["files"]
    assert len(files) == 2 and not any(f["picked"] for f in files)
    assert post("/api/bible/pick", {"project": root, "image": files[0]["file"]}).json()["id"] == "mei"
    assert client.get("/api/bible/renders", params={"project": root, "kind": "character", "id": "mei"}).json()["files"][0]["picked"]
    more = wait(post("/api/task/bible_sheet", {"project": root, "ids": ["mei"], "more": 1}).json()["id"])
    assert more["status"] == "done" and len(fake_comfy) == 3

    confirmed = client.get("/api/bible/card", params={"project": root, "kind": "character", "id": "mei"}).json()["text"]
    stale = post("/api/bible/card", {"project": root, "kind": "character", "id": "mei", "text": confirmed.replace("long black hair", "short black hair")}).json()
    assert stale["stale"] is True
    broken = post("/api/bible/card", {"project": root, "kind": "character", "id": "mei", "text": confirmed.replace("woman", "person")})
    assert broken.status_code == 400                                                          # 定案卡片不能有錯
