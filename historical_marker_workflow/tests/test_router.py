from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from marker_workflow.adapters.box_client import FilesystemBoxClient
from marker_workflow.models import ArtifactBundle, ModerationAssessment, ReviewResult, StoryPackage, SubmissionRecord
from marker_workflow.services.router import Router

from support import build_config


class RouterTests(unittest.TestCase):
    def test_routes_generated_artifacts_into_review_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            box_client = FilesystemBoxClient(config)
            router = Router(config, box_client)

            package_root = config.box_root_path / "processing" / "2026" / "03" / "SUB-20260312-DDDDDD"
            records_dir = package_root / "records"
            drafts_dir = package_root / "drafts"
            records_dir.mkdir(parents=True, exist_ok=True)
            drafts_dir.mkdir(parents=True, exist_ok=True)
            (records_dir / "SUB-20260312-DDDDDD__submission.json").write_text("{}", encoding="utf-8")
            (records_dir / "SUB-20260312-DDDDDD__moderation.json").write_text("{}", encoding="utf-8")
            (drafts_dir / "SUB-20260312-DDDDDD__review.md").write_text("# Review", encoding="utf-8")
            (drafts_dir / "SUB-20260312-DDDDDD__story-package.json").write_text("{}", encoding="utf-8")
            (drafts_dir / "SUB-20260312-DDDDDD__story-package.md").write_text("# Story", encoding="utf-8")

            submission = SubmissionRecord(
                submission_id="SUB-20260312-DDDDDD",
                date_received="2026-03-12T12:00:00Z",
                source_path="intake",
                original_filenames=["story.txt"],
                canonical_package_path="processing/2026/03/SUB-20260312-DDDDDD",
                review_status="received",
            )
            review = ReviewResult(
                classification={"recommended_next_step": "ready_for_human_review"},
                moderation=ModerationAssessment(
                    flags=[],
                    risk_level="low",
                    rationale="No issues",
                    recommended_next_step="ready_for_human_review",
                ),
                story_package=StoryPackage(
                    headline="Sample Story",
                    summary_50="Short summary",
                    narrative_120_180="Narrative body " * 12,
                    associated_media_assets=["story.txt"],
                    suggested_image_caption_placeholders=["Caption placeholder"],
                    suggested_credits_line="Draft credits line",
                    questions_or_gaps=["Confirm date"],
                    display_format_recommendation="touchscreen_story_card",
                    themes=["public memory"],
                    community_labels=["unknown"],
                ),
                deterministic_flags=[],
                duplicate_candidates=[],
                fit_assessment="{}",
                recommended_queue="ready-for-human-review",
                recommended_next_step="ready_for_human_review",
            )
            bundle = ArtifactBundle(
                canonical_package_path="processing/2026/03/SUB-20260312-DDDDDD",
                submission_record_path="processing/2026/03/SUB-20260312-DDDDDD/records/SUB-20260312-DDDDDD__submission.json",
                moderation_record_path="processing/2026/03/SUB-20260312-DDDDDD/records/SUB-20260312-DDDDDD__moderation.json",
                review_markdown_path="processing/2026/03/SUB-20260312-DDDDDD/drafts/SUB-20260312-DDDDDD__review.md",
                story_package_json_path="processing/2026/03/SUB-20260312-DDDDDD/drafts/SUB-20260312-DDDDDD__story-package.json",
                story_package_markdown_path="processing/2026/03/SUB-20260312-DDDDDD/drafts/SUB-20260312-DDDDDD__story-package.md",
            )

            routed = router.route(submission, review, bundle)

            self.assertTrue((config.box_root_path / routed.review_packet_path / "records").exists())
            self.assertTrue((config.box_root_path / routed.review_packet_path / "drafts").exists())
            self.assertTrue((config.box_root_path / routed.manifest_path).exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
