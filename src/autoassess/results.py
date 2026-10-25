"""Report tables and optional figures from existing evaluation JSON outputs."""

from __future__ import annotations

import json
import math
from pathlib import Path


METRICS = ("n", "qwk", "mae", "within_1", "exact", "bias")
HEADERS = ("Comparison", "N", "QWK", "MAE", "Within 1 mark", "Exact", "Signed bias")


def _number(value) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:.3f}"


def _metric(metrics: dict, key: str) -> str:
    value = _number(metrics.get(key))
    interval = metrics.get("ci95", {}).get(key)
    if interval is not None:
        value += f" [{_number(interval[0])}, {_number(interval[1])}]"
    return value


def _metric_row(label: str, metrics: dict) -> list[str]:
    return [label, *(_metric(metrics, key) for key in METRICS)]


def _consensus(report: dict) -> dict:
    if report.get("vs_consensus"):
        return report["vs_consensus"]
    per = report.get("per_grader", {})
    return per[sorted(per)[0]] if per else {}


def _latex(text: str) -> str:
    escapes = {
        "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
        "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
        "—": "--",
    }
    return "".join(escapes.get(char, char) for char in str(text).replace("\n", " "))


def _markdown(text: str) -> str:
    return str(text).replace("|", r"\|").replace("\n", " ")


def _table(out: Path, name: str, caption: str, headers: tuple, rows: list[list[str]]) -> str:
    tex = [r"\begin{tabular}{" + "l" * len(headers) + "}", r"\toprule",
           " & ".join(map(_latex, headers)) + r" \\", r"\midrule"]
    tex += [" & ".join(map(_latex, row)) + r" \\" for row in rows]
    tex += [r"\bottomrule", r"\end{tabular}"]
    (out / "tables" / f"{name}.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
    md = [caption, "", "| " + " | ".join(map(_markdown, headers)) + " |",
          "| " + " | ".join("---" for _ in headers) + " |"]
    md += ["| " + " | ".join(map(_markdown, row)) + " |" for row in rows]
    return "\n".join(md)


def _summary(agreement: dict, robustness: dict | None) -> dict:
    system = _consensus(agreement)
    human = agreement.get("human_vs_human") or {}
    coverage = next((row.get("coverage") for row in agreement.get("coverage_curve", [])
                     if row["threshold"] == 0.8), None)
    pass_rate = None
    if robustness is not None:
        rows = robustness.get("rows", [])
        if rows:
            pass_rate = sum(row["passed"] for row in rows) / len(rows)
        else:
            groups = robustness.get("summary", {}).values()
            n = sum(group["n"] for group in groups)
            if n:
                pass_rate = sum(group["n"] * group["pass_rate"] for group in groups) / n
    return {
        "qwk": system.get("qwk"), "human_qwk": human.get("qwk"), "mae": system.get("mae"),
        "within_1": system.get("within_1"), "bias": system.get("bias"),
        "coverage_at_0_8": coverage, "robustness_pass_rate": pass_rate,
    }


def _save_figure(figure, path: Path) -> None:
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    figure.clear()


def _coverage_figure(agreement: dict, path: Path) -> None:
    from matplotlib.figure import Figure

    figure = Figure(figsize=(6, 4))
    ax = figure.subplots()
    rows = sorted((r for r in agreement.get("coverage_curve", []) if "within_tolerance" in r),
                  key=lambda r: r["coverage"])
    ax.plot([r["coverage"] for r in rows], [r["within_tolerance"] for r in rows], "o-")
    ax.set(xlabel="Share auto-accepted", ylabel="Accuracy (within 0.5 marks)", xlim=(0, 1), ylim=(0, 1.05))
    _save_figure(figure, path)


def _bias_figure(bias: dict, path: Path) -> None:
    from matplotlib.figure import Figure

    figure = Figure(figsize=(max(6, len(bias) * 0.7), 4))
    ax = figure.subplots()
    for i, (qid, value) in enumerate(bias.items()):
        # Current evaluate output is scalar; also accept intervals when supplied by an upstream report.
        point = value.get("bias") if isinstance(value, dict) else value
        interval = value.get("ci95", {}).get("bias") if isinstance(value, dict) else None
        ax.plot(i, point, "o", color="tab:blue")
        if interval is not None:
            ax.vlines(i, interval[0], interval[1], color="tab:blue")
            ax.plot([i, i], interval, "_", color="tab:blue")
    ax.axhline(0, color="gray", linewidth=1)
    ax.set(xticks=range(len(bias)), xticklabels=list(bias), ylabel="Signed bias (system − human)")
    _save_figure(figure, path)


def _ablation_figure(ablation: dict, human: dict, path: Path) -> None:
    from matplotlib.figure import Figure

    figure = Figure(figsize=(max(6, len(ablation) * 0.9), 4))
    ax = figure.subplots()
    rows = [(name, _consensus(report).get("qwk")) for name, report in ablation.items()]
    rows = [(name, qwk) for name, qwk in rows if qwk is not None]
    ax.bar([name for name, _ in rows], [qwk for _, qwk in rows])
    if human.get("qwk") is None:
        human = next((report["human_vs_human"] for report in ablation.values()
                      if report.get("human_vs_human")), {})
    if human.get("qwk") is not None:
        ax.axhline(human["qwk"], color="tab:red", linestyle="--", label="Human vs human")
        ax.legend()
    ax.set(ylabel="QWK")
    ax.tick_params(axis="x", labelrotation=35)
    _save_figure(figure, path)


def _figures(out: Path, agreement: dict, ablation: dict | None) -> None:
    try:
        _coverage_figure(agreement, out / "figures" / "coverage.png")
        if agreement.get("bias_per_question"):
            _bias_figure(agreement["bias_per_question"], out / "figures" / "bias.png")
        if ablation is not None:
            _ablation_figure(ablation, agreement.get("human_vs_human") or {}, out / "figures" / "ablation.png")
    except ModuleNotFoundError as err:
        if err.name != "matplotlib":
            raise
        print('Figures skipped: matplotlib is not installed; install autoassess[report].')


def build_results(
    agreement: dict,
    out: str | Path,
    *,
    ablation: dict | None = None,
    robustness: dict | None = None,
    ocr: list[dict] | None = None,
) -> dict:
    """Write tables, headline values and available figures; return the flat summary."""
    out = Path(out)
    for directory in (out, out / "tables", out / "figures"):
        directory.mkdir(parents=True, exist_ok=True)
    for filename in ("agreement", "ablation", "robustness", "ocr", "groups"):
        (out / "tables" / f"{filename}.tex").unlink(missing_ok=True)
    for filename in ("coverage", "bias", "ablation"):
        (out / "figures" / f"{filename}.png").unlink(missing_ok=True)
    rows = []
    if agreement.get("vs_consensus"):
        rows.append(_metric_row("System vs consensus", agreement["vs_consensus"]))
    rows += [_metric_row(f"System vs {name}", metrics) for name, metrics in agreement.get("per_grader", {}).items()]
    if agreement.get("human_vs_human"):
        rows.append(_metric_row("Human vs human", agreement["human_vs_human"]))
    sections = [_table(out, "agreement", "Agreement with human marks (95% bootstrap CIs where supplied).", HEADERS, rows)]
    if ablation is not None:
        rows = [_metric_row(name, _consensus(report)) for name, report in ablation.items()]
        sections.append(_table(out, "ablation", "Ablation agreement (human consensus when available).", HEADERS, rows))
    if robustness is not None:
        rows = [[name, _number(values["n"]), _number(values["pass_rate"]), _number(values["mean_delta"])]
                for name, values in robustness.get("summary", {}).items()]
        sections.append(_table(out, "robustness", "Robustness by perturbation.",
                               ("Perturbation", "Cases", "Pass rate", "Mean mark change"), rows))
    if ocr is not None:
        rows = [[report["provider"], sid, _number(values["cer"]), _number(values["wer"])]
                for report in ocr for sid, values in report["sheets"].items()]
        sections.append(_table(out, "ocr", "OCR error rates per sheet and provider (mean rows supplied by ocr-eval).",
                               ("Provider", "Sheet", "CER", "WER"), rows))
    groups = agreement.get("per_group", {})
    if any(groups.values()):
        rows = [[column, *_metric_row(group, metrics)]
                for column, values in groups.items() for group, metrics in values.items()]
        sections.append(_table(out, "groups", "Agreement within metadata groups.", ("Grouping", *HEADERS), rows))
    (out / "results.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    summary = _summary(agreement, robustness)
    summary = {key: value if value is None or math.isfinite(value) else None for key, value in summary.items()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    _figures(out, agreement, ablation)
    return summary
