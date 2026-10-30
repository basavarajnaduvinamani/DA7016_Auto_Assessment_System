"""Assignments, durable jobs and append-only teacher/AI decisions."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any

from autoassess.regrade import RegradeRecord
from autoassess.schemas import CriterionResult, ExamSpec, SheetGrade, Verdict


def apply_overrides(grade: SheetGrade, changes: list[dict], accepted: Iterable[str] = ()) -> SheetGrade:
    """Keep the original AI output immutable; derive the current teacher view."""
    current = grade.model_copy(deep=True)
    for change in changes:
        question = next(q for q in current.questions if q.question_id == change["question_id"])
        result = CriterionResult.model_validate_json(change["result_json"])
        question.criteria = [result if c.criterion_id == result.criterion_id else c for c in question.criteria]
        question.marks_awarded = round(sum(c.marks_awarded for c in question.criteria), 2)
        if change.get("kind") == "ai":
            question.needs_review = True
    for question in current.questions:
        if question.question_id in accepted:
            question.needs_review = False
    return current


class AssignmentStore:
    """SQLite operations for assignments, jobs and append-only review decisions."""

    def init_assignments(self) -> None:
        """Create assignment tables and record the supported schema version."""
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS assignments (
                    id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                    title TEXT NOT NULL, spec_json TEXT NOT NULL, released INTEGER NOT NULL DEFAULT 0,
                    is_demo INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY, assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
                    student_id INTEGER REFERENCES students(id), original_name TEXT NOT NULL, path TEXT NOT NULL,
                    grade_json TEXT, run_json TEXT, artifacts_json TEXT, UNIQUE(assignment_id,student_id)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY, submission_id INTEGER NOT NULL UNIQUE REFERENCES submissions(id) ON DELETE CASCADE,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','done','failed')),
                    message TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS accepted (
                    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL, teacher_id INTEGER NOT NULL REFERENCES teachers(id),
                    PRIMARY KEY(submission_id,question_id)
                );
                CREATE TABLE IF NOT EXISTS overrides (
                    id INTEGER PRIMARY KEY, submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL, criterion_id TEXT NOT NULL,
                    old_marks REAL NOT NULL, new_marks REAL NOT NULL, reason TEXT NOT NULL,
                    teacher_id INTEGER NOT NULL REFERENCES teachers(id), kind TEXT NOT NULL,
                    old_json TEXT NOT NULL, result_json TEXT NOT NULL, record_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                UPDATE schema_version SET version=2;
            """)

    def create_assignment(self, class_id: int, title: str, spec: ExamSpec, *, is_demo: bool = False) -> int:
        """Persist a validated rubric and non-empty assignment title."""
        title = title.strip()
        if not title or len(title) > 160:
            raise ValueError("Enter an assignment title (up to 160 characters).")
        with self.connect() as db:
            return db.execute(
                "INSERT INTO assignments(class_id,title,spec_json,is_demo) VALUES(?,?,?,?)",
                (class_id, title, spec.model_dump_json(), int(is_demo)),
            ).lastrowid

    def assignments(self, class_id: int) -> list[dict]:
        """List a class's assignments with the newest first."""
        with self.connect() as db:
            return [
                dict(r) for r in db.execute("SELECT * FROM assignments WHERE class_id=? ORDER BY id DESC", (class_id,))
            ]

    def assignment(self, assignment_id: int, teacher_id: int | None = None) -> dict[str, Any] | None:
        """Find an assignment, optionally restricting it to a teacher owner."""
        with self.connect() as db:
            sql = "SELECT a.* FROM assignments a JOIN classes c ON c.id=a.class_id WHERE a.id=?"
            params = [assignment_id]
            if teacher_id is not None:
                sql += " AND c.teacher_id=?"
                params.append(teacher_id)
            row = db.execute(sql, params).fetchone()
            return dict(row) if row else None

    def submissions(self, assignment_id: int) -> list[dict]:
        """List uploaded sheets with student matches and durable job status."""
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    """
                SELECT s.*, st.roll_no, st.name, j.id AS job_id, j.status, j.message, j.attempts
                FROM submissions s LEFT JOIN students st ON st.id=s.student_id
                LEFT JOIN jobs j ON j.submission_id=s.id WHERE s.assignment_id=? ORDER BY s.id
            """,
                    (assignment_id,),
                )
            ]

    def submission(self, submission_id: int) -> dict[str, Any] | None:
        """Find one upload with its matched student's display details."""
        with self.connect() as db:
            row = db.execute(
                "SELECT s.*, st.roll_no, st.name FROM submissions s LEFT JOIN students st ON st.id=s.student_id WHERE s.id=?",
                (submission_id,),
            ).fetchone()
            return dict(row) if row else None

    def add_submissions(self, assignment_id: int, files: list[tuple]) -> list[int]:
        """Atomically register staged files on an unreleased assignment."""
        with self.connect() as db:
            if db.execute("SELECT released FROM assignments WHERE id=?", (assignment_id,)).fetchone()[0]:
                raise ValueError("This assignment is released. Create another assignment for new uploads.")
            ids = []
            for student_id, name, path in files:
                ids.append(
                    db.execute(
                        "INSERT INTO submissions(assignment_id,student_id,original_name,path) VALUES(?,?,?,?)",
                        (assignment_id, student_id, name, str(path)),
                    ).lastrowid
                )
            return ids

    def match_submission(self, submission_id: int, student_id: int) -> None:
        """Associate an unlocked upload with an unused student in the same class."""
        with self.connect() as db:
            row = db.execute(
                """SELECT s.*, a.class_id,a.released FROM submissions s
                                JOIN assignments a ON a.id=s.assignment_id WHERE s.id=?""",
                (submission_id,),
            ).fetchone()
            student = db.execute("SELECT class_id FROM students WHERE id=?", (student_id,)).fetchone()
            if not row or not student or row["class_id"] != student["class_id"]:
                raise ValueError("Choose a student in this class.")
            if (
                row["released"]
                or row["grade_json"]
                or db.execute("SELECT 1 FROM jobs WHERE submission_id=?", (submission_id,)).fetchone()
            ):
                raise ValueError("Only ungraded sheets can be matched. This sheet is already locked for marking.")
            db.execute("UPDATE submissions SET student_id=? WHERE id=?", (student_id, submission_id))

    def queue_assignment(self, assignment_id: int) -> None:
        """Queue matched ungraded sheets without creating duplicate jobs."""
        with self.connect() as db:
            if db.execute("SELECT released FROM assignments WHERE id=?", (assignment_id,)).fetchone()[0]:
                raise ValueError("This assignment has already been released.")
            db.execute(
                """INSERT OR IGNORE INTO jobs(submission_id,status)
                SELECT id,'queued' FROM submissions WHERE assignment_id=? AND student_id IS NOT NULL AND grade_json IS NULL""",
                (assignment_id,),
            )

    def queued_jobs(self) -> list[int]:
        """List pending job IDs in scheduling order."""
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY id")]

    def recover_jobs(self) -> None:
        """Return interrupted running jobs to the queue for restart recovery."""
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='queued',message='Resuming after restart.' WHERE status='running'")

    def claim_job(self, job_id: int) -> dict[str, Any] | None:
        """Atomically claim a queued job and increment its attempt count."""
        with self.connect() as db:
            changed = db.execute(
                "UPDATE jobs SET status='running',attempts=attempts+1,message='' WHERE id=? AND status='queued'",
                (job_id,),
            ).rowcount
            if not changed:
                return None
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def complete_job(self, job_id: int, grade: SheetGrade, run_json: str, artifacts: dict) -> None:
        """Persist a running job's immutable grade and generated artifacts."""
        with self.connect() as db:
            row = db.execute("SELECT submission_id FROM jobs WHERE id=? AND status='running'", (job_id,)).fetchone()
            if row is None:
                raise ValueError("Job is not running.")
            db.execute(
                "UPDATE submissions SET grade_json=?,run_json=?,artifacts_json=? WHERE id=?",
                (grade.model_dump_json(), run_json, json.dumps(artifacts), row["submission_id"]),
            )
            db.execute("UPDATE jobs SET status='done',message='Marked and ready to review.' WHERE id=?", (job_id,))

    def fail_job(self, job_id: int, message: str) -> None:
        """Record a readable failure notice for a running job."""
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='failed',message=? WHERE id=? AND status='running'", (message, job_id))

    def retry_job(self, job_id: int) -> None:
        """Return a failed job to the queue, rejecting other state transitions."""
        with self.connect() as db:
            if not db.execute(
                "UPDATE jobs SET status='queued',message='' WHERE id=? AND status='failed'", (job_id,)
            ).rowcount:
                raise ValueError("Only failed sheets can be retried.")

    def changes(self, submission_id: int) -> list[dict]:
        """List the append-only criterion decision history for a sheet."""
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute("SELECT * FROM overrides WHERE submission_id=? ORDER BY id", (submission_id,))
            ]

    def accepted_questions(self, submission_id: int) -> set[str]:
        """Return question IDs explicitly accepted by a teacher."""
        with self.connect() as db:
            return {
                r[0] for r in db.execute("SELECT question_id FROM accepted WHERE submission_id=?", (submission_id,))
            }

    def effective_grade(self, submission: dict) -> SheetGrade | None:
        """Derive current marks from the original grade and recorded overrides."""
        if not submission["grade_json"]:
            return None
        return apply_overrides(
            SheetGrade.model_validate_json(submission["grade_json"]),
            self.changes(submission["id"]),
            self.accepted_questions(submission["id"]),
        )

    def accept_question(self, submission_id: int, question_id: str, teacher_id: int) -> None:
        """Record teacher acceptance of an existing marked answer."""
        submission = self.submission(submission_id)
        grade = self.effective_grade(submission)
        if not grade or question_id not in {q.question_id for q in grade.questions}:
            raise ValueError("Mark this sheet before accepting an answer.")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO accepted VALUES(?,?,?)", (submission_id, question_id, teacher_id))

    def add_override(
        self,
        submission_id: int,
        question_id: str,
        criterion_id: str,
        marks: float,
        reason: str,
        teacher_id: int,
        *,
        expected_version: int,
        ai_result: CriterionResult | None = None,
        record: RegradeRecord | None = None,
    ) -> None:
        """Append a bounded criterion decision after checking the sheet version.

        Args:
            submission_id: Stored sheet whose original AI grade remains unchanged.
            expected_version: Last override ID seen by the caller; rejects stale edits.
            ai_result: Optional evidence-checked regrade result instead of a teacher mark.
            record: Optional complete AI challenge record to retain in the audit trail.

        Raises:
            ValueError: The reason, version or proposed mark violates the rubric contract.
        """
        reason = reason.strip()
        if not reason or len(reason) > 2000:
            raise ValueError("Give a reason for the change (up to 2000 characters).")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changes = [
                dict(r)
                for r in db.execute("SELECT * FROM overrides WHERE submission_id=? ORDER BY id", (submission_id,))
            ]
            if expected_version != (changes[-1]["id"] if changes else 0):
                raise ValueError("This sheet changed in another tab. Reload before saving your decision.")
            row = db.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
            if row is None or not row["grade_json"]:
                raise ValueError("Mark this sheet before changing an award.")
            assignment = db.execute("SELECT * FROM assignments WHERE id=?", (row["assignment_id"],)).fetchone()
            spec = ExamSpec.model_validate_json(assignment["spec_json"])
            question = spec.question(question_id)
            criterion = next((c for c in question.criteria if c.id == criterion_id), None)
            if criterion is None or not math.isfinite(marks) or not 0 <= marks <= criterion.marks:
                raise ValueError("Use a mark within this criterion’s allowed range.")
            if not criterion.allow_partial and marks not in (0, criterion.marks):
                raise ValueError("This criterion is all-or-nothing; choose zero or full marks.")
            current = apply_overrides(SheetGrade.model_validate_json(row["grade_json"]), changes)
            qg = next(q for q in current.questions if q.question_id == question_id)
            old = next(c for c in qg.criteria if c.criterion_id == criterion_id)
            result = ai_result or old.model_copy(
                update={
                    "marks_awarded": marks,
                    "reason": f"Teacher override: {reason}",
                    "verdict": Verdict.MET
                    if marks == criterion.marks
                    else Verdict.PARTIAL
                    if marks
                    else Verdict.NOT_MET,
                    "tags": [*old.tags, "teacher_override"],
                }
            )
            db.execute(
                """INSERT INTO overrides(submission_id,question_id,criterion_id,old_marks,new_marks,reason,
                teacher_id,kind,old_json,result_json,record_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    submission_id,
                    question_id,
                    criterion_id,
                    old.marks_awarded,
                    result.marks_awarded,
                    reason,
                    teacher_id,
                    "ai" if ai_result else "teacher",
                    old.model_dump_json(),
                    result.model_dump_json(),
                    record.model_dump_json() if record else None,
                ),
            )
            if ai_result:
                db.execute("DELETE FROM accepted WHERE submission_id=? AND question_id=?", (submission_id, question_id))
            else:
                db.execute("INSERT OR REPLACE INTO accepted VALUES(?,?,?)", (submission_id, question_id, teacher_id))
            db.execute("UPDATE assignments SET released=0 WHERE id=?", (row["assignment_id"],))

    def review_rows(self, assignment_id: int) -> list[dict]:
        """Order marked answers with unresolved review flags before other answers."""
        rows = []
        for submission in self.submissions(assignment_id):
            grade = self.effective_grade(submission)
            if grade is None:
                continue
            accepted = self.accepted_questions(submission["id"])
            for q in grade.questions:
                flagged = q.needs_review or any(
                    f.startswith(
                        (
                            "low_ocr_confidence",
                            "possible_prompt_injection",
                            "possible_keyword_stuffing",
                            "inconsistent_with:",
                        )
                    )
                    for f in q.flags
                )
                rows.append(
                    {
                        "submission": submission,
                        "question": q,
                        "accepted": q.question_id in accepted,
                        "needs_review": flagged and q.question_id not in accepted,
                    }
                )
        return sorted(
            rows,
            key=lambda r: (
                not r["needs_review"],
                r["accepted"],
                r["submission"]["roll_no"] or "",
                r["question"].question_id,
            ),
        )

    def assignment_summary(self, assignment_id: int) -> dict:
        """Count uploaded, graded, accepted and pending work and its average mark."""
        submissions = self.submissions(assignment_id)
        grades = [g for s in submissions if (g := self.effective_grade(s)) is not None]
        rows = self.review_rows(assignment_id)
        return {
            "uploaded": len(submissions),
            "graded": len(grades),
            "needs_review": sum(r["needs_review"] for r in rows),
            "accepted": sum(r["accepted"] for r in rows),
            "answers": len(rows),
            "average": round(sum(g.total for g in grades) / len(grades), 2) if grades else None,
            "pending": sum(s["grade_json"] is None for s in submissions),
            "active": sum(s["status"] in ("queued", "running") for s in submissions),
        }

    def release_assignment(self, assignment_id: int, *, confirm: bool = False) -> None:
        """Release fully graded sheets after resolving or confirming outstanding flags."""
        summary = self.assignment_summary(assignment_id)
        if not summary["uploaded"] or summary["pending"]:
            raise ValueError("Match and finish grading all uploaded sheets before release.")
        if summary["needs_review"] and not confirm:
            raise ValueError("Review flagged answers first, or explicitly confirm release anyway.")
        with self.connect() as db:
            db.execute("UPDATE assignments SET released=1 WHERE id=?", (assignment_id,))
