"""N4：出圖 profile（moss／anima）。

檢查 config.json 的 comfy.profiles、project.yaml 的 comfy_profile、CLI --profile、
檔名 __<profile> 後綴、兩組 workflow 的節點差異，以及錯誤訊息有沒有寫清楚。
全部不連 ComfyUI（comfy.run 換成假的）。
"""
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import comfy, render, workspace  # noqa: E402
from t2c.project import Project  # noqa: E402

SAMPLE = ROOT / "examples" / "sample_comic"

MOSS = {"kind": "moss",
        "models": {"unet": "moss_image.safetensors", "clip": "qwen3.5_9b.safetensors", "vae": "flux2-vae.safetensors"},
        "default_preset": "final",
        "presets": {"final": {"steps": 25, "cfg": 2.5, "scheduler": "simple"},
                    "draft": {"steps": 4, "cfg": 1.0, "scheduler": "simple"}}}
ANIMA = {"kind": "anima",
         "models": {"unet": "UnstableAnima-Art-V4.safetensors", "clip": "qwen_3_06b_base.safetensors",
                    "vae": "qwen_image_vae.safetensors"},
         "negative": "score_4, score_5",
         "default_preset": "final",
         "presets": {"final": {"steps": 12, "cfg": 1.8, "scheduler": "beta"}},
         "loras": [{"name": "ANIMA/style.safetensors", "strength": 0.8}]}


def make_cfg(**comfy_overrides):
    cfg = {"comfy": {"url": "http://127.0.0.1:9", "default_profile": "moss",
                     "profiles": {"moss": copy.deepcopy(MOSS), "anima": copy.deepcopy(ANIMA)}},
           "lettering": {}}
    cfg["comfy"].update(comfy_overrides)
    return cfg


def make_project(tmp_path):
    root = tmp_path / "comic"
    shutil.copytree(SAMPLE, root, ignore=shutil.ignore_patterns("renders", "pages", "build", "picks"))
    return Project(root)


def set_project_yaml(project, **fields):
    text = (project.root / "project.yaml").read_text(encoding="utf-8").rstrip()
    extra = "".join("%s: %s\n" % (key, json.dumps(value, ensure_ascii=False)) for key, value in fields.items())
    (project.root / "project.yaml").write_text(text + "\n" + extra, encoding="utf-8")
    return Project(project.root)


def one_job(project, chapter=1, panel="p001_k1", seed=None):
    jobs = render.chapter_jobs(project, chapter, panel=panel)
    job = jobs[0]
    job["run_seeds"] = [seed if seed is not None else job["seeds"][0]]
    return job


def fake_run(monkeypatch):
    calls = []

    def run(base, wf, out_id, should_stop=lambda: False, timeout=1800):
        calls.append({"base": base, "wf": wf})
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setattr(comfy, "run", run)
    return calls


# ---- profile 的選擇 --------------------------------------------------------------

def test_legacy_config_without_profiles_is_one_moss_profile():
    cfg = {"comfy": {"workflow": "", "models": {"unet": "u.safetensors"},
                     "default_preset": "final", "presets": {"final": {"steps": 25}}}}
    profile = comfy.resolve_profile(cfg)
    assert profile["name"] == "moss" and profile["kind"] == "moss"
    assert profile["workflow"] == comfy.KIND_WORKFLOWS["moss"]
    assert profile["models"] == {"unet": "u.safetensors"} and profile["presets"] == {"final": {"steps": 25}}
    assert profile["base_url"] == "http://127.0.0.1:8188"


def test_project_yaml_chooses_profile_and_the_argument_wins(tmp_path):
    project = set_project_yaml(make_project(tmp_path), comfy_profile="anima")
    assert project.comfy_profile() == "anima"
    assert comfy.resolve_profile(make_cfg(), project_config=project.config)["name"] == "anima"
    assert comfy.resolve_profile(make_cfg(), name="moss", project_config=project.config)["name"] == "moss"
    assert comfy.resolve_profile(make_cfg())["name"] == "moss"            # 沒有 project 就用 default_profile


def test_single_profile_needs_no_default():
    cfg = {"comfy": {"profiles": {"only": {"kind": "anima", "models": {"unet": "u", "clip": "c", "vae": "v"}}}}}
    assert comfy.resolve_profile(cfg)["name"] == "only"


def test_profile_errors_say_which_name_and_what_can_be_used(tmp_path):
    cfg = make_cfg()
    with pytest.raises(comfy.ComfyError) as info:
        comfy.resolve_profile(cfg, "anima2")
    text = str(info.value)
    assert "anima2" in text and "moss" in text and "anima" in text

    many = make_cfg(); del many["comfy"]["default_profile"]
    with pytest.raises(comfy.ComfyError) as info:
        comfy.resolve_profile(many)
    assert "comfy.default_profile" in str(info.value) and "moss" in str(info.value)

    no_kind = make_cfg(profiles={"broken": {"models": {"unet": "u"}}})
    with pytest.raises(comfy.ComfyError) as info:
        comfy.resolve_profile(no_kind, "broken")
    assert "缺少 kind" in str(info.value)

    bad_kind = make_cfg(profiles={"flux": {"kind": "flux"}})
    with pytest.raises(comfy.ComfyError) as info:
        comfy.resolve_profile(bad_kind, "flux")
    assert "flux" in str(info.value) and "moss" in str(info.value)

    bad_workflow = make_cfg(profiles={"anima": dict(ANIMA, workflow="nope.json")})
    with pytest.raises(comfy.ComfyError) as info:
        comfy.resolve_profile(bad_workflow, "anima")
    assert "comfy.profiles.anima.workflow" in str(info.value) and "nope.json" in str(info.value)

    legacy = {"comfy": {"default_profile": "anima"}}
    with pytest.raises(comfy.ComfyError) as info:
        comfy.resolve_profile(legacy)
    assert "comfy.profiles" in str(info.value)


def test_missing_models_are_reported_with_the_profile_name():
    profile = comfy.resolve_profile(make_cfg(), "anima")
    with pytest.raises(comfy.ComfyError) as info:
        comfy.prepare(comfy.load_workflow(profile["workflow"]), "P", "N", 1, 896, 1152, models={}, profile_name="anima")
    assert "comfy.profiles.anima.models.unet" in str(info.value)


# ---- 兩組 workflow 的差別 ----------------------------------------------------------

def test_anima_workflow_uses_its_own_nodes():
    wf = comfy.load_workflow(comfy.KIND_WORKFLOWS["anima"])
    classes = {node["class_type"] for node in wf.values()}
    assert {"ModelSamplingAuraFlow", "EmptySD3LatentImage"} <= classes
    assert "EmptyFlux2LatentImage" not in classes
    clip = next(node for node in wf.values() if node["class_type"] == "CLIPLoader")
    assert clip["inputs"]["type"] == "lumina2"


def test_prepare_anima_fills_size_and_keeps_the_aura_flow_chain():
    profile = comfy.resolve_profile(make_cfg(), "anima")
    wf, out_id = comfy.prepare(comfy.load_workflow(profile["workflow"]), "P", "N", 7, 704, 1216,
                               models=profile["models"], preset=profile["presets"]["final"], profile_name="anima")
    sampler = next(node for node in wf.values() if node["class_type"] == "KSampler")
    assert (sampler["inputs"]["seed"], sampler["inputs"]["steps"], sampler["inputs"]["cfg"]) == (7, 12, 1.8)
    model_node = wf[sampler["inputs"]["model"][0]]
    assert model_node["class_type"] == "ModelSamplingAuraFlow"
    latent = wf[sampler["inputs"]["latent_image"][0]]
    assert node_size(latent) == (704, 1216)
    assert wf[out_id]["class_type"] == "SaveImage"
    unet = next(node for node in wf.values() if node["class_type"] == "UNETLoader")
    assert unet["inputs"]["unet_name"] == ANIMA["models"]["unet"]


def node_size(node):
    return int(node["inputs"]["width"]), int(node["inputs"]["height"])


def test_profile_presets_are_self_contained():
    cfg = make_cfg()
    cfg["comfy"]["presets"] = {"draft": {"steps": 4}}                 # 頂層的舊預設不影響命名過的 profile
    profile = comfy.resolve_profile(cfg, "anima")
    assert list(profile["presets"]) == ["final"]
    with pytest.raises(comfy.ComfyError) as info:
        comfy.resolve_preset(profile, "draft")
    assert "anima" in str(info.value) and "final" in str(info.value)


def test_loras_are_chained_after_the_preset_lora():
    profile = comfy.resolve_profile(make_cfg(), "anima")
    wf, _ = comfy.prepare(comfy.load_workflow(profile["workflow"]), "P", "N", 1, 896, 1152, models=profile["models"],
                          preset={"steps": 12, "lora": "ANIMA/base.safetensors"}, loras=profile["loras"],
                          profile_name="anima")
    sampler = next(node for node in wf.values() if node["class_type"] == "KSampler")
    last = wf[sampler["inputs"]["model"][0]]
    assert last["class_type"] == "LoraLoaderModelOnly" and last["inputs"]["lora_name"] == "ANIMA/style.safetensors"
    first = wf[last["inputs"]["model"][0]]
    assert first["inputs"]["lora_name"] == "ANIMA/base.safetensors"
    assert wf[first["inputs"]["model"][0]]["class_type"] == "ModelSamplingAuraFlow"


# ---- 檔名與候選 ------------------------------------------------------------------

def test_render_name_puts_the_profile_after_the_preset():
    assert comfy.render_name("p001_k1", 5, None, None, "moss", "moss") == "p001_k1_s5.png"
    assert comfy.render_name("p001_k1", 5, None, None, "anima", "moss") == "p001_k1_s5__anima.png"
    assert comfy.render_name("p001_k1", 5, "draft", "final", "anima", "moss") == "p001_k1_s5_draft__anima.png"
    assert comfy.render_name("p001_k1", 5, "draft", "draft", "anima", "moss") == "p001_k1_s5__anima.png"


def test_candidate_info_reads_two_suffixes(tmp_path):
    project = make_project(tmp_path)
    folder = project.root / "renders" / "ch001"
    folder.mkdir(parents=True)
    for name in ("p001_k1_s12.png", "p001_k1_s34__anima.png", "p001_k1_s56_draft__anima.png"):
        (folder / name).write_bytes(b"x")
    assert [workspace.candidate_info(n) for n in ("p001_k1_s12.png", "p001_k1_s34__anima.png", "p001_k1_s56_draft__anima.png")] == [
        {"file": "p001_k1_s12.png", "seed": 12, "preset": "", "profile": ""},
        {"file": "p001_k1_s34__anima.png", "seed": 34, "preset": "", "profile": "anima"},
        {"file": "p001_k1_s56_draft__anima.png", "seed": 56, "preset": "draft", "profile": "anima"},
    ]
    assert render.existing_seeds(project, 1, "p001_k1", None, None, "anima", "moss") == {34}
    assert render.existing_seeds(project, 1, "p001_k1", "draft", None, "anima", "moss") == {56}
    assert render.existing_seeds(project, 1, "p001_k1", None, None, "moss", "moss") == {12}


# ---- 整條路：兩個 profile 各出一張 -------------------------------------------------

def test_render_jobs_writes_both_profiles_for_the_same_panel(tmp_path, monkeypatch):
    calls = fake_run(monkeypatch)
    project = make_project(tmp_path)
    cfg = make_cfg()
    written = render.render_jobs(project, 1, [one_job(project)], cfg)
    assert written == ["p001_k1_s%s.png" % one_job(project)["run_seeds"][0]]
    written += render.render_jobs(project, 1, [one_job(project, seed=1234)], cfg, profile_name="anima")
    assert written[1] == "p001_k1_s1234__anima.png"
    folder = project.root / "renders" / "ch001"
    assert (folder / written[0]).is_file() and (folder / written[1]).is_file()   # 兩張都在

    moss_wf, anima_wf = calls[0]["wf"], calls[1]["wf"]
    assert calls[0]["base"] == cfg["comfy"]["url"]
    assert next(n for n in moss_wf.values() if n["class_type"] == "CLIPLoader")["inputs"]["clip_name"] == MOSS["models"]["clip"]
    assert next(n for n in anima_wf.values() if n["class_type"] == "CLIPLoader")["inputs"]["type"] == "lumina2"
    assert "EmptyFlux2LatentImage" in {n["class_type"] for n in moss_wf.values()}
    assert "EmptySD3LatentImage" in {n["class_type"] for n in anima_wf.values()}


def test_render_jobs_follows_project_yaml_and_falls_back_to_the_profile_negative(tmp_path, monkeypatch):
    calls = fake_run(monkeypatch)
    project = make_project(tmp_path)
    project = set_project_yaml(project, comfy_profile="anima")
    project.config["negative"] = ""                                   # 專案沒寫負向 → 用 profile 的
    job = one_job(project)
    render.render_jobs(project, 1, [job], make_cfg())
    wf = calls[0]["wf"]
    negatives = [node["inputs"]["text"] for node in wf.values() if node["class_type"] == "CLIPTextEncode"]
    assert ANIMA["negative"] in negatives


def test_render_reports_a_missing_preset_with_the_profile_name(tmp_path, monkeypatch):
    fake_run(monkeypatch)
    project = make_project(tmp_path)
    with pytest.raises(render.RenderError) as info:
        render.render_jobs(project, 1, [one_job(project)], make_cfg(), preset_name="draft", profile_name="anima")
    assert "draft" in str(info.value) and "anima" in str(info.value)


def test_panels_api_can_view_another_profile(tmp_path, monkeypatch):
    """介面臨時換 profile：?profile= 換 presets，project_profile 仍是這一章的預設（N4 UI）。"""
    from fastapi.testclient import TestClient
    import app as app_module
    from t2c import settings as tool_settings

    monkeypatch.setattr(tool_settings, "load", lambda path=None, root=None: {
        "lettering": {}, "_path": "test",
        "comfy": {"url": "http://127.0.0.1:1", "default_profile": "moss",
                  "profiles": {"moss": copy.deepcopy(MOSS), "anima": copy.deepcopy(ANIMA)}}})
    project = set_project_yaml(make_project(tmp_path), comfy_profile="anima")
    client = TestClient(app_module.app, base_url="http://127.0.0.1")
    params = {"project": str(project.root), "chapter": 1}

    viewed = client.get("/api/chapter/panels", params=dict(params, profile="moss")).json()
    assert viewed["profile"] == "moss" and viewed["project_profile"] == "anima"
    assert viewed["presets"] == ["final", "draft"] and viewed["default_preset"] == "final"

    default = client.get("/api/chapter/panels", params=params).json()
    assert default["profile"] == "anima" and default["presets"] == ["final"]

    refused = client.get("/api/chapter/panels", params=dict(params, profile="anima2"))
    assert refused.status_code == 400 and "anima2" in refused.json()["error"]


# ---- 命令列 ----------------------------------------------------------------------

def write_config(tmp_path, cfg):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return path


def test_panels_cli_renders_one_page_with_two_profiles(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / "tools"))
    import panels  # noqa: E402

    calls = []

    def run(base, wf, out_id, should_stop=lambda: False, timeout=1800):
        calls.append(wf)
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setattr(comfy, "run", run)
    project = make_project(tmp_path)
    config = write_config(tmp_path, make_cfg())
    base = [str(project.root), "1", "--page", "1", "--render", "--candidates", "1", "--config", str(config)]

    assert panels.main(base + ["--profile", "anima"]) == 0
    anima_files = sorted(p.name for p in (project.root / "renders" / "ch001").glob("*__anima.png"))
    assert len(anima_files) == 5 and all("_s" in name for name in anima_files)
    assert panels.main(base) == 0                                      # 預設 profile（moss）
    moss_files = sorted(p.name for p in (project.root / "renders" / "ch001").glob("*.png") if "__" not in p.name)
    assert len(moss_files) == 5
    assert {n["class_type"] for n in calls[0].values()} >= {"EmptySD3LatentImage"}
    assert {n["class_type"] for n in calls[-1].values()} >= {"EmptyFlux2LatentImage"}

    assert panels.main(base + ["--profile", "anima2"]) == 2
    assert "anima2" in capsys.readouterr().err
