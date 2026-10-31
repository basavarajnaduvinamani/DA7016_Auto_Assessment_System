"""Deterministic text-only replies for offline pipeline dry runs."""

from __future__ import annotations

import json
import re

from autoassess.providers.base import LLMClient


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold()))


STOPWORDS = frozenset(
    "with that this from which their when what into each does have been more than also such used uses".split()
)


def _content_words(text: str) -> set[str]:
    return {w for w in _words(text) if len(w) >= 4 and w not in STOPWORDS}


def _short(criterion: str, limit: int = 60) -> str:
    """A rubric point without its leading verb ("States that ..."), ended with "." or cut to fit with "…"."""
    text = re.sub(
        r"^(states|says|mentions|gives|defines|explains|names|lists)( that)?\s+", "", criterion.strip(), flags=re.I
    )
    text = text.rstrip(".")
    return text + "." if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0].strip("\n")


def _rows(user: str, heading: str) -> list[dict]:
    return json.loads(user.rsplit(heading, 1)[1])


def _award(description: str, marks: float, answer: str) -> dict:
    keywords = _content_words(description)
    evidence = next((line for line in answer.splitlines() if keywords & _content_words(line)), None)
    return {
        "verdict": "met" if evidence else "not_met",
        "marks_awarded": marks if evidence else 0,
        "evidence": evidence,
        "reason": "Rubric word found in the answer." if evidence else "No rubric word found in the answer.",
        "follow_through": False,
    }


class ScriptedLLM(LLMClient):
    """Recognise existing stage prompts; never call a model or execute answer instructions."""

    name = "fake"

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0, seed: int | None = None) -> dict:
        """Return deterministic rubric-shaped replies without network access."""
        from autoassess.advocate import ADVOCATE_SYSTEM
        from autoassess.critic import CRITIC_SYSTEM
        from autoassess.feedback import FEEDBACK_SYSTEM
        from autoassess.grader import GRADER_SYSTEM
        from autoassess.regrade import REGRADE_SYSTEM
        from autoassess.segment import SEGMENT_SYSTEM
        from autoassess.spec_builder import DRAFT_SYSTEM

        if system == GRADER_SYSTEM:
            answer = _between(user, "<student_answer>\n", "\n</student_answer>")
            rubric = _between(user, "RUBRIC:\n", "\n\nMODEL ANSWER:")
            criteria = []
            for cid, marks, description in re.findall(r"^- (\S+) \(([\d.]+) marks, [^\n]*?\): (.+)$", rubric, re.M):
                criteria.append({"criterion_id": cid, **_award(description, float(marks), answer)})
            return {"criteria": criteria}
        if system == CRITIC_SYSTEM:
            return {
                "audits": [
                    {
                        "criterion_id": r["criterion_id"],
                        "decision": "uphold",
                        "marks": r["marks_awarded"],
                        "reason": "Offline review keeps the award.",
                    }
                    for r in _rows(user, "AWARDS TO AUDIT:\n")
                ]
            }
        if system == ADVOCATE_SYSTEM:
            return {
                "proposals": [
                    {
                        "criterion_id": r["criterion_id"],
                        "decision": "keep",
                        "marks": r["marks_awarded"],
                        "evidence": None,
                        "reason": "Offline review keeps the award.",
                    }
                    for r in _rows(user, "CRITERIA BELOW FULL MARKS:\n")
                ]
            }
        if system == FEEDBACK_SYSTEM:
            # Remarks quote the rubric's own wording, so the offline demo reads like real marking.
            rows = _rows(user, "GRADING:\n")
            earned, lost, covered, missing = [], [], [], []
            for r in rows:
                marks, maximum = map(float, r["marks"].split(" of "))
                point = _short(r["criterion"])
                if marks > 0:
                    covered.append(point)
                    earned.append({"criterion_id": r["criterion_id"], "text": f"You covered: {point}"})
                if marks < maximum:
                    missing.append(point)
                    lost.append(
                        {
                            "criterion_id": r["criterion_id"],
                            "text": f"Missing: {point}",
                            "next_step": f"Include this point: {r['criterion']}",
                        }
                    )
            return {
                "earned": earned,
                "lost": lost,
                "errors": [],
                "remark": {
                    "strength": f"{covered[0][0].upper()}{covered[0][1:]}" if covered else "",
                    "fix": f"Add: {missing[0]}" if missing else "",
                    "next_step": "Plan one line per rubric point before writing."
                    if missing
                    else "Add a short example to make it even stronger.",
                },
            }
        if system == SEGMENT_SYSTEM:
            questions = _between(user, "Questions:\n", "\n\n<sheet>")
            sheet = _between(user, "<sheet>\n", "\n</sheet>")
            answers = {line.split(":", 1)[0]: [] for line in questions.splitlines()}
            current = None
            for line in sheet.splitlines():
                for qid in answers:
                    label = re.escape(qid.removeprefix("Q"))
                    if re.match(rf"^\s*(?:Q\s*|Ans\s*)?{label}(?=[\s.):\-]|$)", line, re.I):
                        current = qid
                        break
                if current is not None:
                    answers[current].append(line)
            return {"answers": {qid: "\n".join(lines) for qid, lines in answers.items()}}
        if system == DRAFT_SYSTEM:
            # A single synthetic criterion exercises drafting, without semantic document parsing.
            paper = _between(user, "=== QUESTION PAPER ===\n", "\n\n=== RUBRIC ===")
            rubric = _between(user, "=== RUBRIC ===\n", "\n\n=== MODEL ANSWERS ===")
            model = user.split("=== MODEL ANSWERS ===\n", 1)[1].rstrip("\n")
            return {
                "exam_id": user.splitlines()[0].removeprefix("exam_id: "),
                "title": "Offline scripted draft",
                "language": "en",
                "questions": [
                    {
                        "id": "Q1",
                        "text": paper,
                        "max_marks": 1,
                        "model_answer": model or None,
                        "aliases": ["1"],
                        "criteria": [{"id": "Q1.c1", "description": rubric, "marks": 1, "allow_partial": False}],
                    }
                ],
            }
        if system == REGRADE_SYSTEM:
            answer = _between(user, "<student_answer>\n", "\n</student_answer>")
            match = re.search(r"^CRITERION \S+ \(([\d.]+) marks, [^\n]*?\): (.+)$", user, re.M)
            marks, description = match.groups()
            award = _award(description, float(marks), answer)
            return {key: award[key] for key in ("marks_awarded", "evidence", "reason")} | {
                "response_to_student": "Your answer was checked using offline rubric word overlap."
            }
        raise ValueError("ScriptedLLM: unrecognised prompt")

    def complete_json_images(
        self, system: str, user: str, images: list[bytes], *, temperature: float = 0.0, seed: int | None = None
    ) -> dict:
        """Reject image grading because this scripted provider is text-only."""
        raise NotImplementedError("ScriptedLLM supports text only; image input is not supported")
