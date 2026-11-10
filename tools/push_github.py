"""一鍵推上 GitHub：清除開發資料 → 產生公開快照 → 更新 v1_baseline／main／gh-pages → 推送。

用法（雙擊 `push_github.bat` 也可以）：
    python tools/push_github.py                # 跑測試 → 建快照 → 推 main（與 gh-pages）
    python tools/push_github.py --dry-run      # 只建快照與檢查，不改分支、不推（會印出摘要）
    python tools/push_github.py --no-push      # 改本機分支但不推
    python tools/push_github.py --skip-tests --allow-dirty --message "…"

預設只更新 'main'（GitHub 的預設分支）；要一起更新 'v1_baseline' 加 `--branches main,v1_baseline`。
公開版拿掉：工作資料（work/）、內部文件（docs/00、06、07、HANDOFF、backlog、qa、reports、cases）、
本機設定（config.json）。加上：README.html、範例專案的縮圖（examples/sample_comic/renders）。
所有本機絕對路徑會換成 <專案根目錄> 之類的佔位字。
"""
import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 不進公開版的開發資料（相對於專案根目錄）
EXCLUDE = (
    "work",
    "docs/00_階段計畫.md",
    "docs/06_決策記錄.md",
    "docs/07_微調簡報.md",
    "docs/HANDOFF.md",
    "docs/backlog.md",
    "docs/qa",
    "docs/reports",
    "docs/cases",
    "config.json",
    "config.json.bak",
    "config.json.tmp",
    "secrets.json",
    ".venv",
    ".pytest_cache",
    "__pycache__",
)

# 要換成本機絕對路徑的檔案類型
TEXT_EXT = {".md", ".py", ".json", ".js", ".html", ".bat", ".sh", ".css", ".txt", ".yaml", ".yml", ".svg"}

# 本機路徑 → 公開版的佔位字
REPLACEMENTS = (
    (re.compile(r"E:[\\/]dev[\\/]text2comics", re.I), "<專案根目錄>"),
    (re.compile(r"E:[\\/]dev[\\/]front-end", re.I), "<fekit 專案根>"),
    (re.compile(r"E:[\\/]novel-studio", re.I), "<Novel Studio 根目錄>"),
    (re.compile(r"E:[\\/]text_2_visual_novel", re.I), "<t2vn 根目錄>"),
)

SAMPLE_RENDERS = "examples/sample_comic/renders/ch001"
SAMPLE_MAX_EDGE = 768           # 公開版範例圖的長邊上限（15 張縮完約 4–5 MB）
SAMPLE_COLORS = 64              # 漫畫是黑白＋網點，調色盤 64 色就夠，體積差很多


def say(text):
    print(text, flush=True)


def run(args, check=True, capture=True):
    result = subprocess.run(args, cwd=str(ROOT), capture_output=capture, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise SystemExit("指令失敗（%s）：\n%s%s" % (" ".join(args), (result.stdout or ""), (result.stderr or "")))
    return result


def git(*args, check=True):
    return run(["git", *args], check=check)


def version():
    text = (ROOT / "t2c" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else "?"


def export_head(target):
    """把目前的 HEAD（已 commit 的內容）解到 target；未 commit 的東西不會進去。"""
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=str(ROOT), capture_output=True)
    if data.returncode != 0:
        raise SystemExit("git archive 失敗：%s" % data.stderr.decode("utf-8", "replace"))
    with tarfile.open(fileobj=io.BytesIO(data.stdout)) as tar:
        tar.extractall(target)


def strip_excluded(target):
    removed = []
    for rel in EXCLUDE:
        path = target / rel
        if path.is_dir():
            shutil.rmtree(path)
            removed.append(rel + "/")
        elif path.is_file():
            path.unlink()
            removed.append(rel)
    return removed


def build_readme_html(target):
    run([sys.executable, str(ROOT / "tools" / "md2html.py"), str(ROOT / "README.md"), str(target / "README.html"),
         "--title", "文字轉漫畫 text2comics"])


def shrink_sample_renders(target):
    """範例專案的出圖縮小後放進公開版：下載下來就有圖可以走到「頁面」。"""
    from PIL import Image

    source = ROOT / SAMPLE_RENDERS
    if not source.is_dir():
        return None, "本機沒有 %s，公開版不會附範例出圖" % SAMPLE_RENDERS
    out = target / SAMPLE_RENDERS
    out.mkdir(parents=True, exist_ok=True)
    count, total = 0, 0
    for png in sorted(source.glob("*.png")):
        with Image.open(png) as image:
            image = image.convert("L", dither=Image.Dither.NONE) if image.mode in ("L", "1") else image.convert("L")
            image.thumbnail((SAMPLE_MAX_EDGE, SAMPLE_MAX_EDGE))
            dest = out / png.name
            image.convert("P", palette=Image.ADAPTIVE, colors=SAMPLE_COLORS).save(dest, format="PNG", optimize=True)
        count += 1
        total += dest.stat().st_size
    return (count, total), ""


def rewrite_paths(target):
    changed = 0
    for path in target.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = text
        for pattern, repl in REPLACEMENTS:
            new = pattern.sub(repl, new)
        if new != text:
            path.write_text(new, encoding="utf-8", newline="\n")
            changed += 1
    return changed


def public_index(target):
    """gh-pages 的首頁：README.html 改名成 index.html，圖一起帶過去。"""
    page = target / "README.html"
    html = page.read_text(encoding="utf-8")
    html = html.replace("docs/images/flow.svg", "flow.svg")
    (target / "index.html").write_text(html, encoding="utf-8", newline="\n")
    shutil.copy2(target / "docs" / "images" / "flow.svg", target / "flow.svg")


def commit_tree(target, branch, message, parent=None, keep=None):
    """把 target 變成一個 commit（用暫存 index 與 GIT_WORK_TREE，不動工作目錄）。
    keep：只留這些路徑（給 gh-pages 用）；路徑相對於 target。"""
    index = Path(tempfile.mkdtemp(prefix="t2c-index-")) / "index"
    env = dict(os.environ, GIT_DIR=str(ROOT / ".git"), GIT_WORK_TREE=str(target), GIT_INDEX_FILE=str(index))

    def git_at(*args):
        return subprocess.run(["git", *args], cwd=str(target), env=env, capture_output=True, text=True)

    def must(result, what):
        if result.returncode != 0:
            raise SystemExit("git %s 失敗：%s" % (what, (result.stderr or result.stdout or "").strip()))
        return result.stdout.strip()

    must(git_at("read-tree", "--empty"), "read-tree")
    must(git_at("add", "-A", "-f", "--", *(keep or ["."])), "add")
    tree = must(git_at("write-tree"), "write-tree")
    args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
    sha = must(git_at(*args), "commit-tree")
    shutil.rmtree(index.parent, ignore_errors=True)
    if branch:
        subprocess.run(["git", "update-ref", "refs/heads/%s" % branch, sha], cwd=str(ROOT), check=True)
    return sha


def tree_stats(target):
    files = [p for p in target.rglob("*") if p.is_file()]
    size = sum(p.stat().st_size for p in files)
    return len(files), size


def main(argv=None):
    ap = argparse.ArgumentParser(description="清除開發資料後推送公開版到 GitHub")
    ap.add_argument("--dry-run", action="store_true", help="只建快照與檢查，不改分支、不推")
    ap.add_argument("--no-push", action="store_true", help="更新本機分支但不推")
    ap.add_argument("--skip-tests", action="store_true", help="不跑 pytest（不建議）")
    ap.add_argument("--allow-dirty", action="store_true", help="工作目錄有未 commit 的變更也照做（那些變更不會進公開版）")
    ap.add_argument("--message", default="", help="公開版的 commit 訊息")
    ap.add_argument("--branches", default="main", help="要更新的分支，逗號分隔（預設 main；要連 v1_baseline 就寫 main,v1_baseline）")
    ap.add_argument("--no-pages", action="store_true", help="不建／不推 gh-pages（說明頁）")
    args = ap.parse_args(argv)

    say("文字轉漫畫：準備公開版（版本 %s）" % version())
    git("rev-parse", "--is-inside-work-tree")

    dirty = git("status", "--porcelain").stdout.strip()
    if dirty and not args.allow_dirty:
        say("工作目錄有未 commit 的變更，先 commit 再推（或加 --allow-dirty 只推已 commit 的內容）：")
        say(dirty[:2000])
        return 2

    if not args.skip_tests:
        say("① 跑測試…")
        result = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q"], cwd=str(ROOT), text=True)
        if result.returncode != 0:
            say("測試沒過，停止（--skip-tests 可以跳過，但不建議）")
            return 3

    targets = [b.strip() for b in args.branches.split(",") if b.strip()]
    if not targets:
        say("--branches 是空的")
        return 2

    say("② 抓遠端分支（讓推送是 fast-forward）…")
    git("fetch", "origin", "--prune", check=False)
    bases = {b: git("rev-parse", "--verify", "origin/%s" % b, check=False).stdout.strip() for b in targets}
    for b in targets:
        say("   要更新 %s（本機的快照會接在 %s 後面）" % (b, (bases[b][:12] or "（遠端沒有這個分支，會變第一個 commit）")))

    snapshot = Path(tempfile.mkdtemp(prefix="t2c-public-"))
    try:
        say("③ 取出已 commit 的內容 → %s" % snapshot)
        export_head(snapshot)
        removed = strip_excluded(snapshot)
        say("   移除開發資料 %d 項：%s" % (len(removed), "、".join(removed)))

        say("④ 產生 README.html…")
        build_readme_html(snapshot)

        sample, note = shrink_sample_renders(snapshot)
        if sample:
            say("   範例出圖 %d 張、共 %.1f MB（長邊 ≤ %d）" % (sample[0], sample[1] / 1048576, SAMPLE_MAX_EDGE))
        else:
            say("   ⚠ " + note)

        changed = rewrite_paths(snapshot)
        say("   本機絕對路徑換成佔位字：%d 個檔案" % changed)

        files, size = tree_stats(snapshot)
        say("⑤ 公開版內容：%d 個檔案、%.1f MB" % (files, size / 1048576))

        message = args.message or "公開版 %s（%s）" % (version(), "清除開發資料、附範例出圖與單檔說明")
        if args.dry_run:
            say("（--dry-run）不建 commit、不改分支、不推。")
            return 0

        pushed = []
        for index, branch in enumerate(targets, 6):
            sha = commit_tree(snapshot, branch, message, parent=bases[branch] or None)
            pushed.append(branch)
            say("%s %s → %s" % ("⑥⑦⑧⑨"[index - 6] if index - 6 < 4 else "*", branch, sha[:12]))

        if not args.no_pages:
            public_index(snapshot)
            pages = commit_tree(snapshot, "gh-pages", "公開版說明頁 %s" % version(), parent=None, keep=["index.html", "flow.svg"])
            pushed.append("gh-pages")
            say("   gh-pages → %s（只有 index.html 與 flow.svg）" % pages[:12])

        if args.no_push:
            say("（--no-push）本機分支已更新，沒有推上 GitHub。")
            say("   要推：git push origin %s --force-with-lease" % " ".join(pushed))
            return 0

        say("推上 GitHub：%s" % "、".join(pushed))
        result = subprocess.run(["git", "push", "origin", *pushed, "--force-with-lease"], cwd=str(ROOT), text=True)
        if result.returncode != 0:
            say("推送失敗（看上面的訊息：多半是沒有權限或要先 git pull）")
            return 4
        say("完成：https://github.com/yamasoo/text2comics")
        if "gh-pages" in pushed:
            say("  說明頁（要在 GitHub 的 Settings → Pages 選 gh-pages 分支才會出現）：")
            say("  https://yamasoo.github.io/text2comics/")
        return 0
    finally:
        if not args.dry_run:
            shutil.rmtree(snapshot, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    raise SystemExit(main())
