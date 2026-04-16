from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from marker_workflow.adapters.airtable_client import AirtableClient
from marker_workflow.config import AppConfig

from support import build_config


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class AirtableClientTests(unittest.TestCase):
    def test_test_connection_returns_summary_and_uses_bearer_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            base_config = build_config(workspace)
            config = AppConfig.from_env(
                env={
                    "BOX_ROOT_PATH": str(base_config.box_root_path),
                    "LOCAL_WORKDIR": str(base_config.local_workdir),
                    "SQLITE_PATH": str(base_config.sqlite_path),
                    "AIRTABLE_PERSONAL_ACCESS_TOKEN": "pat_test_token",
                    "AIRTABLE_BASE_ID": "appBase123",
                    "AIRTABLE_TABLE_NAME": "Story Intake",
                    "AIRTABLE_VIEW": "Published",
                },
                cwd=workspace,
            )

            captured: dict[str, object] = {}

            def fake_opener(request, timeout=None):
                captured["url"] = request.full_url
                captured["authorization"] = request.get_header("Authorization")
                captured["timeout"] = timeout
                return _FakeResponse({"records": [{"id": "rec123", "fields": {"Title": "Story"}}]})

            result = AirtableClient(config, opener=fake_opener).test_connection(max_records=2)

            self.assertTrue(result["connected"])
            self.assertEqual(result["retrieved_records"], 1)
            self.assertEqual(result["sample_record_ids"], ["rec123"])
            self.assertEqual(captured["authorization"], "Bearer pat_test_token")
            self.assertEqual(captured["timeout"], 20)
            self.assertIn("pageSize=2", str(captured["url"]))
            self.assertIn("view=Published", str(captured["url"]))
            self.assertIn("Story%20Intake", str(captured["url"]))

    def test_test_connection_lists_tables_when_table_name_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            base_config = build_config(workspace)
            config = AppConfig.from_env(
                env={
                    "BOX_ROOT_PATH": str(base_config.box_root_path),
                    "LOCAL_WORKDIR": str(base_config.local_workdir),
                    "SQLITE_PATH": str(base_config.sqlite_path),
                    "AIRTABLE_PERSONAL_ACCESS_TOKEN": "pat_test_token",
                    "AIRTABLE_URL": "https://airtable.com/appFG4KHwFm3LCbia/shrGuURTF8fy1tCtjv",
                },
                cwd=workspace,
            )

            captured: dict[str, object] = {}

            def fake_opener(request, timeout=None):
                captured["url"] = request.full_url
                return _FakeResponse({"tables": [{"id": "tbl123", "name": "Submissions"}]})

            result = AirtableClient(config, opener=fake_opener).test_connection(max_records=2)

            self.assertTrue(result["connected"])
            self.assertEqual(result["base_id"], "appFG4KHwFm3LCbia")
            self.assertEqual(result["shared_view_id"], "shrGuURTF8fy1tCtjv")
            self.assertEqual(result["available_tables"], [{"id": "tbl123", "name": "Submissions"}])
            self.assertIn("/meta/bases/appFG4KHwFm3LCbia/tables", str(captured["url"]))

    def test_missing_airtable_configuration_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)

            with self.assertRaisesRegex(ValueError, "AIRTABLE_PERSONAL_ACCESS_TOKEN"):
                AirtableClient(config).test_connection()

    def test_update_record_uses_patch_and_returns_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            base_config = build_config(workspace)
            config = AppConfig.from_env(
                env={
                    "BOX_ROOT_PATH": str(base_config.box_root_path),
                    "LOCAL_WORKDIR": str(base_config.local_workdir),
                    "SQLITE_PATH": str(base_config.sqlite_path),
                    "AIRTABLE_PERSONAL_ACCESS_TOKEN": "pat_test_token",
                    "AIRTABLE_BASE_ID": "appBase123",
                },
                cwd=workspace,
            )

            captured: dict[str, object] = {}

            def fake_opener(request, timeout=None):
                captured["url"] = request.full_url
                captured["authorization"] = request.get_header("Authorization")
                captured["method"] = request.get_method()
                captured["body"] = json.loads(request.data.decode("utf-8"))
                captured["timeout"] = timeout
                return _FakeResponse({"id": "rec123", "fields": {"Workflow Status": "Under Human Review"}})

            result = AirtableClient(config, opener=fake_opener).update_record(
                "Submissions",
                "rec123",
                {"Workflow Status": "Under Human Review"},
            )

            self.assertEqual(result["id"], "rec123")
            self.assertEqual(captured["authorization"], "Bearer pat_test_token")
            self.assertEqual(captured["method"], "PATCH")
            self.assertEqual(captured["body"], {"fields": {"Workflow Status": "Under Human Review"}})
            self.assertIn("/appBase123/Submissions/rec123", str(captured["url"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
