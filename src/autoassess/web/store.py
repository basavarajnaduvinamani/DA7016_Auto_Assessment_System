"""Teacher-app persistence (SQLite locally, Postgres with DATABASE_URL); each operation owns its connection."""

from __future__ import annotations

import csv
import io
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from autoassess.web.db import open_database
from autoassess.web.files import FileMirror, open_blobs
from autoassess.web.repository import AssignmentStore


def normal_email(email: str) -> str:
    """Trim and lowercase an email so lookups and rate limits treat spellings alike."""
    return (email or "").strip().lower()


class Store(AssignmentStore):
    """Manage the database, class ownership, validated rosters and teacher accounts."""

    def __init__(self, data_dir: str | Path, database_url: str | None = None) -> None:
        """Open the database and files folder, applying any pending schema migrations.

        Args:
            data_dir: Local folder for the SQLite file and the working copy of uploaded/marked files.
            database_url: A ``postgres://`` URL; defaults to ``DATABASE_URL``. Empty means SQLite.
        """
        self.root = Path(data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "files").mkdir(exist_ok=True)
        url = (os.getenv("DATABASE_URL", "") if database_url is None else database_url).strip()
        self.database = open_database(self.root, url or None)
        self.path = getattr(self.database, "path", None)
        self.database.migrate()
        self.files = FileMirror(self.root / "files", open_blobs(self.connect, self.database.durable_files))

    @contextmanager
    def connect(self) -> Iterator[Any]:
        """Yield a transaction-scoped connection (SQLite with foreign keys on, or Postgres)."""
        with self.database.connect() as db:
            yield db

    def teacher(self, teacher_id: int) -> dict[str, Any] | None:
        """Find a teacher by persistent ID."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM teachers WHERE id=?", (teacher_id,)).fetchone()
            return dict(row) if row else None

    def teacher_by_email(self, email: str) -> dict[str, Any] | None:
        """Find a seeded teacher using a case-insensitive email match."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM teachers WHERE lower(email)=?", (normal_email(email),)).fetchone()
            return dict(row) if row else None

    def create_teacher(self, email: str, name: str = "") -> dict[str, Any]:
        """Create a teacher for a verified email (or return the existing one)."""
        email = normal_email(email)
        existing = self.teacher_by_email(email)
        if existing:
            return existing
        name = name.strip()[:120] or email.split("@", 1)[0]
        with self.connect() as db:
            db.execute("INSERT INTO teachers(name,email) VALUES(?,?)", (name, email))
        return self.teacher_by_email(email)

    def delete_teacher_data(self, teacher_id: int) -> dict[str, int]:
        """Delete a teacher and everything they own: classes, rosters, sheets, marks, logs and files.

        Returns:
            Counts of deleted classes, assignments and sheets, for the confirmation message.
        """
        with self.connect() as db:
            teacher = db.execute("SELECT email FROM teachers WHERE id=?", (teacher_id,)).fetchone()
            if teacher is None:
                return {"classes": 0, "assignments": 0, "sheets": 0}
            class_ids = [r[0] for r in db.execute("SELECT id FROM classes WHERE teacher_id=?", (teacher_id,))]
            assignment_ids = [
                r[0]
                for r in db.execute(
                    "SELECT a.id FROM assignments a JOIN classes c ON c.id=a.class_id WHERE c.teacher_id=?",
                    (teacher_id,),
                )
            ]
            sheets = 0
            for assignment_id in assignment_ids:
                ids = [r[0] for r in db.execute("SELECT id FROM submissions WHERE assignment_id=?", (assignment_id,))]
                sheets += len(ids)
                for sid in ids:
                    for table in ("review_events", "overrides", "accepted", "jobs"):
                        db.execute(f"DELETE FROM {table} WHERE submission_id=?", (sid,))
                db.execute("DELETE FROM submissions WHERE assignment_id=?", (assignment_id,))
                db.execute("DELETE FROM assignments WHERE id=?", (assignment_id,))
            # Decisions this teacher made on anyone else's sheets (none in normal use) go too.
            for table in ("review_events", "overrides", "accepted"):
                db.execute(f"DELETE FROM {table} WHERE teacher_id=?", (teacher_id,))
            for class_id in class_ids:
                db.execute("DELETE FROM students WHERE class_id=?", (class_id,))
                db.execute("DELETE FROM classes WHERE id=?", (class_id,))
            email = normal_email(teacher[0])
            db.execute("DELETE FROM login_codes WHERE email=?", (email,))
            db.execute("DELETE FROM login_requests WHERE email=?", (email,))
            db.execute("DELETE FROM teachers WHERE id=?", (teacher_id,))
        for assignment_id in assignment_ids:
            self.files.forget(assignment_id)
        return {"classes": len(class_ids), "assignments": len(assignment_ids), "sheets": sheets}

    def classes(self, teacher_id: int) -> list[dict]:
        """List owned classes with live roster, assignment and review counts."""
        with self.connect() as db:
            classes = [
                dict(r)
                for r in db.execute(
                    """
                SELECT c.*, COUNT(s.id) AS student_count FROM classes c
                LEFT JOIN students s ON s.class_id=c.id WHERE c.teacher_id=? GROUP BY c.id ORDER BY c.id
            """,
                    (teacher_id,),
                )
            ]
        for classroom in classes:
            assignments = self.assignments(classroom["id"])
            classroom["assignment_count"] = len(assignments)
            classroom["review_count"] = sum(self.assignment_summary(a["id"])["needs_review"] for a in assignments)
        return classes

    def classroom(self, class_id: int, teacher_id: int) -> dict[str, Any] | None:
        """Find a class owned by a specified teacher."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM classes WHERE id=? AND teacher_id=?", (class_id, teacher_id)).fetchone()
            return dict(row) if row else None

    def create_class(self, teacher_id: int, name: str, subject: str, section: str = "") -> int:
        """Validate and save a class under its teacher owner."""
        name, subject, section = name.strip(), subject.strip(), section.strip()
        if not name or not subject or max(len(name), len(subject)) > 120 or len(section) > 60:
            raise ValueError(
                "Enter a class name and subject (up to 120 characters) and an optional section (up to 60)."
            )
        with self.connect() as db:
            return db.execute(
                "INSERT INTO classes(teacher_id,name,subject,section) VALUES(?,?,?,?)",
                (teacher_id, name, subject, section),
            ).lastrowid

    def students(self, class_id: int) -> list[dict]:
        """List students in roll-number order for a class."""
        with self.connect() as db:
            return [
                dict(r) for r in db.execute("SELECT * FROM students WHERE class_id=? ORDER BY roll_no", (class_id,))
            ]

    @staticmethod
    def student_fields(roll_no: str, name: str) -> tuple[str, str]:
        """Validate and normalise a student's roll number and display name."""
        roll_no, name = roll_no.strip(), name.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", roll_no) or not name or len(name) > 120:
            raise ValueError(
                "Use a roll number with letters, numbers, dots, dashes or underscores, and a name (up to 120 characters)."
            )
        return roll_no, name

    def add_student(self, class_id: int, roll_no: str, name: str) -> None:
        """Insert a student or update the name for an existing class roll number."""
        roll_no, name = self.student_fields(roll_no, name)
        with self.connect() as db:
            db.execute(
                "INSERT INTO students(class_id,roll_no,name) VALUES(?,?,?) ON CONFLICT(class_id,roll_no) DO UPDATE SET name=excluded.name",
                (class_id, roll_no, name),
            )

    def import_roster(self, class_id: int, content: bytes) -> int:
        """Validate a bounded CSV completely before atomically updating the roster."""
        if len(content) > 1024 * 1024:
            raise ValueError("Roster CSV must be under 1 MB.")
        try:
            reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), strict=True)
            if reader.fieldnames != ["roll_no", "name"]:
                raise ValueError("CSV must have exactly the header roll_no,name.")
            rows = []
            for row in reader:
                if None in row or row.get("name") is None:
                    raise ValueError("Each CSV row must contain a roll number and a name.")
                rows.append(self.student_fields(row["roll_no"], row["name"]))
            if not rows:
                raise ValueError("Include at least one student in the roster CSV.")
            if len({r for r, _ in rows}) != len(rows):
                raise ValueError("Duplicate roll numbers were found. Each student needs a distinct roll number.")
        except (UnicodeDecodeError, csv.Error) as err:
            raise ValueError("Upload a valid UTF-8 CSV with the header roll_no,name.") from err
        with self.connect() as db:
            db.executemany(
                "INSERT INTO students(class_id,roll_no,name) VALUES(?,?,?) ON CONFLICT(class_id,roll_no) DO UPDATE SET name=excluded.name",
                [(class_id, *row) for row in rows],
            )
        return len(rows)
