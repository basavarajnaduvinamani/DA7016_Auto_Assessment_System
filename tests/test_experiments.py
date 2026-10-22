import pytest

from autoassess.cli import main
from autoassess.experiments import (
    Config,
    ablation_table,
    make_grade_fn,
    ocr_accuracy,
    robustness_table,
    run_ablation,
    run_robustness,
)
from autoassess.metrics import character_error_rate, word_error_rate
from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.schemas import OCRLine, OCRPage
from autoassess.segment import segment_pages
from autoassess.spec_builder import load_spec
from conftest import SAMPLE, FakeLLM

SPEC = load_spec(SAMPLE / "exam_spec.yaml")


def _sheets():
    return {
        sid: segment_pages(SPEC, [PlainTextOCR().read_page(SAMPLE / "answer_sheets" / f"{sid}.txt", 0)])
        for sid in ("S001", "S002", "S003")
    }


HUMAN = {
    "A": {("S001", "Q1"): 5, ("S001", "Q2"): 4, ("S001", "Q3"): 5, ("S002", "Q1"): 2, ("S002", "Q2"): 1,
          ("S002", "Q3"): 2, ("S003", "Q1"): 0, ("S003", "Q2"): 0.5, ("S003", "Q3"): 0},
}  # fmt: skip


def test_error_rates():
    assert character_error_rate("abc", "abc") == 0
    assert character_error_rate("abd", "abc") == pytest.approx(1 / 3)
    assert word_error_rate("the cat sat", "the cat sat down") == pytest.approx(0.25)


def test_ocr_accuracy():
    pages = {"S1": [OCRPage(page_index=0, lines=[OCRLine(text="hello wrld")])]}
    r = ocr_accuracy(pages, {"S1": "hello world", "S2": "x"})
    assert r["S1"]["wer"] == 0.5 and r["mean"]["cer"] == r["S1"]["cer"]


class EchoLLM(FakeLLM):
    """Awards every criterion in full with a quote of the first five words of the answer."""

    def __init__(self):
        super().__init__([])

    def complete_json(self, system, user, *, temperature=0.0, seed=None):
        self.calls.append(user)
        answer = user.split("<student_answer>\n", 1)[1].split("\n</student_answer>", 1)[0]
        ids = [line.split(" (")[0][2:] for line in user.splitlines() if line.startswith("- Q")]
        if "AWARDS TO AUDIT" in user:
            return {"audits": []}
        quote = " ".join(answer.split()[:5]) or None
        return {"criteria": [{"criterion_id": i, "marks_awarded": 99 if quote else 0, "evidence": quote, "reason": "r"} for i in ids]}


def test_ablation_runs_every_config_and_tables():
    results = run_ablation(SPEC, _sheets(), HUMAN, EchoLLM(), EchoLLM())
    assert list(results) == [
        "full", "critic_only", "no_critic", "no_review", "single_run", "no_evidence_rule", "no_model_answer", "lexical_baseline",
    ]  # fmt: skip
    table = ablation_table(results)
    assert table.count("\n") == 9 and "| lexical_baseline |" in table and "| Bias |" in table


def test_ablation_without_llm_runs_baseline_only():
    assert list(run_ablation(SPEC, _sheets(), HUMAN, None)) == ["lexical_baseline"]


def test_robustness_catches_a_gameable_grader():
    # EchoLLM gives full marks to anything non-empty, so it must fail stuffing and restating.
    report = run_robustness(SPEC, _sheets(), make_grade_fn(Config("full", runs=1, critic=False), EchoLLM(), None))
    s = report["summary"]
    assert s["keyword_stuffing"]["pass_rate"] == 0 and s["restate_question"]["pass_rate"] == 0
    assert s["blank"]["pass_rate"] == 1 and s["injection"]["pass_rate"] == 1
    assert s["wrong_question"]["pass_rate"] == 0  # full marks for another question's answer
    assert {"injection_hindi", "injection_kannada", "injection_subtle", "spelling_errors"} <= set(s)
    assert "| padding |" in robustness_table(report)


def test_cli_robustness_baseline(tmp_path, capsys):
    sheets = [str(SAMPLE / "answer_sheets" / f"S00{i}.txt") for i in (1, 2, 3)]
    assert main(["experiment", "robustness", "--spec", str(SAMPLE / "exam_spec.yaml"), "--out", str(tmp_path), "--baseline-only", *sheets]) == 0
    assert (tmp_path / "robustness.md").exists()
    assert "| injection |" in capsys.readouterr().out
