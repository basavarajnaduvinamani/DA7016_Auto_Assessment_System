# 05: Import the SPRAG dataset for evaluation

Status: done

## Goal

Get the first evaluation numbers with two human graders by converting SPRAG into the project's formats: an exam spec, one sheet per answer, a two-grader human marks CSV and a metadata CSV. Then `grade`, `evaluate` and `results` run on it unchanged.

## Data (read this first)

SPRAG: typed English short answers from an Indian engineering college. There are 4,039 answers to 114 questions (Python and ML), each scored 0-5 by two graders. Zenodo record 10.5281/zenodo.14928181 lists it as CC BY 4.0. The GitHub copy `https://github.com/sridevibonthu/SPRAG` has no licence file, so **never commit the data**. It goes under `data/private/` (git-ignored). Files in `Data/`:

- `Question_data.csv`: `QuestionID, QuestionText, QuestionType, Reference Answer` (114 rows; ids like `PythonQ001`, `BasicML045`; QuestionType is Explain/Define/Remember/Difference/Apply, one empty).
- `MLResponses.csv` (1,110) and `PyResponses.csv` (2,929): `QuestionID, StudentAnswer, Score1, Score2`. Scores are `0`-`5`, sometimes `5.0`, and about 28 rows have a missing score. There are **no student ids**, so each answer is its own "sheet". Empty-looking answers such as `-` or `No answer for this` are real zero-mark answers: keep them.
- `refstdcombined.csv` duplicates the above. Ignore it.

## Files

- New `src/autoassess/datasets/sprag.py` (and `datasets/__init__.py`).
- `src/autoassess/cli.py`: new subcommand `import-sprag`.
- New `tests/test_sprag_import.py` with a tiny **invented** fixture under `tests/fixtures/sprag/` (same columns, around 6 questions and 20 answers, made-up text). No real SPRAG rows in the repo.
- `docs/evaluation.md`: a section "Public data: SPRAG" with the commands below and the licence note.

## Interface

```bash
git clone --depth 1 https://github.com/sridevibonthu/SPRAG data/private/SPRAG
autoassess import-sprag --src data/private/SPRAG/Data --out data/private/sprag \
    [--subject ml|python|all] [--per-question 5] [--dev-share 0.2] [--seed 0]
```

Writes into `--out`:

- `exam_spec.yaml`: one question per SPRAG question that has at least one sampled answer. Ids are `Q1..Qn` in a stable order (sorted SPRAG id), with `aliases` holding the SPRAG id. `max_marks: 5`, `model_answer` = Reference Answer, and `text` = QuestionText. Each question gets **one holistic criterion** `Qn.c1` (5 marks, `allow_partial: true`) described as: "Answer states the key points of the reference answer correctly; marks in proportion to how much of it is correct and complete." `exam_id: sprag-<subject>`. It must pass `autoassess validate-spec`. Lint warnings about a single holistic criterion are acceptable; list them in the PR.
- `sheets/<sid>.txt`: one per sampled answer, with `sid` = `<SPRAGid>-<nnnn>` (stable per row). The content is the question label line in a form `segment.py` already recognises for `Qn`, followed by the answer text, so segmentation assigns it to the right question. Check this with a test that runs `segment` on every fixture sheet.
- `human_marks.csv` in the `data/sample_exam/human_marks_template.csv` format: two rows per answer, `grader_A` = Score1 and `grader_B` = Score2, criterion `Qn.c1`. Skip a grader's row when its score is missing, and count these in a printed summary.
- `sheets.csv` metadata for `evaluate --meta`: `student_id, subject (ml|python), question_type, split (dev|test)`. The split is **by question**, not by answer: a seeded `--dev-share` of questions is dev and the rest is test, so prompt tuning on dev never sees test questions.
- `--per-question N` samples at most N answers per question (seeded, stratified so each question's score spread is kept roughly). `0` means all. Default 5 keeps a full run cheap: about 570 answers for `all`, about 230 for `ml`.

Print a one-line summary: questions, answers, dev/test counts, and missing scores.

## Done when

- On the fixture: the spec validates, every sheet segments to its own question, `human_marks.csv` round-trips through `evaluate`'s loader and gives a `human_vs_human` block, sampling is deterministic for a seed, and dev/test never share a question.
- `evaluate` runs end to end on the fixture output using `--baseline` grades (no LLM). Put this in a test.
- `pytest -q` passes. No network in tests (the clone is a manual step).

## Out of scope

Analytic (multi-criterion) rubrics for SPRAG: a later task can draft them with `draft-spec` as an ablation. Running the LLM grader on real data, other datasets, and committing any SPRAG content.
