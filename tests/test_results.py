"""Results packs consume the output shapes of evaluate and experiments."""

import builtins
import copy
import json
from pathlib import Path

import pytest

from autoassess.cli import main
from autoassess.results import build_results

FIXTURES = Path(__file__).parent / "fixtures" / "results"


def read(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def without_matplotlib(monkeypatch):
    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ModuleNotFoundError("No module named 'matplotlib'", name="matplotlib")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)


def all_args(out):
    return ["results", "--agreement", str(FIXTURES / "agreement.json"),
            "--ablation", str(FIXTURES / "ablation.json"),
            "--robustness", str(FIXTURES / "robustness.json"),
            "--ocr", str(FIXTURES / "ocr_bodhan.json"), str(FIXTURES / "ocr_text.json"), "--out", str(out)]


def test_pack_tables_summary_and_escaping(tmp_path, without_matplotlib):
    assert main(all_args(tmp_path)) == 0
    agreement, robustness = read("agreement"), read("robustness")
    summary = json.loads((tmp_path / "summary.json").read_text())
    metrics = agreement["vs_consensus"]
    assert summary == {
        "qwk": metrics["qwk"], "human_qwk": agreement["human_vs_human"]["qwk"],
        "mae": metrics["mae"], "within_1": metrics["within_1"], "bias": metrics["bias"],
        "coverage_at_0_8": agreement["coverage_curve"][1]["coverage"],
        "robustness_pass_rate": sum(r["passed"] for r in robustness["rows"]) / len(robustness["rows"]),
    }
    for section in ("agreement", "ablation", "robustness", "ocr", "groups"):
        tex = (tmp_path / "tables" / f"{section}.tex").read_text()
        assert r"\toprule" in tex and r"\bottomrule" in tex
        assert r"\begin{tabular}" in tex and r"\begin{table}" not in tex
    groups = (tmp_path / "tables" / "groups.tex").read_text()
    assert r"language\_\%" in groups and r"English \& Hindi" in groups
    assert r"bodhan\_\%\&" in (tmp_path / "tables" / "ocr.tex").read_text()
    md = (tmp_path / "results.md").read_text()
    assert "0.712 [0.650, 0.770]" in md
    assert "-0.250 [-0.500, -0.100]" in md
    assert "0.123" in md and "no_review" in md and "text" in md
    assert not list((tmp_path / "figures").glob("*.png"))


def test_missing_matplotlib_prints_one_skip_line(tmp_path, capsys, without_matplotlib):
    assert main(all_args(tmp_path)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len([line for line in lines if "Figures skipped" in line]) == 1
    assert (tmp_path / "results.md").is_file()
    assert (tmp_path / "summary.json").is_file()


def test_missing_optional_inputs_and_groups(tmp_path, without_matplotlib):
    agreement = read("agreement")
    agreement.pop("per_group")
    agreement.pop("bias_per_question")
    source = tmp_path / "input.json"
    source.write_text(json.dumps(agreement))
    out = tmp_path / "out"
    assert main(["results", "--agreement", str(source), "--out", str(out)]) == 0
    assert sorted(p.name for p in (out / "tables").iterdir()) == ["agreement.tex"]
    summary = json.loads((out / "summary.json").read_text())
    assert summary["robustness_pass_rate"] is None
    assert "Ablation" not in (out / "results.md").read_text()


def test_missing_metrics_are_unavailable_not_zero(tmp_path, without_matplotlib):
    summary = build_results({"per_grader": {}, "human_vs_human": None}, tmp_path)
    assert all(value is None for value in summary.values())
    assert "NaN" not in (tmp_path / "summary.json").read_text()


def test_fallback_to_first_grader_and_weighted_robustness(tmp_path, without_matplotlib):
    agreement = read("agreement")
    agreement.pop("vs_consensus")
    robustness = read("robustness")
    robustness.pop("rows")
    assert build_results(agreement, tmp_path, robustness=robustness)["robustness_pass_rate"] == 2 / 3
    assert json.loads((tmp_path / "summary.json").read_text())["qwk"] == agreement["per_grader"]["A"]["qwk"]


def test_pack_figures_and_plotted_values(tmp_path, monkeypatch):
    pytest.importorskip("matplotlib")
    from autoassess import results

    figures = {}
    original = results._save_figure

    def record(figure, path):
        ax = figure.axes[0]
        figures[path.stem] = [(list(line.get_xdata()), list(line.get_ydata())) for line in ax.lines]
        original(figure, path)

    monkeypatch.setattr(results, "_save_figure", record)
    assert main(all_args(tmp_path)) == 0
    for name in ("coverage", "bias", "ablation"):
        assert (tmp_path / "figures" / f"{name}.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert figures["coverage"][0] == ([0.667, 1.0], [1.0, 0.667])
    assert figures["bias"][0][1] == [-0.5]
    assert figures["ablation"][-1][1] == [0.94, 0.94]


def test_bias_intervals_when_supplied(tmp_path, monkeypatch):
    pytest.importorskip("matplotlib")
    from autoassess import results

    agreement = read("agreement")
    agreement["bias_per_question"] = {"Q1": {"bias": -0.2, "ci95": {"bias": [-0.4, 0.1]}}}
    original = results._save_figure
    intervals = []

    def record(figure, path):
        if path.stem == "bias":
            intervals.extend(figure.axes[0].collections[0].get_segments())
        original(figure, path)

    monkeypatch.setattr(results, "_save_figure", record)
    build_results(agreement, tmp_path)
    assert intervals[0].tolist() == [[0.0, -0.4], [0.0, 0.1]]


def test_inputs_unchanged(tmp_path, without_matplotlib):
    agreement, ablation, robustness, ocr = read("agreement"), read("ablation"), read("robustness"), [read("ocr_text")]
    before = copy.deepcopy((agreement, ablation, robustness, ocr))
    build_results(agreement, tmp_path, ablation=ablation, robustness=robustness, ocr=ocr)
    assert (agreement, ablation, robustness, ocr) == before


def test_rerun_removes_stale_generated_sections(tmp_path, without_matplotlib):
    agreement = read("agreement")
    build_results(agreement, tmp_path, ablation=read("ablation"), robustness=read("robustness"), ocr=[read("ocr_text")])
    (tmp_path / "figures" / "ablation.png").write_bytes(b"old figure")
    (tmp_path / "tables" / "notes.txt").write_text("keep me")
    agreement.pop("per_group")
    build_results(agreement, tmp_path)
    assert sorted(p.name for p in (tmp_path / "tables").glob("*.tex")) == ["agreement.tex"]
    assert not list((tmp_path / "figures").glob("*.png"))
    assert (tmp_path / "tables" / "notes.txt").read_text() == "keep me"
