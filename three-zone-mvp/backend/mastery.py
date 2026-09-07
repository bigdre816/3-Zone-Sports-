"""Load and render Three Zone Mastery as printable HTML. Stdlib only."""

from __future__ import annotations

import html
import os
import re

MASTERY_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "THREE_ZONE_MASTERY.md")
)

_PRINT_CSS = """
@page { margin: 0.7in; }
html, body { background: #fff; color: #111; }
body { font: 12pt/1.45 Georgia, "Times New Roman", serif; max-width: 820px; margin: 0 auto; padding: 24px; }
h1 { font-size: 26pt; margin: 0 0 8px; page-break-after: avoid; }
h2 { font-size: 16pt; margin: 28px 0 10px; border-bottom: 2px solid #111; padding-bottom: 4px; page-break-after: avoid; }
h3 { font-size: 13pt; margin: 18px 0 6px; page-break-after: avoid; }
h4 { font-size: 12pt; margin: 14px 0 4px; }
p { margin: 0 0 10px; }
ul, ol { margin: 0 0 12px 22px; }
li { margin: 0 0 4px; }
code { font: 10pt ui-monospace, SFMono-Regular, Menlo, monospace; background: #f3f5f8; padding: 0 3px; }
pre { font: 9.5pt/1.35 ui-monospace, SFMono-Regular, Menlo, monospace; background: #f3f5f8; border: 1px solid #d0d7de; padding: 10px; overflow: auto; white-space: pre-wrap; }
table { width: 100%; border-collapse: collapse; margin: 8px 0 16px; font-size: 10pt; }
th, td { border: 1px solid #cdd5de; padding: 5px 7px; text-align: left; vertical-align: top; }
th { background: #eef2f6; }
.eyebrow { color: #4a5460; font: 11pt sans-serif; letter-spacing: .08em; text-transform: uppercase; }
.toolbar { font: 12pt sans-serif; margin: 0 0 18px; }
.toolbar button { font: inherit; padding: 8px 14px; }
@media print {
  .toolbar { display: none !important; }
  a { color: inherit; text-decoration: none; }
}
"""


def load_markdown() -> str:
    with open(MASTERY_PATH, encoding="utf-8") as handle:
        return handle.read()


def _inline(text: str) -> str:
    parts: list[str] = []
    last = 0
    for match in re.finditer(r"`([^`]+)`|\*\*([^*]+)\*\*", text):
        parts.append(html.escape(text[last:match.start()]))
        if match.group(1) is not None:
            parts.append("<code>" + html.escape(match.group(1)) + "</code>")
        else:
            parts.append("<strong>" + html.escape(match.group(2)) + "</strong>")
        last = match.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)


def markdown_to_html(source: str) -> str:
    lines = source.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    in_ul = in_ol = in_table = in_code = False
    code_lines: list[str] = []

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def close_table():
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    while i < len(lines):
        line = lines[i]
        if in_code:
            if line.startswith("```"):
                out.append("<pre>" + html.escape("\n".join(code_lines)) + "</pre>")
                code_lines = []
                in_code = False
            else:
                code_lines.append(line)
            i += 1
            continue
        if line.startswith("```"):
            close_lists()
            close_table()
            in_code = True
            code_lines = []
            i += 1
            continue
        if re.match(r"^\s*\|.+\|\s*$", line) and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[i + 1]):
            close_lists()
            close_table()
            headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(h)}</th>" for h in headers) + "</tr></thead><tbody>")
            in_table = True
            i += 2
            continue
        if in_table:
            if re.match(r"^\s*\|.+\|\s*$", line):
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
                i += 1
                continue
            close_table()
        if not line.strip():
            close_lists()
            i += 1
            continue
        if line.startswith("# "):
            close_lists(); close_table()
            out.append("<h1>" + _inline(line[2:].strip()) + "</h1>")
        elif line.startswith("## "):
            close_lists(); close_table()
            out.append("<h2>" + _inline(line[3:].strip()) + "</h2>")
        elif line.startswith("### "):
            close_lists(); close_table()
            out.append("<h3>" + _inline(line[4:].strip()) + "</h3>")
        elif line.startswith("#### "):
            close_lists(); close_table()
            out.append("<h4>" + _inline(line[5:].strip()) + "</h4>")
        elif line.strip() in ("---", "***"):
            close_lists(); close_table()
            out.append("<hr />")
        elif re.match(r"^\s*[-*] ", line):
            close_table()
            if in_ol:
                out.append("</ol>"); in_ol = False
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append("<li>" + _inline(re.sub(r"^\s*[-*] ", "", line)) + "</li>")
        elif re.match(r"^\s*\d+\. ", line):
            close_table()
            if in_ul:
                out.append("</ul>"); in_ul = False
            if not in_ol:
                out.append("<ol>"); in_ol = True
            out.append("<li>" + _inline(re.sub(r"^\s*\d+\. ", "", line)) + "</li>")
        else:
            close_lists(); close_table()
            out.append("<p>" + _inline(line.strip()) + "</p>")
        i += 1
    if in_code:
        out.append("<pre>" + html.escape("\n".join(code_lines)) + "</pre>")
    close_lists()
    close_table()
    return "\n".join(out)


def article_html() -> str:
    return markdown_to_html(load_markdown())


def full_page_html() -> str:
    body = article_html()
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8' />"
        "<meta name='viewport' content='width=device-width, initial-scale=1' />"
        "<title>Three Zone Mastery</title><style>" + _PRINT_CSS + "</style></head><body>"
        "<p class='eyebrow'>Owner back portal · printable master map</p>"
        "<div class='toolbar'><button type='button' onclick='window.print()'>Print this guide</button></div>"
        + body
        + "</body></html>"
    )
