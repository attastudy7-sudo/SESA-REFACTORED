"""
Render cheatsheet JSON documents to PDF using Playwright + MathJax.

This mirrors the knowly_gen cheatsheet renderer so admins can regenerate a
cheatsheet PDF directly from its JSON sidecar inside the main app.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Optional


_BRAND_INDIGO = "#2563EB"
_BRAND_NAME = "knowly"

_SECTION_ICONS = {
  "formulas": "√",
  "definitions": "📖",
  "rules": "📋",
  "steps": "≡",
  "examples": "💡",
  "summary_table": "⊞",
}


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_entry(entry: dict) -> str:
    label = _escape(entry.get("label", ""))
    content_html = _escape(entry.get("content", "")).replace("\n", "<br>")
    notes = _escape(entry.get("notes", ""))
    example_html = _escape(entry.get("example", "")).replace("\n", "<br>")

    return f"""
    <div class="entry">
      <div class="entry-label">{label}</div>
      <div class="entry-body">
        <div class="entry-content">{content_html}</div>
        {"<div class='entry-notes'>" + notes + "</div>" if notes else ""}
        {"<div class='entry-eg'><span class='eg-tag'>e.g.</span> " + example_html + "</div>" if example_html else ""}
      </div>
    </div>"""


def _render_step_entry(entry: dict, index: int) -> str:
    label = _escape(entry.get("label", ""))
    content_html = _escape(entry.get("content", "")).replace("\n", "<br>")
    notes = _escape(entry.get("notes", ""))
    example_html = _escape(entry.get("example", "")).replace("\n", "<br>")

    return f"""
    <div class="step">
      <div class="step-num">{index}</div>
      <div class="step-body">
        <div class="step-label">{label}</div>
        {"<div class='step-content'>" + content_html + "</div>" if content_html else ""}
        {"<div class='entry-notes'>" + notes + "</div>" if notes else ""}
        {"<div class='entry-eg'><span class='eg-tag'>e.g.</span> " + example_html + "</div>" if example_html else ""}
      </div>
    </div>"""


def _build_html(doc: dict) -> str:
    title = _escape(doc.get("title", "Cheatsheet"))
    course = _escape(doc.get("course", ""))
    level = _escape(doc.get("level", ""))
    metadata = doc.get("metadata", {})
    purpose = _escape(metadata.get("purpose", ""))
    sections = doc.get("sections", [])

    sections_html = ""
    for section in sections:
        sec_title = _escape(section.get("section_title", section.get("title", "")))
        sec_type = str(section.get("section_type", "formulas")).lower()
        icon = _SECTION_ICONS.get(sec_type, "*")
        entries = section.get("entries", [])

        entries_html = ""
        if sec_type == "steps":
            for i, entry in enumerate(entries, 1):
                if isinstance(entry, dict):
                    entries_html += _render_step_entry(entry, i)
        else:
            for entry in entries:
                if isinstance(entry, dict):
                    entries_html += _render_entry(entry)

        sections_html += f"""
        <div class="section section-{sec_type}">
          <div class="section-header">
            <span class="section-icon">{icon}</span>
            <h2 class="section-title">{sec_title}</h2>
            <span class="section-count">{len(entries)} {"entry" if len(entries) == 1 else "entries"}</span>
          </div>
          <div class="section-entries {'section-steps' if sec_type == 'steps' else ''}">
            {entries_html}
          </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;800&family=Nunito:wght@700;800&display=swap" rel="stylesheet">
<script>
window.MathJax = {{
  tex: {{
    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
    displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
    packages: {{'[+]': ['amsmath', 'amssymb']}}
  }},
  chtml: {{
    scale: 1.02,
    fontURL: 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/output/chtml/fonts/woff-v2'
  }},
  loader: {{ load: ['[tex]/amsmath', '[tex]/amssymb'] }},
  options: {{ skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre'] }},
  startup: {{
    ready() {{
      MathJax.startup.defaultReady();
      MathJax.startup.promise.then(() => {{
        document.body.setAttribute('data-mathjax-ready', 'true');
      }});
    }}
  }}
}};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 11pt; line-height: 1.55; color: #1e293b; background: #fff; padding: 20px 24px; }}
.doc-header {{ border-bottom: 3px solid {_BRAND_INDIGO}; padding-bottom: 12px; margin-bottom: 20px; }}
.doc-brand {{ font-size: 9pt; font-weight: 700; color: {_BRAND_INDIGO}; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 4px; }}
.doc-title {{ font-family: 'Nunito', 'DM Sans', sans-serif; font-size: 18pt; font-weight: 800; color: #0f172a; margin-bottom: 4px; }}
.doc-meta {{ font-size: 9pt; color: #64748b; }}
.doc-purpose {{ font-size: 9pt; color: #64748b; margin-top: 4px; font-style: italic; }}
.section {{ margin-bottom: 20px; break-inside: avoid; }}
.section-header {{ display: flex; align-items: center; gap: 8px; background: {_BRAND_INDIGO}; color: white; padding: 6px 10px; border-radius: 4px 4px 0 0; }}
.section-icon {{ font-size: 11pt; font-weight: 700; width: 18px; text-align: center; }}
.section-title {{ font-size: 11pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; flex: 1; }}
.section-count {{ font-size: 8pt; opacity: 0.8; }}
.section-entries {{ border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 4px 4px; overflow: hidden; }}
.entry {{ display: grid; grid-template-columns: 180px 1fr; border-bottom: 1px solid #e2e8f0; }}
.entry:last-child {{ border-bottom: none; }}
.entry-label {{ background: #f5f3ff; padding: 8px 10px; font-weight: 700; font-size: 9.5pt; color: {_BRAND_INDIGO}; border-right: 1px solid #e2e8f0; display: flex; align-items: flex-start; }}
.entry-body {{ padding: 8px 10px; background: #f9fafb; }}
.entry-content {{ font-size: 10pt; margin-bottom: 4px; line-height: 1.6; }}
.entry-notes {{ font-size: 8.5pt; color: #4f46e5; font-style: italic; margin-top: 4px; padding-top: 4px; border-top: 1px dashed #e2e8f0; }}
.entry-eg {{ font-size: 8.5pt; color: #64748b; margin-top: 4px; }}
.eg-tag {{ font-weight: 700; color: {_BRAND_INDIGO}; margin-right: 4px; font-size: 7.5pt; text-transform: uppercase; }}
.section-steps {{ display: flex; flex-direction: column; }}
.step {{ display: flex; gap: 12px; padding: 10px; border-bottom: 1px solid #e2e8f0; align-items: flex-start; }}
.step:last-child {{ border-bottom: none; }}
.step-num {{ width: 24px; height: 24px; border-radius: 50%; background: {_BRAND_INDIGO}; color: white; font-size: 9pt; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px; }}
.step-body {{ flex: 1; }}
.step-label {{ font-weight: 700; font-size: 10pt; margin-bottom: 4px; }}
.step-content {{ font-size: 9.5pt; color: #334155; }}
@media print {{ body {{ padding: 10px 14px; }} .section {{ break-inside: avoid; }} .entry {{ break-inside: avoid; }} }}
.MathJax {{ font-size: 100% !important; }}
mjx-container[display='true'] {{ display: block !important; margin: .28rem 0 !important; overflow-x: auto; }}
mjx-container {{ max-width: 100%; overflow-x: auto; }}
</style>
</head>
<body>
<div class="doc-header">
  <div class="doc-brand">{_BRAND_NAME} · Cheatsheet</div>
  <div class="doc-title">{title}</div>
  <div class="doc-meta">{course}{"  ·  " + level if level else ""}</div>
  {"<div class='doc-purpose'>" + purpose + "</div>" if purpose else ""}
</div>
{sections_html}
<div style="margin-top:16px;padding-top:8px;border-top:1px solid #e2e8f0;font-size:8pt;color:#94a3b8;text-align:center;">
  {_BRAND_NAME} - For personal study only. Generated content - verify before use.
</div>
</body>
</html>"""


def generate_cheatsheet_pdf(doc: dict, output_path: Path) -> Optional[Path]:
    output_path = Path(output_path)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    html_content = _build_html(doc)

    with tempfile.TemporaryDirectory(prefix="knowly_cs_pdf_") as tmp:
        html_path = Path(tmp) / "cheatsheet.html"
        html_path.write_text(html_content, encoding="utf-8")

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page()
                page.goto(f"file://{html_path.resolve()}", wait_until="networkidle")

                try:
                    page.wait_for_selector("body[data-mathjax-ready='true']", timeout=30_000)
                except Exception:
                    pass

                try:
                    page.evaluate("document.fonts && document.fonts.ready")
                except Exception:
                    pass

                page.pdf(
                    path=str(output_path),
                    format="A4",
                    margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"},
                    print_background=True,
                )
                browser.close()

            if output_path.exists() and output_path.stat().st_size > 500:
                return output_path
            return None
        except Exception:
            return None
