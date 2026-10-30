# Robustness: injection and keyword-stuffing checks

These checks run before any model call and only route an answer to the teacher. They never change marks. The code is in `src/autoassess/injection.py`.

## Protocol

- `data/robustness/injection_dev.jsonl` has 20 attacks and 20 clean answers in en, hi, hinglish, kn, ta and te. I wrote it, and the patterns were tuned on it only.
- `data/robustness/injection_test.jsonl` has 40 attacks and 40 clean answers. A separate author wrote it from a brief, without seeing the detector code. It was scored **once**, after the patterns were frozen, and nothing was tuned on it afterwards.
- The real-answer false-alarm check uses all 4,039 SPRAG student answers (public CSVs; the data isn't committed).

Reproduce with `autoassess injection-eval --out results/robustness/injection_eval.json`.

## Results (30 Oct 2026)

| Set | Attacks caught | Clean answers flagged |
| --- | --- | --- |
| Dev (tuned on) | 20 / 20 | 0 / 20 |
| Held-out test, previous English-only regex | 0 / 40 | 1 / 40 |
| **Held-out test, current check** | **23 / 40 (57%)** | **5 / 40 (12.5%)** |
| SPRAG real answers | – | 0 / 4,039 injection, 8 / 4,039 keyword stuffing |

Held-out results by language (caught / attacks):

| Language | en | hi | hinglish | kn | ta | te |
| --- | --- | --- | --- | --- | --- | --- |
| Caught | 8/12 | 3/8 | 3/5 | 3/5 | 3/5 | 3/5 |

**What it misses:** authority claims ("the professor said..."), skip-the-check requests, and subtle claims that the rubric is satisfied. **What it falsely flags:** clean answers that explain prompt injection or jailbreaking, and Indic answers saying a topic "had many marks last year". The held-out set is now spent. Any future pattern change needs a new unseen set before claiming a new number.

The grader prompt treats the student's answer as data and tells the model to ignore instructions inside it. That stays the main defence. This check adds a teacher review on top. Whether a missed attack actually raises marks can only be measured with live grading, which costs API credit and hasn't been rerun yet.
