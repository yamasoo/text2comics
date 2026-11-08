#!/usr/bin/env python3
"""分鏡 → 每格的 MOSS layout prompt；加 --render 就送 ComfyUI 出圖。

用法（在 text2comics 資料夾執行）：
    python tools/panels.py examples/sample_comic 1                 # 只編譯第 1 章，寫到 build/ch001/
    python tools/panels.py examples/sample_comic 1 --page 1        # 只編譯第 1 頁
    python tools/panels.py examples/sample_comic 1 --page 1 --render --candidates 3
出圖結果放 renders/ch001/p001_k1_s<seed>.png，每格每個 seed 一張。已經存在的檔案會跳過（加 --force 重畫）。
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

    cfg = settings.load(args.config)
    base = cfg["comfy"]["url"]
    workflow = comfy.load_workflow(ROOT / cfg["comfy"].get("workflow", "workflows/moss_layout.api.json"))
    renders = project.out_dir("renders", chapter)
    total = sum(len(job["seeds"]) for job in jobs)
    done = 0
    for job in jobs:
        for seed in job["seeds"]:
            done += 1
            target = renders / ("%s_s%d.png" % (job["id"], seed))
            if target.exists() and not args.force:
                print("[%d/%d] 略過（已存在）%s" % (done, total, target.name))
                continue
            wf, out_id = comfy.prepare(workflow, job["prompt"], job["negative"], seed, job["width"], job["height"],
                                       models=cfg["comfy"].get("models"), prefix="text2comics/%s" % chapter)
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
