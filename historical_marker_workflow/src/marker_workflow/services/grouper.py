from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import List, Sequence, Tuple

from ..config import AppConfig
from ..models import BoxItem, SubmissionGroup
from ..utils import normalize_basename


class SubmissionGrouper:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def build(self, items: Sequence[BoxItem]) -> List[SubmissionGroup]:
        grouped: List[SubmissionGroup] = []
        folder_buckets = {}
        root_items: List[BoxItem] = []
        intake_root = self.config.box_intake_folder
        for item in items:
            if item.parent_path != intake_root:
                folder_buckets.setdefault(item.parent_path, []).append(item)
            else:
                root_items.append(item)

        for parent_path, bucket in sorted(folder_buckets.items()):
            grouped.append(
                SubmissionGroup(
                    group_id=f"group-{len(grouped) + 1}",
                    items=sorted(bucket, key=lambda value: (value.created_at, value.name)),
                    confidence=1.0,
                    rationale=[f"Grouped by shared intake subfolder: {parent_path}"],
                )
            )

        root_groups: List[SubmissionGroup] = []
        for item in sorted(root_items, key=lambda value: (value.created_at, value.name)):
            best_index = -1
            best_score = 0.0
            best_reasons: List[str] = []
            for index, group in enumerate(root_groups):
                score, reasons = self._score_candidate(item, group.items)
                if score > best_score:
                    best_index = index
                    best_score = score
                    best_reasons = reasons
            if best_index >= 0 and best_score >= 0.80:
                existing = root_groups[best_index]
                updated = replace(
                    existing,
                    items=existing.items + [item],
                    confidence=min(existing.confidence, best_score),
                    rationale=existing.rationale + best_reasons,
                )
                root_groups[best_index] = updated
            else:
                root_groups.append(
                    SubmissionGroup(
                        group_id=f"group-{len(grouped) + len(root_groups) + 1}",
                        items=[item],
                        confidence=0.50,
                        rationale=["No high-confidence grouping match found; kept separate."],
                    )
                )
        grouped.extend(root_groups)
        return grouped

    def _score_candidate(self, item: BoxItem, existing_items: Sequence[BoxItem]) -> Tuple[float, List[str]]:
        anchor = existing_items[0]
        reasons: List[str] = []
        score = 0.0
        if normalize_basename(item.name) == normalize_basename(anchor.name):
            if item.parent_path == anchor.parent_path and self._within_minutes(item.created_at, anchor.created_at, 30):
                score = 0.85
                reasons.append("Matched normalized basename and intake timing within 30 minutes.")
        contributor_name = item.metadata.get("contributor_name")
        anchor_contributor = anchor.metadata.get("contributor_name")
        if contributor_name and anchor_contributor and contributor_name == anchor_contributor:
            if self._within_minutes(item.created_at, anchor.created_at, 120):
                score = max(score, 0.80)
                reasons.append("Matched contributor metadata within 2 hours.")
        return score, reasons

    def _within_minutes(self, left: str, right: str, minutes: int) -> bool:
        return abs(self._parse(left) - self._parse(right)).total_seconds() <= minutes * 60

    def _parse(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

