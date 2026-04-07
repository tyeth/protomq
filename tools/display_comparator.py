"""
tools/display_comparator.py
===========================
Generate an HTML report showing distinct frames grouped by change type.
"""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import List

from tools.frame_extractor import Frame


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Display Test Report — {test_name}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #f5f5f5; }}
  h1 {{ color: #333; }}
  h2 {{ color: #555; margin-top: 2rem; border-bottom: 2px solid #ddd; padding-bottom: .3rem; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
  .card {{
    background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.12);
    padding: .75rem; max-width: 320px; text-align: center;
  }}
  .card img {{ max-width: 100%; border-radius: 4px; }}
  .card .meta {{ font-size: .85rem; color: #666; margin-top: .4rem; }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: .75rem; font-weight: 600; color: #fff; margin-bottom: .3rem;
  }}
  .badge-display {{ background: #2563eb; }}
  .badge-led {{ background: #d97706; }}
  .badge-initial {{ background: #6b7280; }}
</style>
</head>
<body>
<h1>Display Test Report</h1>
<p><strong>Test:</strong> {test_name}</p>
<p><strong>Total distinct frames:</strong> {total}</p>
{sections}
</body>
</html>
"""

_SECTION_TEMPLATE = """\
<h2>{change_type} frames ({count})</h2>
<div class="grid">
{cards}
</div>
"""

_CARD_TEMPLATE = """\
<div class="card">
  <span class="badge badge-{change_type}">{change_type}</span>
  <img src="{img_src}" alt="Frame {frame_number}">
  <div class="meta">Frame #{frame_number} &middot; {timestamp_s}s</div>
</div>
"""


def generate_report(
    frames: List[Frame],
    test_name: str,
    output_dir: str = "artifacts/reports",
) -> str:
    """
    Generate an HTML report with a thumbnail grid of distinct frames.

    Parameters
    ----------
    frames : list[Frame]
        The distinct frames to include.
    test_name : str
        Human-readable test identifier.
    output_dir : str
        Directory for the HTML file.

    Returns
    -------
    str
        Absolute path to the generated HTML file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Group by change_type, preserving order
    groups: dict[str, list[Frame]] = {}
    for f in frames:
        groups.setdefault(f.change_type, []).append(f)

    sections_html = ""
    for ctype in ("initial", "display", "led"):
        group = groups.get(ctype, [])
        if not group:
            continue

        cards = ""
        for f in group:
            # Make image path relative to the report
            img_src = os.path.relpath(f.path, str(out)) if f.path else ""
            cards += _CARD_TEMPLATE.format(
                change_type=ctype,
                img_src=html.escape(img_src),
                frame_number=f.frame_number,
                timestamp_s=f.timestamp_s,
            )

        sections_html += _SECTION_TEMPLATE.format(
            change_type=ctype.capitalize(),
            count=len(group),
            cards=cards,
        )

    report_html = _HTML_TEMPLATE.format(
        test_name=html.escape(test_name),
        total=len(frames),
        sections=sections_html,
    )

    safe_name = test_name.replace("/", "_").replace("::", "__").replace(" ", "_")
    report_path = out / f"report_{safe_name}.html"
    report_path.write_text(report_html, encoding="utf-8")

    return str(report_path.resolve())
