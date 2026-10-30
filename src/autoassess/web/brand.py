"""Red-Ink brand for the Gradio lab, matching the Classroom app's app.css tokens."""

from __future__ import annotations

import gradio as gr

RED = gr.themes.Color(
    c50="#fbebeb", c100="#f6d5d6", c200="#ecaeb1", c300="#de8287", c400="#cc5a60", c500="#ad343b",
    c600="#922a30", c700="#7c2329", c800="#641d22", c900="#4f181c", c950="#2e0d10", name="redink",
)
FONT = ["system-ui", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"]

THEME = gr.themes.Default(primary_hue=RED, secondary_hue=RED, neutral_hue="stone", font=FONT,
                          font_mono=["ui-monospace", "monospace"], radius_size="md").set(
    body_background_fill="#f7f6f2", body_text_color="#252b35", background_fill_primary="#ffffff",
    block_border_color="#e5e4df", border_color_primary="#e5e4df", block_radius="14px",
    button_primary_background_fill="#ad343b", button_primary_background_fill_hover="#922a30",
    button_primary_text_color="#ffffff", button_secondary_background_fill="#ffffff",
    button_secondary_background_fill_hover="#f7f6f2", button_secondary_border_color="#e5e4df",
    button_secondary_text_color="#252b35", checkbox_background_color_selected="#ad343b",
    link_text_color="#ad343b", link_text_color_hover="#922a30", color_accent="#ad343b",
)

CSS = """
.redink-bar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:4px 0 14px;border-bottom:1px solid #e5e4df;margin-bottom:6px}
.redink-brand{display:flex;align-items:center;gap:12px;color:#252b35;font-size:18px;text-decoration:none}
.redink-icon{position:relative;display:grid;place-items:center;width:34px;height:38px;color:#ad343b;border:1px solid #dfc6c5;border-radius:7px;font:italic bold 25px Georgia,serif;background:#fff}
.redink-icon span{position:absolute;bottom:-6px;right:-7px;font-size:19px;background:#f7f6f2;color:#ad343b}
.redink-brand strong{font-weight:450}
.redink-back{color:#ad343b !important;font-size:14px;font-weight:600;text-decoration:none}
.redink-back:hover{text-decoration:underline}
.redink-lede{color:#6c727d;margin:6px 0 0}
button.secondary{border:1px solid #e5e4df !important}
"""

HEADER = """<div class="redink-bar"><a class="redink-brand" href="/" aria-label="Red-Ink Classroom home"><span class="redink-icon">R<span>✓</span></span><span>Red-Ink <strong>Grader lab</strong></span></a><a class="redink-back" href="/">← Back to Red-Ink Classroom</a></div>
<p class="redink-lede">Upload an answer sheet and get it back marked, with marks a student can check and feedback they can act on.</p>"""
