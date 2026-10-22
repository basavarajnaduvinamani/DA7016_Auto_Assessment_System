"""Command line entry point: `autoassess <command>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError


def _validate_spec(args: argparse.Namespace) -> int:
    from autoassess.spec_builder import lint_spec, load_spec

    try:
        spec = load_spec(args.spec)
    except ValidationError as err:
        print(f"INVALID {args.spec}\n{err}", file=sys.stderr)
        return 1
    print(f"OK {spec.exam_id}: {len(spec.questions)} questions, {spec.total_marks:g} marks")
    for w in lint_spec(spec):
        print(f"  warning: {w}")
    return 0


def _draft_spec(args: argparse.Namespace) -> int:
    from autoassess.config import Settings
    from autoassess.providers import make_llm
    from autoassess.spec_builder import draft_spec, lint_spec, save_spec

    read = lambda p: Path(p).read_text(encoding="utf-8")  # noqa: E731
    spec = draft_spec(read(args.paper), read(args.rubric), read(args.model_answers), make_llm(Settings.load()), args.exam_id)
    save_spec(spec, args.out)
    print(f"wrote {args.out}; review it before grading")
    for w in lint_spec(spec):
        print(f"  warning: {w}")
    return 0


def _ingest(args: argparse.Namespace) -> int:
    from autoassess.ingest import ingest

    pages = ingest(args.source, args.out_dir, args.dpi)
    print(f"wrote {len(pages)} cleaned pages to {args.out_dir}")
    return 0


def _grade(args: argparse.Namespace) -> int:
    from autoassess.config import Settings
    from autoassess.pipeline import read_sheet, run
    from autoassess.providers import make_llm, make_ocr, make_translator
    from autoassess.spec_builder import load_spec

    settings = Settings.load()
    spec = load_spec(args.spec)
    llm = None if args.baseline else make_llm(settings)
    critic = make_llm(settings, critic=True) if args.critic and llm else None
    ocr = make_ocr(settings)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    translator = make_translator(settings) if args.feedback_language else None
    for sheet in args.sheets:
        sid = Path(sheet).stem
        result = run(
            spec,
            read_sheet(sheet, ocr, language=spec.language),
            sid,
            llm,
            runs=args.runs,
            critic=critic,
            translator=translator,
            feedback_language=args.feedback_language,
        )
        grade = result.grade
        (out / f"{sid}.json").write_text(grade.model_dump_json(indent=2), encoding="utf-8")
        (out / f"{sid}.html").write_text(result.html(), encoding="utf-8")
        flags = sum(1 for q in grade.questions if q.flags and q.flags != ["unanswered"])
        print(f"{sid}: {grade.total:g} / {spec.total_marks:g}" + (f"  ({flags} flagged)" if flags else ""))
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    import json

    from autoassess.evaluate import compare, load_grades, load_human_marks, write_report
    from autoassess.spec_builder import load_spec

    report = compare(load_spec(args.spec), load_grades(args.grades), load_human_marks(args.human))
    if args.out:
        write_report(report, args.out)
    print(json.dumps({k: v for k, v in report.items() if k != "flagged_questions"}, indent=2))
    print(f"{len(report['flagged_questions'])} flagged questions")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autoassess")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate-spec", help="check an exam spec and warn about vague criteria")
    p.add_argument("spec")
    p.set_defaults(func=_validate_spec)

    p = sub.add_parser("draft-spec", help="draft an exam spec from text files with an LLM")
    p.add_argument("--paper", required=True)
    p.add_argument("--rubric", required=True)
    p.add_argument("--model-answers", required=True)
    p.add_argument("--exam-id", default="exam")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_draft_spec)

    p = sub.add_parser("ingest", help="PDF or photos -> cleaned page images")
    p.add_argument("source")
    p.add_argument("out_dir")
    p.add_argument("--dpi", type=int, default=200)
    p.set_defaults(func=_ingest)

    p = sub.add_parser("grade", help="grade answer sheets (.txt, .pdf or images) against a spec")
    p.add_argument("--spec", required=True)
    p.add_argument("--out", required=True, help="folder for a JSON grade and an HTML report per sheet")
    p.add_argument("--runs", type=int, default=3, help="independent grading runs per question")
    p.add_argument("--critic", action="store_true", help="let a second model audit awarded marks")
    p.add_argument("--baseline", action="store_true", help="use the lexical baseline, no LLM")
    p.add_argument("--feedback-language", help="translate feedback, e.g. Hindi or Kannada (Bodhan Indic-Translate)")
    p.add_argument("sheets", nargs="+")
    p.set_defaults(func=_grade)

    p = sub.add_parser("evaluate", help="compare grades with human marks")
    p.add_argument("--spec", required=True)
    p.add_argument("--grades", required=True, help="folder written by `grade`")
    p.add_argument("--human", required=True, help="human marks CSV")
    p.add_argument("--out")
    p.set_defaults(func=_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
