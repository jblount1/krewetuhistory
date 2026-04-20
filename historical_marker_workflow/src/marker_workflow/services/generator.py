from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from ..adapters.box_client import FilesystemBoxClient
from ..config import AppConfig
from ..models import ArtifactBundle, ExtractedSubmission, ReviewResult, SubmissionRecord
from ..utils import dump_json, format_bullets, render_template, write_text


class OutputGenerator:
    def __init__(self, config: AppConfig, box_client: FilesystemBoxClient) -> None:
        self.config = config
        self.box_client = box_client
        self.template_root = Path(__file__).resolve().parent.parent / "templates"

    def create(self, submission: SubmissionRecord, extracted: ExtractedSubmission, review: ReviewResult) -> ArtifactBundle:
        package_root = self.box_client.absolute_path(submission.canonical_package_path or "")
        records_dir = package_root / "records"
        drafts_dir = package_root / "drafts"
        submission_record_path = records_dir / f"{submission.submission_id}__submission.json"
        moderation_record_path = records_dir / f"{submission.submission_id}__moderation.json"
        review_markdown_path = drafts_dir / f"{submission.submission_id}__review.md"
        story_package_json_path = drafts_dir / f"{submission.submission_id}__story-package.json"
        story_package_markdown_path = drafts_dir / f"{submission.submission_id}__story-package.md"

        moderation_payload = {
            "submission_id": submission.submission_id,
            "flags": review.moderation.flags,
            "risk_level": review.moderation.risk_level,
            "rationale": review.moderation.rationale,
            "recommended_next_step": review.moderation.recommended_next_step,
            "duplicate_candidates": [
                {"submission_id": candidate.submission_id, "score": candidate.score, "reasons": candidate.reasons}
                for candidate in review.duplicate_candidates
            ],
            "fit_assessment": review.fit_assessment,
            "deterministic_flags": review.deterministic_flags,
        }
        story_package_payload = {
            "submission_id": submission.submission_id,
            "headline": review.story_package.headline,
            "summary_50": review.story_package.summary_50,
            "narrative_120_180": review.story_package.narrative_120_180,
            "associated_media_assets": review.story_package.associated_media_assets,
            "suggested_image_caption_placeholders": review.story_package.suggested_image_caption_placeholders,
            "suggested_credits_line": review.story_package.suggested_credits_line,
            "questions_or_gaps": review.story_package.questions_or_gaps,
            "display_format_recommendation": review.story_package.display_format_recommendation,
            "themes": review.story_package.themes,
            "community_labels": review.story_package.community_labels,
        }
        dump_json(submission_record_path, submission.to_dict())
        dump_json(moderation_record_path, moderation_payload)
        dump_json(story_package_json_path, story_package_payload)
        write_text(review_markdown_path, self._render_review_markdown(submission, extracted, review))
        write_text(story_package_markdown_path, self._render_story_markdown(submission, review))

        return ArtifactBundle(
            canonical_package_path=submission.canonical_package_path or "",
            submission_record_path=self._relative(submission_record_path),
            moderation_record_path=self._relative(moderation_record_path),
            review_markdown_path=self._relative(review_markdown_path),
            story_package_json_path=self._relative(story_package_json_path),
            story_package_markdown_path=self._relative(story_package_markdown_path),
        )

    def render_existing(self, submission: SubmissionRecord, review: ReviewResult) -> ArtifactBundle:
        extracted = ExtractedSubmission(
            submission_id=submission.submission_id,
            files=[],
            combined_text=submission.story_summary or "",
            media_types=submission.media_types,
            detected_language=submission.detected_language or "unknown",
            errors=submission.processing_errors,
        )
        return self.create(submission, extracted, review)

    def _render_review_markdown(self, submission: SubmissionRecord, extracted: ExtractedSubmission, review: ReviewResult) -> str:
        template = (self.template_root / "review_summary.md.j2").read_text(encoding="utf-8")
        context: Dict[str, str] = {
            "submission_id": submission.submission_id,
            "date_received": submission.date_received,
            "source_path": submission.source_path,
            "filenames": format_bullets(submission.original_filenames),
            "media_types": format_bullets(submission.media_types),
            "grouping_confidence": f"{submission.grouping_confidence:.2f}",
            "project_relevance": submission.project_relevance or "unknown",
            "community_label": submission.community_label or "unknown",
            "geographic_label": submission.geographic_label or "unknown",
            "tulane_connection": submission.tulane_connection or "unknown",
            "story_theme": submission.story_theme or "unknown",
            "completeness_status": submission.completeness_status or "unknown",
            "review_status": submission.review_status or "unknown",
            "risk_level": submission.public_display_risk_level or "unknown",
            "moderation_flags": format_bullets(submission.moderation_flags),
            "duplicate_candidates": format_bullets(
                [f"{candidate.submission_id} (score={candidate.score:.2f})" for candidate in review.duplicate_candidates]
            ),
            "recommended_next_step": submission.recommended_next_step or "unknown",
            "notes_for_human_reviewer": format_bullets(submission.notes_for_human_reviewer),
            "fit_assessment": review.fit_assessment,
            "extraction_errors": format_bullets(extracted.errors),
        }
        return render_template(template, context)

    def _render_story_markdown(self, submission: SubmissionRecord, review: ReviewResult) -> str:
        template = (self.template_root / "story_package.md.j2").read_text(encoding="utf-8")
        context: Dict[str, str] = {
            "submission_id": submission.submission_id,
            "headline": review.story_package.headline,
            "summary_50": review.story_package.summary_50,
            "narrative_120_180": review.story_package.narrative_120_180,
            "associated_media_assets": format_bullets(review.story_package.associated_media_assets),
            "caption_placeholders": format_bullets(review.story_package.suggested_image_caption_placeholders),
            "credits_line": review.story_package.suggested_credits_line,
            "questions_or_gaps": format_bullets(review.story_package.questions_or_gaps),
            "display_format_recommendation": review.story_package.display_format_recommendation,
            "theme_labels": format_bullets(review.story_package.themes),
            "community_labels": format_bullets(review.story_package.community_labels),
        }
        return render_template(template, context)

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.config.box_root_path.resolve()).as_posix()

