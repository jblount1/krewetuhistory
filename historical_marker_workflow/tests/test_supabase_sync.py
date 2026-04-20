from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from marker_workflow.adapters.box_client import FilesystemBoxClient
from marker_workflow.services.site_builder import SiteBuilder
from marker_workflow.services.supabase_sync import SupabaseSyncService

from support import build_config
from test_site_builder import FakeAirtableClient


class FakeSupabaseClient:
    def __init__(self) -> None:
        self.uploads = []
        self.story_rows = []
        self.submission_rows = []
        self.response_rows = []

    def upload_public_file(self, *, local_path: Path, remote_path: str, content_type: str) -> str:
        self.uploads.append(
            {
                "local_path": str(local_path),
                "remote_path": remote_path,
                "content_type": content_type,
            }
        )
        return f"https://supabase.example/storage/v1/object/public/stories-public/{remote_path}"

    def upsert_stories(self, stories):
        self.story_rows = list(stories)
        return self.story_rows

    def upsert_submissions(self, submissions):
        self.submission_rows = []
        for index, row in enumerate(submissions, start=1):
            payload = dict(row)
            payload["id"] = f"submission-{index}"
            self.submission_rows.append(payload)
        return self.submission_rows

    def upsert_responses(self, responses):
        self.response_rows = list(responses)
        return self.response_rows


class SupabaseSyncTests(unittest.TestCase):
    def test_sync_public_stories_uploads_local_media_and_upserts_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            box_client = FilesystemBoxClient(config)
            fake_airtable = FakeAirtableClient(
                submissions=[
                    {
                        "id": "recSubmission1",
                        "createdTime": "2026-04-03T10:00:00.000Z",
                        "fields": {
                            "Submission ID": "SUB-SUPABASE-1",
                            "Story Title": "Supabase Story",
                            "Summary": "Submission summary",
                            "Narrative": "Submission narrative",
                            "Theme": "Labor",
                            "Response QR": [
                                {
                                    "url": "https://assets.example/qr.png",
                                    "filename": "qr.png",
                                }
                            ],
                            "Response Link": "https://example.com/react",
                            "Avg Rating": 4.5,
                            "Number of Responses": 2,
                            "Clicks": None,
                            "Workflow Status": "Approved and Published",
                        },
                    }
                ],
                assets=[
                    {
                        "id": "recAssetPdf",
                        "fields": {
                            "Linked Submission": ["recSubmission1"],
                            "Filename": "story.pdf",
                            "Attachment": [
                                {
                                    "url": "https://assets.example/story.pdf",
                                    "filename": "story.pdf",
                                }
                            ],
                            "Caption": "Story PDF",
                            "MLA Citation": "Archive. Story PDF. 2026.",
                        },
                    }
                ],
                responses=[
                    {
                        "id": "recResponse1",
                        "fields": {
                            "Response": "This helped me understand the story.",
                            "Submissions": ["recSubmission1"],
                            "Show Response": True,
                        },
                    },
                    {
                        "id": "recResponse2",
                        "fields": {
                            "Response": "Keep this private.",
                            "Submissions": ["recSubmission1"],
                            "Show response": False,
                        },
                    },
                ],
            )

            def fake_preview(source_path: Path, preview_path: Path):
                del source_path
                preview_path.write_bytes(b"preview")
                return preview_path

            builder = SiteBuilder(
                config,
                box_client,
                airtable_client=fake_airtable,
                downloader=lambda _: b"%PDF fake pdf bytes",
                pdf_preview_generator=fake_preview,
            )
            fake_supabase = FakeSupabaseClient()

            result = SupabaseSyncService(
                config=config,
                site_builder=builder,
                supabase_client=fake_supabase,
            ).sync_public_stories()

            self.assertEqual(result["stories_synced"], 1)
            self.assertEqual(result["submissions_synced"], 1)
            self.assertEqual(result["responses_synced"], 2)
            self.assertEqual(result["uploaded_files"], 3)
            self.assertEqual(len(fake_supabase.story_rows), 1)
            self.assertEqual(len(fake_supabase.submission_rows), 1)
            self.assertEqual(len(fake_supabase.response_rows), 2)
            payload = fake_supabase.story_rows[0]["payload"]
            self.assertEqual(payload["story_slug"], "supabase-story")
            self.assertEqual(payload["workflow_status"], "Approved and Published")
            self.assertEqual(payload["submission_record_id"], "submission-1")
            self.assertEqual(payload["response_qr"], "https://supabase.example/storage/v1/object/public/stories-public/stories/media/SUB-SUPABASE-1/qr.png")
            self.assertEqual(payload["media_assets"][0]["preview_url"], "https://supabase.example/storage/v1/object/public/stories-public/stories/media/SUB-SUPABASE-1/story__preview.png")
            self.assertEqual(payload["media_assets"][0]["document_url"], "https://supabase.example/storage/v1/object/public/stories-public/stories/media/SUB-SUPABASE-1/story.pdf")
            self.assertEqual(
                fake_supabase.submission_rows[0]["Response QR"],
                "https://supabase.example/storage/v1/object/public/stories-public/stories/media/SUB-SUPABASE-1/qr.png",
            )
            self.assertTrue(fake_supabase.response_rows[0]["Show response"])
            self.assertFalse(fake_supabase.response_rows[1]["Show response"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
