from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..config import AppConfig
from ..models import AuditEvent, RunContext, SubmissionRecord, SubmissionSnapshot
from ..utils import dump_json, ensure_directory, excerpt, generate_prefixed_id, isoformat_z, utc_now


class WorkflowStateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        ensure_directory(db_path.parent)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS locks (
                    name TEXT PRIMARY KEY,
                    acquired_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    log_path TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS processed_items (
                    item_id TEXT PRIMARY KEY,
                    modified_at TEXT NOT NULL,
                    submission_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    processed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS submission_snapshots (
                    submission_id TEXT PRIMARY KEY,
                    review_status TEXT NOT NULL,
                    pipeline_status TEXT NOT NULL,
                    community_label TEXT,
                    story_slug TEXT,
                    canonical_package_path TEXT NOT NULL,
                    text_preview TEXT NOT NULL,
                    filenames_json TEXT NOT NULL,
                    source_hashes_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS file_hashes (
                    file_hash TEXT NOT NULL,
                    submission_id TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                """
            )

    def acquire_lock(self, name: str) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO locks (name, acquired_at) VALUES (?, ?)",
                    (name, isoformat_z()),
                )
        except sqlite3.IntegrityError as exc:
            raise RuntimeError(f"Workflow lock '{name}' is already held.") from exc

    def release_lock(self, name: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM locks WHERE name = ?", (name,))

    def register_run(self, run: RunContext) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs (run_id, started_at, status, log_path) VALUES (?, ?, ?, ?)",
                (run.run_id, run.started_at, "running", run.log_path),
            )

    def finish_run(self, run_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET finished_at = ?, status = ? WHERE run_id = ?",
                (isoformat_z(), status, run_id),
            )

    def processed_versions(self) -> Dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT item_id, modified_at FROM processed_items").fetchall()
        return {row["item_id"]: row["modified_at"] for row in rows}

    def mark_item_processed(self, item_id: str, modified_at: str, submission_id: str, source_path: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO processed_items (item_id, modified_at, submission_id, source_path, processed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    modified_at = excluded.modified_at,
                    submission_id = excluded.submission_id,
                    source_path = excluded.source_path,
                    processed_at = excluded.processed_at
                """,
                (item_id, modified_at, submission_id, source_path, isoformat_z()),
            )

    def upsert_submission_snapshot(self, snapshot: SubmissionSnapshot) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO submission_snapshots (
                    submission_id, review_status, pipeline_status, community_label, story_slug,
                    canonical_package_path, text_preview, filenames_json, source_hashes_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(submission_id) DO UPDATE SET
                    review_status = excluded.review_status,
                    pipeline_status = excluded.pipeline_status,
                    community_label = excluded.community_label,
                    story_slug = excluded.story_slug,
                    canonical_package_path = excluded.canonical_package_path,
                    text_preview = excluded.text_preview,
                    filenames_json = excluded.filenames_json,
                    source_hashes_json = excluded.source_hashes_json,
                    updated_at = excluded.updated_at
                """,
                (
                    snapshot.submission_id,
                    snapshot.review_status,
                    snapshot.pipeline_status,
                    snapshot.community_label,
                    snapshot.story_slug,
                    snapshot.canonical_package_path,
                    snapshot.text_preview,
                    json.dumps(snapshot.filenames),
                    json.dumps(snapshot.source_hashes),
                    snapshot.updated_at,
                ),
            )

    def record_file_hashes(self, submission_id: str, filenames: Iterable[str], source_hashes: Iterable[str]) -> None:
        with self._connect() as connection:
            for filename, file_hash in zip(filenames, source_hashes):
                connection.execute(
                    "INSERT INTO file_hashes (file_hash, submission_id, original_filename, recorded_at) VALUES (?, ?, ?, ?)",
                    (file_hash, submission_id, filename, isoformat_z()),
                )

    def list_submission_snapshots(self) -> List[SubmissionSnapshot]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM submission_snapshots").fetchall()
        snapshots: List[SubmissionSnapshot] = []
        for row in rows:
            snapshots.append(
                SubmissionSnapshot(
                    submission_id=row["submission_id"],
                    review_status=row["review_status"],
                    pipeline_status=row["pipeline_status"],
                    community_label=row["community_label"],
                    story_slug=row["story_slug"],
                    canonical_package_path=row["canonical_package_path"],
                    text_preview=row["text_preview"],
                    filenames=json.loads(row["filenames_json"]),
                    source_hashes=json.loads(row["source_hashes_json"]),
                    updated_at=row["updated_at"],
                )
            )
        return snapshots

    def get_submission_snapshot(self, submission_id: str) -> Optional[SubmissionSnapshot]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM submission_snapshots WHERE submission_id = ?",
                (submission_id,),
            ).fetchone()
        if not row:
            return None
        return SubmissionSnapshot(
            submission_id=row["submission_id"],
            review_status=row["review_status"],
            pipeline_status=row["pipeline_status"],
            community_label=row["community_label"],
            story_slug=row["story_slug"],
            canonical_package_path=row["canonical_package_path"],
            text_preview=row["text_preview"],
            filenames=json.loads(row["filenames_json"]),
            source_hashes=json.loads(row["source_hashes_json"]),
            updated_at=row["updated_at"],
        )


class AuditLogger:
    def __init__(self, config: AppConfig, state_store: Optional[WorkflowStateStore] = None) -> None:
        self.config = config
        self.state_store = state_store or WorkflowStateStore(config.sqlite_path)

    def start_run(self, lock_name: str = "poll") -> RunContext:
        self.state_store.acquire_lock(lock_name)
        started_at = isoformat_z()
        run_id = generate_prefixed_id("RUN", utc_now())
        stamp = utc_now()
        log_dir = ensure_directory(
            self.config.box_root_path / "logs" / "runs" / stamp.strftime("%Y") / stamp.strftime("%m") / stamp.strftime("%d")
        )
        log_path = log_dir / f"{run_id}.jsonl"
        run = RunContext(run_id=run_id, started_at=started_at, log_path=str(log_path))
        self.state_store.register_run(run)
        self.write_event(run, AuditEvent(timestamp=started_at, run_id=run_id, action="run_started"))
        return run

    def close_run(self, run: RunContext, status: str = "completed", lock_name: str = "poll") -> None:
        self.write_event(run, AuditEvent(timestamp=isoformat_z(), run_id=run.run_id, action="run_finished"))
        self.state_store.finish_run(run.run_id, status)
        self.state_store.release_lock(lock_name)

    def write_event(self, run: RunContext, event: AuditEvent) -> None:
        ensure_directory(Path(run.log_path).parent)
        with Path(run.log_path).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=True))
            handle.write("\n")

    def record_submission(
        self,
        run: RunContext,
        submission: SubmissionRecord,
        combined_text: str,
        artifacts_created: List[str],
        flags_raised: List[str],
        errors: List[str],
    ) -> None:
        snapshot = SubmissionSnapshot(
            submission_id=submission.submission_id,
            review_status=submission.review_status or "received",
            pipeline_status=submission.pipeline_status,
            community_label=submission.community_label,
            story_slug=submission.story_slug,
            canonical_package_path=submission.canonical_package_path or "",
            text_preview=excerpt(combined_text, limit=1500),
            filenames=submission.original_filenames,
            source_hashes=submission.source_hashes,
            updated_at=isoformat_z(),
        )
        self.state_store.upsert_submission_snapshot(snapshot)
        self.state_store.record_file_hashes(submission.submission_id, submission.original_filenames, submission.source_hashes)
        event = AuditEvent(
            timestamp=isoformat_z(),
            run_id=run.run_id,
            action="submission_processed",
            submission_id=submission.submission_id,
            box_file_ids=submission.box_file_ids,
            source_path=submission.source_path,
            destination_path=submission.canonical_package_path,
            classification_decisions={
                "review_status": submission.review_status,
                "recommended_next_step": submission.recommended_next_step,
                "community_label": submission.community_label,
                "story_theme": submission.story_theme,
            },
            flags_raised=flags_raised,
            artifacts_created=artifacts_created,
            errors=errors,
        )
        self.write_event(run, event)

    def write_report(self, relative_path: str, payload: dict) -> str:
        report_path = self.config.box_root_path / relative_path
        dump_json(report_path, payload)
        return relative_path

