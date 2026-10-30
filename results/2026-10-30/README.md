### FILE: README.md

scope: offline evidence study; blocked paid-model and handwritten measurements are recorded in ../../07_build_autoassessment.md. [../../07_build_autoassessment.md]

## Reproduce the new aggregates

command: `.venv/bin/python scripts/study.py reproduce --out /tmp/autoassess-study-reproduction.json` [../../scripts/study.py]

inputs: anonymised score pairs, split manifests, per-case robustness records and evidence manifests in this directory. Raw answers, evidence quotes, model embeddings and private keys are excluded. [historical-lexical/scores.json] [current-lexical/scores.json] [lexical-detector-robustness.json]

semantics: exact equality against the stored aggregates and export hashes; recomputes question counts, QWK, MAE, bias, exact agreement, within-one agreement, robustness outcomes and detector flag counts. Does not call providers. [../../scripts/study.py]

## Published report verification

command: `.venv/bin/python scripts/study.py verify-numbers --out /tmp/autoassess-report-verification.json` [../../scripts/study.py]

status: BLOCKED; this command inventories numeric literals and exits unsuccessfully because the raw paid-model and handwritten runs are unavailable. It does not independently verify the report by comparing transcribed tables. [report-number-verification.json]

## Pending analyses

referral command: `.venv/bin/python scripts/study.py calibrate --scores PRIVATE_DEFAULT_SCORES.json --minimum-coverage 0.5 --out PRIVATE_REFERRAL_RESULTS.json` [../../scripts/study.py]

referral protocol: development accepted MAE minimisation subject to the coverage floor; ties prefer greater coverage. Frozen threshold evaluated on test. Forced review for injection or low OCR confidence remains mandatory. Export must distinguish forced review from the original confidence-based review decision; historical exports without that metadata fail closed. Test curves are descriptive and must not be used for selection. [../../src/autoassess/validation_study.py]

random referral: uniform sampling of the same number of test answers. Expected MAE is the full test MAE. Percentile bands describe random selection variability. [../../src/autoassess/validation_study.py]

paired command: `.venv/bin/python scripts/study.py compare --default PRIVATE_DEFAULT_SCORES.json --baseline PRIVATE_BASELINE_SCORES.json --out PRIVATE_PAIRED_RESULTS.json` [../../scripts/study.py]

paired protocol: complete matched items, equal human references, question IDs and split; question clusters sampled with replacement using identical indices for both systems. Differences are default minus baseline. Positive QWK difference favours default; positive MAE difference favours baseline. Missing predictions fail instead of silently disappearing in an inner join. [../../src/autoassess/validation_study.py]

embedding command: `.venv/bin/python scripts/study.py embedding --scores PRIVATE_SCORE_PAIRS.json --embeddings PRIVATE_FROZEN_EMBEDDINGS.json --out PRIVATE_EMBEDDING_RESULTS` [../../scripts/study.py]

embedding input: JSON object with `model_id`, `revision`, `model_sha256`, `encoding_command` and `rows`; each row has `item_id`, numeric `answer` and `reference` vectors, and boolean `blank`. Vectors remain private. Freeze one encoder for dev and test; do not train it on test labels. [../../scripts/study.py]

embedding mapping: answer-reference cosine, with a nonnegative slope and intercept fitted to development mark fractions only; clip to question bounds, force blanks to zero. This is a score baseline, not a replacement for evidence-bound rubric grading. No neural embedding-model run was executed. [../../src/autoassess/embedding_study.py] [baseline-status.json]

single-pass configuration: `Config("single_pass", runs=1, critic=False, advocate=False)` through `make_grade_fn`; quote verification and mark clipping remain enabled. No paid run was executed. [../../src/autoassess/experiments.py] [baseline-status.json]

historical provenance: model ID, prompt/config hashes, execution dates and receipts are UNKNOWN. File modification times are recorded separately and are not claimed as execution dates. [historical-lexical/evidence-manifest.json]

API spend: session paid calls and spend are recorded in each run manifest; historical experiment spend is UNKNOWN. [lexical-run.json] [lexical-detector-robustness.json]
