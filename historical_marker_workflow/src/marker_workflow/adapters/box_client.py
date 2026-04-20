from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import AppConfig
from ..models import BoxItem
from ..utils import copy_and_verify, ensure_directory, isoformat_z, relative_to


class FilesystemBoxClient:
    """Local filesystem adapter that mirrors the Box project folder model."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.ensure_runtime_directories()

    def list_intake_items(self, processed_versions: Optional[Dict[str, str]] = None) -> List[BoxItem]:
        processed_versions = processed_versions or {}
        intake_root = self.config.box_root_path / self.config.box_intake_folder
        items: List[BoxItem] = []
        for path in sorted(intake_root.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            stat = path.stat()
            modified_at = isoformat_z(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))
            item_id = relative_to(path, self.config.box_root_path)
            if processed_versions.get(item_id) == modified_at:
                continue
            items.append(
                BoxItem(
                    item_id=item_id,
                    name=path.name,
                    source_path=item_id,
                    parent_path=relative_to(path.parent, self.config.box_root_path),
                    created_at=isoformat_z(datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)),
                    modified_at=modified_at,
                    size_bytes=stat.st_size,
                    extension=path.suffix.lower(),
                    metadata={},
                    local_path=str(path),
                )
            )
        return items

    def absolute_path(self, relative_path: str) -> Path:
        return (self.config.box_root_path / relative_path).resolve()

    def ensure_folder(self, relative_path: str) -> Path:
        path = self.absolute_path(relative_path)
        ensure_directory(path)
        return path

    def promote_file(self, source_relative_path: str, destination_relative_path: str) -> str:
        source = self.absolute_path(source_relative_path)
        destination = self.absolute_path(destination_relative_path)
        copy_and_verify(source, destination)
        source.unlink()
        return relative_to(destination, self.config.box_root_path)

    def copy_file(self, source_relative_path: str, destination_relative_path: str) -> str:
        source = self.absolute_path(source_relative_path)
        destination = self.absolute_path(destination_relative_path)
        ensure_directory(destination.parent)
        shutil.copy2(source, destination)
        return relative_to(destination, self.config.box_root_path)

    def copy_tree(self, source_relative_path: str, destination_relative_path: str) -> str:
        source = self.absolute_path(source_relative_path)
        destination = self.absolute_path(destination_relative_path)
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return relative_to(destination, self.config.box_root_path)

    def exists(self, relative_path: str) -> bool:
        return self.absolute_path(relative_path).exists()

    def locate_processing_package(self, submission_id: str) -> Optional[Path]:
        processing_root = self.config.box_root_path / "processing"
        for candidate in processing_root.rglob(submission_id):
            if candidate.is_dir():
                return candidate
        return None

    def locate_submission_record(self, submission_id: str) -> Optional[Path]:
        for root_name in ("processing", "review", "approved", "rejected", "needs-more-info", "archive"):
            root = self.config.box_root_path / root_name
            if not root.exists():
                continue
            pattern = f"{submission_id}__submission.json"
            for candidate in root.rglob(pattern):
                if candidate.is_file():
                    return candidate
        return None
