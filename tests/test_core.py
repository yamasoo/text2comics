"""核心（t2c/）的檢查：座標換算、格子模板、分鏡編譯。不需要 ComfyUI。"""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import comfy, layout  # noqa: E402
from t2c.compile import CompileError, compile_chapter  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"


# ---- 座標 ------------------------------------------------------------------------

def test_moss_bbox_is_yxyx_centered_pixels():
    # 1024x1024：整張圖 → 四邊都是 ±512，而且 y 在前
    assert layout.to_moss_bbox([0, 0, 1, 1], 1024, 1024) == [-512, -512, 512, 512]
    # 右上四分之一：x 0.5–1、y 0–0.5
    assert layout.to_moss_bbox([0.5, 0, 1, 0.5], 1024, 768) == [-384, 0, 0, 512]


def test_moss_bbox_round_trip():
    box = [0.12, 0.3, 0.77, 0.95]
    back = layout.from_moss_bbox(layout.to_moss_bbox(box, 1088, 1920), 1088, 1920)
    assert all(abs(a - b) < 0.002 for a, b in zip(box, back))


@pytest.mark.parametrize("bad", [[0, 0, 1], [0.5, 0, 0.4, 1], [0, 0, 1.2, 1], ["a", 0, 1, 1]])
def test_bad_boxes_are_rejected(bad):
    with pytest.raises(layout.LayoutError):
        layout.check_box(bad)


def test_gen_size_multiple_of_16_and_about_one_megapixel():
    for aspect in (0.2, 0.5, 1.0, 1.4, 2.5, 6.0):
        width, height = layout.gen_size(aspect, 1.0)
        assert width % 16 == 0 and height % 16 == 0
        assert 0.85e6 < width * height < 1.15e6
        assert 1 / 3 - 0.05 <= width / height <= 3 + 0.05     # 太細長的格子被夾住


def test_page_templates_cover_the_page():
    data = layout.load_pages()
    for key, tpl in data["templates"].items():
        area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in tpl["panels"])
        assert abs(area - 1) < 0.01, "模板 %s 的格子沒有剛好鋪滿：%.3f" % (key, area)


def test_reading_order_starts_top_right():
    data = layout.load_pages()
    for key, tpl in data["templates"].items():
        x0, y0, x1, y1 = tpl["panels"][0]
        assert y0 == 0 and x1 == 1, "模板 %s 第 1 格要在右上" % key


# ---- 編譯 ------------------------------------------------------------------------

def sample():
    project = Project(SAMPLE)
    return project, project.load_storyboard(1)


def test_compile_sample_page():
    project, board = sample()
    jobs = compile_chapter(project, board)
    assert [job["id"] for job in jobs] == ["p001_k1", "p001_k2", "p001_k3", "p001_k4", "p001_k5"]
    for job in jobs:
        doc = json.loads(job["prompt"])
        assert doc["bbox_coord_space"] == "abs_centralized" and doc["bbox_format"] == "yxyx"
        assert len(job["seeds"]) == project.config["candidates"]
        for item in doc["items"]:
            y0, x0, y1, x1 = item["bbox"]
            assert -job["height"] / 2 - 1 <= y0 < y1 <= job["height"] / 2 + 1
            assert -job["width"] / 2 - 1 <= x0 < x1 <= job["width"] / 2 + 1


def test_character_look_is_copied_verbatim_and_only_when_present():
    project, board = sample()
    jobs = {job["id"]: json.loads(job["prompt"]) for job in compile_chapter(project, board)}
    lin_look = " ".join(project.characters["lin"]["look_en"].split())
    hao_look = " ".join(project.characters["hao"]["look_en"].split())
    k3 = json.dumps(jobs["p001_k3"], ensure_ascii=False)
    assert hao_look in k3 and lin_look not in k3                  # 第 3 格只有阿浩
    k5 = [item for item in jobs["p001_k5"]["items"] if item["label"] == "character"]
    assert len(k5) == 2
    assert "exactly two people" in jobs["p001_k5"]["summary"]["caption"]
    assert "no people" in jobs["p001_k2"]["summary"]["caption"]


def test_dialogue_never_reaches_the_prompt():
    project, board = sample()
    for job in compile_chapter(project, board):
        assert "香菜" not in job["prompt"] and "對不起" not in job["prompt"]


def test_every_panel_says_no_border_and_no_lettering():
    project, board = sample()
    for job in compile_chapter(project, board):
        caption = job["layout"]["summary"]["caption"]
        assert "The image has no border or frame." in caption
        assert caption.endswith("The artwork has no speech bubbles, captions or lettering.")


def test_two_characters_get_left_right_sentences_from_their_boxes():
    # S1 實測：over_shoulder 會讓左右對調，多角色時要明寫位置
    project, board = sample()
    jobs = {job["id"]: job["layout"] for job in compile_chapter(project, board)}
    k5 = {item["caption"].split(" ")[0]: item["caption"] for item in jobs["p001_k5"]["items"] if item["label"] == "character"}
    assert k5["He"].startswith("He is on the right side of the frame.")      # 阿浩的 box 在右半
    assert k5["She"].startswith("She is on the left side of the frame.")     # 小林的 box 在左半
    for pid in ("p001_k1", "p001_k3", "p001_k4"):                            # 單人格不加
        for item in jobs[pid]["items"]:
            assert "side of the frame" not in item["caption"]


def test_side_of_frame_thresholds():
    from t2c.compile import side_of_frame
    assert side_of_frame((0, 0, 0.5, 1)) == "left"
    assert side_of_frame((0.55, 0, 1, 1)) == "right"
    assert side_of_frame((0.25, 0, 0.75, 1)) == "center"


def test_sfx_mode_moss_adds_text_item():
    project, board = sample()
    jobs = compile_chapter(project, board, overrides={"sfx_mode": "moss"})
    k3 = json.loads(next(job for job in jobs if job["id"] == "p001_k3")["prompt"])
    assert any(item["label"] == "text" and item["text"] == "碰！" for item in k3["items"])


def test_seeds_are_reproducible():
    project, board = sample()
    first = [job["seeds"] for job in compile_chapter(project, board)]
    second = [job["seeds"] for job in compile_chapter(project, board)]
    assert first == second


def test_unknown_character_reports_page_and_panel():
    project, board = sample()
    board = copy.deepcopy(board)
    board["pages"][0]["panels"][0]["characters"][0]["id"] = "nobody"
    with pytest.raises(CompileError) as error:
        compile_chapter(project, board)
    assert "第 1 頁第 1 格" in str(error.value) and "nobody" in str(error.value)


def test_slot_count_must_match_template():
    project, board = sample()
    board = copy.deepcopy(board)
    board["pages"][0]["panels"].pop()
    with pytest.raises(CompileError):
        compile_chapter(project, board)


# ---- ComfyUI workflow（不連線）---------------------------------------------------

def test_prepare_fills_prompt_seed_size_and_models():
    project, board = sample()
    job = compile_chapter(project, board)[0]
    models = {"unet": "u.safetensors", "clip": "c.safetensors", "vae": "v.safetensors"}
    wf, out_id = comfy.prepare(comfy.load_workflow(), job["prompt"], job["negative"], 42,
                               job["width"], job["height"], models=models)
    texts = [node["inputs"]["text"] for node in wf.values() if node["class_type"] == "CLIPTextEncode"]
    assert job["prompt"] in texts
    sampler = next(node for node in wf.values() if node["class_type"] == "KSampler")
    assert sampler["inputs"]["seed"] == 42
    latent = next(node for node in wf.values() if node["class_type"] == "EmptyFlux2LatentImage")
    assert (latent["inputs"]["width"], latent["inputs"]["height"]) == (job["width"], job["height"])
    assert wf[out_id]["class_type"] == "SaveImage"


def test_prepare_requires_model_names():
    with pytest.raises(comfy.ComfyError):
        comfy.prepare(comfy.load_workflow(), "{}", "", 1, 1024, 1024, models={})


# ---- 出圖預設（steps、cfg、取樣器、LoRA）-----------------------------------------

MODELS = {"unet": "u.safetensors", "clip": "c.safetensors", "vae": "v.safetensors"}
DRAFT = {"steps": 4, "cfg": 1.0, "sampler": "euler", "scheduler": "simple",
         "lora": "ANIMA\\moss_image_sft_4step_v2.0.safetensors", "lora_strength": 1.0}


def test_preset_sets_sampler_and_inserts_lora_before_ksampler():
    wf, _ = comfy.prepare(comfy.load_workflow(), "{}", "n", 7, 1024, 1024, models=MODELS, preset=DRAFT)
    sampler = next(node for node in wf.values() if node["class_type"] == "KSampler")
    assert (sampler["inputs"]["steps"], sampler["inputs"]["cfg"], sampler["inputs"]["sampler_name"]) == (4, 1.0, "euler")
    lora = wf[comfy.LORA_NODE_ID]
    assert lora["class_type"] == "LoraLoaderModelOnly" and lora["inputs"]["lora_name"] == DRAFT["lora"]
    assert sampler["inputs"]["model"] == [comfy.LORA_NODE_ID, 0]               # KSampler 吃 LoRA 後的模型
    unet_id = next(nid for nid, node in wf.items() if node["class_type"] == "UNETLoader")
    assert lora["inputs"]["model"] == [unet_id, 0]                              # LoRA 吃原本的模型


def test_preset_without_lora_adds_no_node_and_does_not_touch_the_source_workflow():
    source = comfy.load_workflow()
    wf, _ = comfy.prepare(source, "{}", "n", 7, 1024, 1024, models=MODELS, preset={"steps": 30, "cfg": 3})
    assert comfy.LORA_NODE_ID not in wf
    assert next(n for n in wf.values() if n["class_type"] == "KSampler")["inputs"]["steps"] == 30
    assert next(n for n in source.values() if n["class_type"] == "KSampler")["inputs"]["steps"] == 25


def test_preset_rejects_unknown_field_and_bad_numbers():
    with pytest.raises(comfy.ComfyError):
        comfy.apply_preset(comfy.load_workflow(), {"step": 4})
    with pytest.raises(comfy.ComfyError):
        comfy.apply_preset(comfy.load_workflow(), {"steps": "four"})


def test_render_name_adds_suffix_only_for_non_default_preset():
    assert comfy.render_name("p001_k1", 5) == "p001_k1_s5.png"
    assert comfy.render_name("p001_k1", 5, "final", "final") == "p001_k1_s5.png"
    assert comfy.render_name("p001_k1", 5, "draft", "final") == "p001_k1_s5_draft.png"


def test_example_config_presets_are_valid():
    cfg = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))["comfy"]
    presets = {k: v for k, v in cfg["presets"].items() if not k.startswith("_")}
    assert cfg["default_preset"] in presets and "draft" in presets
    for preset in presets.values():
        comfy.apply_preset(comfy.load_workflow(), dict(preset))                 # 不丟錯


def test_panels_cli_with_fake_comfyui(tmp_path):
    """用假的 ComfyUI 跑 tools/panels.py：--preset、--seed、檔名後綴、略過已存在。"""
    import http.server
    import shutil
    import threading

    png = b"\x89PNG\r\n\x1a\nfake"
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, payload, ctype="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(body["prompt"])
            self._send(json.dumps({"prompt_id": "p%d" % len(received)}).encode())

        def do_GET(self):
            if self.path.startswith("/history/"):
                pid = self.path.split("/")[-1]
                wf = received[int(pid[1:]) - 1]
                out = next(nid for nid, node in wf.items() if node["class_type"] == "SaveImage")
                entry = {"status": {"status_str": "success", "completed": True},
                         "outputs": {out: {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}}}
                self._send(json.dumps({pid: entry}).encode())
            else:
                self._send(png, "image/png")

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        project_dir = tmp_path / "comic"
        shutil.copytree(SAMPLE, project_dir, ignore=shutil.ignore_patterns("build", "renders"))
        cfg = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
        cfg["comfy"]["url"] = "http://127.0.0.1:%d" % server.server_address[1]
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

        sys.path.insert(0, str(ROOT / "tools"))
        import panels
        base = [str(project_dir), "1", "--page", "1", "--render", "--config", str(cfg_path)]

        assert panels.main(base + ["--seed", "1390808158"]) == 0                # 預設（final）：沒有後綴
        assert (project_dir / "renders" / "ch001" / "p001_k1_s1390808158.png").is_file()
        sampler = next(n for n in received[0].values() if n["class_type"] == "KSampler")
        assert sampler["inputs"]["steps"] == 25 and comfy.LORA_NODE_ID not in received[0]

        assert panels.main(base + ["--seed", "1390808158", "--preset", "draft"]) == 0
        assert (project_dir / "renders" / "ch001" / "p001_k1_s1390808158_draft.png").is_file()
        sampler = next(n for n in received[1].values() if n["class_type"] == "KSampler")
        assert sampler["inputs"]["steps"] == 4 and received[1][comfy.LORA_NODE_ID]["inputs"]["lora_name"].endswith("4step_v2.0.safetensors")

        count = len(received)
        assert panels.main(base + ["--seed", "1390808158"]) == 0                # 已存在 → 略過，不再送
        assert len(received) == count

        assert panels.main(base + ["--preset", "nope"]) == 2                    # 沒這個預設
        assert panels.main(base + ["--seed", "1"]) == 2                         # 不在 seeds 裡
    finally:
        server.shutdown()
