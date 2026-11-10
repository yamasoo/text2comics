"""極簡 Markdown → 單檔 HTML（只給 docs 與 README 用，沒有第三方依賴）。

支援：ATX 標題（#～####）、段落、無序清單、表格、圍欄程式碼區塊（```）、引用（>）、
行內 **粗體**、`程式碼`、[連結](網址)。輸出是一份自帶樣式的單檔 HTML（不連 CDN、沒有外部資源）。

用法：
    python tools/md2html.py README.md README.html --title "文字轉漫畫"
"""
import argparse
import html
import re
from pathlib import Path

CSS = """
:root { --ink: #1c1f26; --ink-2: #4b5262; --line: #d8dce3; --bg: #fbfbf9; --paper: #fff; --accent: #8c2f26; --code: #f2f3f5; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 16px/1.78 -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft JhengHei", "PingFang TC", "Noto Sans TC", sans-serif; }
.page { max-width: 52rem; margin: 0 auto; padding: 3rem 1.5rem 6rem; background: var(--paper);
  box-shadow: 0 0 0 1px var(--line); }
.doc h1 { font-size: 2rem; line-height: 1.3; margin: 0 0 1rem; letter-spacing: .01em; }
.doc h1 + p { color: var(--ink-2); }
.doc h2 { font-size: 1.4rem; margin: 2.6rem 0 .8rem; padding-bottom: .35rem; border-bottom: 1px solid var(--line); }
.doc h3 { font-size: 1.12rem; margin: 1.8rem 0 .6rem; }
.doc h4 { font-size: 1rem; margin: 1.4rem 0 .4rem; }
.doc p, .doc li { color: var(--ink); }
.doc a { color: var(--accent); text-decoration-thickness: 1px; text-underline-offset: 2px; }
.doc img { display: block; max-width: 100%; height: auto; margin: 1.2rem 0; }
.doc ul { padding-left: 1.35rem; }
.doc li { margin: .3rem 0; }
.doc code { background: var(--code); padding: .1em .35em; border-radius: 3px;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; font-size: .9em; }
.doc pre { background: #23252b; color: #e9ecf1; padding: 1rem 1.1rem; border-radius: 6px; overflow-x: auto; }
.doc pre code { background: none; color: inherit; padding: 0; font-size: .86rem; line-height: 1.6; }
.doc blockquote { margin: 1.2rem 0; padding: .6rem 1rem; border-left: 3px solid var(--accent);
  background: #faf7f6; color: var(--ink-2); }
.doc blockquote p { margin: 0; }
.doc table { width: 100%; border-collapse: collapse; margin: 1.1rem 0; font-size: .95rem; }
.doc th, .doc td { border: 1px solid var(--line); padding: .5rem .7rem; text-align: left; vertical-align: top; }
.doc th { background: var(--code); font-weight: 600; }
.doc td code, .doc th code { white-space: nowrap; }
@media (max-width: 640px) { .page { padding: 1.6rem 1rem 4rem; } .doc table { display: block; overflow-x: auto; } }
@media print { body { background: #fff; } .page { box-shadow: none; max-width: none; padding: 0; } }
"""


def inline(text):
    """行內的粗體、程式碼與連結（先跳脫 HTML，再套標記）。"""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", lambda m: "<code>%s</code>" % m.group(1), out)
    out = re.sub(r"\*\*([^*]+)\*\*", lambda m: "<strong>%s</strong>" % m.group(1), out)
    out = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                 lambda m: '<img src="%s" alt="%s">' % (html.escape(m.group(2)), html.escape(m.group(1))), out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: '<a href="%s">%s</a>' % (html.escape(m.group(2)), m.group(1)), out)
    return out


def convert(markdown, title=""):
    lines = markdown.replace("\r\n", "\n").split("\n")
    out, i, in_list = [], 0, ""          # in_list：""／"ul"／"ol"

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</%s>" % in_list)
            in_list = ""

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):                      # 圍欄程式碼
            close_list()
            block, i = [], i + 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>%s</code></pre>" % html.escape("\n".join(block)))
            continue
        if re.match(r"^#{1,4} ", line):
            close_list()
            level = len(line) - len(line.lstrip("#"))
            out.append("<h%d>%s</h%d>" % (level, inline(line[level + 1:].strip()), level))
            i += 1
            continue
        if line.startswith(">"):
            close_list()
            quoted = []
            while i < len(lines) and lines[i].startswith(">"):
                quoted.append(lines[i].lstrip(">").strip())
                i += 1
            out.append("<blockquote><p>%s</p></blockquote>" % inline(" ".join(q for q in quoted if q)))
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|", lines[i + 1]):
            close_list()
            rows = []
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>%s</tr></thead><tbody>" % "".join("<th>%s</th>" % inline(c) for c in header))
            for row in rows:
                out.append("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in row))
            out.append("</tbody></table>")
            continue
        bullet = re.match(r"^\s*[-*] ", line)
        numbered = re.match(r"^\s*\d+[.)] ", line)
        if bullet or numbered:
            want = "ul" if bullet else "ol"
            if in_list != want:
                close_list()
                out.append("<%s>" % want)
                in_list = want
            text = re.sub(r"^\s*(?:[-*]|\d+[.)]) ", "", line).strip()
            out.append("<li>%s</li>" % inline(text))
            i += 1
            continue
        if not line.strip():
            close_list()
            i += 1
            continue
        close_list()
        paragraph = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4} |\s*[-*] |\s*\d+[.)] |\||>|```)", lines[i]):
            paragraph.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % inline(" ".join(paragraph)))
    close_list()
    body = "\n".join(out)
    return ("<!doctype html>\n<html lang=\"zh-Hant-TW\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n<title>%s</title>\n"
            "<style>%s</style>\n</head>\n<body>\n<div class=\"page\"><article class=\"doc\">\n%s\n"
            "</article></div>\n</body>\n</html>\n") % (html.escape(title or "說明"), CSS, body)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Markdown → 單檔 HTML（沒有第三方依賴）")
    ap.add_argument("source", help="來源 .md")
    ap.add_argument("target", help="輸出 .html")
    ap.add_argument("--title", default="", help="HTML 的 <title>")
    args = ap.parse_args(argv)
    text = Path(args.source).read_text(encoding="utf-8")
    Path(args.target).write_text(convert(text, args.title), encoding="utf-8", newline="\n")
    print("寫出 %s" % args.target)


if __name__ == "__main__":
    main()
