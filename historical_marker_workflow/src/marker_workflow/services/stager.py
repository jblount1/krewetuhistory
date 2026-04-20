from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..adapters.box_client import FilesystemBoxClient
from ..config import AppConfig
from ..models import BoxItem, SubmissionGroup, SubmissionRecord
from ..utils import dump_json, ensure_directory, isoformat_z, load_json, relative_to, sha256_file, slugify


class Stager:
    def __init__(self, config: AppConfig, box_client: FilesystemBoxClient) -> None:
        self.config = config
        self.box_client = box_client

    def stage(self, group: SubmissionGroup) -> SubmissionRecord:
        now = datetime.now(timezone.utc)
        year = now.strftime("%Y")
        month = now.strftime("%m")
        submission_id = self._submission_id(group.items, now)
        package_root = self.config.processing_package_path(submission_id, year, month)
        for child in ("originals", "derivatives", "records", "drafts", "manifests"):
            ensure_directory(package_root / child)

        source_hashes: List[str] = []
        original_filenames: List[str] = []
        filename_counts: Counter[str] = Counter()
        promoted_items: List[Dict[str, str]] = []
        for item in group.items:
            filename_counts[item.name] += 1
            source_abs = self.box_client.absolute_path(item.source_path)
            source_hash = sha256_file(source_abs)
            destination_name = self._destination_name(item.name, filename_counts[item.name])
            destination_relative = relative_to(package_root / "originals" / destination_name, self.config.box_root_path)
            promoted_relative = self.box_client.promote_file(item.source_path, destination_relative)
            source_hashes.append(source_hash)
            original_filenames.append(item.name)
            promoted_items.append(
                {
                    "item_id": item.item_id,
                    "source_path": item.source_path,
                    "promoted_path": promoted_relative,
                    "hash": source_hash,
                }
            )

        contributor_name = self._pick_metadata(group.items, "contributor_name")
        contributor_contact = self._pick_metadata(group.items, "contributor_contact")
        rights_status = self._pick_metadata(group.items, "rights_or_permission_status") or "unstated"
        notes = []
        if group.confidence < 0.80:
            notes.append("Files were intentionally kept separate because submission grouping confidence was low.")
        elif group.confidence < 1.0:
            notes.append("Submission package was grouped heuristically; confirm that all files belong together.")
        record = SubmissionRecord(
            submission_id=submission_id,
            date_received=isoformat_z(now),
            source_path=self._common_source_path(group.items),
            original_filenames=original_filenames,
            contributor_name=contributor_name,
            contributor_contact=contributor_contact,
            rights_or_permission_status=rights_status,
            grouping_confidence=group.confidence,
            box_file_ids=[item.item_id for item in group.items],
            source_hashes=source_hashes,
            notes_for_human_reviewer=notes,
            pipeline_status="staged",
            review_status="received",
            canonical_package_path=relative_to(package_root, self.config.box_root_path),
        )
        dump_json(
            package_root / "manifests" / f"{submission_id}__source-manifest.json",
            {
                "submission_id": submission_id,
                "group_confidence": group.confidence,
                "group_rationale": group.rationale,
                "items": promoted_items,
            },
        )
        return record

    def load_existing(self, submission_id: str) -> SubmissionRecord:
        package_root = self.box_client.locate_processing_package(submission_id)
        if not package_root:
            raise FileNotFoundError(f"Could not find processing package for {submission_id}.")
        record_path = package_root / "records" / f"{submission_id}__submission.json"
        if record_path.exists():
            payload = load_json(record_path)
            return SubmissionRecord(**payload)
        originals = sorted(path.name for path in (package_root / "originals").glob("*") if path.is_file())
        return SubmissionRecord(
            submission_id=submission_id,
            date_received=isoformat_z(),
            source_path="processing-reload",
            original_filenames=originals,
            rights_or_permission_status="unstated",
            review_status="received",
            pipeline_status="staged",
            canonical_package_path=relative_to(package_root, self.config.box_root_path),
        )

    def _submission_id(self, items: Sequence[BoxItem], now: datetime) -> str:
        digest = hashlib.sha1("|".join(sorted(item.item_id for item in items)).encode("utf-8")).hexdigest()[:6].upper()
        return f"SUB-{now.strftime('%Y%m%d')}-{digest}"

    def _destination_name(self, original_name: str, occurrence: int) -> str:
        if occurrence == 1:
            return original_name
        stem = Path(original_name).stem
        suffix = Path(original_name).suffix
        return f"{stem}__{occurrence}{suffix}"

    def _pick_metadata(self, items: Sequence[BoxItem], key: str) -> Optional[str]:
        for item in items:
            if item.metadata.get(key):
                return str(item.metadata[key])
        return None

    def _common_source_path(self, items: Sequence[BoxItem]) -> str:
        parents = sorted({item.parent_path for item in items})
        if len(parents) == 1:
            return parents[0]
        common_parts = Path(parents[0]).parts
        for parent in parents[1:]:
            parts = Path(parent).parts
            common_parts = tuple(left for left, right in zip(common_parts, parts) if left == right)
        return Path(*common_parts).as_posix() if common_parts else self.config.box_intake_folder
