#!/usr/bin/env python3
"""
WHITEPAPER_KR.md → PDF 자동 변환기.

우선 순위:
  1. weasyprint 가 설치돼 있으면 HTML 경유 PDF (한글 폰트 + 다크 테마)
  2. 없으면 markdown → HTML 만 생성하고 안내

산출:
  docs/WHITEPAPER_KR.pdf   (또는 .html)
"""

from __future__ import annotations

import os
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "WHITEPAPER_KR.md"
OUT_PDF = ROOT / "docs" / "WHITEPAPER_KR.pdf"
OUT_HTML = ROOT / "docs" / "WHITEPAPER_KR.html"


def md_to_html(md: str) -> str:
    """초경량 markdown 변환기. 헤딩·표·리스트·코드블록·강조·링크만."""
    lines = md.split("\n")
    out: list[str] = []
    in_code = False
    in_table = False
    table_buf: list[str] = []

    def flush_table():
        nonlocal table_buf
        if not table_buf:
            return
        rows = [r for r in table_buf if r.strip()]
        if len(rows) < 2:
            table_buf = []
            return
        head_cells = [c.strip() for c in rows[0].strip("|").split("|")]
        # row 1 is the separator (---)
        body_rows = rows[2:]
        thead = "<tr>" + "".join(f"<th>{c}</th>" for c in head_cells) + "</tr>"
        tbody = ""
        for r in body_rows:
            cells = [c.strip() for c in r.strip("|").split("|")]
            tbody += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
        out.append(f"<table><thead>{thead}</thead><tbody>{tbody}</tbody></table>")
        table_buf = []

    def inline(s: str) -> str:
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                out.append("</code></pre>")
                in_code = False
            else:
                out.append('<pre><code>')
                in_code = True
            continue
        if in_code:
            out.append(re.sub(r"&", "&amp;", line).replace("<", "&lt;").replace(">", "&gt;"))
            continue
        if "|" in line and line.strip().startswith("|"):
            in_table = True
            table_buf.append(line)
            continue
        if in_table:
            flush_table()
            in_table = False

        if not line.strip():
            out.append("")
            continue

        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            continue
        m = re.match(r"^>\s+(.*)$", line)
        if m:
            out.append(f"<blockquote>{inline(m.group(1))}</blockquote>")
            continue
        m = re.match(r"^-\s+(?:\[[ x]\]\s+)?(.*)$", line)
        if m:
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if line.strip() == "---":
            out.append("<hr/>")
            continue
        out.append(f"<p>{inline(line)}</p>")

    if in_table:
        flush_table()
    if in_code:
        out.append("</code></pre>")

    body = "\n".join(out)
    # ul wrapping (간단 휴리스틱: 연속 li 를 ul 로)
    body = re.sub(r"(<li>(?:.|\n)*?</li>(?:\s*<li>(?:.|\n)*?</li>)*)",
                  lambda m: f"<ul>{m.group(0)}</ul>", body)

    return body


CSS = """
@page { size: A4; margin: 22mm 18mm; }
:root {
  --bg: #ffffff;
  --text: #1a2030;
  --muted: #5a7a9a;
  --accent: #006b9c;
  --accent2: #5a3aaa;
  --border: #d8e1ec;
  --code-bg: #f3f6fb;
}
* { box-sizing: border-box; }
html, body {
  font-family: 'Noto Sans KR', 'Malgun Gothic', sans-serif;
  color: var(--text);
  font-size: 10.5pt;
  line-height: 1.6;
  background: var(--bg);
}
h1 { font-size: 26pt; color: var(--accent); border-bottom: 3px solid var(--accent); padding-bottom: 6pt; margin-top: 0; }
h2 { font-size: 17pt; color: var(--accent); margin-top: 18pt; padding-bottom: 4pt; border-bottom: 1px solid var(--border); }
h3 { font-size: 13pt; color: var(--accent2); margin-top: 14pt; }
h4 { font-size: 11pt; color: var(--text); margin-top: 12pt; }
p, li { font-size: 10.5pt; }
em { color: var(--accent); font-style: normal; font-weight: 700; }
strong { color: var(--text); font-weight: 700; }
a { color: var(--accent); text-decoration: none; }
code { font-family: 'JetBrains Mono', 'Consolas', monospace; background: var(--code-bg); padding: 1pt 4pt; border-radius: 3pt; font-size: 9.5pt; color: var(--accent2); }
pre { background: var(--code-bg); padding: 10pt; border-radius: 6pt; border: 1px solid var(--border); overflow-x: auto; page-break-inside: avoid; }
pre code { padding: 0; background: transparent; color: var(--text); font-size: 9pt; }
blockquote { border-left: 3px solid var(--accent); padding: 4pt 12pt; color: var(--muted); margin: 8pt 0; background: rgba(0,107,156,0.04); }
table { width: 100%; border-collapse: collapse; margin: 10pt 0; page-break-inside: avoid; font-size: 9.5pt; }
th, td { border: 1px solid var(--border); padding: 5pt 8pt; text-align: left; vertical-align: top; }
th { background: rgba(0,107,156,0.08); color: var(--accent); font-weight: 700; }
hr { border: none; border-top: 1px dashed var(--border); margin: 16pt 0; }
ul { padding-left: 18pt; }
"""


def render_html(body_html: str) -> str:
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"/>
<title>AuraView K-Perception · 기술 백서</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;700;900&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet"/>
<style>{CSS}</style>
</head><body>{body_html}</body></html>"""


def _convert(src: Path, out_html: Path, out_pdf: Path) -> bool:
    if not src.exists():
        print(f"[skip] {src} 없음")
        return False
    md = src.read_text(encoding="utf-8")
    body = md_to_html(md)
    html = render_html(body)
    out_html.write_text(html, encoding="utf-8")
    print(f"[ok] HTML : {out_html}")
    try:
        from weasyprint import HTML  # type: ignore
    except ImportError:
        print(f"[hint] PDF skip ({src.name}): pip install weasyprint")
        return True
    HTML(string=html).write_pdf(str(out_pdf))
    size_kb = out_pdf.stat().st_size // 1024
    print(f"[ok] PDF  : {out_pdf}  ({size_kb} KB)")
    return True


def main():
    # 1) Whitepaper
    _convert(SRC, OUT_HTML, OUT_PDF)
    # 2) Press Kit (있으면 같이 빌드 — 한 페이지 수상 자료)
    _convert(
        ROOT / "docs" / "PRESS_KIT.md",
        ROOT / "docs" / "PRESS_KIT.html",
        ROOT / "docs" / "PRESS_KIT.pdf",
    )


if __name__ == "__main__":
    main()
