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
