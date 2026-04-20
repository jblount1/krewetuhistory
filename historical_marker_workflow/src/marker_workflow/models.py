from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BoxItem:
    item_id: str
    name: str
    source_path: str
    parent_path: str
    created_at: str
    modified_at: str
    size_bytes: int
    extension: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    local_path: Optional[str] = None


@dataclass
class SubmissionGroup:
    group_id: str
    items: List[BoxItem]
    confidence: float
    rationale: List[str] = field(default_factory=list)


@dataclass
class FileExtraction:
    item_id: str
    original_name: str
    relative_path: str
    media_type: str
    extracted_text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None


@dataclass
class ExtractedSubmission:
    submission_id: str
    files: List[FileExtraction]
    combined_text: str
    media_types: List[str]
    detected_language: str
    errors: List[str] = field(default_factory=list)


@dataclass
class DuplicateCandidate:
    submission_id: str
    score: float
    reasons: List[str]


@dataclass
class ModerationAssessment:
    flags: List[str]
    risk_level: str
    rationale: str
    recommended_next_step: str


@dataclass
class StoryPackage:
    headline: str
    summary_50: str
    narrative_120_180: str
    associated_media_assets: List[str]
    suggested_image_caption_placeholders: List[str]
    suggested_credits_line: str
    questions_or_gaps: List[str]
    display_format_recommendation: str
    themes: List[str] = field(default_factory=list)
    community_labels: List[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    classification: Dict[str, Any]
    moderation: ModerationAssessment
    story_package: StoryPackage
    deterministic_flags: List[str]
    duplicate_candidates: List[DuplicateCandidate]
    fit_assessment: str
    recommended_queue: str
    recommended_next_step: str


@dataclass
class SubmissionRecord:
    submission_id: str
    date_received: str
    source_path: str
    original_filenames: List[str]
    contributor_name: Optional[str] = None
    contributor_contact: Optional[str] = None
    community_label: Optional[str] = None
    geographic_label: Optional[str] = None
    tulane_connection: Optional[str] = None
    story_title: Optional[str] = None
    story_summary: Optional[str] = None
    story_type: Optional[str] = None
    story_theme: Optional[str] = None
    media_types: List[str] = field(default_factory=list)
    detected_language: Optional[str] = None
    rights_or_permission_status: Optional[str] = None
    completeness_status: Optional[str] = None
    review_status: Optional[str] = None
    public_display_risk_level: Optional[str] = None
    moderation_flags: List[str] = field(default_factory=list)
    recommended_next_step: Optional[str] = None
    notes_for_human_reviewer: List[str] = field(default_factory=list)
    pipeline_status: str = "received"
    grouping_confidence: float = 0.0
    duplicate_candidates: List[Dict[str, Any]] = field(default_factory=list)
    box_file_ids: List[str] = field(default_factory=list)
    source_hashes: List[str] = field(default_factory=list)
    processing_errors: List[str] = field(default_factory=list)
    project_relevance: Optional[str] = None
    display_format_recommendation: Optional[str] = None
    story_slug: Optional[str] = None
    canonical_package_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ArtifactBundle:
    canonical_package_path: str
    submission_record_path: str
    moderation_record_path: str
    review_markdown_path: str
    story_package_json_path: str
    story_package_markdown_path: str
    review_packet_path: Optional[str] = None
    manifest_path: Optional[str] = None

    def all_paths(self) -> List[str]:
        paths = [
            self.submission_record_path,
            self.moderation_record_path,
            self.review_markdown_path,
            self.story_package_json_path,
            self.story_package_markdown_path,
        ]
        if self.review_packet_path:
            paths.append(self.review_packet_path)
        if self.manifest_path:
            paths.append(self.manifest_path)
        return paths


@dataclass
class AuditEvent:
    timestamp: str
    run_id: str
    action: str
    submission_id: Optional[str] = None
    box_file_ids: List[str] = field(default_factory=list)
    source_path: Optional[str] = None
    destination_path: Optional[str] = None
    classification_decisions: Dict[str, Any] = field(default_factory=dict)
    flags_raised: List[str] = field(default_factory=list)
    artifacts_created: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    operator: str = "system"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunContext:
    run_id: str
    started_at: str
    log_path: str


@dataclass
class SubmissionSnapshot:
    submission_id: str
    review_status: str
    pipeline_status: str
    community_label: Optional[str]
    story_slug: Optional[str]
    canonical_package_path: str
    text_preview: str
    filenames: List[str]
    source_hashes: List[str]
    updated_at: str
