# Auto-Assessment

DA7016 (Recent Advances in Generative AI) final project. It grades a full answer sheet against a rubric and gives marks per question with feedback a student can act on. Every mark points to a rubric criterion and a verbatim quote from the answer.

Inputs are the question paper, the answer sheet, the rubric and a model answer per question. Outputs are marks per question, feedback that the rubric supports, and the sheet itself marked in red ink the way an Indian examiner marks a booklet. It grades on its own and knows when to defer: a mark it is unsure of is written with a **?** and sent to a teacher, and the evaluation reports accuracy on the marks it accepts by itself.

Plan: [Auto-Assessment: Build Plan](https://claude.ai/artifact/9nQFs4PiXSN8tURk7ajeVo)

## Pipeline

```
teacher docs ──> exam spec builder ─────────────────────┐
answer sheet ──> ingest ──> OCR ──> segmentation ──> rubric grading ──> feedback + verifier ──> report
                             ^                                              ^
                    Bodhan IndicOCR (week 5)                  Bodhan Indic-Translate (week 5)
```

Each stage reads and writes a Pydantic model from `src/autoassess/schemas.py`. OCR, LLM and translation sit behind interfaces in `src/autoassess/providers/`, so Bodhan AI plugs in by config. Every paid call is cached by content hash under `.cache/`.

## Status

| Week | Phase | State |
| --- | --- | --- |
| 1 | Foundations: schemas, exam spec builder, ingest, providers, cache | done |
| 2 | Criterion grader with evidence quotes, critic, segmentation, baseline, agreement metrics | done |
| 3 | OCR: IndicOCR open weights (local or Colab JSON), vision-LLM baseline; segmentation on OCR pages | done |
| 4 | Feedback with verifier, HTML report with highlighted evidence, FastAPI, Gradio demo | done |
| 5 | Bodhan hosted IndicOCR and Indic-Translate, with cache and budget guard | done |
| 6 | Evaluation harness: ablations, robustness suite, OCR error rates ([protocol](docs/evaluation.md)) | done; needs real sheets and human marks |
| 7 | [Design review](https://claude.ai/artifact/PKrBZ3ECvzbwnB3jw41d9V) changes: two-sided review, multi-signal confidence and "?", second examiner, follow-through (ECF), crossed-out work, fuzzy quotes, rubric lint, anonymiser, harder robustness, signed bias, CIs, coverage curve, fairness | done |
| 8 | Input ablation: OCR text vs page image vs both | done; needs real scans |
| 9 | Red-ink annotator, class mode and report, regrade requests, Gradio demo, Render deploy | done |

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ingest,dev]"
cp .env.example .env      # add your Gemini, OpenRouter and Bodhan keys
autoassess doctor         # one tiny live call per key, plus OpenRouter credit left; --free skips Bodhan (~Rs 0.20)
pytest
```

For an offline text-only dry run with no key or network, set `AUTOASSESS_LLM_PROVIDER=fake` (scripted word overlap, not semantic grading).

## Commands

```bash
# Check an exam spec: marks add up, ids are unique, criteria are checkable
autoassess validate-spec data/sample_exam/exam_spec.yaml

# Draft a spec from plain-text documents with an LLM, then review it by hand
autoassess draft-spec --paper paper.txt --rubric rubric.txt --model-answers answers.txt \
    --exam-id midterm --out data/midterm/exam_spec.yaml

# Answer sheet PDF, photo or folder of photos -> cleaned grayscale pages
autoassess ingest scans/S001.pdf work/S001

# Grade sheets: 3 runs per question, median marks, two-sided review, red-ink PDF
autoassess grade --spec data/sample_exam/exam_spec.yaml --out runs/llm --critic --advocate --annotate \
    data/sample_exam/answer_sheets/*.txt
#   --second-model openai/gpt-4.1-mini   a second examiner for the confidence check
#   --input image|hybrid                 grade from the page image (vision model), or image + OCR text

# A whole class, question by question, with a consistency pass and a class report
autoassess grade-class --spec ... --out runs/class --critic --advocate --annotate sheets...
autoassess class-report --spec ... --grades runs/class

# A student's regrade request for one criterion (logged beside the grade)
autoassess regrade --spec ... --grade runs/llm/S002.json --sheet S002.txt --criterion Q2.c3 --reason 'I named RAG'

# Same, with the no-LLM lexical baseline (the floor every model must beat)
autoassess grade --spec data/sample_exam/exam_spec.yaml --out runs/baseline --baseline data/sample_exam/answer_sheets/*.txt

# Agreement with human marks (QWK, MAE, signed bias, bootstrap CIs, coverage curve), plus human-vs-human;
# --meta adds results per language / handwriting / split, --transcript-grades the handwriting penalty
autoassess evaluate --spec data/sample_exam/exam_spec.yaml --grades runs/llm --human data/private/human_marks.csv \
    --meta data/private/sheets.csv --transcript-grades runs/llm_typed

# Experiments: ablations, robustness, OCR accuracy (see docs/evaluation.md)
autoassess experiment ablation --spec ... --human ... --out runs/ablation sheets...
autoassess experiment robustness --spec ... --out runs/robustness sheets...
autoassess ocr-eval --reference transcripts/ sheets...
```

## How grading stays defensible

- **One verdict per rubric criterion**, each with a quote copied from the answer. Code checks the quote really occurs in the answer; a made-up quote gets one repair round, then the marks are withdrawn and flagged.
- **Rubric rules in code**: marks are clipped to each criterion's range, and all-or-nothing criteria snap to 0 or full.
- **Three independent runs**, combined by the median per criterion.
- **Two-sided review**: an advocate looks for missed credit (another valid method, a correct idea in other words) and can raise a mark only with a verified quote; then a critic audits every award, the advocate's included, and can lower it. The strict-only design this replaced pushed marks down, and LLM graders already under-mark, so the evaluation reports **signed bias**, not just error size.
- **Knows when to defer**: confidence is the weakest of several signals: spread across runs, disagreement with a second examiner model, how much the reviewers changed, OCR confidence and withdrawn quotes. Below 0.8 the mark gets a **?** and goes to a teacher. `evaluate` reports the coverage curve: accuracy on the share accepted automatically at each threshold.
- **Quotes matched loosely enough** that one misread OCR character doesn't cost a criterion, and **spelling is never penalised** unless a criterion asks for it.
- **Follow-through (ECF)**: a criterion with `follow_through: true` on a question with `depends_on` sees the student's earlier answers and can credit correct working from a wrong earlier value. **Crossed-out work** (`~~text~~`, `[crossed out]`) is ignored.
- **Rubric lint** before grading: vague, bundled, duplicate or orphan follow-through criteria, and missing model answers.
- **Prompt-injection safe**: the answer is passed as data. The robustness suite covers English, Hindi, Kannada and subtle rubric-citing injections, keyword stuffing, an answer to a different question and spelling noise.
- **Privacy**: names, roll numbers, emails and phone numbers are removed before any LLM call, and `AUTOASSESS_REAL_SHEETS=1` refuses the free Gemini tier, which may use prompts for training.

Paid calls go through spend guards (`src/autoassess/budget.py`). OpenRouter calls record the exact cost the API reports and stop at `OPENROUTER_BUDGET_USD` (default $18 of the course's $20). Bodhan calls stop at `BODHAN_BUDGET_INR` (default ₹100 of ₹110). `grade` and `doctor` print the running totals.

The LLM client works with any OpenAI-compatible endpoint. `AUTOASSESS_LLM_PROVIDER` switches between Gemini (free tier, for development), OpenRouter (the course key, for evaluation and the demo) and a custom endpoint such as Ollama or vLLM.

## Try it

**Web demo (no key needed):** https://claude.ai/artifact/L2FPAup8f9jBFYfi8UVpxC runs the offline pipeline in the browser: segmentation, the lexical baseline and rubric feedback, on the sample quiz or your own spec and typed sheets. Its engine (`web/engine.js`) is a port of the Python baseline, and `tests/test_web_parity.py` checks both give identical marks and feedback. The LLM grader, critic, OCR and translation run in the Python app once keys are set.

## Feedback, report and demo

- **Feedback** says what earned marks, what lost them, and one concrete next step per lost point. A verifier keeps only items the grading supports: real criteria, praise only where marks were given, and quotes that occur in the answer. Gaps are filled from the rubric, so every lost mark gets a next step.
- **Report**: `grade` writes `<student>.html` beside the JSON. It shows the mark sheet, the answer with evidence highlighted, verdicts per criterion, feedback, flags and, when OCR gave boxes, the scanned page with evidence lines outlined.
- **API**: `pip install -e ".[api,ingest]"` then `uvicorn autoassess.api:app`. `POST /grade` takes `spec` and `sheet` files and returns the grade and the HTML report.
- **Demo**: `pip install -e ".[demo,ingest]"` then `python app.py`. Upload a sheet and get it back marked in red ink, with a comment-first summary, the marked PDF, the full evidence report and a regrade box; a second tab marks a class. `render.yaml` deploys it on Render's free plan ([docs/deploy.md](docs/deploy.md)). The demo extra pins Gradio to `>=6.30,<6.31` (tested with 6.30.0). Sample files are bundled for non-editable installs; choose `S002_scan.pdf` in Sample sheets to try the ruled-page PDF with configured OCR.
- **Red ink** (`--annotate`): one tick per mark at the evidence line, fractions for part marks, ECF and BOD where they apply, a wavy underline and correction under a wrong statement, a caret where a point is missing, bracketed marks in the margin, the total circled, a **?** for review, a strength / fix / next-time remark, a booklet cover with the marks grid, an **AI-marked** stamp, and a last page with the full feedback. Typed sheets are laid out on ruled pages first.
- **Translated feedback**: `--feedback-language Hindi` (Bodhan Indic-Translate, week 5). Evidence quotes stay as written, and the English feedback is kept for the teacher.

## Reading scanned sheets

Choose the OCR with `AUTOASSESS_OCR_PROVIDER`:

| Provider | What it is | Needs |
| --- | --- | --- |
| `text` | Typed `.txt` sheets, no OCR | nothing |
| `indic-precomputed` | Bodhan IndicOCR JSON made in [`notebooks/indic_ocr_colab.ipynb`](notebooks/indic_ocr_colab.ipynb) | a free Colab GPU, once per batch |
| `indic-local` | Bodhan IndicOCR open weights in-process | a GPU and the gated `bodhan-ai/indic-ocr` weights |
| `vision` | A vision LLM transcribes the page (baseline) | `AUTOASSESS_VISION_MODEL` |
| `bodhan` | Bodhan hosted API | week 5, uses the coupon credits |

IndicOCR handles printed English and 22 Indian languages, and handwriting in English and 12 Indian languages, including Hindi, Kannada, Tamil and Telugu. It returns boxes per block, which the report uses to highlight evidence on the page. Questions with low OCR confidence or a diagram are flagged.

## Data

- `data/sample_exam/` holds a 15-mark sample quiz with three typed answer sheets at different quality levels (S001 strong, S002 partial and out of order, S003 weak with Q3 missing).
- `human_marks_template.csv` is the format for human marks, one row per criterion per grader. Two independent graders per sheet give the human-to-human agreement baseline.
- Real student sheets go in `data/private/`, which git ignores. Remove names and roll numbers before any API call.

## Bodhan AI

Bodhan AI (IIT Madras with AI4Bharat) serves IndicOCR and Indic-Translate as hosted APIs, and as open weights on Hugging Face.

- **Hosted OCR**: set `AUTOASSESS_OCR_PROVIDER=bodhan` and `BODHAN_API_KEY`. Each page goes to `POST https://api.bodhan.ai/v1/chat/completions` with model `indic-ocr`; layout blocks come back with boxes, as with the open weights.
- **Translated feedback**: `autoassess grade ... --feedback-language Kannada` sends feedback paragraph by paragraph to `POST /v1/chat/completions` with model `indic-translate` and `target_language`. (The cookbook's `POST /translate` returns 404 on the live API.)
- **Credits**: every call is cached by content, so re-running costs nothing. A ledger in `.cache/bodhan_ledger.json` estimates spend (about Rs 0.20 per page) and stops paid calls at `BODHAN_BUDGET_INR` (default Rs 100 of the Rs 110 credit).
- **Free route**: the open weights run on a Colab GPU through `notebooks/indic_ocr_colab.ipynb`, which gives the same output format at no cost.

## Course and author

- Student: Basavaraj A Naduvinamani (DA25C005), Joint M.Sc. in Data Science and AI, IIT Madras and University of Birmingham
- Course: DA7016, Recent Advances in Generative AI (Jul to Nov 2026), Prof. Mitesh M. Khapra
- Earlier interim reports are kept in `docs/archive/`; this README and the build plan supersede them.
