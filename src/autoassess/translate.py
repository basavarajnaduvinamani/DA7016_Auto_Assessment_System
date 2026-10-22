"""Return feedback in the student's language (Bodhan Indic-Translate, week 5).

Only the student-facing text is translated: feedback items, the rendered
feedback and the sheet summary. Evidence quotes stay as the student wrote
them, and the English originals are kept so a teacher can check the grading.
"""

from __future__ import annotations

from autoassess.providers.base import Translator
from autoassess.schemas import SheetGrade


def translate_feedback(grade: SheetGrade, translator: Translator, language: str) -> SheetGrade:
    questions = []
    for q in grade.questions:
        items = [
            i.model_copy(
                update={
                    "text": translator.translate(i.text, language),
                    "next_step": translator.translate(i.next_step, language) if i.next_step else None,
                }
            )
            for i in q.feedback_items
        ]
        remark = q.remark
        if remark is not None:
            remark = remark.model_copy(
                update={k: translator.translate(v, language) if v else "" for k, v in remark.model_dump().items()}
            )
        questions.append(
            q.model_copy(
                update={
                    "remark": remark,
                    "feedback_items": items,
                    "feedback": translator.translate(q.feedback, language) if q.feedback else "",
                    "feedback_en": q.feedback,
                }
            )
        )
    return grade.model_copy(
        update={
            "questions": questions,
            "summary_feedback": translator.translate(grade.summary_feedback, language) if grade.summary_feedback else "",
            "summary_feedback_en": grade.summary_feedback,
            "feedback_language": language,
        }
    )
