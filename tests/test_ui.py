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
from t2c import comfy, gpu, llm, render, settings, styles, workspace  # noqa: E402
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
    assert proj.config["title"] == "新作品" and proj.config["style_preset"] == "mono"   # N5：畫風由預設集來
    assert "manga" in styles.resolve(proj.config)["style"]
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

# ---- N4：出圖 profile 與專案版型（介面）-----------------------------------------------

PROFILES = {
    "moss": {"kind": "moss", "models": {"unet": "moss.safetensors", "clip": "q.safetensors", "vae": "f.safetensors"},
             "default_preset": "final", "presets": {"final": {"steps": 25, "cfg": 2.5}}},
    "anima": {"kind": "anima", "models": {"unet": "anima.safetensors", "clip": "qwen3.safetensors", "vae": "qwen_vae.safetensors"},
              "negative": "score_4", "default_preset": "rough", "presets": {"rough": {"steps": 12, "cfg": 1.8}}},
}


@pytest.fixture
def profile_cfg(monkeypatch):
    """有 comfy.profiles 的設定（moss／anima 兩組），default_profile 是 moss。"""
    monkeypatch.setattr(settings, "load", lambda path=None, root=None: {
        "comfy": {"url": "http://127.0.0.1:1", "default_profile": "moss", "profiles": json.loads(json.dumps(PROFILES))},
        "lettering": {}, "_path": "test"})


def sample_project(tmp_path, **yaml_fields):
    """從範例新建專案；yaml_fields 追加到 project.yaml（comfy_profile、layout…）。"""
    proj = workspace.create_project(str(tmp_path / "c"), "", sample=SAMPLE)
    if yaml_fields:
        text = (proj.root / "project.yaml").read_text(encoding="utf-8").rstrip()
        extra = "".join("\n%s: %s" % (key, json.dumps(value, ensure_ascii=False)) for key, value in yaml_fields.items())
        (proj.root / "project.yaml").write_text(text + extra + "\n", encoding="utf-8")
    return proj


def write_project_pages(proj, box):
    """專案自己的版型檔（模板 key 是 solo）；project.yaml 的 layout 指到它。"""
    (proj.root / "pages.json").write_text(json.dumps({"templates": {"solo": {"name": "單格特寫", "panels": [box]}}},
                                                     ensure_ascii=False), encoding="utf-8")
    text = (proj.root / "project.yaml").read_text(encoding="utf-8").rstrip()
    (proj.root / "project.yaml").write_text(text + '\nlayout: {"file": "pages.json", "mode": "merge"}\n', encoding="utf-8")


def test_panels_api_carries_profiles_and_candidate_profile(tmp_path, profile_cfg):
    """介面要的欄位＋候選圖的 profile：profiles／default_profile／profile（這一章的）。"""
    proj = sample_project(tmp_path, comfy_profile="anima")
    folder = proj.root / "renders" / "ch001"
    folder.mkdir(parents=True)
    (folder / "p001_k1_s7.png").write_bytes(png_bytes())
    (folder / "p001_k1_s7__anima.png").write_bytes(png_bytes())
    data = client.get("/api/chapter/panels", params={"project": str(proj.root), "chapter": 1}).json()
    assert data["profiles"] == ["moss", "anima"]                       # config.json 的 comfy.profiles
    assert data["default_profile"] == "moss"                           # config.json 的 comfy.default_profile
    assert data["profile"] == "anima" and data["kind"] == "anima"      # project.yaml 的 comfy_profile 優先
    assert data["project_profile"] == "anima"                          # 這一章的預設＝project.yaml 的 comfy_profile
    assert [c["profile"] for c in data["panels"][0]["candidates"]] == ["", "anima"]
    assert data["presets"] == ["rough"] and data["default_preset"] == "rough"   # 預設清單用 anima 那一組的


def test_panels_api_profile_query_switches_presets(tmp_path, profile_cfg):
    """介面臨時換 profile：?profile=moss 回 moss 那一組的 presets，project_profile 仍是這一章的 anima。"""
    proj = sample_project(tmp_path, comfy_profile="anima")
    params = {"project": str(proj.root), "chapter": 1}
    switched = client.get("/api/chapter/panels", params=dict(params, profile="moss")).json()
    assert switched["profile"] == "moss" and switched["kind"] == "moss"
    assert switched["project_profile"] == "anima" and switched["default_profile"] == "moss"
    assert switched["presets"] == ["final"] and switched["default_preset"] == "final"
    assert switched["profiles"] == ["moss", "anima"]
    refused = client.get("/api/chapter/panels", params=dict(params, profile="anima2"))
    assert refused.status_code == 400 and "anima2" in refused.json()["error"]


def test_render_with_profile_uses_that_profile(tmp_path, profile_cfg, fake_comfy):
    """介面選 anima 出圖：檔名帶 __anima，送進 ComfyUI 的是 anima 的 workflow。"""
    proj = sample_project(tmp_path, comfy_profile="anima")
    done = wait(post("/api/task/render", {"project": str(proj.root), "chapter": 1, "panel": "p001_k1", "profile": "anima"}).json()["id"])
    assert done["status"] == "done", done
    names = [c["file"] for c in client.get("/api/chapter/panels", params={"project": str(proj.root), "chapter": 1}).json()["panels"][0]["candidates"]]
    assert names and all(name.endswith("__anima.png") for name in names)
    classes = {node.get("class_type") for node in fake_comfy[-1].values()}
    assert {"ModelSamplingAuraFlow", "EmptySD3LatentImage"} <= classes


def test_settings_api_saves_profiles_and_blocks_bad_kind(tmp_path, monkeypatch):
    """設定頁存的 profiles／default_profile 寫進（暫存的）config.json；kind 亂寫回 400。"""
    from server import settings_api

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"providers": CFG["providers"], "default_provider": "fake",
                                "comfy": {"url": "http://127.0.0.1:1", "models": {"unet": "u.safetensors"},
                                          "default_preset": "final", "presets": {"final": {"steps": 25}}},
                                "lettering": {}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings_api, "settings_path", lambda: path)

    saved = post("/api/settings", {"settings": {"comfy": {"profiles": json.loads(json.dumps(PROFILES)), "default_profile": "anima"}}})
    assert saved.status_code == 200, saved.json()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(on_disk["comfy"]["profiles"]) == ["anima", "moss"] and on_disk["comfy"]["default_profile"] == "anima"
    assert on_disk["comfy"]["url"] == "http://127.0.0.1:1"                      # 一層合併：沒送的欄位留著
    assert (tmp_path / "config.json.bak").is_file()

    refused = post("/api/settings", {"settings": {"comfy": {"profiles": {"anima": {"kind": "moss2"}}}}})
    assert refused.status_code == 400 and "kind" in refused.json()["error"]
    outside = post("/api/settings", {"settings": {"comfy": {"default_profile": "anima2"}}})
    assert outside.status_code == 400 and "default_profile" in outside.json()["error"]


def test_storyboard_vocab_marks_template_source_and_layout(tmp_path, profile_cfg):
    """分鏡編輯器的模板下拉要分得出內建／專案，並知道專案版型檔。"""
    proj = sample_project(tmp_path)
    write_project_pages(proj, [0.08, 0.1, 0.92, 0.9])
    vocab = client.get("/api/chapter/storyboard", params={"project": str(proj.root), "chapter": 1}).json()["vocab"]
    assert vocab["templates"]["solo"]["source"] == "project" and vocab["templates"]["5a"]["source"] == "builtin"
    assert vocab["layout"]["file"].endswith("pages.json") and vocab["layout"]["mode"] == "merge"
    assert vocab["layout"]["templates"] == ["solo"]


def test_storyboard_api_shows_layout_file_error(tmp_path, profile_cfg):
    """版型檔壞掉：400 的訊息要有檔名與第幾格（介面直接顯示，不吞掉）。"""
    proj = sample_project(tmp_path)
    write_project_pages(proj, [0.1, 0.2, 1.5, 0.8])
    broken = client.get("/api/chapter/storyboard", params={"project": str(proj.root), "chapter": 1})
    assert broken.status_code == 400
    assert "pages.json" in broken.json()["error"] and "第 1 格" in broken.json()["error"]

# ---- N6：設定頁與環境檢查的 profile 資訊 -------------------------------------------

def test_env_api_carries_profiles_and_chapter_profile(tmp_path, profile_cfg, monkeypatch):
    """GET /api/env：comfy.profiles（名稱、kind、unet）、這一章的 profile／kind／unet，
    presets 跟著 project.yaml 的 comfy_profile；沒開專案時用 config.json 的 default_profile。"""
    asked = []
    monkeypatch.setattr(gpu, "comfy_stats", lambda url, timeout=3.0: asked.append(url) or None)   # 不真的連 ComfyUI
    proj = sample_project(tmp_path, comfy_profile="anima")
    data = client.get("/api/env", params={"project": str(proj.root)}).json()
    assert data["comfy"]["profiles"] == [{"name": "moss", "kind": "moss", "unet": "moss.safetensors"},
                                         {"name": "anima", "kind": "anima", "unet": "anima.safetensors"}]
    assert data["comfy"]["profile"] == "anima" and data["comfy"]["kind"] == "anima"
    assert data["comfy"]["unet"] == "anima.safetensors"
    assert data["comfy"]["default_profile"] == "moss"                 # config.json 的 default_profile
    assert data["comfy"]["ok"] is False and data["comfy"]["url"] == "http://127.0.0.1:1"
    assert asked == ["http://127.0.0.1:1"]                            # 問的是設定裡那一臺
    assert data["presets"] == ["rough"] and data["default_preset"] == "rough"

    opened = client.get("/api/env").json()                            # 沒帶 project：用 default_profile
    assert opened["comfy"]["profile"] == "moss" and opened["comfy"]["kind"] == "moss"
    assert opened["comfy"]["unet"] == "moss.safetensors"
    assert opened["comfy"]["profiles"] == data["comfy"]["profiles"]
    assert opened["presets"] == ["final"] and opened["default_preset"] == "final"


def test_panels_api_carries_profile_info(tmp_path, profile_cfg):
    """GET /api/chapter/panels 的 profile_info：[{name, kind, unet}]；profiles 仍是名稱字串陣列。"""
    proj = sample_project(tmp_path, comfy_profile="anima")
    params = {"project": str(proj.root), "chapter": 1}
    data = client.get("/api/chapter/panels", params=params).json()
    assert data["profile_info"] == [{"name": "moss", "kind": "moss", "unet": "moss.safetensors"},
                                    {"name": "anima", "kind": "anima", "unet": "anima.safetensors"}]
    assert data["profiles"] == ["moss", "anima"] and all(isinstance(name, str) for name in data["profiles"])
    assert data["profile"] == "anima" and data["kind"] == "anima"
    switched = client.get("/api/chapter/panels", params=dict(params, profile="moss")).json()
    assert switched["profile"] == "moss" and switched["profile_info"] == data["profile_info"]   # 換看的 profile 不影響清單


def test_panels_api_profile_info_for_legacy_config(comic, cfg):
    """沒有 comfy.profiles 的舊設定也回一組 moss（介面不用分兩種情況）。"""
    data = client.get("/api/chapter/panels", params={"project": str(comic.root), "chapter": 1}).json()
    assert data["profile_info"] == [{"name": "moss", "kind": "moss", "unet": "u.safetensors"}]
    assert data["profiles"] == ["moss"]


def test_settings_api_carries_stages_and_keyring(tmp_path, monkeypatch):
    """GET /api/settings 的 stages（設定頁的下拉來源）與 keyring 狀態；金鑰庫換成假的，不碰真的。"""
    from server import settings_api

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"providers": CFG["providers"], "default_provider": "fake",
                                "comfy": {"url": "http://127.0.0.1:1"}, "lettering": {}}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings_api, "settings_path", lambda: path)
    monkeypatch.setattr(llm, "keyring_get", lambda account: "")
    data = client.get("/api/settings").json()
    assert data["stages"] == ["adapt", "script", "storyboard", "bible", "annotate", "plan"]
    assert data["stages"] == list(settings.STAGES)
    assert {"available", "service"} <= set(data["keyring"])
    assert data["keyring"]["service"] == "novel-studio" == llm.KEYRING_SERVICE
    assert isinstance(data["keyring"]["available"], bool) and isinstance(data["keyring"]["message"], str)
    assert data["keys"] == [{"id": "fake", "name": "假模型", "key_env": "", "env_set": False, "keyring": False}]
    assert data["path"] == str(path) and data["writable"] == list(settings.WRITABLE)


def test_static_pages_show_profile_notes():
    """出圖 profile 的說明文字在靜態檔裡；兩支都用 FE.h 建節點，不拼 innerHTML。"""
    bible = (ROOT / "web" / "static" / "bible.js").read_text(encoding="utf-8")
    panels = (ROOT / "web" / "static" / "panels.js").read_text(encoding="utf-8")
    assert "出圖 profile" in bible and "同一臺 ComfyUI 一次只掛一組模型" in bible
    assert "profile_info" in panels and "同一臺 ComfyUI 一次只掛一組模型" in panels
    assert "innerHTML" not in bible and "innerHTML" not in panels


def test_static_settings_page_has_the_new_controls():
    """設定頁（N6）：F1／F4／F5 的必用字串都在，階段下拉不寫死，沒有 innerHTML。"""
    text = (ROOT / "web" / "static" / "settings.js").read_text(encoding="utf-8")
    for literal in ("這是 workflow 不是 profiles；workflow 請填 profile.workflow 路徑或留空用內建",
                    "進階：直接編輯 JSON", "依 kind 自動挑", "複製這組", "刪除這組",
                    "從 ComfyUI 抓模型清單", "測試連線", "存進金鑰庫", "新增一組",
                    "provider／模型／網址改完即生效，只有行程環境變數要重啟。"):
        assert literal in text, literal
    assert "innerHTML" not in text
    assert "/api/comfy/models" in text and "/api/llm/probe" in text and "/api/llm/key" in text
    assert "data.stages" in text                                        # 階段清單由伺服器給
    assert '["adapt", "script", "storyboard", "bible"]' not in text      # 不再寫死在頁面上

def test_env_api_profile_query_switches_presets(tmp_path, profile_cfg):
    """定裝圖對話框換出圖 profile 時，出圖預設要跟著換：?profile=moss 回 moss 那一組的 presets。"""
    proj = sample_project(tmp_path, comfy_profile="anima")
    params = {"project": str(proj.root)}
    chapter = client.get("/api/env", params=params).json()
    assert chapter["comfy"]["profile"] == "anima" and chapter["presets"] == ["rough"] and chapter["default_preset"] == "rough"
    switched = client.get("/api/env", params=dict(params, profile="moss")).json()
    assert switched["comfy"]["profile"] == "moss" and switched["comfy"]["kind"] == "moss"
    assert switched["presets"] == ["final"] and switched["default_preset"] == "final"
    assert client.get("/api/env", params=dict(params, profile="nope")).status_code == 400

def test_styles_api_and_project_style_switch(tmp_path):
    """N5：畫風清單與換畫風（/api/styles、/api/project/style）；範例專案明寫的 style／meta 會被拿掉。"""
    presets = client.get("/api/styles").json()
    assert [row["name"] for row in presets["presets"]] == ["american", "color", "mono"]
    assert presets["default"] == "mono" and all(row["label"] for row in presets["presets"])
    proj = sample_project(tmp_path)
    resp = post("/api/project/style", {"project": str(proj.root), "preset": "color"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["preset"] == "color" and data["resolved"]["name"] == styles.preset("color")["name"]
    assert sorted(data["dropped"]) == ["meta", "style"]                      # 範例的 project.yaml 明寫了這兩欄
    assert data["overview"]["config"]["style_preset"] == "color"
    text = (proj.root / "project.yaml").read_text(encoding="utf-8")
    assert "style_preset: color" in text and "screentone shading" not in text
    resolved = styles.resolve(workspace.open_project(str(proj.root)).config)
    assert resolved["style"] == styles.preset("color")["style"]


def test_project_style_api_rejects_bad_preset_and_missing_project(tmp_path):
    """preset 亂寫回 400 並列出可用值；沒帶 project 回 400。"""
    proj = sample_project(tmp_path)
    bad = post("/api/project/style", {"project": str(proj.root), "preset": "no_such_preset"})
    assert bad.status_code == 400
    assert "可用：" in bad.json()["error"] and "mono" in bad.json()["error"]
    missing = post("/api/project/style", {"preset": "mono"})
    assert missing.status_code == 400
    assert "請先選擇" in missing.json()["error"]
