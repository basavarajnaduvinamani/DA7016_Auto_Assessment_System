"""Convert a local SPRAG checkout; never download or bundle student responses."""

from __future__ import annotations

import csv
import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from autoassess.schemas import ExamSpec, Question, RubricCriterion
from autoassess.spec_builder import save_spec

HOLISTIC = (
    "Answer states the key points of the reference answer correctly; marks in proportion "
    "to how much of it is correct and complete."
)
FILES = {"ml": "MLResponses.csv", "python": "PyResponses.csv"}
HUMAN_FIELDS = ("exam_id", "student_id", "grader", "question_id", "criterion_id", "marks_awarded", "note")
META_FIELDS = ("student_id", "subject", "question_type", "split")


@dataclass(frozen=True)
class _Answer:
    source_id: str
    ordinal: int
    text: str
    scores: tuple[float | None, float | None]
    subject: str

    @property
    def sid(self) -> str:
        return f"{self.source_id}-{self.ordinal:04d}"


@dataclass(frozen=True)
class ImportSummary:
    questions: int
    answers: int
    dev_questions: int
    test_questions: int
    dev_answers: int
    test_answers: int
    missing_scores: int

    def __str__(self) -> str:
        return (f"{self.questions} questions, {self.answers} answers; "
                f"dev/test: {self.dev_questions}/{self.test_questions} questions, "
                f"{self.dev_answers}/{self.test_answers} answers; {self.missing_scores} missing scores")


def _read_csv(path: Path, fields: tuple[str, ...]) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not set(fields) <= set(reader.fieldnames or []):
            raise ValueError(f"{path.name}: expected columns {', '.join(fields)}")
        return list(reader)


def _score(raw: str | None, location: str) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{location}: score must be a number between 0 and 5 or empty") from None
    if not math.isfinite(value) or not 0 <= value <= 5:
        raise ValueError(f"{location}: score must be finite and between 0 and 5")
    return value


def _sample(answers: list[_Answer], limit: int, rng: random.Random) -> list[_Answer]:
    """Balance score strata, keeping low/high strata when the limit is small."""
    if limit == 0 or len(answers) <= limit:
        return answers
    strata: dict[float | None, list[_Answer]] = defaultdict(list)
    for answer in answers:
        scores = [s for s in answer.scores if s is not None]
        strata[sum(scores) / len(scores) if scores else None].append(answer)
    for group in strata.values():
        rng.shuffle(group)
    keys = sorted(key for key in strata if key is not None)
    if None in strata:
        keys.append(None)
    if limit < len(keys):
        # With too few slots, prefer known score levels over wholly unscored rows.
        known = [key for key in keys if key is not None]
        pool = known if len(known) >= limit else keys
        indices = [len(pool) // 2] if limit == 1 else [round(i * (len(pool) - 1) / (limit - 1)) for i in range(limit)]
        keys = [pool[i] for i in indices]
    chosen = []
    while len(chosen) < limit:
        for key in keys:
            if strata[key]:
                chosen.append(strata[key].pop())
                if len(chosen) == limit:
                    break
    return sorted(chosen, key=lambda answer: answer.ordinal)


def _label(number: int) -> str:
    # segment.py accepts at most two numeric digits, but supports lettered aliases.
    return f"Q{number}" if number < 100 else f"Q{(number - 100) // 8 + 1}{chr(ord('a') + (number - 100) % 8)}"


def import_sprag(
    src: str | Path,
    out: str | Path,
    *,
    subject: str = "all",
    per_question: int = 5,
    dev_share: float = 0.2,
    seed: int = 0,
) -> ImportSummary:
    """Import into a new/empty directory; return counts for the selected records."""
    if subject not in (*FILES, "all"):
        raise ValueError("subject must be ml, python or all")
    if per_question < 0:
        raise ValueError("per-question must be nonnegative (0 means all)")
    if not math.isfinite(dev_share) or not 0 <= dev_share <= 1:
        raise ValueError("dev-share must be between 0 and 1")
    src, out = Path(src), Path(out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("out must be a new or empty directory, to avoid mixing stale sheets")
    catalog = {}
    for row in _read_csv(src / "Question_data.csv", ("QuestionID", "QuestionText", "QuestionType", "Reference Answer")):
        qid = row["QuestionID"].strip()
        if not re.fullmatch(r"(?:PythonQ|BasicML)\d+", qid) or qid in catalog:
            raise ValueError("Question_data.csv: invalid or duplicate QuestionID")
        catalog[qid] = row
    grouped: dict[str, list[_Answer]] = defaultdict(list)
    for part, filename in FILES.items():
        if subject not in (part, "all"):
            continue
        rows = _read_csv(src / filename, ("QuestionID", "StudentAnswer", "Score1", "Score2"))
        for line, row in enumerate(rows, 2):
            qid = row["QuestionID"].strip()
            if qid not in catalog or not qid.startswith("BasicML" if part == "ml" else "PythonQ"):
                raise ValueError(f"{filename}:{line}: unknown question or mismatched subject")
            scores = tuple(_score(row[field], f"{filename}:{line}:{field}") for field in ("Score1", "Score2"))
            grouped[qid].append(_Answer(qid, len(grouped[qid]) + 1, row["StudentAnswer"], scores, part))
    selected = {qid: _sample(grouped[qid], per_question, random.Random(f"{seed}:{qid}")) for qid in sorted(grouped)}
    if not selected:
        raise ValueError("No answers found for the selected subject")
    questions, labels = [], {}
    for number, source_id in enumerate(selected, 1):
        row, qid, label = catalog[source_id], f"Q{number}", _label(number)
        aliases = [source_id] + ([label] if label != qid else [])
        questions.append(Question(
            id=qid, text=row["QuestionText"], model_answer=row["Reference Answer"], max_marks=5, aliases=aliases,
            # The reference answer goes into the criterion so the lexical baseline has content words to match.
            criteria=[RubricCriterion(id=f"{qid}.c1", description=f"{HOLISTIC} Key points: {row['Reference Answer'].strip()}",
                                      marks=5, allow_partial=True)],
        ))
        labels[source_id] = (qid, label)
    spec = ExamSpec(exam_id=f"sprag-{subject}", title=f"SPRAG ({subject})", language="en", questions=questions)
    split_ids = list(selected)
    random.Random(seed).shuffle(split_ids)
    dev_ids = set(split_ids[:round(len(split_ids) * dev_share)])
    out.mkdir(parents=True, exist_ok=True)
    (out / "sheets").mkdir()
    save_spec(spec, out / "exam_spec.yaml")
    missing = dev_answers = total = 0
    with (out / "human_marks.csv").open("w", newline="", encoding="utf-8") as human, \
            (out / "sheets.csv").open("w", newline="", encoding="utf-8") as meta:
        hw, mw = csv.DictWriter(human, HUMAN_FIELDS), csv.DictWriter(meta, META_FIELDS)
        hw.writeheader()
        mw.writeheader()
        for source_id, answers in selected.items():
            qid, label = labels[source_id]
            split = "dev" if source_id in dev_ids else "test"
            for answer in answers:
                total += 1
                dev_answers += split == "dev"
                (out / "sheets" / f"{answer.sid}.txt").write_text(f"{label}\n{answer.text}\n", encoding="utf-8")
                mw.writerow(dict(student_id=answer.sid, subject=answer.subject,
                                 question_type=catalog[source_id]["QuestionType"], split=split))
                for grader, score in zip(("grader_A", "grader_B"), answer.scores, strict=True):
                    if score is None:
                        missing += 1
                        continue
                    hw.writerow(dict(exam_id=spec.exam_id, student_id=answer.sid, grader=grader,
                                     question_id=qid, criterion_id=f"{qid}.c1", marks_awarded=score, note=""))
    return ImportSummary(len(questions), total, len(dev_ids), len(questions) - len(dev_ids),
                         dev_answers, total - dev_answers, missing)
