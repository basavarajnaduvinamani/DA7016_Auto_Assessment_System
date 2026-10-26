"""SQLite persistence for the teacher app; each operation owns its connection."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "files").mkdir(exist_ok=True)
        self.path = self.root / "redink.db"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
                CREATE TABLE IF NOT EXISTS teachers (
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE
                );
                CREATE TABLE IF NOT EXISTS classes (
                    id INTEGER PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES teachers(id),
                    name TEXT NOT NULL, subject TEXT NOT NULL, section TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
                    roll_no TEXT NOT NULL, name TEXT NOT NULL, UNIQUE(class_id, roll_no)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def teacher(self, teacher_id: int):
        with self.connect() as db:
            row = db.execute("SELECT * FROM teachers WHERE id=?", (teacher_id,)).fetchone()
            return dict(row) if row else None

    def teacher_by_email(self, email: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM teachers WHERE email=?", (email.strip(),)).fetchone()
            return dict(row) if row else None

    def classes(self, teacher_id: int) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("""
                SELECT c.*, COUNT(s.id) AS student_count, 0 AS assignment_count, 0 AS review_count
                FROM classes c LEFT JOIN students s ON s.class_id=c.id
                WHERE c.teacher_id=? GROUP BY c.id ORDER BY c.id
            """, (teacher_id,))]

    def classroom(self, class_id: int, teacher_id: int):
        with self.connect() as db:
            row = db.execute("SELECT * FROM classes WHERE id=? AND teacher_id=?", (class_id, teacher_id)).fetchone()
            return dict(row) if row else None

    def create_class(self, teacher_id: int, name: str, subject: str, section: str = "") -> int:
        name, subject, section = name.strip(), subject.strip(), section.strip()
        if not name or not subject or max(len(name), len(subject)) > 120 or len(section) > 60:
            raise ValueError("Enter a class name and subject (up to 120 characters) and an optional section (up to 60).")
        with self.connect() as db:
            return db.execute("INSERT INTO classes(teacher_id,name,subject,section) VALUES(?,?,?,?)",
                              (teacher_id, name, subject, section)).lastrowid

    def students(self, class_id: int) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM students WHERE class_id=? ORDER BY roll_no", (class_id,))]

    @staticmethod
    def student_fields(roll_no: str, name: str) -> tuple[str, str]:
        roll_no, name = roll_no.strip(), name.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", roll_no) or not name or len(name) > 120:
            raise ValueError("Use a roll number with letters, numbers, dots, dashes or underscores, and a name (up to 120 characters).")
        return roll_no, name

    def add_student(self, class_id: int, roll_no: str, name: str):
        roll_no, name = self.student_fields(roll_no, name)
        with self.connect() as db:
            db.execute("INSERT INTO students(class_id,roll_no,name) VALUES(?,?,?) ON CONFLICT(class_id,roll_no) DO UPDATE SET name=excluded.name",
                       (class_id, roll_no, name))

    def import_roster(self, class_id: int, content: bytes) -> int:
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
            if not rows or len({r for r, _ in rows}) != len(rows):
                raise ValueError("Include students with distinct roll numbers in the CSV.")
        except (UnicodeDecodeError, csv.Error) as err:
            raise ValueError("Upload a valid UTF-8 CSV with the header roll_no,name.") from err
        with self.connect() as db:
            db.executemany("INSERT INTO students(class_id,roll_no,name) VALUES(?,?,?) ON CONFLICT(class_id,roll_no) DO UPDATE SET name=excluded.name",
                           [(class_id, *row) for row in rows])
        return len(rows)
