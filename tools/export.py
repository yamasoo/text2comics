#!/usr/bin/env python3
"""輸出：把已經輸出的頁面（pages/chNNN/pNNN.png）打包成 PDF 或 CBZ（日式右翻）。

先用 tools/pages.py（或介面的「輸出頁面」）產生頁面 PNG，再用這個工具打包。

用法（在 text2comics 資料夾執行）：
    python tools/export.py examples/sample_comic 1                      # 整章 → <專案>/out/ch001.pdf
    python tools/export.py examples/sample_comic 1 --format cbz         # 整章 → out/ch001.cbz
    python tools/export.py examples/sample_comic 1 --format all         # PDF 與 CBZ 都做
    python tools/export.py examples/sample_comic 1 --page 3             # 只輸出第 3 頁 → out/ch001_p003.pdf
    python tools/export.py examples/sample_comic 1 --out E:\\books       # 放到別的資料夾（或給完整檔名）
    python tools/export.py examples/sample_comic 1 --quality 95         # PDF 內頁 JPEG 品質（預設 90）
    python tools/export.py examples/sample_comic 1 --lossless           # PDF 內頁無損（檔案大很多）
    python tools/export.py examples/sample_comic 1 --single             # PDF 用單頁檢視開啟（預設雙頁、第 1 頁在右）
PDF 設了 /Direction /R2L；CBZ 的 ComicInfo.xml 是 Manga=YesAndRightToLeft。
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import compose, export  # noqa: E402
from t2c.project import Project, ProjectError  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="頁面 PNG → PDF／CBZ（右翻）")
    ap.add_argument("project", help="漫畫專案資料夾（有 project.yaml）")
    ap.add_argument("chapter", type=int, help="章節編號")
    ap.add_argument("--format", choices=["pdf", "cbz", "all"], default="pdf", help="輸出格式（預設 pdf）")
    ap.add_argument("--page", type=int, help="只輸出這一頁")
    ap.add_argument("--out", help="輸出資料夾，或完整檔名（預設 <專案>/out/）")
    ap.add_argument("--quality", type=int, default=export.DEFAULT_QUALITY, help="PDF 內頁 JPEG 品質 1–95（預設 %d）" % export.DEFAULT_QUALITY)
    ap.add_argument("--lossless", action="store_true", help="PDF 內頁無損（Flate），不用 JPEG")
    ap.add_argument("--single", action="store_true", help="PDF 用單頁檢視開啟（預設雙頁，第 1 頁單獨在右）")
    args = ap.parse_args(argv)

    formats = ["pdf", "cbz"] if args.format == "all" else [args.format]
    try:
        if len(formats) > 1 and args.out and Path(args.out).suffix:
            raise export.ExportError("同時輸出 PDF 與 CBZ 時，--out 要給資料夾，不是檔名")
        project = Project(args.project)
        for fmt in formats:
            path, warnings = export.export_chapter(project, args.chapter, fmt, page=args.page, out=args.out,
                                                   quality=None if args.lossless else args.quality, spread=not args.single)
            for message in warnings:
                print("警告：%s" % message, file=sys.stderr)
            print("%s → %s（%.1f MB）" % (fmt.upper(), path, path.stat().st_size / 1048576))
    except (ProjectError, compose.ComposeError, export.ExportError) as error:
        print("錯誤：%s" % error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
