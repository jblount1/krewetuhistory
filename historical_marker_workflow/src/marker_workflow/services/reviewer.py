from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from ..adapters.ai_client import AIClient
from ..config import AppConfig
from ..models import DuplicateCandidate, ExtractedSubmission, ModerationAssessment, ReviewResult, StoryPackage, SubmissionRecord
from ..utils import excerpt, slugify


class ReviewEngine:
    def __init__(self, config: AppConfig, ai_client: AIClient) -> None:
        self.config = config
        self.ai_client = ai_client
        self.prompt_root = Path(__file__).resolve().parent.parent / "prompts"

    def first_pass(
        self,
        submission: SubmissionRecord,
        extracted: ExtractedSubmission,
        duplicate_candidates: List[DuplicateCandidate],
    ) -> ReviewResult:
        deterministic_flags = self._deterministic_flags(submission, extracted, duplicate_candidates)
        payload = self._build_payload(submission, extracted, duplicate_candidates, deterministic_flags)
        classification = self.ai_client.classify_submission(self._prompt_text("classify.txt"), payload)
        moderation_payload = dict(payload)
        moderation_payload["classification"] = classification
        moderation = self.ai_client.moderate_submission(self._prompt_text("moderate.txt"), moderation_payload)
        story_payload = dict(payload)
        story_payload.update(classification)
        story_payload["notes_for_human_reviewer"] = list(
            {
                *payload.get("notes_for_human_reviewer", []),
                *classification.get("notes_for_human_reviewer", []),
            }
        )
        story_package_payload = self.ai_client.draft_story_package(self._prompt_text("draft_story.txt"), story_payload)
        moderation_assessment = ModerationAssessment(
            flags=list(moderation.get("flags", [])),
            risk_level=moderation.get("risk_level", "medium"),
            rationale=moderation.get("rationale", ""),
            recommended_next_step=moderation.get("recommended_next_step", "ready_for_human_review"),
        )
        story_package = StoryPackage(**story_package_payload)
        recommended_next_step = self._resolve_next_step(classification, moderation_assessment, duplicate_candidates, deterministic_flags)
        recommended_queue = slugify(recommended_next_step, fallback="triage")
        fit_assessment = self._fit_assessment(classification, moderation_assessment, duplicate_candidates)
        return ReviewResult(
            classification=classification,
            moderation=moderation_assessment,
            story_package=story_package,
            deterministic_flags=deterministic_flags,
            duplicate_candidates=duplicate_candidates,
            fit_assessment=fit_assessment,
            recommended_queue=recommended_queue,
            recommended_next_step=recommended_next_step,
        )

    def apply_review(self, submission: SubmissionRecord, extracted: ExtractedSubmission, review: ReviewResult) -> SubmissionRecord:
        classification = review.classification
        submission.project_relevance = classification.get("project_relevance")
        submission.community_label = classification.get("community_label")
        submission.geographic_label = classification.get("geographic_label")
        submission.tulane_connection = classification.get("tulane_connection")
        submission.story_theme = classification.get("story_theme")
        submission.story_type = classification.get("story_type")
        submission.media_types = classification.get("media_types") or extracted.media_types
        submission.completeness_status = classification.get("completeness_status")
        submission.public_display_risk_level = classification.get("public_display_risk_level")
        submission.review_status = review.recommended_queue
        submission.recommended_next_step = review.recommended_next_step
        submission.moderation_flags = sorted(set(review.deterministic_flags + review.moderation.flags))
        submission.notes_for_human_reviewer = list(
            {
                *submission.notes_for_human_reviewer,
                *(classification.get("notes_for_human_reviewer") or []),
                *review.story_package.questions_or_gaps,
            }
        )
        submission.story_title = review.story_package.headline
        submission.story_summary = review.story_package.summary_50
        submission.display_format_recommendation = review.story_package.display_format_recommendation
        submission.duplicate_candidates = [
            {"submission_id": candidate.submission_id, "score": candidate.score, "reasons": candidate.reasons}
            for candidate in review.duplicate_candidates
        ]
        submission.processing_errors.extend(error for error in extracted.errors if error not in submission.processing_errors)
        submission.story_slug = slugify(review.story_package.headline, fallback=submission.submission_id.lower())
        if review.recommended_next_step == "sensitive_content_review":
            submission.pipeline_status = "flagged"
        elif review.recommended_next_step == "technical_processing_needed":
            submission.pipeline_status = "needs_more_info"
        else:
            submission.pipeline_status = "classified"
        return submission

    def _deterministic_flags(
        self,
        submission: SubmissionRecord,
        extracted: ExtractedSubmission,
        duplicate_candidates: List[DuplicateCandidate],
    ) -> List[str]:
        flags: List[str] = []
        if any(media_type == "unsupported" for media_type in extracted.media_types):
            flags.append("unsupported_file_type")
        if any("Unsupported file type." in error for error in extracted.errors):
            flags.append("unsupported_file_type")
        if any(candidate.score >= 0.95 for candidate in duplicate_candidates):
            flags.append("exact_duplicate_hash")
        elif any(candidate.score >= 0.70 for candidate in duplicate_candidates):
            flags.append("possible_duplicate")
        if not extracted.combined_text.strip():
            flags.append("missing_usable_text")
        text = extracted.combined_text.lower()
        if any(keyword in text for keyword in ("copyright", "permission", "all rights reserved")):
            flags.append("copyright_or_permissions_concern")
        if any(keyword in text for keyword in ("legend says", "rumor", "unverified", "possibly true")):
            flags.append("historical_verification_needed")
        if self._contains_pii(text):
            flags.append("doxxing_or_private_information")
        for error in extracted.errors:
            if "unavailable" in error.lower() or "unsupported" in error.lower():
                flags.append("technical_processing_needed")
        if any(
            hash_value.endswith("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
            for hash_value in submission.source_hashes
        ):
            flags.append("empty_or_corrupt_file")
        return sorted(set(flags))

    def _contains_pii(self, text: str) -> bool:
        patterns = [
            r"\b\d{3}-\d{2}-\d{4}\b",
            r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",
            r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        ]
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    def _build_payload(
        self,
        submission: SubmissionRecord,
        extracted: ExtractedSubmission,
        duplicate_candidates: List[DuplicateCandidate],
        deterministic_flags: List[str],
    ) -> Dict[str, Any]:
        return {
            "submission_id": submission.submission_id,
            "source_path": submission.source_path,
            "original_filenames": submission.original_filenames,
            "contributor_name": submission.contributor_name,
            "contributor_contact": submission.contributor_contact,
            "rights_or_permission_status": submission.rights_or_permission_status,
            "media_types": extracted.media_types,
            "detected_language": extracted.detected_language,
            "combined_text": excerpt(extracted.combined_text, limit=6000),
            "extracted_text_length": len(extracted.combined_text),
            "notes_for_human_reviewer": submission.notes_for_human_reviewer,
            "duplicate_candidates": [
                {"submission_id": candidate.submission_id, "score": candidate.score, "reasons": candidate.reasons}
                for candidate in duplicate_candidates
            ],
            "deterministic_flags": deterministic_flags,
        }

    def _resolve_next_step(
        self,
        classification: Dict[str, Any],
        moderation: ModerationAssessment,
        duplicate_candidates: List[DuplicateCandidate],
        deterministic_flags: List[str],
    ) -> str:
        if any(candidate.score >= 0.95 for candidate in duplicate_candidates) or "exact_duplicate_hash" in deterministic_flags:
            return "possible_duplicate"
        if moderation.recommended_next_step == "sensitive_content_review":
            return "sensitive_content_review"
        if "unsupported_file_type" in deterministic_flags or "technical_processing_needed" in deterministic_flags:
            return "technical_processing_needed"
        if classification.get("project_relevance") == "unlikely_relevant":
            return "not_project_fit"
        return classification.get("recommended_next_step") or moderation.recommended_next_step or "ready_for_human_review"

    def _fit_assessment(
        self,
        classification: Dict[str, Any],
        moderation: ModerationAssessment,
        duplicate_candidates: List[DuplicateCandidate],
    ) -> str:
        payload = {
            "project_relevance": classification.get("project_relevance"),
            "risk_level": moderation.risk_level,
            "duplicate_candidates": [candidate.submission_id for candidate in duplicate_candidates],
            "summary": classification.get("notes_for_human_reviewer") or [],
        }
        return json.dumps(payload, ensure_ascii=True)

    def _prompt_text(self, filename: str) -> str:
        return (self.prompt_root / filename).read_text(encoding="utf-8")
