"""Reproduce text-free evidence and offline study analyses; never calls an API."""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from autoassess.baseline import grade_question_lexical
from autoassess.datasets.sprag import import_sprag
from autoassess.embedding_study import cosine, fit_similarity, similarity_mark
from autoassess.evaluate import human_consensus, load_human_marks
from autoassess.providers.text_ocr import PlainTextOCR
from autoassess.schemas import SheetGrade
from autoassess.segment import segment_pages
from autoassess.spec_builder import load_spec
from autoassess.validation_study import (
    Score,
    fit_referral,
    paired_comparison,
    risk_coverage,
    score_metrics,
    validate_split,
)

ROOT = Path(__file__).resolve().parents[1]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _load(path: Path) -> list[Score]:
    rows = [Score(**row) for row in json.loads(path.read_text())]
    validate_split(rows)
    return rows


def _provenance(config: dict, inputs: list[Path]) -> dict:
    return {
        "executed_at": datetime.now(UTC).isoformat(),
        "command": [sys.executable, *sys.argv],
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
        "seed": 0,
        "config": config,
        "config_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "code_sha256": {
            str(p.relative_to(ROOT)): _digest(p) for p in [Path(__file__), ROOT / "src/autoassess/validation_study.py"]
        },
        "inputs": {
            str(p): {"sha256": _digest(p), "modified_at": datetime.fromtimestamp(p.stat().st_mtime, UTC).isoformat()}
            for p in inputs
        },
        "paid_api_calls": 0,
        "session_api_spend_usd": 0,
        "historical_spend": "UNKNOWN",
    }


def _export(args: argparse.Namespace) -> None:
    dataset, grades, out = args.dataset.resolve(), args.grades.resolve(), args.out
    salt_path = ROOT / "data/private/upgrade-2026-10-30/export.key"
    salt_path.parent.mkdir(parents=True, exist_ok=True)
    if not salt_path.exists():
        with salt_path.open("xb") as stream:
            os.chmod(salt_path, 0o600)
            stream.write(os.urandom(32))
    salt = salt_path.read_bytes()

    def anonymise(value: str) -> str:
        return hmac.new(salt, value.encode(), hashlib.sha256).hexdigest()

    meta_path, human_path, spec_path = [dataset / p for p in ("sheets.csv", "human_marks.csv", "exam_spec.yaml")]
    with meta_path.open(newline="") as stream:
        metadata = list(csv.DictReader(stream))
    if len({r["student_id"] for r in metadata}) != len(metadata):
        raise ValueError("duplicate sheet metadata")
    human = load_human_marks(human_path)
    if set(human) != {"grader_A", "grader_B"}:
        raise ValueError("expected exactly two reference graders")
    consensus = human_consensus(human)
    rows = []
    used_inputs = [meta_path, human_path, spec_path]
    for sheet in sorted(metadata, key=lambda r: r["student_id"]):
        sid = sheet["student_id"]
        path = grades / f"{sid}.json"
        grade = SheetGrade.model_validate_json(path.read_text())
        if grade.student_id != sid:
            raise ValueError("grade identity differs from its metadata")
        used_inputs.append(path)
        found = set()
        for q in grade.questions:
            key = (sid, q.question_id)
            if key not in consensus:
                continue
            if key in found:
                raise ValueError("duplicate marked question")
            found.add(key)
            rows.append(
                Score(
                    anonymise("item:" + sid + ":" + q.question_id),
                    anonymise("question:" + q.question_id),
                    sheet["split"],
                    q.marks_awarded,
                    consensus[key],
                    q.max_marks,
                    q.confidence,
                    q.needs_review,
                    human["grader_A"][key],
                    human["grader_B"][key],
                )
            )
        if found != {k for k in consensus if k[0] == sid}:
            raise ValueError("missing predictions for human-marked questions")
    if {k[0] for k in consensus} != {r["student_id"] for r in metadata}:
        raise ValueError("reference and split sheet populations differ")
    validate_split(rows)
    _write(out / "scores.json", [asdict(r) for r in rows])
    _write(
        out / "split-manifest.json",
        [{"item_id": r.item_id, "question_id": r.question_id, "split": r.split} for r in rows],
    )
    manifest = _provenance(
        {
            "label": args.label,
            "provider_model_id": "UNKNOWN: historical lexical output; no LLM",
            "historical_prompt_sha256": "UNKNOWN",
            "historical_config_sha256": "UNKNOWN",
            "historical_run_date": "UNKNOWN; file modification times are not execution dates",
            "consensus": "mean of grader_A and grader_B",
            "qwk_step": 0.5,
        },
        [],
    )
    # Directory content hashes bind original files without publishing identifying filenames.
    if args.run_manifest:
        manifest["recorded_run"] = json.loads(args.run_manifest.read_text())
        manifest["recorded_run_sha256"] = _digest(args.run_manifest)
    manifest["source_directories"] = [str(dataset), str(grades)]
    manifest["source_tree_sha256"] = hashlib.sha256(
        "\n".join(str(p.relative_to(ROOT)) + ":" + _digest(p) for p in used_inputs).encode()
    ).hexdigest()
    manifest["known_inputs"] = {str(p): _digest(p) for p in (meta_path, human_path, spec_path)}
    manifest["source_grade_mtime_range"] = [
        datetime.fromtimestamp(t, UTC).isoformat()
        for t in (min(p.stat().st_mtime for p in used_inputs[3:]), max(p.stat().st_mtime for p in used_inputs[3:]))
    ]
    manifest["output_sha256"] = {p.name: _digest(p) for p in (out / "scores.json", out / "split-manifest.json")}
    _write(out / "evidence-manifest.json", manifest)


def _aggregate(args: argparse.Namespace) -> None:
    rows = _load(args.scores)
    results = {split: score_metrics([r for r in rows if r.split == split]) for split in ("dev", "test")}
    payload = {
        "provenance": _provenance({"qwk_step": 0.5, "precision": "unrounded"}, [args.scores]),
        "results": results,
    }
    if args.assert_equal:
        expected = json.loads(args.assert_equal.read_text())["results"]
        if results != expected:
            raise AssertionError(f"regenerated results differ: {results!r} != {expected!r}")
    _write(args.out, payload)


def _verify_numbers(args: argparse.Namespace) -> None:
    # Do not mistake table-transcription consistency for experimental verification.
    # Each literal remains unsupported until it has an independently recomputable source.
    text = args.numbers.read_text()
    literals = [
        {
            "line": line_no,
            "column": match.start() + 1,
            "literal": match.group(),
            "status": "UNKNOWN: raw source evidence unavailable",
        }
        for line_no, line in enumerate(text.splitlines(), 1)
        for match in re.finditer(r"(?<![\w])[-+]?\d+(?:\.\d+)?%?", line)
    ]
    _write(
        args.out,
        {
            "provenance": _provenance({}, [args.numbers]),
            "status": "BLOCKED",
            "scope": "numeric literal inventory; includes dates, counts, costs, model IDs and metrics",
            "reason": "reported private experiment predictions, configs and receipts are not present",
            "literals": literals,
        },
    )
    raise SystemExit("BLOCKED: cannot assert report numbers against missing raw experiments; see " + str(args.out))


def _calibrate(args: argparse.Namespace) -> None:
    rows = _load(args.scores)
    fitted = fit_referral([r for r in rows if r.split == "dev"], args.minimum_coverage)
    _write(
        args.out,
        {
            "provenance": _provenance({"minimum_coverage": args.minimum_coverage}, [args.scores]),
            "results": risk_coverage([r for r in rows if r.split == "test"], fitted),
        },
    )


def _compare(args: argparse.Namespace) -> None:
    left, right = _load(args.default), _load(args.baseline)
    _write(
        args.out,
        {
            "provenance": _provenance({"draws": 2000, "split": "test"}, [args.default, args.baseline]),
            "results": paired_comparison(
                [r for r in left if r.split == "test"], [r for r in right if r.split == "test"]
            ),
        },
    )


def _lexical(args: argparse.Namespace) -> None:
    # Import a fresh directory; retain every historical run and its original rubric.
    import_sprag(args.source, args.dataset, seed=0, per_question=5, dev_share=0.2)
    spec = load_spec(args.dataset / "exam_spec.yaml")
    reference = load_human_marks(args.dataset / "human_marks.csv")
    targets = {(sid, qid) for grader in reference.values() for sid, qid in grader}
    args.grades.mkdir(parents=True, exist_ok=False)
    for path in sorted((args.dataset / "sheets").glob("*.txt")):
        segments = segment_pages(spec, [PlainTextOCR().read_page(path)])
        questions = [q for q in spec.questions if (path.stem, q.id) in targets]
        if any(q.id not in segments for q in questions):
            raise ValueError("human-marked question missing after segmentation")
        grade = SheetGrade(
            exam_id=spec.exam_id,
            student_id=path.stem,
            questions=[grade_question_lexical(q, segments[q.id]) for q in questions],
        )
        (args.grades / f"{path.stem}.json").write_text(grade.model_dump_json(indent=2))
    files = [args.source / name for name in ("Question_data.csv", "MLResponses.csv", "PyResponses.csv")]
    manifest = _provenance(
        {
            "method": "lexical",
            "provider_model_id": "none: deterministic lexical",
            "per_question": 5,
            "dev_share": 0.2,
            "seed": 0,
        },
        files,
    )
    manifest["pipeline_code_sha256"] = {
        name: _digest(ROOT / name)
        for name in ("src/autoassess/baseline.py", "src/autoassess/datasets/sprag.py", "src/autoassess/segment.py")
    }
    _write(args.manifest, manifest)


def _embedding(args: argparse.Namespace) -> None:
    # Embeddings stay private. Only numeric scores and source hashes are exported.
    from dataclasses import replace

    scores = _load(args.scores)
    data = json.loads(args.embeddings.read_text())
    if not all(data.get(k) for k in ("model_id", "revision", "model_sha256", "encoding_command")):
        raise ValueError("embedding model identity, revision, weights hash and command required")
    vectors = data["rows"]
    if len(vectors) != len(scores) or {r["item_id"] for r in vectors} != {r.item_id for r in scores}:
        raise ValueError("complete unique matched embeddings required")
    vectors = {r["item_id"]: r for r in vectors}
    similarities = {r.item_id: cosine(vectors[r.item_id]["answer"], vectors[r.item_id]["reference"]) for r in scores}
    dev = [r for r in scores if r.split == "dev"]
    frozen = fit_similarity([similarities[r.item_id] for r in dev], [r.human / r.max_marks for r in dev])
    predictions = [
        replace(
            r,
            system=similarity_mark(similarities[r.item_id], r.max_marks, frozen, blank=vectors[r.item_id]["blank"]),
            confidence=1.0,
            needs_review=False,
        )
        for r in scores
    ]
    _write(args.out / "scores.json", [asdict(r) for r in predictions])
    _write(
        args.out / "embedding-fit.json",
        {
            "provenance": _provenance(
                {
                    "model_id": data["model_id"],
                    "revision": data["revision"],
                    "model_sha256": data["model_sha256"],
                    "encoding_command": data["encoding_command"],
                    "mapping": "nonnegative slope, dev-only least squares",
                },
                [args.scores, args.embeddings],
            ),
            "frozen_dev_fit": frozen,
        },
    )


def main() -> None:
    """Dispatch explicit local study operations with caller-selected input paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    for name in ("dataset", "grades", "out"):
        export.add_argument("--" + name, type=Path, required=True)
    export.add_argument("--label", required=True)
    export.add_argument("--run-manifest", type=Path)
    export.set_defaults(fn=_export)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--scores", type=Path, required=True)
    aggregate.add_argument("--out", type=Path, required=True)
    aggregate.add_argument("--assert-equal", type=Path)
    aggregate.set_defaults(fn=_aggregate)
    verify = commands.add_parser("verify-numbers")
    verify.add_argument("--numbers", type=Path, default=ROOT / "docs/report/numbers.md")
    verify.add_argument("--out", type=Path, required=True)
    verify.set_defaults(fn=_verify_numbers)
    calibration = commands.add_parser("calibrate")
    calibration.add_argument("--scores", type=Path, required=True)
    calibration.add_argument("--minimum-coverage", type=float, default=0.5)
    calibration.add_argument("--out", type=Path, required=True)
    calibration.set_defaults(fn=_calibrate)
    compare = commands.add_parser("compare")
    compare.add_argument("--default", type=Path, required=True)
    compare.add_argument("--baseline", type=Path, required=True)
    compare.add_argument("--out", type=Path, required=True)
    compare.set_defaults(fn=_compare)
    lexical = commands.add_parser("lexical")
    for name in ("source", "dataset", "grades"):
        lexical.add_argument("--" + name, type=Path, required=True)
    lexical.add_argument("--manifest", type=Path, required=True)
    lexical.set_defaults(fn=_lexical)
    embedding = commands.add_parser("embedding")
    for name in ("scores", "embeddings", "out"):
        embedding.add_argument("--" + name, type=Path, required=True)
    embedding.set_defaults(fn=_embedding)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
