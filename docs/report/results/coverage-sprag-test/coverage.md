# Coverage: selective auto-marking

Source: SPRAG test, final config (advocate only), fresh run 2026-10-31. Answers with a human mark: 455.

An answer is auto-marked when confidence >= threshold and it has no review flag; agreement is measured on the auto-marked answers against the human consensus.

**At confidence >= 0.8: auto-mark 91% of answers (415 of 455) at QWK 0.773 [0.731, 0.811], MAE 0.78; 40 go to the teacher.**

| Confidence >= | Auto-marked | To teacher | QWK [95% CI] | MAE | Within 1 | Bias |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 100% (453) | 2 | 0.723 [0.666, 0.772] | 0.86 | 76% | 0.218 |
| 0.5 | 99% (449) | 6 | 0.734 [0.678, 0.781] | 0.847 | 77% | 0.236 |
| 0.6 | 98% (448) | 7 | 0.734 [0.678, 0.781] | 0.847 | 77% | 0.238 |
| 0.7 | 91% (415) | 40 | 0.773 [0.731, 0.811] | 0.779 | 79% | 0.121 |
| 0.75 | 91% (415) | 40 | 0.773 [0.731, 0.811] | 0.779 | 79% | 0.121 |
| 0.8 | 91% (415) | 40 | 0.773 [0.731, 0.811] | 0.779 | 79% | 0.121 |
| 0.85 | 50% (229) | 226 | 0.889 [0.856, 0.916] | 0.548 | 86% | -0.181 |
| 0.9 | 50% (229) | 226 | 0.889 [0.856, 0.916] | 0.548 | 86% | -0.181 |
| 0.95 | 50% (228) | 227 | 0.889 [0.856, 0.916] | 0.548 | 86% | -0.184 |
| 1 | 50% (228) | 227 | 0.889 [0.856, 0.916] | 0.548 | 86% | -0.184 |
