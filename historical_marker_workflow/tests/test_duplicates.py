from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from marker_workflow.models import ExtractedSubmission, SubmissionRecord, SubmissionSnapshot
from marker_workflow.services.audit import WorkflowStateStore
from marker_workflow.services.duplicate_detector import DuplicateDetector

from support import build_config


class DuplicateDetectorTests(unittest.TestCase):
    def test_exact_hash_match_is_flagged_as_duplicate_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            store = WorkflowStateStore(config.sqlite_path)
            store.upsert_submission_snapshot(
                SubmissionSnapshot(
                    submission_id="SUB-20260310-AAAAAA",
                    review_status="ready-for-review",
                    pipeline_status="classified",
                    community_label="unknown",
                    story_slug="sample-story",
                    canonical_package_path="processing/2026/03/SUB-20260310-AAAAAA",
                    text_preview="Tulane history in New Orleans community memory.",
                    filenames=["story.txt"],
                    source_hashes=["sha256:12345"],
                    updated_at="2026-03-10T12:00:00Z",
                )
            )
            detector = DuplicateDetector(store)
            submission = SubmissionRecord(
                submission_id="SUB-20260312-BBBBBB",
                date_received="2026-03-12T12:00:00Z",
                source_path="intake",
                original_filenames=["story copy.txt"],
                source_hashes=["sha256:12345"],
                review_status="received",
            )
            extracted = ExtractedSubmission(
                submission_id=submission.submission_id,
                files=[],
                combined_text="Tulane history in New Orleans community memory.",
                media_types=["document"],
                detected_language="en",
            )

            candidates = detector.find(submission, extracted)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].submission_id, "SUB-20260310-AAAAAA")
            self.assertGreaterEqual(candidates[0].score, 0.95)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
