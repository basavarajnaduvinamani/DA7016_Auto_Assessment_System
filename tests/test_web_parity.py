"""The web demo's JavaScript engine must give the same marks and feedback as the Python baseline."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from autoassess.pipeline import run
from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.spec_builder import load_spec
from conftest import ROOT, SAMPLE

NODE = shutil.which("node")

JS = """
const E = require(process.argv[2]);
const data = JSON.parse(require("fs").readFileSync(0, "utf8"));
const { spec, errors } = E.validateSpec(data.spec);
if (errors.length) throw new Error(errors.join("; "));
const out = {};
for (const [sid, text] of Object.entries(data.sheets)) {
  const g = E.gradeSheet(spec, text, sid);
  out[sid] = { summary: g.summary_feedback, q: g.questions.map((q) => [q.question_id, q.marks_awarded,
    q.criteria.map((c) => [c.criterion_id, c.marks_awarded, c.evidence ?? null]),
    q.feedback_items.map((x) => [x.kind, x.criterion_id, x.text, x.next_step ?? null])]) };
}
console.log(JSON.stringify(out));
"""

EXTRA = {
    "X1": "Q1 softmax of QK scaled by sqrt dk, weighted sum of values, multi-head concatenated.\n"
    "Q2. Hallucination: false fluent output. Cause: training rewards plausibility.\nQ3 1. fine-tuning updates weights\n2. in-context learning",
    "X2": "3) ICL is cheap to prototype; fine-tune for stable high-volume tasks with labelled data.\n1) attention",
}


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_js_engine_matches_python(tmp_path):
    spec = load_spec(SAMPLE / "exam_spec.yaml")
    texts = {s: (SAMPLE / "answer_sheets" / f"{s}.txt").read_text() for s in ("S001", "S002", "S003")} | EXTRA
    expected = {}
    for sid, text in texts.items():
        p = tmp_path / f"{sid}.txt"
        p.write_text(text)
        g = run(spec, [PlainTextOCR().read_page(p, 0)], sid, None).grade
        expected[sid] = {
            "summary": g.summary_feedback,
            "q": [[q.question_id, q.marks_awarded, [[c.criterion_id, c.marks_awarded, c.evidence] for c in q.criteria],
                   [[i.kind, i.criterion_id, i.text, i.next_step] for i in q.feedback_items]] for q in g.questions],
        }  # fmt: skip
    script = tmp_path / "parity.js"
    script.write_text(JS)
    payload = json.dumps({"spec": yaml.safe_load((SAMPLE / "exam_spec.yaml").read_text()), "sheets": texts})
    out = subprocess.run([NODE, str(script), str(ROOT / "web" / "engine.js")], input=payload, capture_output=True, text=True, check=True)
    assert json.loads(out.stdout) == expected
