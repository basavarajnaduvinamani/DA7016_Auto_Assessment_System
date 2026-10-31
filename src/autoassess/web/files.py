"""Keep uploaded sheets and marked output across restarts on hosts with a throwaway disk.

The app always reads and writes files on local disk under ``<data dir>/files``. When a durable
backend is configured, every file the app writes is also copied there, and an assignment's
folder is restored from it the first time the assignment is opened after a restart.

Backends, picked by :func:`open_blobs`:
- none: SQLite runs keep files next to the database file, nothing to copy;
- database: the ``blobs`` table of the Postgres database (the default with ``DATABASE_URL``);
- s3: any S3-compatible bucket (Backblaze B2, Cloudflare R2, Supabase Storage), when
  ``AUTOASSESS_S3_BUCKET`` is set.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any


class Blobs:
    """A flat key -> bytes store; keys are forward-slash paths relative to the files folder."""

    name = "none"

    def put(self, key: str, data: bytes) -> None:
        """Save one file."""

    def get(self, key: str) -> bytes | None:
        """Read one file, or None when it was never saved."""
        return None

    def keys(self, prefix: str) -> list[str]:
        """Every saved key under a prefix."""
        return []

    def delete_prefix(self, prefix: str) -> int:
        """Remove every key under a prefix; return how many were removed."""
        return 0

    def usage(self) -> tuple[int, int]:
        """Number of saved files and their total bytes."""
        return 0, 0


def _like(prefix: str) -> str:
    """A LIKE pattern for keys under a prefix (prefixes are ``<assignment id>/``, no wildcards)."""
    if any(c in prefix for c in "%_\\"):
        raise ValueError("Blob prefixes must not contain LIKE wildcards.")
    return prefix + "%"


class DatabaseBlobs(Blobs):
    """Files as rows of the ``blobs`` table."""

    name = "database"

    def __init__(self, connect: Callable[[], AbstractContextManager[Any]]) -> None:
        self.connect = connect

    def put(self, key: str, data: bytes) -> None:
        """Save one file under a key."""
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO blobs(path,data,size,updated_at) VALUES(?,?,?,?)",
                (key, data, len(data), time.time()),
            )

    def get(self, key: str) -> bytes | None:
        """Read one file, or None when it was never saved."""
        with self.connect() as db:
            row = db.execute("SELECT data FROM blobs WHERE path=?", (key,)).fetchone()
        return bytes(row[0]) if row else None

    def keys(self, prefix: str) -> list[str]:
        """Every saved key under a prefix."""
        with self.connect() as db:
            rows = db.execute("SELECT path FROM blobs WHERE path LIKE ?", (_like(prefix),)).fetchall()
        return [r[0] for r in rows]

    def delete_prefix(self, prefix: str) -> int:
        """Remove every key under a prefix and return how many went."""
        with self.connect() as db:
            return db.execute("DELETE FROM blobs WHERE path LIKE ?", (_like(prefix),)).rowcount

    def usage(self) -> tuple[int, int]:
        """Number of saved files and their total bytes."""
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM blobs").fetchone()
        return int(row[0]), int(row[1])


class S3Blobs(Blobs):
    """Files in an S3-compatible bucket (needs ``pip install ".[s3]"``)."""

    name = "s3"

    def __init__(self, bucket: str, *, prefix: str = "", client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=os.getenv("AUTOASSESS_S3_ENDPOINT") or None,
                region_name=os.getenv("AUTOASSESS_S3_REGION") or None,
                aws_access_key_id=os.getenv("AUTOASSESS_S3_KEY_ID") or None,
                aws_secret_access_key=os.getenv("AUTOASSESS_S3_SECRET") or None,
            )
        self.client, self.bucket, self.prefix = client, bucket, prefix.strip("/") + "/" if prefix else ""

    def put(self, key: str, data: bytes) -> None:
        """Save one file under a key."""
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data)

    def get(self, key: str) -> bytes | None:
        """Read one file, or None when it was never saved."""
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self.prefix + key)["Body"].read()
        except Exception as err:  # botocore raises NoSuchKey or a generic ClientError
            if "NoSuchKey" in type(err).__name__ or "404" in str(err) or "NoSuchKey" in str(err):
                return None
            raise

    def _objects(self, prefix: str) -> Iterator[dict[str, Any]]:
        token = None
        while True:
            extra = {"ContinuationToken": token} if token else {}
            page = self.client.list_objects_v2(Bucket=self.bucket, Prefix=self.prefix + prefix, **extra)
            yield from page.get("Contents", [])
            if not page.get("IsTruncated"):
                return
            token = page["NextContinuationToken"]

    def keys(self, prefix: str) -> list[str]:
        """Every saved key under a prefix."""
        return [o["Key"][len(self.prefix) :] for o in self._objects(prefix)]

    def delete_prefix(self, prefix: str) -> int:
        """Remove every key under a prefix and return how many went."""
        keys = [o["Key"] for o in self._objects(prefix)]
        for start in range(0, len(keys), 1000):
            chunk = keys[start : start + 1000]
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": [{"Key": k} for k in chunk]})
        return len(keys)

    def usage(self) -> tuple[int, int]:
        """Number of saved files and their total bytes."""
        objects = list(self._objects(""))
        return len(objects), sum(int(o.get("Size", 0)) for o in objects)


class FileMirror:
    """Local files folder plus an optional durable copy of everything written to it."""

    def __init__(self, folder: Path, blobs: Blobs | None = None) -> None:
        self.folder = folder
        self.blobs = blobs or Blobs()
        self._restored: set[int] = set()
        self._lock = threading.Lock()

    @property
    def durable(self) -> bool:
        """True when files are copied somewhere that outlives this disk."""
        return self.blobs.name != "none"

    def key(self, path: str | Path) -> str | None:
        """The blob key for a path inside the files folder, or None for paths outside it."""
        try:
            return Path(path).resolve().relative_to(self.folder.resolve()).as_posix()
        except ValueError:
            return None

    def save(self, path: str | Path) -> None:
        """Copy one local file to the durable backend."""
        key = self.key(path)
        if self.durable and key and Path(path).is_file():
            self.blobs.put(key, Path(path).read_bytes())

    def save_tree(self, folder: str | Path) -> None:
        """Copy every file under a folder to the durable backend."""
        if not self.durable or not Path(folder).is_dir():
            return
        for path in sorted(Path(folder).rglob("*")):
            if path.is_file():
                self.save(path)

    def restore(self, assignment_id: int) -> None:
        """Bring an assignment's files back to local disk once per process (no-op without a backend)."""
        if not self.durable or assignment_id in self._restored:
            return
        with self._lock:
            if assignment_id in self._restored:
                return
            for key in self.blobs.keys(f"{assignment_id}/"):
                target = self.folder / key
                if not target.exists():
                    data = self.blobs.get(key)
                    if data is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
            self._restored.add(assignment_id)

    def forget(self, assignment_id: int) -> None:
        """Delete an assignment's files locally and from the durable backend."""
        self.blobs.delete_prefix(f"{assignment_id}/")
        shutil.rmtree(self.folder / str(assignment_id), ignore_errors=True)
        self._restored.discard(assignment_id)


def open_blobs(connect: Callable[[], AbstractContextManager[Any]], database_durable: bool) -> Blobs:
    """S3 when a bucket is configured, the database's blobs table for Postgres, otherwise none."""
    bucket = os.getenv("AUTOASSESS_S3_BUCKET", "").strip()
    if bucket:
        return S3Blobs(bucket, prefix=os.getenv("AUTOASSESS_S3_PREFIX", "secondread"))
    if database_durable:
        return DatabaseBlobs(connect)
    return Blobs()
