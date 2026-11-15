# -*- coding: utf-8 -*-
"""markdown -> PDF через Playwright/Chromium (системные шрифты => кириллица ок).
Использование: python reports/make_pdf.py <in.md> <out.pdf>
"""
import io
import os
import sys

import markdown
from playwright.sync_api import sync_playwright

CSS = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11pt; line-height: 1.45;
       color: #111; max-width: 100%; }
h1 { font-size: 17pt; border-bottom: 2px solid #333; padding-bottom: 4px; }
h2 { font-size: 13.5pt; margin-top: 18px; }
h3 { font-size: 12pt; }
table { border-collapse: collapse; width: 100%; font-size: 9.5pt; margin: 8px 0; }
th, td { border: 1px solid #999; padding: 4px 6px; vertical-align: top; }
th { background: #eee; }
code { background: #f2f2f2; padding: 1px 3px; font-family: Consolas, monospace; font-size: 9pt; }
blockquote { border-left: 3px solid #888; margin: 8px 0; padding: 2px 12px; color: #333;
             background: #fafafa; }
hr { border: none; border-top: 1px solid #ccc; margin: 14px 0; }
"""


def md_to_html(md_text):
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    return "<!doctype html><html><head><meta charset='utf-8'><style>%s</style>" \
           "</head><body>%s</body></html>" % (CSS, body)


def to_pdf(md_path, pdf_path):
    md_text = io.open(md_path, encoding="utf-8").read()
    html = md_to_html(md_text)
    html_path = os.path.splitext(pdf_path)[0] + ".html"
    io.open(html_path, "w", encoding="utf-8").write(html)
    url = "file:///" + os.path.abspath(html_path).replace("\\", "/")
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(url, wait_until="networkidle")
        page.pdf(path=pdf_path, format="A4", print_background=True,
                 margin={"top": "10mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        b.close()
    os.remove(html_path)
    return os.path.getsize(pdf_path)


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "reports/analytics-note-2026-11.md"
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + ".pdf"
    size = to_pdf(src, dst)
    print("PDF:", dst, size, "bytes")
