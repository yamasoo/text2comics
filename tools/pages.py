#!/usr/bin/env python3
"""選圖＋組版：把每格選好的圖排成頁面 PNG（pages/chNNN/pNNN.png）。

用法（在 text2comics 資料夾執行）：
    python tools/pages.py examples/sample_comic 1                     # 組整章
    python tools/pages.py examples/sample_comic 1 --page 1            # 只組第 1 頁
    python tools/pages.py examples/sample_comic 1 --list              # 列出每格的候選與目前選的
    python tools/pages.py examples/sample_comic 1 --pick p001_k1=1390808158      # 選圖（seed 或檔名），寫進 picks/ch001.json
    python tools/pages.py examples/sample_comic 1 --focus p001_k1=0.3,0.6        # 裁切焦點（原圖比例 x,y）
    python tools/pages.py examples/sample_comic 1 --zoom p001_k1=1.5             # 再放大（1–4）
    python tools/pages.py examples/sample_comic 1 --numbers           # 在每格標 slot 編號（檢查閱讀順序用）
    python tools/pages.py examples/sample_comic 1 --color             # 保留原色（預設轉灰階）
    python tools/pages.py examples/sample_comic 1 --no-letter         # 只組版、不嵌字
    python tools/pages.py examples/sample_comic 1 --guides            # 嵌字加上臉框與 anchor（檢查自動位置用）
--pick／--focus／--zoom 可重複；先寫入 picks 再組版。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import compose, letter, settings  # noqa: E402
from t2c.compile import CompileError, compile_chapter  # noqa: E402
from t2c.project import Project, ProjectError  # noqa: E402


def _pairs(items, what):
    result = {}
    for item in items or []:
        if "=" not in item:
            raise compose.ComposeError("%s 要寫成 格id=值（例：p001_k1=…），目前是 %r" % (what, item))
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _panel_ids(storyboard):
    return [p.get("id") or "p%03d_k%d" % (pg["page"], p["slot"])
            for pg in storyboard.get("pages") or [] for p in sorted(pg.get("panels") or [], key=lambda x: x["slot"])]


def apply_edits(project, chapter, storyboard, picks, pick, focus, zoom):
    """把 --pick／--focus／--zoom 套到 picks（就地修改），回傳是否有變動。"""
    ids = set(_panel_ids(storyboard))
    changed = False
    for pid in set(pick) | set(focus) | set(zoom):
        if pid not in ids:
            raise compose.ComposeError("分鏡裡沒有格「%s」" % pid)
    for pid, value in pick.items():
        name = "%s_s%d.png" % (pid, int(value)) if value.isdigit() else value
        entry = dict(picks.get(pid) or {})
        entry["image"] = name
        picks[pid] = entry
        changed = True
    for pid, value in focus.items():
        try:
            fx, fy = (float(v) for v in value.split(","))
        except ValueError:
            raise compose.ComposeError("--focus 要寫成 格id=x,y（兩個 0–1 的數字），目前是 %s=%s" % (pid, value))
        if pid not in picks:
            raise compose.ComposeError("「%s」還沒有選圖，請先加 --pick %s=<seed 或檔名>" % (pid, pid))
        picks[pid]["focus"] = [fx, fy]
        changed = True
    for pid, value in zoom.items():
        try:
            z = float(value)
        except ValueError:
            raise compose.ComposeError("--zoom 要寫成 格id=數字，目前是 %s=%s" % (pid, value))
        if pid not in picks:
            raise compose.ComposeError("「%s」還沒有選圖，請先加 --pick %s=<seed 或檔名>" % (pid, pid))
        picks[pid]["zoom"] = z
        changed = True
    for pid in set(pick) | set(focus) | set(zoom):      # 寫檔前整筆驗證，也確認圖存在
        picks[pid] = compose.check_pick(pid, picks[pid])
        if not (compose.renders_dir(project, chapter) / picks[pid]["image"]).is_file():
            raise compose.ComposeError("「%s」選的圖不存在：renders/%s/%s" % (pid, compose.chapter_name(chapter), picks[pid]["image"]))
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description="選圖＋組版 → 頁面 PNG")
    ap.add_argument("project", help="漫畫專案資料夾（有 project.yaml）")
    ap.add_argument("chapter", type=int, help="章節編號")
    ap.add_argument("--page", type=int, help="只處理這一頁")
    ap.add_argument("--list", action="store_true", help="列出每格的候選與目前選的，不組版")
    ap.add_argument("--pick", action="append", help="格id=seed或檔名（可重複）")
    ap.add_argument("--focus", action="append", help="格id=x,y（可重複）")
    ap.add_argument("--zoom", action="append", help="格id=倍率（可重複）")
    ap.add_argument("--numbers", action="store_true", help="每格標上 slot 編號（只用來檢查順序）")
    ap.add_argument("--color", action="store_true", help="保留原色（預設轉灰階）")
    ap.add_argument("--out", help="輸出資料夾（預設 pages/chNNN/）")
    ap.add_argument("--no-letter", action="store_true", help="只組版，不嵌字")
    ap.add_argument("--guides", action="store_true", help="嵌字時畫出臉框與 anchor（檢查用，不是正式輸出）")
    ap.add_argument("--config", help="工具設定檔（預設 config.json，沒有就用 config.example.json）")
    args = ap.parse_args(argv)

    try:
        project = Project(args.project)
        storyboard = project.load_storyboard(args.chapter)
        compile_chapter(project, storyboard, only_page=args.page)      # 先過分鏡驗證（模板、slot、角色…）
        picks = compose.load_picks(project, args.chapter)
        if apply_edits(project, args.chapter, storyboard, picks, _pairs(args.pick, "--pick"),
                       _pairs(args.focus, "--focus"), _pairs(args.zoom, "--zoom")):
            print("已更新 %s" % compose.save_picks(project, args.chapter, picks))
        if args.list:
            for pid in _panel_ids(storyboard):
                chosen = (picks.get(pid) or {}).get("image")
                print(pid + ("" if chosen else "  （未選）"))
                for name in compose.candidates(project, args.chapter, pid):
                    print("  %s %s" % ("*" if name == chosen else " ", name))
            return 0
        lettering = None
        if not args.no_letter:
            lettering = letter.Settings.from_config(settings.load(args.config).get("lettering"))
        written, warnings = compose.compose_chapter(project, args.chapter, storyboard, only_page=args.page, picks=picks,
                                                    gray=not args.color, numbers=args.numbers, out_dir=args.out,
                                                    lettering=lettering, guides=args.guides)
    except (ProjectError, CompileError, compose.ComposeError, letter.LetterError) as error:
        print("錯誤：%s" % error, file=sys.stderr)
        return 2
    for message in warnings:
        print("警告：%s" % message, file=sys.stderr)
    for page, path in written:
        print("第 %d 頁 → %s" % (page, path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
