"""``autoassess migrate``: bring a database up to the current schema, optionally copying a SQLite workspace in.

Typical uses:

    autoassess migrate                              # create/upgrade the schema at DATABASE_URL (or the local SQLite)
    autoassess migrate --from-sqlite .redink        # copy a local workspace (database and files) into DATABASE_URL

The copy keeps every id, rewrites stored file paths from the old data folder to the new one
(``--data-dir`` or ``AUTOASSESS_DATA_DIR``), uploads the files to the durable file store, and
refuses to run into a database that already has teachers unless ``--force`` is given.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from autoassess.web.db import SQLiteDatabase
from autoassess.web.store import Store

# Copy order respects foreign keys. Sign-in codes and rate-limit rows are short-lived and not copied.
TABLES = [
    "teachers",
    "classes",
    "students",
    "assignments",
    "submissions",
    "jobs",
    "accepted",
    "overrides",
    "review_events",
]
# Text columns that may hold absolute file paths under the old data folder.
PATH_COLUMNS = {"submissions": ("path", "run_json", "artifacts_json")}


def migrate(
    database_url: str | None = None,
    data_dir: str | Path | None = None,
    from_sqlite: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run migrations and, with ``from_sqlite``, copy that workspace in. Returns a summary for printing."""
    data_dir = Path(data_dir or os.getenv("AUTOASSESS_DATA_DIR", ".redink"))
    target = Store(data_dir, database_url=database_url)
    summary: dict[str, Any] = {"backend": target.database.dialect, "files_backend": target.files.blobs.name}
    if not from_sqlite:
        return summary
    source_dir = Path(from_sqlite).resolve()
    source_db = source_dir / "redink.db"
    if not source_db.is_file():
        raise SystemExit(f"No redink.db in {source_dir}")
    if source_dir == target.root and target.database.dialect == "sqlite":
        raise SystemExit("The source and target are the same SQLite workspace.")
    source = SQLiteDatabase(source_db)
    source.migrate()
    with target.connect() as db:
        if db.execute("SELECT 1 FROM teachers LIMIT 1").fetchone() and not force:
            raise SystemExit("The target database already has teachers. Pass --force to copy anyway.")
    old_files, new_files = str(source_dir / "files"), str(target.root / "files")
    copied: dict[str, int] = {}
    with source.connect() as src, target.connect() as dst:
        for table in TABLES:
            rows = [dict(r) for r in src.execute(f"SELECT * FROM {table}")]
            if not rows:
                copied[table] = 0
                continue
            columns = list(rows[0])
            for row in rows:
                for column in PATH_COLUMNS.get(table, ()):
                    if isinstance(row.get(column), str):
                        row[column] = row[column].replace(old_files, new_files)
            placeholders = ",".join("?" for _ in columns)
            dst.executemany(
                f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",
                [tuple(row[c] for c in columns) for row in rows],
            )
            copied[table] = len(rows)
    if target.database.dialect == "postgres":
        target.database.reset_sequences([t for t in TABLES if t != "accepted"])
    files = 0
    for path in sorted((source_dir / "files").rglob("*")):
        if path.is_file():
            destination = target.root / "files" / path.relative_to(source_dir / "files")
            if destination != path:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(path.read_bytes())
            target.files.save(destination)
            files += 1
    summary.update({"copied": copied, "files": files})
    return summary
