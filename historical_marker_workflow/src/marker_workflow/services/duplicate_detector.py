from __future__ import annotations

from typing import List

from ..models import DuplicateCandidate, ExtractedSubmission, SubmissionRecord
from ..utils import normalize_basename, token_overlap_score
from .audit import WorkflowStateStore


class DuplicateDetector:
    def __init__(self, state_store: WorkflowStateStore) -> None:
        self.state_store = state_store

    def find(self, submission: SubmissionRecord, extracted: ExtractedSubmission) -> List[DuplicateCandidate]:
        candidates: List[DuplicateCandidate] = []
        current_text = extracted.combined_text
        current_names = {normalize_basename(name) for name in submission.original_filenames}
        for snapshot in self.state_store.list_submission_snapshots():
            if snapshot.submission_id == submission.submission_id:
                continue
            score = 0.0
            reasons: List[str] = []
            exact_hashes = set(submission.source_hashes) & set(snapshot.source_hashes)
            if exact_hashes:
                score += 1.0
                reasons.append("Exact source hash match detected.")
            previous_names = {normalize_basename(name) for name in snapshot.filenames}
            if current_names & previous_names:
                score += 0.30
                reasons.append("Filename similarity overlap detected.")
            overlap = token_overlap_score(current_text, snapshot.text_preview)
            if overlap >= 0.50:
                score += 0.40
                reasons.append(f"Text overlap score {overlap:.2f} exceeded threshold.")
            elif overlap >= 0.25:
                score += 0.20
                reasons.append(f"Moderate text overlap score {overlap:.2f} detected.")
            score = min(score, 1.0)
            if score >= 0.50:
                candidates.append(DuplicateCandidate(submission_id=snapshot.submission_id, score=score, reasons=reasons))
        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates

