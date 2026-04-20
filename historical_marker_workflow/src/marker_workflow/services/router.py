from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..adapters.box_client import FilesystemBoxClient
from ..config import AppConfig
from ..models import ArtifactBundle, ReviewResult, SubmissionRecord
from ..utils import dump_json, ensure_directory


class Router:
    def __init__(self, config: AppConfig, box_client: FilesystemBoxClient) -> None:
        self.config = config
        self.box_client = box_client

    def route(self, submission: SubmissionRecord, review: ReviewResult, bundle: ArtifactBundle) -> ArtifactBundle:
        date_received = datetime.fromisoformat(submission.date_received.replace("Z", "+00:00")).astimezone(timezone.utc)
        queue_root = self.config.review_packet_path(
            review.recommended_queue,
            submission.submission_id,
            date_received.strftime("%Y"),
            date_received.strftime("%m"),
        )
        ensure_directory(queue_root / "records")
        ensure_directory(queue_root / "drafts")

        for source_relative in (
            bundle.submission_record_path,
            bundle.moderation_record_path,
            bundle.review_markdown_path,
            bundle.story_package_json_path,
            bundle.story_package_markdown_path,
        ):
            source = self.box_client.absolute_path(source_relative)
            relative_parts = Path(source_relative).parts
            if "records" in relative_parts:
                start_index = relative_parts.index("records")
            else:
                start_index = relative_parts.index("drafts")
            destination = queue_root.joinpath(*relative_parts[start_index:])
            ensure_directory(destination.parent)
            shutil.copy2(source, destination)

        manifest_path = queue_root / f"{submission.submission_id}__review-packet.json"
        dump_json(
            manifest_path,
            {
                "submission_id": submission.submission_id,
                "recommended_queue": review.recommended_queue,
                "recommended_next_step": review.recommended_next_step,
                "canonical_package_path": submission.canonical_package_path,
                "artifacts": bundle.all_paths(),
            },
        )
        bundle.review_packet_path = queue_root.resolve().relative_to(self.config.box_root_path.resolve()).as_posix()
        bundle.manifest_path = manifest_path.resolve().relative_to(self.config.box_root_path.resolve()).as_posix()
        return bundle
