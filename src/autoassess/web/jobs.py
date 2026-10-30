"""Two-worker local job runner backed by durable SQLite job states."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import TYPE_CHECKING

from autoassess.web.grading import grade_submission

if TYPE_CHECKING:
    from autoassess.web.store import Store


class Jobs:
    """Run durable grading jobs on a bounded two-worker thread pool."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="redink-grade")
        self.lock = Lock()
        self.scheduled: set[int] = set()
        self.closed = False

    def start(self) -> None:
        """Recover interrupted jobs and schedule queued work."""
        self.store.recover_jobs()
        self.kick()

    def kick(self) -> None:
        """Schedule queued jobs not already submitted to the local executor."""
        with self.lock:
            if self.closed:
                return
            for job_id in self.store.queued_jobs():
                if job_id not in self.scheduled:
                    self.scheduled.add(job_id)
                    self.pool.submit(self.work, job_id)

    def work(self, job_id: int) -> None:
        """Claim one job, persist its result and record a safe failure notice."""
        try:
            job = self.store.claim_job(job_id)
            if not job:
                return
            try:
                grade, run_json, artifacts = grade_submission(self.store, job["submission_id"])
                self.store.complete_job(job_id, grade, run_json, artifacts)
            except ValueError as err:
                # Validation errors originate in local upload/demo checks.
                self.store.fail_job(
                    job_id,
                    str(err)
                    if str(err).startswith(("Dry-run", "This sheet is a scan", "Upload", "PDF", "Use a ."))
                    else "The sheet could not be marked. Check the file and OCR setup, then retry.",
                )
            except Exception:
                self.store.fail_job(
                    job_id, "The sheet could not be marked. Check the file and provider setup, then retry."
                )
        finally:
            with self.lock:
                self.scheduled.discard(job_id)
            self.kick()

    def close(self) -> None:
        """Stop scheduling work and wait for submitted jobs to finish."""
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=True)
