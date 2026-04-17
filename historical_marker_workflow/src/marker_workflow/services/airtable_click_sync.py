from __future__ import annotations

from typing import Dict, List

from ..adapters.airtable_client import AirtableClient
from ..adapters.supabase_client import SupabaseClient
from ..config import AppConfig


class AirtableClickSyncService:
    def __init__(
        self,
        config: AppConfig,
        airtable_client: AirtableClient,
        supabase_client: SupabaseClient,
    ) -> None:
        self.config = config
        self.airtable_client = airtable_client
        self.supabase_client = supabase_client

    def sync_clicks(self) -> Dict[str, object]:
        airtable_records = self.airtable_client.list_all_records(self.config.airtable_submissions_table)
        airtable_clicks_by_id = {
            str(record.get("id") or ""): self._integer_value(record.get("fields", {}).get("Clicks"), default=0)
            for record in airtable_records
            if record.get("id")
        }

        supabase_rows = self.supabase_client.list_submission_clicks()
        updates = 0
        skipped_missing = 0
        unchanged = 0

        for row in supabase_rows:
            airtable_id = str(row.get("airtable_id") or "").strip()
            if not airtable_id:
                skipped_missing += 1
                continue

            supabase_clicks = self._integer_value(row.get("Clicks"), default=0)
            airtable_clicks = airtable_clicks_by_id.get(airtable_id)
            if airtable_clicks is None:
                skipped_missing += 1
                continue

            if airtable_clicks == supabase_clicks:
                unchanged += 1
                continue

            self.airtable_client.update_record(
                self.config.airtable_submissions_table,
                airtable_id,
                {"Clicks": supabase_clicks},
            )
            updates += 1

        return {
            "submissions_seen": len(supabase_rows),
            "records_updated": updates,
            "records_unchanged": unchanged,
            "records_skipped_missing_airtable": skipped_missing,
        }

    def _integer_value(self, value: object, default: int = 0) -> int:
        if value in (None, ""):
            return default
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return default
