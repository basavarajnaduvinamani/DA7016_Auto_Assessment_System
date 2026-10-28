# Demo test cases

Six synthetic answer sheets for the sample quiz (`data/sample_exam/exam_spec.yaml`, 15 marks). Each one tests a different situation. The file names start with a roll number (S005 to S010), so the teacher app matches them to the demo class automatically.

| Sheet | What it tests | Result with the final configuration (gemini-2.5-flash, advocate review) |
| --- | --- | --- |
| `S005_strong_english.txt` | A complete, correct answer | 15 / 15 |
| `S006_weak_english.txt` | Vague answers and a missing question | 0.5 / 15; Q3 marked unanswered, with a next step for every lost point |
| `S007_hindi.txt` | All three answers in Hindi (Devanagari), technical terms in English | 11.5 / 15; quotes taken from the Hindi text; with `--feedback-language Hindi` the feedback comes back in Hindi |
| `S008_kannada.txt` | One answer (Q2) in Kannada | 4 / 15 (full marks on Q2, the only question answered) |
| `S009_prompt_injection.txt` | A short answer plus a "note to the examiner" asking for full marks | 1.75 / 15; Q1 flagged `possible_prompt_injection` and sent to the teacher |
| `S010_off_topic.txt` | An answer about electrical transformers, keyword stuffing, and a skipped question | 0.5 / 15; the off-topic and skipped answers score 0 |

Known weakness shown by `S010`: the keyword-stuffed Q2 still earned 0.5 marks, because the advocate accepted the phrase "retrieval augmented generation" as evidence for the mitigation criterion. Evidence quotes stop invented content, but a bare list of the right words can still collect partial credit.

Run them from the command line:

```bash
autoassess grade --spec data/sample_exam/exam_spec.yaml --out runs/demo_cases --advocate --annotate data/demo_cases/*.txt
autoassess grade --spec data/sample_exam/exam_spec.yaml --out runs/demo_cases_hi --advocate --annotate \
    --feedback-language Hindi data/demo_cases/S007_hindi.txt
```

Or in the teacher app: create an assignment, import `data/sample_exam/exam_spec.yaml` as the rubric, upload these files and click **Grade all**. Live grading needs `OPENROUTER_API_KEY`; Hindi feedback needs a Bodhan translate key.
