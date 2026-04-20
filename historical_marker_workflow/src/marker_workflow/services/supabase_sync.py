from __future__ import annotations

import copy
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..adapters.supabase_client import SupabaseClient
from ..config import AppConfig
from ..utils import isoformat_z, load_json, slugify
from .site_builder import SiteBuilder


class SupabaseSyncService:
    def __init__(
        self,
        config: AppConfig,
        site_builder: SiteBuilder,
        supabase_client: SupabaseClient,
    ) -> None:
        self.config = config
        self.site_builder = site_builder
        self.supabase_client = supabase_client

    def sync_public_stories(self, limit: Optional[int] = None) -> Dict[str, object]:
        build_result = self.site_builder.build(source_mode="airtable", limit=limit)
        payload = load_json(Path(build_result["data_path"]))
        stories = payload.get("stories") or []
        rewritten_stories: List[Dict[str, object]] = []
        uploaded_files = 0
        uploaded_urls: Dict[str, str] = {}

        for story in stories:
            story_payload = copy.deepcopy(story)
            response_qr, qr_uploads = self._rewrite_public_path(
                story_payload.get("response_qr"), uploaded_urls
            )
            story_payload["response_qr"] = response_qr
            media_assets, story_uploads = self._rewrite_media_assets(
                story_payload.get("media_assets") or [], uploaded_urls
            )
            story_payload["media_assets"] = media_assets
            uploaded_files += qr_uploads + story_uploads
            rewritten_stories.append(story_payload)

        story_slugs = {
            str(story.get("story_slug") or "").strip()
            for story in rewritten_stories
            if str(story.get("story_slug") or "").strip()
        }
        stories_by_slug = {
            str(story.get("story_slug") or "").strip(): story
            for story in rewritten_stories
            if str(story.get("story_slug") or "").strip()
        }

        submissions_synced = []
        submission_ids_by_airtable_id: Dict[str, str] = {}
        submission_ids_by_story_slug: Dict[str, str] = {}
        if story_slugs:
            submissions_synced = self._sync_submissions(
                story_slugs=story_slugs,
                stories_by_slug=stories_by_slug,
                limit=limit,
            )
            submission_ids_by_airtable_id = {
                str(row.get("airtable_id") or ""): str(row.get("id") or "")
                for row in submissions_synced
                if row.get("airtable_id") and row.get("id")
            }
            submission_ids_by_story_slug = {
                str(row.get("story_slug") or ""): str(row.get("id") or "")
                for row in submissions_synced
                if row.get("story_slug") and row.get("id")
            }

        responses_synced, unresolved_responses = self._sync_responses(submission_ids_by_airtable_id)

        synced_rows: List[Dict[str, object]] = []
        for story_payload in rewritten_stories:
            story_payload = copy.deepcopy(story_payload)
            story_payload["submission_record_id"] = submission_ids_by_story_slug.get(
                str(story_payload.get("story_slug") or "").strip()
            )
            synced_rows.append(
                {
                    "story_slug": story_payload.get("story_slug"),
                    "headline": story_payload.get("headline"),
                    "workflow_status": story_payload.get("workflow_status"),
                    "date_received": story_payload.get("date_received"),
                    "payload": story_payload,
                    "synced_at": isoformat_z(),
                }
            )

        response = self.supabase_client.upsert_stories(synced_rows)
        return {
            "source_mode": "airtable",
            "stories_built": len(stories),
            "stories_synced": len(synced_rows),
            "submissions_synced": len(submissions_synced),
            "responses_synced": responses_synced,
            "responses_skipped_unresolved": unresolved_responses,
            "uploaded_files": uploaded_files,
            "supabase_table": self.config.supabase_stories_table,
            "storage_bucket": self.config.supabase_storage_bucket,
            "upsert_response_count": len(response or []),
        }

    def _sync_submissions(
        self,
        *,
        story_slugs: set[str],
        stories_by_slug: Dict[str, Dict[str, object]],
        limit: Optional[int],
    ) -> List[Dict[str, object]]:
        del limit
        submissions = self.site_builder.airtable_client.list_all_records(self.config.airtable_submissions_table)

        rows: List[Dict[str, object]] = []
        for submission in submissions:
            fields = submission.get("fields", {})
            headline = self._text_value(fields.get("Story Title"))
            if not headline:
                continue

            story_slug = slugify(headline)
            if story_slug not in story_slugs:
                continue

            rows.append(
                {
                    "airtable_id": submission.get("id"),
                    "story_slug": story_slug,
                    "headline": headline,
                    "Response QR": stories_by_slug.get(story_slug, {}).get("response_qr"),
                    "Response Link": self._null_if_blank(fields.get("Response Link")),
                    "Avg Rating": self._numeric_value(fields.get("Avg Rating")),
                    "Number of Responses": self._integer_value(fields.get("Number of Responses")),
                    "Clicks": self._integer_value(fields.get("Clicks"), default=0),
                }
            )

        return self.supabase_client.upsert_submissions(rows)

    def _sync_responses(self, submission_ids_by_airtable_id: Dict[str, str]) -> Tuple[int, int]:
        if not submission_ids_by_airtable_id:
            return 0, 0

        records = self.site_builder.airtable_client.list_all_records(self.config.airtable_responses_table)
        rows: List[Dict[str, object]] = []
        unresolved = 0

        for record in records:
            fields = record.get("fields", {})
            linked_ids = fields.get("Submissions") or []
            submission_airtable_id = linked_ids[0] if isinstance(linked_ids, list) and linked_ids else None
            if not submission_airtable_id:
                print(
                    f"Warning: skipping response {record.get('id')} because it has no linked Submissions record."
                )
                unresolved += 1
                continue

            submission_id = submission_ids_by_airtable_id.get(str(submission_airtable_id))
            if not submission_id:
                print(
                    f"Warning: skipping response {record.get('id')} because linked submission {submission_airtable_id} was not resolved."
                )
                unresolved += 1
                continue

            rows.append(
                {
                    "airtable_id": record.get("id"),
                    "submission_id": submission_id,
                    "Response": self._null_if_blank(fields.get("Response")),
                    "Show response": self._checkbox_value(
                        fields.get("Show Response", fields.get("Show response"))
                    ),
                }
            )

        synced = self.supabase_client.upsert_responses(rows)
        return len(synced), unresolved

    def _rewrite_media_assets(
        self,
        assets: List[Dict[str, object]],
        uploaded_urls: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[Dict[str, object]], int]:
        rewritten: List[Dict[str, object]] = []
        uploaded_files = 0
        uploaded_urls = uploaded_urls or {}

        for asset in assets:
            public_asset = copy.deepcopy(asset)
            for key in ("url", "preview_url", "document_url"):
                rewritten_value, upload_count = self._rewrite_public_path(public_asset.get(key), uploaded_urls)
                public_asset[key] = rewritten_value
                uploaded_files += upload_count
            rewritten.append(public_asset)

        return rewritten, uploaded_files

    def _rewrite_public_path(
        self,
        value: object,
        uploaded_urls: Dict[str, str],
    ) -> Tuple[object, int]:
        if not isinstance(value, str) or not value or value.startswith("http://") or value.startswith("https://"):
            return value, 0

        local_path = (self.config.site_output_path / value).resolve()
        if not local_path.exists() or not local_path.is_file():
            return value, 0

        if value not in uploaded_urls:
            remote_path = self._remote_storage_path(value)
            content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
            uploaded_urls[value] = self.supabase_client.upload_public_file(
                local_path=local_path,
                remote_path=remote_path,
                content_type=content_type,
            )
            return uploaded_urls[value], 1

        return uploaded_urls[value], 0

    def _remote_storage_path(self, relative_path: str) -> str:
        cleaned = relative_path.strip().lstrip("./").lstrip("/")
        prefix = self.config.supabase_storage_prefix.strip().strip("/")
        return f"{prefix}/{cleaned}" if prefix else cleaned

    def _text_value(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts = [self._text_value(item) for item in value]
            return "\n".join(part for part in parts if part).strip()
        if isinstance(value, dict):
            for key in ("value", "text", "name", "label", "title"):
                nested = self._text_value(value.get(key))
                if nested:
                    return nested
            parts = [self._text_value(item) for item in value.values()]
            return "\n".join(part for part in parts if part).strip()
        return str(value).strip()

    def _null_if_blank(self, value: object) -> Optional[str]:
        text = self._text_value(value)
        return text or None

    def _first_attachment_url(self, value: object) -> Optional[str]:
        if not isinstance(value, list) or not value:
            return None
        first = value[0]
        if isinstance(first, dict) and first.get("url"):
            return str(first.get("url")).strip()
        return None

    def _integer_value(self, value: object, default: Optional[int] = None) -> Optional[int]:
        if value in (None, ""):
            return default
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default

    def _numeric_value(self, value: object) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _checkbox_value(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        return text in {"true", "yes", "1", "checked"}
