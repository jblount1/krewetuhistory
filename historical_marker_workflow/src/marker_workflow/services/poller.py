from __future__ import annotations

from typing import Dict, Tuple

from ..adapters.box_client import FilesystemBoxClient
from ..models import ArtifactBundle, ExtractedSubmission, ReviewResult, SubmissionGroup, SubmissionRecord
from .audit import AuditLogger, WorkflowStateStore
from .duplicate_detector import DuplicateDetector
from .extractor import ExtractionService
from .generator import OutputGenerator
from .grouper import SubmissionGrouper
from .reviewer import ReviewEngine
from .router import Router
from .stager import Stager


class WorkflowOrchestrator:
    def __init__(
        self,
        box_client: FilesystemBoxClient,
        state_store: WorkflowStateStore,
        audit_logger: AuditLogger,
        grouper: SubmissionGrouper,
        stager: Stager,
        extractor: ExtractionService,
        duplicate_detector: DuplicateDetector,
        reviewer: ReviewEngine,
        generator: OutputGenerator,
        router: Router,
    ) -> None:
        self.box_client = box_client
        self.state_store = state_store
        self.audit_logger = audit_logger
        self.grouper = grouper
        self.stager = stager
        self.extractor = extractor
        self.duplicate_detector = duplicate_detector
        self.reviewer = reviewer
        self.generator = generator
        self.router = router

    def poll(self) -> Dict[str, int]:
        run = self.audit_logger.start_run(lock_name="poll")
        stats = {"items_discovered": 0, "groups_processed": 0}
        try:
            items = self.box_client.list_intake_items(self.state_store.processed_versions())
            stats["items_discovered"] = len(items)
            groups = self.grouper.build(items)
            for group in groups:
                self._process_group(run, group)
                stats["groups_processed"] += 1
            self.audit_logger.close_run(run, status="completed", lock_name="poll")
        except Exception:
            self.audit_logger.close_run(run, status="failed", lock_name="poll")
            raise
        return stats

    def process_submission(self, submission_id: str) -> SubmissionRecord:
        submission = self.stager.load_existing(submission_id)
        self._process_existing(submission)
        return submission

    def rebuild_artifacts(self, submission_id: str) -> SubmissionRecord:
        submission = self.stager.load_existing(submission_id)
        self._process_existing(submission)
        return submission

    def _process_group(self, run, group: SubmissionGroup) -> None:
        submission = self.stager.stage(group)
        extracted = self.extractor.run(submission)
        review = self.reviewer.first_pass(submission, extracted, self.duplicate_detector.find(submission, extracted))
        self.reviewer.apply_review(submission, extracted, review)
        artifacts = self.generator.create(submission, extracted, review)
        artifacts = self.router.route(submission, review, artifacts)
        self.audit_logger.record_submission(
            run,
            submission,
            extracted.combined_text,
            artifacts.all_paths(),
            submission.moderation_flags,
            submission.processing_errors,
        )
        for item in group.items:
            self.state_store.mark_item_processed(item.item_id, item.modified_at, submission.submission_id, item.source_path)

    def _process_existing(self, submission: SubmissionRecord) -> Tuple[ExtractedSubmission, ReviewResult, ArtifactBundle]:
        extracted = self.extractor.run(submission)
        review = self.reviewer.first_pass(submission, extracted, self.duplicate_detector.find(submission, extracted))
        self.reviewer.apply_review(submission, extracted, review)
        artifacts = self.generator.create(submission, extracted, review)
        artifacts = self.router.route(submission, review, artifacts)
        snapshot_run = self.audit_logger.start_run(lock_name="maintenance")
        try:
            self.audit_logger.record_submission(
                snapshot_run,
                submission,
                extracted.combined_text,
                artifacts.all_paths(),
                submission.moderation_flags,
                submission.processing_errors,
            )
            self.audit_logger.close_run(snapshot_run, status="completed", lock_name="maintenance")
        except Exception:
            self.audit_logger.close_run(snapshot_run, status="failed", lock_name="maintenance")
            raise
        return extracted, review, artifacts
