"""One small database layer for the teacher app: SQLite by default, Postgres when ``DATABASE_URL`` is set.

The store's SQL is written once, in SQLite's dialect. :class:`PostgresDatabase` translates the few
SQLite-only spellings it uses (``?`` placeholders, ``INSERT OR IGNORE/REPLACE``, ``BEGIN IMMEDIATE``,
``lastrowid``) so both backends run the same queries. The schema lives here as numbered migrations,
applied in order on startup and by ``autoassess migrate``.
"""

from __future__ import annotations

import re
import sqlite3
import weakref
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Each migration is a list of statements in SQLite's dialect; Postgres gets them translated.
# Append new migrations; never edit one that has shipped.
MIGRATIONS: list[list[str]] = [
    # 1: classes and rosters
    [
        """CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE
        )""",
        """CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY, teacher_id INTEGER NOT NULL REFERENCES teachers(id),
            name TEXT NOT NULL, subject TEXT NOT NULL, section TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            roll_no TEXT NOT NULL, name TEXT NOT NULL, UNIQUE(class_id, roll_no)
        )""",
    ],
    # 2-3: assignments, durable jobs, append-only decisions and review telemetry
    [
        """CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            title TEXT NOT NULL, spec_json TEXT NOT NULL, released INTEGER NOT NULL DEFAULT 0,
            is_demo INTEGER NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY, assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            student_id INTEGER REFERENCES students(id), original_name TEXT NOT NULL, path TEXT NOT NULL,
            grade_json TEXT, run_json TEXT, artifacts_json TEXT, UNIQUE(assignment_id,student_id)
        )""",
        """CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY, submission_id INTEGER NOT NULL UNIQUE REFERENCES submissions(id) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK(status IN ('queued','running','done','failed')),
            message TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS accepted (
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            question_id TEXT NOT NULL, teacher_id INTEGER NOT NULL REFERENCES teachers(id),
            PRIMARY KEY(submission_id,question_id)
        )""",
        """CREATE TABLE IF NOT EXISTS overrides (
            id INTEGER PRIMARY KEY, submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            question_id TEXT NOT NULL, criterion_id TEXT NOT NULL,
            old_marks REAL NOT NULL, new_marks REAL NOT NULL, reason TEXT NOT NULL,
            teacher_id INTEGER NOT NULL REFERENCES teachers(id), kind TEXT NOT NULL,
            old_json TEXT NOT NULL, result_json TEXT NOT NULL, record_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS review_events (
            id INTEGER PRIMARY KEY, submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            question_id TEXT NOT NULL, teacher_id INTEGER NOT NULL REFERENCES teachers(id),
            kind TEXT NOT NULL CHECK(kind IN ('open','accept','override')), at REAL NOT NULL
        )""",
    ],
    # 4: feedback language (older SQLite files gain it through _legacy_columns)
    ["ADD COLUMN assignments feedback_language TEXT NOT NULL DEFAULT 'English'"],
    # 5: email sign-in codes, rate-limit log and durable uploaded/marked files
    [
        """CREATE TABLE IF NOT EXISTS login_codes (
            id INTEGER PRIMARY KEY, email TEXT NOT NULL, code_hash TEXT NOT NULL,
            created_at REAL NOT NULL, expires_at REAL NOT NULL, used_at REAL,
            attempts INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX IF NOT EXISTS login_codes_email ON login_codes(email, created_at)",
        """CREATE TABLE IF NOT EXISTS login_requests (
            id INTEGER PRIMARY KEY, email TEXT NOT NULL, client TEXT NOT NULL, kind TEXT NOT NULL, at REAL NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS login_requests_at ON login_requests(at)",
        """CREATE TABLE IF NOT EXISTS blobs (
            path TEXT PRIMARY KEY, data BLOB NOT NULL, size INTEGER NOT NULL, updated_at REAL NOT NULL
        )""",
    ],
]
SCHEMA_VERSION = len(MIGRATIONS)

# Tables whose INSERTs return a generated ``id`` (used for ``lastrowid`` on Postgres).
ID_TABLES = {
    "teachers",
    "classes",
    "students",
    "assignments",
    "submissions",
    "jobs",
    "overrides",
    "review_events",
    "login_codes",
    "login_requests",
}
# Primary keys for translating SQLite's ``INSERT OR REPLACE`` into an upsert.
UPSERT_KEYS = {"accepted": ("submission_id", "question_id"), "blobs": ("path",)}


class Row(dict):
    """A result row that reads like ``sqlite3.Row``: by column name, by position, or as a dict."""

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Database:
    """Base class: run the migrations and hand out transaction-scoped connections."""

    dialect = "sqlite"
    durable_files = False  # True when uploaded and marked files must be copied into the database

    @contextmanager
    def connect(self) -> Iterator[Any]:  # pragma: no cover - interface
        """Yield a transaction-scoped connection."""
        raise NotImplementedError
        yield

    def migrate(self) -> int:
        """Apply every migration newer than the stored version; return the version now in place."""
        with self.connect() as db:
            self.begin_migration(db)
            row = db.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                db.execute("INSERT INTO schema_version VALUES(0)")
            current = row[0] if row else 0
            if current < 4:
                # Databases made before migrations were numbered recorded 1 or 3 but may lack tables;
                # every CREATE is IF NOT EXISTS, so re-running the early ones is safe.
                current = 0
            for version, statements in enumerate(MIGRATIONS, start=1):
                if version <= current:
                    continue
                for statement in statements:
                    self.apply(db, statement)
                db.execute("UPDATE schema_version SET version=?", (version,))
            self.end_migration(db)
            return max(current, SCHEMA_VERSION)

    def begin_migration(self, db: Any) -> None:
        """Create the version table; subclasses may also take a lock here."""
        db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")

    def end_migration(self, db: Any) -> None:
        """Hook for dialect-specific indexes, run in the migration's transaction."""

    def apply(self, db: Any, statement: str) -> None:
        """Run one migration statement, with ``ADD COLUMN table column ...`` made idempotent."""
        if statement.startswith("ADD COLUMN "):
            table, column, definition = statement.removeprefix("ADD COLUMN ").split(" ", 2)
            if column not in self.columns(db, table):
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            return
        db.execute(statement)

    def columns(self, db: Any, table: str) -> set[str]:
        """Column names of a table."""
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


class SQLiteDatabase(Database):
    """The default local database: one file, one connection per operation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a transaction-scoped connection with foreign keys enabled."""
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()


_INSERT = re.compile(r"^\s*INSERT\s+(OR\s+(IGNORE|REPLACE)\s+)?INTO\s+(\w+)", re.I)


def translate(sql: str) -> tuple[str, str | None]:
    """Rewrite one SQLite-dialect statement for Postgres; also return the table an INSERT targets."""
    table = None
    match = _INSERT.match(sql)
    if match:
        mode, table = (match.group(2) or "").upper(), match.group(3)
        sql = _INSERT.sub(f"INSERT INTO {table}", sql, count=1)
        if mode == "IGNORE":
            sql += " ON CONFLICT DO NOTHING"
        elif mode == "REPLACE":
            keys = UPSERT_KEYS[table]
            cols = re.search(rf"INTO\s+{table}\s*\(([^)]*)\)", sql)
            names = [c.strip() for c in cols.group(1).split(",")] if cols else None
            if names is None:  # INSERT INTO accepted VALUES(...) uses the table's column order
                names = {"accepted": ["submission_id", "question_id", "teacher_id"]}[table]
            updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in names if c not in keys)
            sql += f" ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {updates}"
    sql = sql.replace("%", "%%").replace("?", "%s")
    return sql, table


def translate_ddl(statement: str) -> str:
    """Rewrite a SQLite CREATE statement for Postgres types."""
    statement = re.sub(r"\bINTEGER PRIMARY KEY\b", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", statement)
    statement = re.sub(r"\bINTEGER\b", "BIGINT", statement)
    statement = re.sub(r"\bREAL\b", "DOUBLE PRECISION", statement)
    statement = re.sub(r"\bBLOB\b", "BYTEA", statement)
    statement = statement.replace(" COLLATE NOCASE", "")
    return statement.replace("DEFAULT CURRENT_TIMESTAMP", "DEFAULT (CURRENT_TIMESTAMP::text)")


class _Result:
    """The slice of ``sqlite3.Cursor`` the store uses: fetchone, fetchall, iteration, rowcount, lastrowid."""

    def __init__(self, cursor: Any, lastrowid: int | None = None) -> None:
        self.cursor, self.lastrowid = cursor, lastrowid
        self.rowcount = cursor.rowcount

    def fetchone(self) -> Row | None:
        """The next row, or None."""
        return self.cursor.fetchone() if self.cursor.description else None

    def fetchall(self) -> list[Row]:
        """Every remaining row."""
        return self.cursor.fetchall() if self.cursor.description else []

    def __iter__(self) -> Iterator[Row]:
        return iter(self.fetchall())


class _PgConnection:
    """Wrap a psycopg connection so the store's SQLite-dialect SQL runs unchanged."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _Result:
        """Run one SQLite-dialect statement on Postgres."""
        stripped = sql.strip().upper()
        if stripped == "BEGIN IMMEDIATE":
            # One writer at a time for the check-then-append in add_override, as SQLite gives.
            sql = "SELECT pg_advisory_xact_lock(7016)"
        elif stripped.startswith("PRAGMA"):
            raise ValueError("PRAGMA is SQLite-only")
        sql, table = translate(sql)
        returning = table in ID_TABLES and "RETURNING" not in sql.upper()
        if returning:
            sql += " RETURNING id"
        cursor = self.conn.cursor()
        cursor.execute(sql, tuple(params))
        lastrowid = None
        if returning:
            row = cursor.fetchone()
            lastrowid = row["id"] if row else None
        return _Result(cursor, lastrowid)

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        """Run one statement for many parameter rows."""
        sql, _ = translate(sql)
        with self.conn.cursor() as cursor:
            cursor.executemany(sql, [tuple(r) for r in rows])


class PostgresDatabase(Database):
    """Postgres through a small connection pool; durable files are kept in the ``blobs`` table."""

    dialect = "postgres"
    durable_files = True

    def __init__(self, url: str, *, min_size: int = 1, max_size: int = 5) -> None:
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as err:  # pragma: no cover - depends on install
            raise RuntimeError('DATABASE_URL is set; install Postgres support with pip install ".[postgres]"') from err

        def row_factory(cursor: Any) -> Any:
            """Make psycopg return Row objects."""
            make = dict_row(cursor)
            return lambda values: Row(make(values))

        self.url = url
        OPEN_POOLS.add(self)
        self.pool = ConnectionPool(
            url,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": row_factory, "autocommit": False},
            # Neon and Supabase close idle connections; check each one before handing it out.
            check=ConnectionPool.check_connection,
            open=True,
        )

    @contextmanager
    def connect(self) -> Iterator[_PgConnection]:
        """Yield a connection inside one transaction: committed on success, rolled back on error."""
        with self.pool.connection() as conn:
            yield _PgConnection(conn)

    def apply(self, db: Any, statement: str) -> None:
        """Run one migration statement translated to Postgres types."""
        if statement.startswith("ADD COLUMN "):
            table, column, definition = statement.removeprefix("ADD COLUMN ").split(" ", 2)
            db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {translate_ddl(definition)}")
            return
        db.execute(translate_ddl(statement))

    def begin_migration(self, db: Any) -> None:
        """Serialise migrations across starting processes, then create the version table."""
        db.execute("SELECT pg_advisory_xact_lock(7017)")
        db.execute("CREATE TABLE IF NOT EXISTS schema_version (version BIGINT NOT NULL)")

    def end_migration(self, db: Any) -> None:
        """Add the case-insensitive unique email that SQLite gets from COLLATE NOCASE."""
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS teachers_email_lower ON teachers (lower(email))")

    def reset_sequences(self, tables: Sequence[str]) -> None:
        """Move each identity sequence past the largest copied id (after a bulk copy with explicit ids)."""
        with self.connect() as db:
            for table in tables:
                db.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
                )

    def close(self) -> None:
        """Close the pool's connections."""
        self.pool.close()
        OPEN_POOLS.discard(self)


# Every open Postgres pool, so tests (and shutdown) can close them all.
OPEN_POOLS: weakref.WeakSet[PostgresDatabase] = weakref.WeakSet()


def close_all() -> None:
    """Close every open Postgres pool."""
    for database in list(OPEN_POOLS):
        database.close()


def open_database(root: Path, url: str | None) -> Database:
    """Postgres when a ``postgres://`` URL is given, otherwise the SQLite file in ``root``."""
    if url and url.startswith(("postgres://", "postgresql://")):
        return PostgresDatabase(url)
    if url:
        raise ValueError("DATABASE_URL must start with postgres:// or postgresql://")
    return SQLiteDatabase(root / "redink.db")
