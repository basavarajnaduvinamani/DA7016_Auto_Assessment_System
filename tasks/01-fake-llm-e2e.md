# 01: Offline "fake" LLM provider and end-to-end smoke test

Status: done

## Goal

Run the whole LLM pipeline (grade with critic, advocate, feedback, HTML report, red-ink PDF) with no key and no network, so CI proves the full path works and the demo can run in a "dry run" mode.

## Files

- New `src/autoassess/providers/scripted.py`: `ScriptedLLM(LLMClient)`.
- `src/autoassess/providers/__init__.py`: `make_llm` returns `ScriptedLLM` when `settings.llm_provider == "fake"` (no key needed, skip the real-sheets privacy check).
- `src/autoassess/config.py`: accept `fake` as an `AUTOASSESS_LLM_PROVIDER` value.
- New `tests/test_e2e_fake.py`.
- `README.md`: one line under Setup about `AUTOASSESS_LLM_PROVIDER=fake`.

## Behaviour

`ScriptedLLM` answers each prompt deterministically by recognising which stage sent it (grader, critic, advocate, feedback, segmentation re-split, spec drafting, regrade) from the system prompt, and returns a JSON reply in that stage's expected schema. Look at the prompt builders and parsers in `grader.py`, `critic.py`, `advocate.py`, `feedback.py`, `segment.py`, `regrade.py`, `spec_builder.py` to get the shapes right. Rules for the replies:

- Grader: for each criterion, award full marks if at least one rubric keyword/phrase from the criterion description (case-insensitive word overlap is enough) appears in the answer, else 0. The evidence quote must be an exact substring of the answer (pick the line containing the overlap) so the quote check passes.
- Critic and advocate: return "no change" for every criterion.
- Feedback: return a minimal valid strength / fix / next-time remark that passes the verifier.
- `complete_json_images`: raise `NotImplementedError` with a clear message (image input is out of scope).
- Same input gives the same output (no randomness).
- Unknown prompt: raise `ValueError("ScriptedLLM: unrecognised prompt")` so a new stage fails loudly instead of silently.

## Done when

- `AUTOASSESS_LLM_PROVIDER=fake autoassess grade --spec data/sample_exam/exam_spec.yaml --out <tmp> --critic --advocate --annotate data/sample_exam/answer_sheets/*.txt` exits 0 and writes, for each of S001-S003, a grade JSON, an HTML report and an annotated PDF.
- `tests/test_e2e_fake.py` runs that command in-process (call `cli.main([...])`) on a tmp dir and asserts: files exist; every awarded criterion has a quote that is a substring of the answer; S001 total > S003 total; no criterion is flagged for a withdrawn quote.
- A unit test shows `ScriptedLLM` raises on an unknown prompt.
- `pytest -q` passes; no test does network I/O.

## Out of scope

Changing any real prompt, schema, or grading rule. Image input. Touching `app.py` (task 04 uses this provider).
