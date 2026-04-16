from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..adapters.box_client import FilesystemBoxClient
from ..config import AppConfig
from ..models import SubmissionSnapshot
from ..utils import dump_json, ensure_directory, isoformat_z, load_json, relative_to
from .audit import WorkflowStateStore


class ReconcileService:
    def __init__(self, config: AppConfig, box_client: FilesystemBoxClient, state_store: WorkflowStateStore) -> None:
        self.config = config
        self.box_client = box_client
        self.state_store = state_store

    def run(self) -> Dict[str, List[str]]:
        report = {
            "timestamp": isoformat_z(),
            "approved": [],
            "rejected": [],
            "needs_more_info": [],
            "archived": [],
            "unresolved": [],
        }
        status_index = self._scan_status_folders()
        for snapshot in self.state_store.list_submission_snapshots():
            status_path = status_index.get(snapshot.submission_id)
            if not status_path:
                report["unresolved"].append(snapshot.submission_id)
                continue
            folder_name = Path(status_path).parts[0]
            if folder_name == "approved":
                report["approved"].append(snapshot.submission_id)
            elif folder_name == "rejected":
                report["rejected"].append(snapshot.submission_id)
            elif folder_name == "needs-more-info":
                report["needs_more_info"].append(snapshot.submission_id)
            if folder_name in {"approved", "rejected", "needs-more-info"}:
                archived = self._archive_snapshot(snapshot)
                if archived:
                    report["archived"].append(archived)
        report_path = self._write_report(report)
        report["report_path"] = report_path
        return report

    def _scan_status_folders(self) -> Dict[str, str]:
        index: Dict[str, str] = {}
        for folder_name in ("approved", "rejected", "needs-more-info"):
            root = self.config.box_root_path / folder_name
            if not root.exists():
                continue
            for record_path in root.rglob("*__submission.json"):
                try:
                    payload = load_json(record_path)
                except Exception:
                    continue
                submission_id = payload.get("submission_id")
                if submission_id:
                    index[submission_id] = relative_to(record_path, self.config.box_root_path)
        return index

    def _archive_snapshot(self, snapshot: SubmissionSnapshot) -> Optional[str]:
        canonical_root = self.box_client.absolute_path(snapshot.canonical_package_path)
        if not canonical_root.exists():
            return None
        stamp = datetime.now(timezone.utc)
        archive_root = self.config.archive_package_path(snapshot.submission_id, stamp.strftime("%Y"), stamp.strftime("%m"))
        if archive_root.exists():
            return None
        ensure_directory(archive_root.parent)
        for path in canonical_root.rglob("*"):
            destination = archive_root / path.relative_to(canonical_root)
            if path.is_dir():
                ensure_directory(destination)
            else:
                ensure_directory(destination.parent)
                destination.write_bytes(path.read_bytes())
        return relative_to(archive_root, self.config.box_root_path)

    def _write_report(self, report: Dict[str, List[str]]) -> str:
        stamp = datetime.now(timezone.utc)
        path = (
            self.config.box_root_path
            / "logs"
            / "reconcile"
            / stamp.strftime("%Y")
            / stamp.strftime("%m")
            / stamp.strftime("%d")
            / f"RECON-{stamp.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        dump_json(path, report)
        return relative_to(path, self.config.box_root_path)

