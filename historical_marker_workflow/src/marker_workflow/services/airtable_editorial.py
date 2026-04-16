from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Dict, Optional

from ..adapters.ai_client import AIClient
from ..adapters.airtable_client import AirtableClient
from ..adapters.box_client import FilesystemBoxClient
from ..adapters.extractor_registry import ExtractorRegistry
from ..config import AppConfig
from ..utils import ensure_directory, excerpt, slugify


class AirtableEditorialWorkflow:
    HANDLED_WORKFLOW_STATUSES = {
        "ai rejected",
        "under ai review",
        "under human review",
        "approved and published",
    }
    ELIGIBLE_AI_REVIEW_STATUSES = {"", "waiting"}

    def __init__(
        self,
        config: AppConfig,
        box_client: FilesystemBoxClient,
        airtable_client: AirtableClient,
        ai_client: AIClient,
        extractor_registry: ExtractorRegistry,
        downloader: Optional[Callable[[str], bytes]] = None,
    ) -> None:
        self.config = config
        self.box_client = box_client
        self.airtable_client = airtable_client
        self.ai_client = ai_client
        self.extractor_registry = extractor_registry
        self.downloader = downloader or self._download_bytes
        self.prompt_root = Path(__file__).resolve().parent.parent / "prompts"

    def process_pending(self, limit: Optional[int] = None) -> Dict[str, int]:
        submissions = self.airtable_client.list_all_records(self.config.airtable_submissions_table)
        eligible = [record for record in submissions if self._is_eligible(record)]
        if limit is not None:
            eligible = eligible[:limit]

        stats = {
            "submissions_scanned": len(submissions),
            "eligible_submissions": len(eligible),
            "processed_submissions": 0,
            "rejected_submissions": 0,
            "queued_for_human_review": 0,
            "errors": 0,
        }

        for record in eligible:
            try:
                outcome = self._process_record(record)
            except Exception:
                stats["errors"] += 1
                continue
            stats["processed_submissions"] += 1
            if outcome == "rejected":
                stats["rejected_submissions"] += 1
            elif outcome == "under_human_review":
                stats["queued_for_human_review"] += 1
        return stats

    def _is_eligible(self, record: dict) -> bool:
        fields = record.get("fields", {})
        has_dossier = bool(fields.get("Story Dossier Doc") or [])
        ai_review_status = self._normalized_status(fields.get("AI Review Status"))
        workflow_status = self._normalized_status(fields.get("Workflow Status"))
        return (
            has_dossier
            and ai_review_status in self.ELIGIBLE_AI_REVIEW_STATUSES
            and workflow_status not in self.HANDLED_WORKFLOW_STATUSES
        )

    def _process_record(self, record: dict) -> str:
        record_id = record.get("id") or ""
        fields = record.get("fields", {})
        submission_id = self._submission_id(fields, record_id)
        dossier = self._pick_dossier_attachment(fields)
        dossier_text = self._extract_dossier_text(record_id, dossier) if dossier else ""
        context_connections = self._context_connections(fields)
        payload = {
            "submission_id": submission_id,
            "story_title": fields.get("Story Title") or "",
            "theme": fields.get("Theme") or "",
            "keywords": self._list_value(fields.get("Keywords")),
            "summary": fields.get("Summary") or "",
            "narrative": fields.get("Narrative") or "",
            "context_connections": context_connections,
            "references": self._references_text(fields.get("References")),
            "dossier_text": excerpt(dossier_text, limit=8000),
        }

        review = self.ai_client.review_story_dossier(self._prompt_text("review_dossier.txt"), payload)
        notes = (review.get("ai_notes") or "AI review did not return a reason.").strip()
        if review.get("decision") != "pass":
            self.airtable_client.update_record(
                self.config.airtable_submissions_table,
                record_id,
                {
                    "Workflow Status": "AI Rejected",
                    "AI Notes": notes,
                },
            )
            return "rejected"

        self.airtable_client.update_record(
            self.config.airtable_submissions_table,
            record_id,
            {
                "Workflow Status": "Under Human Review",
                "AI Notes": "",
            },
        )
        return "under_human_review"

    def _pick_dossier_attachment(self, fields: dict) -> Optional[dict]:
        attachments = fields.get("Story Dossier Doc") or []
        if not attachments:
            return None
        preferred = sorted(
            attachments,
            key=lambda item: (
                0 if str(item.get("filename") or "").lower().endswith(".pdf") else 1,
                str(item.get("filename") or "").lower(),
            ),
        )
        return preferred[0]

    def _extract_dossier_text(self, record_id: str, attachment: dict) -> str:
        attachment_url = attachment.get("url")
        filename = attachment.get("filename") or "story-dossier"
        if not attachment_url:
            return ""
        tmp_root = ensure_directory(self.config.local_workdir / "tmp")
        with TemporaryDirectory(dir=tmp_root) as temp_dir:
            local_path = Path(temp_dir) / Path(filename).name
            local_path.write_bytes(self.downloader(attachment_url))
            extraction = self.extractor_registry.extract(
                local_path,
                item_id=record_id,
                relative_path=local_path.name,
            )
            return extraction.extracted_text or ""

    def _context_connections(self, fields: dict) -> str:
        explicit = (fields.get("Context and Connections") or "").strip()
        if explicit:
            return explicit
        parts = []
        if fields.get("New Orleans Connection"):
            parts.append(f"New Orleans: {fields.get('New Orleans Connection')}")
        if fields.get("Tulane Connection"):
            parts.append(f"Tulane: {fields.get('Tulane Connection')}")
        if fields.get("Global Community Connection"):
            parts.append(f"Global: {fields.get('Global Community Connection')}")
        return " ".join(parts)

    def _references_text(self, value: object) -> str:
        if isinstance(value, list):
            return "\n".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    def _submission_id(self, fields: dict, record_id: str) -> str:
        value = str(fields.get("Submission ID") or "").strip()
        if value:
            return value
        title = str(fields.get("Story Title") or "").strip()
        if title:
            return slugify(title)
        return record_id or "submission"

    def _list_value(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [part.strip() for part in value.split(",") if part.strip()]
        return []

    def _normalized_status(self, value: object) -> str:
        return str(value or "").strip().lower()

    def _prompt_text(self, filename: str) -> str:
        return (self.prompt_root / filename).read_text(encoding="utf-8")

    def _download_bytes(self, remote_url: str) -> bytes:
        request = urllib.request.Request(remote_url, headers={"User-Agent": "historical-marker-workflow/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=self.config.airtable_timeout_seconds) as response:
                return response.read()
        except urllib.error.URLError as error:
            raise RuntimeError(f"Unable to download Airtable attachment: {error.reason}") from error
