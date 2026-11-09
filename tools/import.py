#!/usr/bin/env python3
"""整本小說匯入 → 自動切章 → `<專案>/source/chNNN.txt`（一章一個檔）。

用法（在 text2comics 資料夾執行）：
    python tools/import.py <專案> <檔案…>                        # 預覽，不寫檔
    python tools/import.py <專案> <檔案…> --commit               # 寫入
    python tools/import.py <專案> <檔案…> --commit --conflict overwrite
    python tools/import.py <專案> <檔案…> --mode chapter --numbering sequential --start 3
    python tools/import.py <專案> <檔案…> --preface-as-chapter --preface-title 序章
    python tools/import.py <專案> <檔案…> --convert              # 簡轉繁（需要 opencc，沒有就跳過）
    python tools/import.py <專案> <檔案…> --json                 # 給程式看的結果

支援 .txt、.md、.docx（docx 用標準函式庫讀，不需要 python-docx）。
預設只預覽；要真的寫檔要加 --commit。重複匯入預設 skip（已存在的章節不動）；
用 --conflict overwrite 覆寫，覆寫前會備份到 <專案>/build/import/backup/。
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from t2c import importer  # noqa: E402


def _opts(args):
    return {"mode": args.mode, "lang": args.lang, "convert": args.convert,
            "preface_as_chapter": args.preface_as_chapter, "preface_title": args.preface_title,
            "numbering": args.numbering, "start": args.start, "conflict": args.conflict}


def _print_preview(result):
    for src in result["sources"]:
        print("來源：%s（%s，%d 章，簡體字 %d）"
              % (src["name"], src["encoding"], src["chapters"], src["simplified"]))
    print("章節：")
    for c in result["chapters"]:
        flags = ("  ⚠ " + "、".join(c["flags"])) if c.get("flags") else ""
        print("  第 %d 章 %s（%d 字）%s" % (c["no"], c["title"] or "（無章名）", c["chars"], flags))
        if c.get("head"):
            print("      %s…" % c["head"])
    if result["preface"]:
        total = sum(p["chars"] for p in result["preface"])
        print("前言：%d 段、%d 字（預設不匯入；要當成一章加 --preface-as-chapter）"
              % (len(result["preface"]), total))
    for message in result["warnings"]:
        print("提醒：%s" % message)
    print("（預覽，沒有寫入；要寫入加 --commit）")


def _print_commit(result):
    print("已寫入 %d 章 → %s\\source" % (len(result["written"]), result["project"]))
    for item in result["written"]:
        print("  第 %d 章 → %s（%d 字）" % (item["no"], item["file"], item["chars"]))
    if result["skipped"]:
        print("略過 %d 章（已存在）：%s" % (len(result["skipped"]),
                                         "、".join("第%d章" % n for n in result["skipped"])))
    if result["replaced"]:
        print("覆寫 %d 章（舊檔已備份）：%s" % (len(result["replaced"]),
                                           "、".join("第%d章" % n for n in result["replaced"])))
    for item in result["backups"]:
        for path in item["files"]:
            print("  備份：%s" % path)
    for message in result["warnings"]:
        print("提醒：%s" % message)


def main(argv=None):
    ap = argparse.ArgumentParser(description="整本小說匯入 → 自動切章 → source/chNNN.txt")
    ap.add_argument("project", help="漫畫專案資料夾（有 project.yaml）")
    ap.add_argument("files", nargs="+", help="要匯入的檔案（.txt／.md／.docx，可多個）")
    ap.add_argument("--commit", action="store_true", help="真的寫檔（預設只預覽）")
    ap.add_argument("--mode", choices=importer.MODE_CHOICES, default="auto",
                    help="切章方式：auto（先找第X章，找不到再用 # 標題）、chapter、markdown")
    ap.add_argument("--lang", choices=("zh-TW", "en", "ja"), default="zh-TW",
                    help="稿子的語言（影響簡體偵測、簡轉繁與場景分隔線）")
    ap.add_argument("--convert", action="store_true", help="簡轉繁（需要 opencc；沒有安裝就跳過）")
    ap.add_argument("--preface-as-chapter", action="store_true", help="把第一個章節標題之前的文字也當成一章")
    ap.add_argument("--preface-title", default="序章", help="前言那一章的章名（預設：序章）")
    ap.add_argument("--numbering", choices=importer.NUMBERING_CHOICES, default="auto",
                    help="編號：auto（標號連續就沿用）、titles（一定用標題章號）、sequential（依順序重編）")
    ap.add_argument("--start", type=int, default=1, help="sequential 時的起始章號（預設 1）")
    ap.add_argument("--conflict", choices=importer.CONFLICT_CHOICES, default="skip",
                    help="章節檔已存在時：skip（預設）或 overwrite（覆寫前備份）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON（給程式接）")
    args = ap.parse_args(argv)

    opts = _opts(args)
    try:
        if args.commit:
            result = importer.commit(args.project, args.files, opts)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                _print_commit(result)
        else:
            result = importer.preview(args.files, opts)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                _print_preview(result)
    except (importer.ImporterError, OSError) as error:
        print("錯誤：%s" % error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
