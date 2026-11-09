#!/usr/bin/env python3
"""分鏡 → 每格的 MOSS layout prompt；加 --render 就送 ComfyUI 出圖。

用法（在 text2comics 資料夾執行）：
    python tools/panels.py examples/sample_comic 1                 # 只編譯第 1 章，寫到 build/ch001/
    python tools/panels.py examples/sample_comic 1 --page 1        # 只編譯第 1 頁
    python tools/panels.py examples/sample_comic 1 --page 1 --render --candidates 3
    python tools/panels.py examples/sample_comic 1 --page 1 --render --preset draft          # 4 步＋LoRA 的草稿（較快）
    python tools/panels.py examples/sample_comic 1 --page 1 --render --seed 1390808158        # 只畫指定的 seed（例如重畫定稿）
出圖結果放 renders/ch001/p001_k1_s<seed>.png，每格每個 seed 一張。已經存在的檔案會跳過（加 --force 重畫）。
出圖 profile（workflow、模型、預設、LoRA）寫在 config.json 的 comfy.profiles，專案用 project.yaml 的
comfy_profile 指定，也可以用 --profile 臨時換（例：--profile anima）；不是預設 profile 的，檔名會加
__<profile>，所以同一頁兩個 profile 的圖不會互相蓋掉，例如 p001_k1_s1390808158__anima.png。
出圖預設用 --preset 選；不是該 profile 的 default_preset 的預設，檔名再加 _<預設>。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import comfy, settings  # noqa: E402
from t2c.compile import CompileError, compile_chapter, save_job  # noqa: E402
from t2c.project import Project, ProjectError  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="分鏡 → MOSS-Image 每格提示詞／出圖")
    ap.add_argument("project", help="漫畫專案資料夾（有 project.yaml）")
    ap.add_argument("chapter", type=int, help="章節編號")
    ap.add_argument("--page", type=int, help="只處理這一頁")
    ap.add_argument("--render", action="store_true", help="送 ComfyUI 出圖")
    ap.add_argument("--candidates", type=int, help="每格幾個 seed（覆蓋 project.yaml）")
    ap.add_argument("--profile", help="出圖 profile 名稱（config.json 的 comfy.profiles）；省略用 project.yaml 的 comfy_profile，再沒有就 comfy.default_profile")
    ap.add_argument("--preset", help="出圖預設名稱（該 profile 的 presets）；省略用它的 default_preset")
    ap.add_argument("--seed", type=int, action="append", help="只畫這個 seed（可重複）；必須是該格 seeds 裡的")
    ap.add_argument("--force", action="store_true", help="已經有的圖也重畫")
    ap.add_argument("--config", help="指定 config.json")
    args = ap.parse_args(argv)

    try:
        project = Project(args.project)
        overrides = {"candidates": args.candidates} if args.candidates else None
        jobs = compile_chapter(project, project.load_storyboard(args.chapter), only_page=args.page, overrides=overrides)
    except (ProjectError, CompileError) as error:
        print("錯誤：%s" % error, file=sys.stderr)
        return 2

    chapter = "ch%03d" % args.chapter
    build = project.out_dir("build", chapter)
    for job in jobs:
        save_job(build, job)
    print("已編譯 %d 格 → %s" % (len(jobs), build))
    if not args.render:
        return 0

    cfg = settings.load(args.config, root=ROOT)
    try:
        profile = comfy.resolve_profile(cfg, name=args.profile, project_config=project.config)
        workflow = comfy.load_workflow(profile["workflow"])
        default_profile = comfy.default_profile_name(cfg)
        preset_name, preset, default_preset = comfy.resolve_preset(profile, args.preset)
    except comfy.ComfyError as error:
        print("錯誤：%s" % error, file=sys.stderr)
        return 2
    base = profile["base_url"]
    only = set(args.seed or [])
    for job in jobs:
        job["run_seeds"] = [s for s in job["seeds"] if not only or s in only]
    if only and not any(job["run_seeds"] for job in jobs):
        print("錯誤：--seed %s 不在這些格的 seeds 裡" % "、".join(str(s) for s in sorted(only)), file=sys.stderr)
        return 2
    print("出圖 profile：%s（%s，%s）" % (profile["name"], profile["kind"], profile["workflow"].name))
    if preset_name:
        print("出圖預設：%s%s" % (preset_name, "（LoRA %s）" % preset["lora"] if preset and preset.get("lora") else ""))
    renders = project.out_dir("renders", chapter)
    total = sum(len(job["run_seeds"]) for job in jobs)
    done = 0
    for job in jobs:
        for seed in job["run_seeds"]:
            done += 1
            target = renders / comfy.render_name(job["id"], seed, preset_name, default_preset, profile["name"], default_profile)
            if target.exists() and not args.force:
                print("[%d/%d] 略過（已存在）%s" % (done, total, target.name))
                continue
            negative = job.get("negative") or profile.get("negative") or ""
            wf, out_id = comfy.prepare(workflow, job["prompt"], negative, seed, job["width"], job["height"],
                                       models=profile.get("models"), prefix="text2comics/%s" % chapter, preset=preset,
                                       loras=profile.get("loras"), profile_name=profile["name"])
            try:
                data = comfy.run(base, wf, out_id)
            except comfy.ComfyError as error:
                print("錯誤：%s（%s seed %d）" % (error, job["id"], seed), file=sys.stderr)
                return 3
            target.write_bytes(data)
            print("[%d/%d] %s（%d×%d）" % (done, total, target.name, job["width"], job["height"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
