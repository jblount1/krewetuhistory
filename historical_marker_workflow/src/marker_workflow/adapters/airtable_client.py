from __future__ import annotations

import json
from typing import Any, Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ..config import AppConfig


class AirtableClient:
    def __init__(
        self,
        config: AppConfig,
        opener: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.config = config
        self.opener = opener or urlopen

    def ensure_configured(self, *, require_table: bool = True) -> None:
        missing = []
        if not self.config.airtable_api_key:
            missing.append("AIRTABLE_PERSONAL_ACCESS_TOKEN")
        if not self.config.airtable_base_id:
            missing.append("AIRTABLE_BASE_ID or AIRTABLE_URL")
        if require_table and not self.config.airtable_table_name:
            missing.append("AIRTABLE_TABLE_NAME")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Airtable connection is not configured. Missing: {joined}")

    def list_records(self, max_records: int = 3, view: Optional[str] = None) -> list[dict[str, Any]]:
        self.ensure_configured(require_table=True)
        payload = self._list_table_payload(
            table_name=self.config.airtable_table_name,
            max_records=max_records,
            view=view or self.config.airtable_view,
        )
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError("Unexpected Airtable response: 'records' was not a list.")
        return records

    def list_all_records(
        self,
        table_name: str,
        *,
        view: Optional[str] = None,
        max_records: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        self.ensure_configured(require_table=False)
        if not table_name:
            raise ValueError("Airtable table name is required.")
        records: list[dict[str, Any]] = []
        offset: Optional[str] = None
        while True:
            page_limit = 100 if max_records is None else max(1, min(max_records - len(records), 100))
            payload = self._list_table_payload(
                table_name=table_name,
                max_records=page_limit,
                view=view,
                offset=offset,
            )
            batch = payload.get("records")
            if not isinstance(batch, list):
                raise ValueError("Unexpected Airtable response: 'records' was not a list.")
            records.extend(batch)
            offset = payload.get("offset")
            if not offset or (max_records is not None and len(records) >= max_records):
                break
        return records[:max_records] if max_records is not None else records

    def get_base_schema(self) -> list[dict[str, Any]]:
        self.ensure_configured(require_table=False)
        base_id = quote(self.config.airtable_base_id or "", safe="")
        url = f"{self.config.airtable_base_url}/meta/bases/{base_id}/tables"
        payload = self._request_json(url)
        tables = payload.get("tables")
        if not isinstance(tables, list):
            raise ValueError("Unexpected Airtable response: 'tables' was not a list.")
        return tables

    def test_connection(self, max_records: int = 3) -> dict[str, Any]:
        summary = {
            "connected": True,
            "base_id": self.config.airtable_base_id,
            "table_name": self.config.airtable_table_name,
            "view": self.config.airtable_view,
            "airtable_url": self.config.airtable_url,
            "shared_view_id": self.config.airtable_share_id,
        }
        if self.config.airtable_table_name:
            records = self.list_records(max_records=max_records)
            summary["retrieved_records"] = len(records)
            summary["sample_record_ids"] = [record.get("id") for record in records[:3] if record.get("id")]
        else:
            tables = self.get_base_schema()
            summary["retrieved_records"] = 0
            summary["available_tables"] = [
                {"id": table.get("id"), "name": table.get("name")}
                for table in tables[:10]
                if isinstance(table, dict)
            ]
        return summary

    def update_record(self, table_name: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.ensure_configured(require_table=False)
        if not table_name:
            raise ValueError("Airtable table name is required.")
        if not record_id:
            raise ValueError("Airtable record id is required.")
        base_id = quote(self.config.airtable_base_id or "", safe="")
        encoded_table_name = quote(table_name, safe="")
        encoded_record_id = quote(record_id, safe="")
        url = f"{self.config.airtable_base_url}/{base_id}/{encoded_table_name}/{encoded_record_id}"
        payload = self._request_json(url, method="PATCH", data={"fields": fields})
        if not isinstance(payload, dict):
            raise ValueError("Unexpected Airtable update response payload.")
        return payload

    def _list_table_payload(
        self,
        *,
        table_name: Optional[str],
        max_records: int,
        view: Optional[str] = None,
        offset: Optional[str] = None,
    ) -> dict[str, Any]:
        if not table_name:
            raise ValueError("Airtable table name is required.")
        page_size = max(1, min(max_records, 100))
        params = {"pageSize": page_size}
        if view:
            params["view"] = view
        if offset:
            params["offset"] = offset
        base_id = quote(self.config.airtable_base_id or "", safe="")
        encoded_table_name = quote(table_name, safe="")
        url = f"{self.config.airtable_base_url}/{base_id}/{encoded_table_name}?{urlencode(params)}"
        return self._request_json(url)

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        body = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {
            "Authorization": f"Bearer {self.config.airtable_api_key}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener(request, timeout=self.config.airtable_timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Airtable request failed with HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise RuntimeError(f"Unable to reach Airtable: {error.reason}") from error

        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise ValueError("Airtable returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise ValueError("Unexpected Airtable response payload.")
        return payload
