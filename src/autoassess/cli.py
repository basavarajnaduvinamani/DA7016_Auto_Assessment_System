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
    spec = draft_spec(
        read(args.paper), read(args.rubric), read(args.model_answers), make_llm(Settings.load()), args.exam_id
    )
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
    from autoassess.spec_builder import lint_spec

    for w in lint_spec(spec):
        print(f"  rubric warning: {w}")
    llm = None if args.baseline else make_llm(settings)
    reviewer = make_llm(settings, critic=True) if llm else None
    critic = reviewer if args.critic and llm else None
    advocate = reviewer if args.advocate and llm else None
    second_model = args.second_model or settings.second_model
    second = make_llm(settings, model=second_model) if second_model and llm else None
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
            advocate=advocate,
            second=second,
            mode=args.input,
            translator=translator,
            feedback_language=args.feedback_language,
        )
        grade = result.grade
        (out / f"{sid}.json").write_text(grade.model_dump_json(indent=2), encoding="utf-8")
        (out / f"{sid}.html").write_text(result.html(), encoding="utf-8")
        if args.annotate:
            marked = result.annotate(out / "marked")
            print(f"  marked sheet: {marked.pdf}")
        review = [q.question_id for q in grade.questions if q.needs_review]
        print(
            f"{sid}: {grade.total:g} / {spec.total_marks:g}"
            + (f"  (? for review: {', '.join(review)})" if review else "")
        )
    from autoassess.doctor import spend_summary

    print(f"spend so far: {spend_summary(settings)}")
    return 0


def _evaluate(args: argparse.Namespace) -> int:
    import json

    from autoassess.evaluate import (
        compare,
        handwriting_penalty,
        load_grades,
        load_human_marks,
        load_sheet_meta,
        write_report,
    )
    from autoassess.spec_builder import load_spec

    meta = load_sheet_meta(args.meta) if args.meta else None
    grades = load_grades(args.grades)
    report = compare(load_spec(args.spec), grades, load_human_marks(args.human), meta)
    if args.transcript_grades:
        report["handwriting_penalty"] = handwriting_penalty(grades, load_grades(args.transcript_grades), meta)
    if args.out:
        write_report(report, args.out)
    print(json.dumps({k: v for k, v in report.items() if k != "flagged_questions"}, indent=2))
    print(f"{len(report['flagged_questions'])} flagged questions")
    return 0


def _load_sheets(spec, sheets, ocr, llm):
    from autoassess.experiments import read_pages_for_sheets
    from autoassess.segment import segment

    return {sid: segment(spec, pages, llm) for sid, pages in read_pages_for_sheets(sheets, ocr, spec.language).items()}


def _experiment(args: argparse.Namespace) -> int:
    import json

    from autoassess.config import Settings
    from autoassess.evaluate import load_human_marks
    from autoassess.experiments import (
        DEFAULT_CONFIGS,
        ablation_table,
        make_grade_fn,
        robustness_table,
        run_ablation,
        run_robustness,
    )
    from autoassess.providers import make_llm, make_ocr
    from autoassess.spec_builder import load_spec

    settings = Settings.load()
    spec = load_spec(args.spec)
    llm = None if args.baseline_only else make_llm(settings)
    critic = make_llm(settings, critic=True) if llm else None
    from autoassess.experiments import read_pages_for_sheets
    from autoassess.segment import segment

    pages = read_pages_for_sheets(args.sheets, make_ocr(settings), spec.language)
    sheets = {sid: segment(spec, p, llm) for sid, p in pages.items()}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.kind == "ablation":
        if not args.human:
            print("ablation needs --human", file=sys.stderr)
            return 2
        # Typed sheets keep their .txt path in image_path, so check for real image files.
        has_images = any(
            pg.image_path and Path(pg.image_path).suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
            for ps in pages.values()
            for pg in ps
        )
        results = run_ablation(
            spec, sheets, load_human_marks(args.human), llm, critic, pages=pages if has_images else None
        )
        (out / "ablation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        table = ablation_table(results)
    else:
        by_name = {c.name: c for c in DEFAULT_CONFIGS}
        cfg = by_name["lexical_baseline"] if args.baseline_only else by_name["full"]
        report = run_robustness(spec, sheets, make_grade_fn(cfg, llm, critic))
        (out / "robustness.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        table = robustness_table(report)
    (out / f"{args.kind}.md").write_text(table + "\n", encoding="utf-8")
    print(table)
    return 0


def _ocr_eval(args: argparse.Namespace) -> int:
    import json

    from autoassess.config import Settings
    from autoassess.experiments import ocr_accuracy, read_pages_for_sheets
    from autoassess.providers import make_ocr

    refs = {p.stem: p.read_text(encoding="utf-8") for p in Path(args.reference).glob("*.txt")}
    settings = Settings.load()
    result = ocr_accuracy(read_pages_for_sheets(args.sheets, make_ocr(settings), args.language), refs)
    result = {"provider": settings.ocr_provider, "sheets": result}
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


def _grade_class(args: argparse.Namespace) -> int:
    import json

    from autoassess.classwork import class_report, class_report_html, grade_class
    from autoassess.config import Settings
    from autoassess.experiments import read_pages_for_sheets
    from autoassess.feedback import add_feedback
    from autoassess.providers import make_llm, make_ocr
    from autoassess.segment import segment
    from autoassess.spec_builder import lint_spec, load_spec

    settings = Settings.load()
    spec = load_spec(args.spec)
    for w in lint_spec(spec):
        print(f"  rubric warning: {w}")
    llm = make_llm(settings)
    reviewer = make_llm(settings, critic=True)
    pages = read_pages_for_sheets(args.sheets, make_ocr(settings), spec.language)
    sheets = {sid: segment(spec, p, llm) for sid, p in pages.items()}
    images = None
    if args.input != "text":
        from autoassess.page_images import answer_crops

        images = lambda sid, seg: answer_crops(seg, pages[sid]) or None  # noqa: E731
    grades = grade_class(
        spec, sheets, llm, runs=args.runs, critic=reviewer if args.critic else None,
        advocate=reviewer if args.advocate else None, images=images, mode=args.input,
    )  # fmt: skip
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for g in grades:
        g = add_feedback(spec, g, {k: v.text for k, v in sheets[g.student_id].items()}, llm)
        (out / f"{g.student_id}.json").write_text(g.model_dump_json(indent=2), encoding="utf-8")
        if args.annotate:
            from autoassess.annotate import annotate_sheet

            annotate_sheet(spec, g, sheets[g.student_id], pages[g.student_id], out / "marked")
        review = [q.question_id for q in g.questions if q.needs_review]
        print(
            f"{g.student_id}: {g.total:g} / {spec.total_marks:g}"
            + (f"  (? for review: {', '.join(review)})" if review else "")
        )
    report = class_report(
        spec, [type(grades[0]).model_validate_json((out / f"{g.student_id}.json").read_text()) for g in grades]
    )
    (out / "class_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "class_report.html").write_text(class_report_html(report, spec.title), encoding="utf-8")
    print(f"class report: {out / 'class_report.html'}")
    return 0


def _class_report(args: argparse.Namespace) -> int:
    import json

    from autoassess.classwork import class_report, class_report_html
    from autoassess.evaluate import load_grades
    from autoassess.spec_builder import load_spec

    spec = load_spec(args.spec)
    report = class_report(spec, load_grades(args.grades))
    out = Path(args.out or args.grades)
    (out / "class_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "class_report.html").write_text(class_report_html(report, spec.title), encoding="utf-8")
    print(f"class report: {out / 'class_report.html'}")
    return 0


def _regrade(args: argparse.Namespace) -> int:
    from autoassess.config import Settings
    from autoassess.pipeline import read_sheet
    from autoassess.providers import make_llm, make_ocr
    from autoassess.regrade import regrade
    from autoassess.schemas import SheetGrade
    from autoassess.segment import segment
    from autoassess.spec_builder import load_spec

    settings = Settings.load()
    spec = load_spec(args.spec)
    grade = SheetGrade.model_validate_json(Path(args.grade).read_text(encoding="utf-8"))
    segs = segment(spec, read_sheet(args.sheet, make_ocr(settings), language=spec.language))
    qid = args.criterion.split(".")[0]
    new, rec = regrade(spec, grade, segs[qid].text, qid, args.criterion, args.reason, make_llm(settings),
                       log=Path(args.grade).with_name("regrades.jsonl"))  # fmt: skip
    Path(args.grade).write_text(new.model_dump_json(indent=2), encoding="utf-8")
    print(f"{rec.criterion_id}: {rec.old_marks:g} -> {rec.new_marks:g} ({rec.decision}). {rec.response}")
    return 0


def _results(args: argparse.Namespace) -> int:
    import json

    from autoassess.results import build_results

    read = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))  # noqa: E731
    build_results(
        read(args.agreement),
        args.out,
        ablation=read(args.ablation) if args.ablation else None,
        robustness=read(args.robustness) if args.robustness else None,
        ocr=[read(path) for path in args.ocr] if args.ocr else None,
    )
    print(f"results pack: {args.out}")
    return 0


def _coverage(args: argparse.Namespace) -> int:
    from autoassess.coverage import THRESHOLDS, answer_rows, coverage_table, write_coverage
    from autoassess.evaluate import load_grades, load_human_marks
    from autoassess.spec_builder import load_spec

    rows = answer_rows(load_spec(args.spec), load_grades(args.grades), load_human_marks(args.human))
    if not rows:
        print("No graded answer has a human mark: check that student and question ids match.", file=sys.stderr)
        return 2
    table = coverage_table(rows, args.thresholds or THRESHOLDS, ci=not args.no_ci)
    written = write_coverage(table, args.out, source=args.source or f"{args.grades} vs {Path(args.human).name}")
    print(written["headline"] or "No answers auto-marked at the headline threshold.")
    print(
        f"coverage table: {Path(args.out) / 'coverage.md'}"
        + ("" if written["figure"] else " (figure skipped: matplotlib not installed)")
    )
    return 0


def _import_sprag(args: argparse.Namespace) -> int:
    import csv

    from autoassess.datasets.sprag import import_sprag

    try:
        summary = import_sprag(
            args.src,
            args.out,
            subject=args.subject,
            per_question=args.per_question,
            dev_share=args.dev_share,
            seed=args.seed,
        )
    except (ValueError, OSError, csv.Error) as err:
        print(f"Cannot import SPRAG: {err}", file=sys.stderr)
        return 2
    print(summary)
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from autoassess.config import Settings
    from autoassess.doctor import FAIL, report, run_doctor

    settings = Settings.load()
    checks = run_doctor(settings, paid=not args.free)
    print(report(settings, checks))
    return 1 if any(c.status == FAIL for c in checks) else 0


def _serve(args) -> int:
    import uvicorn

    from autoassess.web.app import create_app

    app = create_app(args.data_dir, reset_demo=args.reset_demo)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse command-line arguments and run the selected operation."""
    parser = argparse.ArgumentParser(prog="autoassess")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="start the Red-Ink Classroom teacher app")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--data-dir")
    p.add_argument("--reset-demo", action="store_true", help="replace local app data with the synthetic demo")
    p.set_defaults(func=_serve)

    p = sub.add_parser("doctor", help="check each configured key with one tiny live request")
    p.add_argument("--free", action="store_true", help="skip the Bodhan checks (they cost about Rs 0.20)")
    p.set_defaults(func=_doctor)

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
    p.add_argument("--critic", action="store_true", help="let a reviewer lower marks it finds too generous")
    p.add_argument(
        "--advocate",
        action="store_true",
        help="let a reviewer raise marks it finds were missed (verified quote needed)",
    )
    p.add_argument("--second-model", help="a second examiner model for the confidence check, e.g. openai/gpt-4.1-mini")
    p.add_argument("--baseline", action="store_true", help="use the lexical baseline, no LLM")
    p.add_argument(
        "--input",
        choices=["text", "image", "hybrid"],
        default="text",
        help="grade the OCR text, the page image (vision model), or both",
    )
    p.add_argument("--annotate", action="store_true", help="also write the sheet marked in red ink (PDF + PNGs)")
    p.add_argument("--feedback-language", help="translate feedback, e.g. Hindi or Kannada (Bodhan Indic-Translate)")
    p.add_argument("sheets", nargs="+")
    p.set_defaults(func=_grade)

    p = sub.add_parser(
        "grade-class", help="grade a class question by question, with a consistency pass and class report"
    )
    p.add_argument("--spec", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--critic", action="store_true")
    p.add_argument("--advocate", action="store_true")
    p.add_argument("--input", choices=["text", "image", "hybrid"], default="text")
    p.add_argument("--annotate", action="store_true")
    p.add_argument("sheets", nargs="+")
    p.set_defaults(func=_grade_class)

    p = sub.add_parser("class-report", help="class report from a folder of grades")
    p.add_argument("--spec", required=True)
    p.add_argument("--grades", required=True)
    p.add_argument("--out")
    p.set_defaults(func=_class_report)

    p = sub.add_parser("regrade", help="regrade one criterion after a student's request")
    p.add_argument("--spec", required=True)
    p.add_argument(
        "--grade", required=True, help="the sheet's grade JSON (updated in place; requests logged beside it)"
    )
    p.add_argument("--sheet", required=True, help="the answer sheet")
    p.add_argument("--criterion", required=True, help="e.g. Q2.c3")
    p.add_argument("--reason", required=True, help="the student's reason")
    p.set_defaults(func=_regrade)

    p = sub.add_parser("evaluate", help="compare grades with human marks")
    p.add_argument("--spec", required=True)
    p.add_argument("--grades", required=True, help="folder written by `grade`")
    p.add_argument("--human", required=True, help="human marks CSV")
    p.add_argument("--meta", help="sheet metadata CSV: student_id plus columns such as language, handwriting, split")
    p.add_argument("--transcript-grades", help="folder of grades for the typed transcripts of the same sheets")
    p.add_argument("--out")
    p.set_defaults(func=_evaluate)

    p = sub.add_parser("experiment", help="ablation or robustness experiment")
    p.add_argument("kind", choices=["ablation", "robustness"])
    p.add_argument("--spec", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--human", help="human marks CSV (ablation)")
    p.add_argument("--baseline-only", action="store_true", help="no LLM: run the lexical baseline only")
    p.add_argument("sheets", nargs="+")
    p.set_defaults(func=_experiment)

    p = sub.add_parser("ocr-eval", help="CER/WER of the configured OCR against typed transcripts")
    p.add_argument("--reference", required=True, help="folder of <sheet>.txt transcripts")
    p.add_argument("--language")
    p.add_argument("--out")
    p.add_argument("sheets", nargs="+")
    p.set_defaults(func=_ocr_eval)

    p = sub.add_parser("results", help="tables and optional figures from existing evaluation JSON")
    p.add_argument("--agreement", required=True)
    p.add_argument("--ablation")
    p.add_argument("--robustness")
    p.add_argument("--ocr", nargs="+")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_results)

    p = sub.add_parser("coverage", help="share auto-marked vs agreement across confidence thresholds")
    p.add_argument("--spec", required=True)
    p.add_argument("--grades", required=True, help="folder written by `grade`")
    p.add_argument("--human", required=True, help="human marks CSV")
    p.add_argument("--out", required=True, help="folder for coverage.md/.csv/.json and coverage.png")
    p.add_argument("--thresholds", type=float, nargs="+", help="default: 0 0.5 0.6 0.7 0.75 0.8 0.85 0.9 0.95 1")
    p.add_argument("--no-ci", action="store_true", help="skip the question-clustered bootstrap intervals")
    p.add_argument("--source", help="label for the table, e.g. 'SPRAG test, final config'")
    p.set_defaults(func=_coverage)

    p = sub.add_parser("import-sprag", help="convert local SPRAG CSVs into evaluation inputs")
    p.add_argument("--src", required=True, help="SPRAG checkout's Data directory")
    p.add_argument("--out", required=True, help="new or empty output directory (keep real data under data/private)")
    p.add_argument("--subject", choices=["ml", "python", "all"], default="all")
    p.add_argument("--per-question", type=int, default=5, help="answers per question; 0 selects all")
    p.add_argument("--dev-share", type=float, default=0.2, help="share of questions reserved for development")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=_import_sprag)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
