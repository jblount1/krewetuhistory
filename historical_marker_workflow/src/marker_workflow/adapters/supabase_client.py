from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ..config import AppConfig


class SupabaseClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def ensure_configured(self) -> None:
        missing = []
        if not self.config.supabase_url:
            missing.append("SUPABASE_URL")
        if not self.config.supabase_service_role_key:
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Supabase connection is not configured. Missing: {joined}")

    def upsert_stories(self, stories: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
        return self.upsert_rows(
            table_name=self.config.supabase_stories_table,
            rows=stories,
            conflict_key="story_slug",
            select="story_slug,headline,workflow_status,date_received,payload,synced_at",
        )

    def upsert_submissions(self, submissions: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
        return self.upsert_rows(
            table_name=self.config.supabase_submissions_table,
            rows=submissions,
            conflict_key="airtable_id",
            select='id,airtable_id,story_slug,headline,"Response QR","Response Link","Avg Rating","Number of Responses","Clicks"',
        )

    def upsert_responses(self, responses: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
        return self.upsert_rows(
            table_name=self.config.supabase_responses_table,
            rows=responses,
            conflict_key="airtable_id",
            select='id,submission_id,"Response","Show response",airtable_id',
        )

    def upsert_rows(
        self,
        *,
        table_name: str,
        rows: Iterable[Dict[str, object]],
        conflict_key: str,
        select: str = "*",
    ) -> List[Dict[str, object]]:
        self.ensure_configured()
        payload_rows = list(rows)
        if not payload_rows:
            return []
        payload = json.dumps(payload_rows, ensure_ascii=True).encode("utf-8")
        endpoint = self._rest_endpoint(
            f"{table_name}?on_conflict={quote(conflict_key, safe='')}",
            select=select,
        )
        request = Request(
            endpoint,
            data=payload,
            method="POST",
            headers={
                **self._auth_headers(),
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=representation",
            },
        )
        response = self._request_json(request)
        return response if isinstance(response, list) else []

    def list_submission_clicks(self) -> List[Dict[str, object]]:
        self.ensure_configured()
        endpoint = self._rest_endpoint(
            self.config.supabase_submissions_table,
            select='id,airtable_id,"Clicks"',
        )
        request = Request(
            endpoint,
            headers=self._auth_headers(),
            method="GET",
        )
        response = self._request_json(request)
        return response if isinstance(response, list) else []

    def upload_public_file(self, local_path: Path, remote_path: str, content_type: str) -> str:
        self.ensure_configured()
        bucket = quote(self.config.supabase_storage_bucket, safe="")
        object_path = quote(remote_path.strip("/"), safe="/")
        endpoint = f"{self.config.supabase_url}/storage/v1/object/{bucket}/{object_path}"
        request = Request(
            endpoint,
            data=local_path.read_bytes(),
            method="POST",
            headers={
                **self._auth_headers(),
                "Content-Type": content_type,
                "x-upsert": "true",
            },
        )
        self._request_json(request, allow_empty=True)
        return self.public_storage_url(remote_path)

    def public_storage_url(self, remote_path: str) -> str:
        bucket = quote(self.config.supabase_storage_bucket, safe="")
        object_path = quote(remote_path.strip("/"), safe="/")
        return f"{self.config.supabase_url}/storage/v1/object/public/{bucket}/{object_path}"

    def _rest_endpoint(self, resource: str, *, select: str = "*") -> str:
        encoded_select = quote(select, safe='*()," ')
        encoded_select = encoded_select.replace(" ", "%20")
        if "?" in resource:
            return f"{self.config.supabase_url}/rest/v1/{resource}&select={encoded_select}"
        return f"{self.config.supabase_url}/rest/v1/{resource}?select={encoded_select}"

    def _auth_headers(self) -> Dict[str, str]:
        token = self.config.supabase_service_role_key or ""
        schema = self.config.supabase_schema
        return {
            "apikey": token,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Accept-Profile": schema,
            "Content-Profile": schema,
        }

    def _request_json(self, request: Request, allow_empty: bool = False) -> Optional[object]:
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Supabase request failed with HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"Unable to reach Supabase: {error.reason}") from error

        if not raw:
            return {} if allow_empty else None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("Supabase returned invalid JSON.") from error
