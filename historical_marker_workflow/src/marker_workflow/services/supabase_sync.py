from __future__ import annotations

import copy
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..adapters.supabase_client import SupabaseClient
from ..config import AppConfig
from ..utils import isoformat_z, load_json
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

        synced_rows: List[Dict[str, object]] = []
        uploaded_files = 0
        for story in stories:
            story_payload = copy.deepcopy(story)
            media_assets, story_uploads = self._rewrite_media_assets(story_payload.get("media_assets") or [])
            story_payload["media_assets"] = media_assets
            uploaded_files += story_uploads
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
            "uploaded_files": uploaded_files,
            "supabase_table": self.config.supabase_stories_table,
            "storage_bucket": self.config.supabase_storage_bucket,
            "upsert_response_count": len(response or []),
        }

    def _rewrite_media_assets(self, assets: List[Dict[str, object]]) -> Tuple[List[Dict[str, object]], int]:
        rewritten: List[Dict[str, object]] = []
        uploaded_files = 0
        uploaded_urls: Dict[str, str] = {}

        for asset in assets:
            public_asset = copy.deepcopy(asset)
            for key in ("url", "preview_url", "document_url"):
                value = public_asset.get(key)
                if not isinstance(value, str) or not value or value.startswith("http://") or value.startswith("https://"):
                    continue
                local_path = (self.config.site_output_path / value).resolve()
                if not local_path.exists() or not local_path.is_file():
                    continue
                if value not in uploaded_urls:
                    remote_path = self._remote_storage_path(value)
                    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
                    uploaded_urls[value] = self.supabase_client.upload_public_file(
                        local_path=local_path,
                        remote_path=remote_path,
                        content_type=content_type,
                    )
                    uploaded_files += 1
                public_asset[key] = uploaded_urls[value]
            rewritten.append(public_asset)

        return rewritten, uploaded_files

    def _remote_storage_path(self, relative_path: str) -> str:
        cleaned = relative_path.lstrip("./").lstrip("/")
        prefix = self.config.supabase_storage_prefix.strip("/")
        return f"{prefix}/{cleaned}" if prefix else cleaned
