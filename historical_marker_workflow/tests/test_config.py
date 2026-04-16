from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from marker_workflow.config import AppConfig


class AppConfigTests(unittest.TestCase):
    def test_reads_airtable_env_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = AppConfig.from_env(
                env={
                    "AIRTABLE_PERSONAL_ACCESS_TOKEN": "pat_token",
                    "AIRTABLE_BASE_ID": "app123",
                    "AIRTABLE_TABLE_NAME": "Table 1",
                    "AIRTABLE_VIEW": "Grid view",
                    "AIRTABLE_TIMEOUT_SECONDS": "45",
                },
                cwd=workspace,
            )

            self.assertEqual(config.airtable_api_key, "pat_token")
            self.assertEqual(config.airtable_base_id, "app123")
            self.assertEqual(config.airtable_table_name, "Table 1")
            self.assertEqual(config.airtable_view, "Grid view")
            self.assertEqual(config.airtable_timeout_seconds, 45)

    def test_accepts_legacy_airtable_api_key_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = AppConfig.from_env(
                env={"AIRTABLE_API_KEY": "legacy_key"},
                cwd=workspace,
            )

            self.assertEqual(config.airtable_api_key, "legacy_key")

    def test_extracts_base_and_share_ids_from_airtable_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = AppConfig.from_env(
                env={"AIRTABLE_URL": "https://airtable.com/appFG4KHwFm3LCbia/shrGuURTF8fy1tCtjv"},
                cwd=workspace,
            )

            self.assertEqual(config.airtable_base_id, "appFG4KHwFm3LCbia")
            self.assertEqual(config.airtable_share_id, "shrGuURTF8fy1tCtjv")

    def test_loads_values_from_local_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".env").write_text(
                "AIRTABLE_URL=https://airtable.com/appFG4KHwFm3LCbia/shrGuURTF8fy1tCtjv\n",
                encoding="utf-8",
            )
            config = AppConfig.from_env(env={}, cwd=workspace)

            self.assertEqual(config.airtable_base_id, "appFG4KHwFm3LCbia")
            self.assertEqual(config.airtable_share_id, "shrGuURTF8fy1tCtjv")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
