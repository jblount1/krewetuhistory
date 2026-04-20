from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from marker_workflow.services.airtable_click_sync import AirtableClickSyncService

from support import build_config


class FakeAirtableClient:
    def __init__(self, records):
        self.records = list(records)
        self.updates = []

    def list_all_records(self, table_name: str, **_: object):
        del table_name
        return list(self.records)

    def update_record(self, table_name: str, record_id: str, fields: dict):
        self.updates.append(
            {
                "table_name": table_name,
                "record_id": record_id,
                "fields": dict(fields),
            }
        )
        return {"id": record_id, "fields": fields}


class FakeSupabaseClient:
    def __init__(self, rows):
        self.rows = list(rows)

    def list_submission_clicks(self):
        return list(self.rows)


class AirtableClickSyncTests(unittest.TestCase):
    def test_sync_clicks_updates_only_changed_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_config(Path(temp_dir))
            airtable_client = FakeAirtableClient(
                [
                    {"id": "rec1", "fields": {"Clicks": 1}},
                    {"id": "rec2", "fields": {"Clicks": 7}},
                ]
            )
            supabase_client = FakeSupabaseClient(
                [
                    {"airtable_id": "rec1", "Clicks": 5},
                    {"airtable_id": "rec2", "Clicks": 7},
                    {"airtable_id": "rec-missing", "Clicks": 9},
                ]
            )

            result = AirtableClickSyncService(
                config=config,
                airtable_client=airtable_client,
                supabase_client=supabase_client,
            ).sync_clicks()

            self.assertEqual(result["submissions_seen"], 3)
            self.assertEqual(result["records_updated"], 1)
            self.assertEqual(result["records_unchanged"], 1)
            self.assertEqual(result["records_skipped_missing_airtable"], 1)
            self.assertEqual(
                airtable_client.updates,
                [
                    {
                        "table_name": "Submissions",
                        "record_id": "rec1",
                        "fields": {"Clicks": 5},
                    }
                ],
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
