from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from marker_workflow.adapters.ai_client import HeuristicAIClient
from marker_workflow.models import ExtractedSubmission, SubmissionRecord
from marker_workflow.services.reviewer import ReviewEngine

from support import build_config


class ReviewEngineTests(unittest.TestCase):
    def test_flags_private_information_for_sensitive_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_config(Path(temp_dir))
            engine = ReviewEngine(config, HeuristicAIClient())
            submission = SubmissionRecord(
                submission_id="SUB-20260312-CCCCCC",
                date_received="2026-03-12T12:00:00Z",
                source_path="intake",
                original_filenames=["interview.txt"],
                rights_or_permission_status="unstated",
                review_status="received",
            )
            extracted = ExtractedSubmission(
                submission_id=submission.submission_id,
                files=[],
                combined_text=(
                    "This interview discusses Tulane and New Orleans neighborhood history. "
                    "Please contact historian@example.com for questions."
                ),
                media_types=["document"],
                detected_language="en",
            )

            review = engine.first_pass(submission, extracted, [])
            engine.apply_review(submission, extracted, review)

            self.assertIn("doxxing_or_private_information", submission.moderation_flags)
            self.assertEqual(submission.recommended_next_step, "sensitive_content_review")
            self.assertEqual(submission.pipeline_status, "flagged")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
