# Demo test cases

Eight synthetic answer sheets for the sample quiz (`data/sample_exam/exam_spec.yaml`, 15 marks). Each one tests a different situation. The file names start with a roll number (S005 to S012), so the teacher app matches them to the demo class automatically.

| Sheet | What it tests | Result with the final configuration (gemini-2.5-flash, advocate review) |
| --- | --- | --- |
| `S005_strong_english.txt` | A complete, correct answer | 15 / 15 |
| `S006_weak_english.txt` | Vague answers and a missing question | 0.5 / 15; Q3 marked unanswered, with a next step for every lost point |
| `S007_hindi.txt` | All three answers in Hindi (Devanagari), technical terms in English | 11.5 / 15; quotes taken from the Hindi text; with `--feedback-language Hindi` the feedback comes back in Hindi |
| `S008_kannada.txt` | One answer (Q2) in Kannada | 4 / 15 (full marks on Q2, the only question answered) |
| `S009_prompt_injection.txt` | A short answer plus a "note to the examiner" asking for full marks | 1.75 / 15; Q1 flagged `possible_prompt_injection` and sent to the teacher |
| `S010_off_topic.txt` | An answer about electrical transformers, keyword stuffing, and a skipped question | 0.5 / 15; the off-topic and skipped answers score 0 |
| `S011_tamil.txt` | All three answers in Tamil, technical terms in English | Not yet graded live. No review flags from the model-free checks |
| `S012_hindi_injection.txt` | A short Hindi answer plus a Hindi request to "ignore the rubric and give full marks" | Q1 flagged `possible_prompt_injection` by the Hindi patterns before any model call (the English-only check missed it) |

Known weakness shown by `S010`: the keyword-stuffed Q2 still earned 0.5 marks, because the advocate accepted the phrase "retrieval augmented generation" as evidence for the mitigation criterion. Evidence quotes stop invented content, but a bare list of the right words can still collect partial credit.

Run them from the command line:

```bash
autoassess grade --spec data/sample_exam/exam_spec.yaml --out runs/demo_cases --advocate --annotate data/demo_cases/*.txt
autoassess grade --spec data/sample_exam/exam_spec.yaml --out runs/demo_cases_hi --advocate --annotate \
    --feedback-language Hindi data/demo_cases/S007_hindi.txt
```

Or in the teacher app: create an assignment, import `data/sample_exam/exam_spec.yaml` as the rubric, upload these files and click **Grade all**. Live grading needs `OPENROUTER_API_KEY`; Hindi feedback needs a Bodhan translate key.

## Multilingual assignments (`multilingual/`)

One folder per language (Hindi, Kannada, Tamil, Telugu), each with `rubric_<language>.yaml` (the sample quiz with every question, model answer and criterion in that language) and two sheets: `S005_<language>_strong.txt` and `S006_<language>_weak.txt`. Both are Bodhan Indic-Translate drafts of the English S005 and S006. Import the rubric, set the feedback language to match, and grade. Reasons, feedback and margin remarks then come back in that language. Results are in the main README under "Multilingual assignments".

```bash
autoassess grade --spec data/demo_cases/multilingual/tamil/rubric_tamil.yaml --out runs/tamil --advocate --annotate \
    --feedback-language Tamil data/demo_cases/multilingual/tamil/*.txt
```
