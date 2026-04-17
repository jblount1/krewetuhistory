from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from marker_workflow.adapters.box_client import FilesystemBoxClient
from marker_workflow.services.site_builder import SiteBuilder
from marker_workflow.utils import dump_json

from support import build_config


class FakeAirtableClient:
    def __init__(self, submissions=None, assets=None, display_queue=None, responses=None) -> None:
        self._tables = {
            "Submissions": submissions or [],
            "Assets": assets or [],
            "Display Queue": display_queue or [],
            "Responses": responses or [],
        }

    def list_all_records(self, table_name: str, **_: object):
        return list(self._tables.get(table_name, []))


class FailingAirtableClient:
    def list_all_records(self, table_name: str, **_: object):
        del table_name
        raise ValueError("Airtable connection is not configured. Missing: AIRTABLE_PERSONAL_ACCESS_TOKEN")


class SiteBuilderTests(unittest.TestCase):
    def test_build_site_exports_story_payload_and_media(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            box_client = FilesystemBoxClient(config)

            canonical_root = config.box_root_path / "processing" / "2026" / "03" / "SUB-20260312-EEEEEE"
            approved_root = config.box_root_path / "approved" / "community" / "story-slug" / "drafts"
            record_root = config.box_root_path / "approved" / "community" / "story-slug" / "records"
            originals_root = canonical_root / "originals"

            originals_root.mkdir(parents=True, exist_ok=True)
            approved_root.mkdir(parents=True, exist_ok=True)
            record_root.mkdir(parents=True, exist_ok=True)

            (originals_root / "photo.jpg").write_bytes(b"fake-image")
            dump_json(
                record_root / "SUB-20260312-EEEEEE__submission.json",
                {
                    "submission_id": "SUB-20260312-EEEEEE",
                    "canonical_package_path": "processing/2026/03/SUB-20260312-EEEEEE",
                    "story_slug": "story-slug",
                    "date_received": "2026-03-12T12:00:00Z",
                    "community_label": "Vietnamese",
                    "geographic_label": "New Orleans",
                    "tulane_connection": "possible",
                    "review_status": "approved",
                    "public_display_risk_level": "low",
                    "notes_for_human_reviewer": [],
                },
            )
            dump_json(
                approved_root / "SUB-20260312-EEEEEE__story-package.json",
                {
                    "submission_id": "SUB-20260312-EEEEEE",
                    "headline": "Market Memories",
                    "summary_50": "A concise summary.",
                    "narrative_120_180": "A fuller narrative about migration, markets, and memory.",
                    "associated_media_assets": ["photo.jpg"],
                    "suggested_image_caption_placeholders": ["A market portrait"],
                    "suggested_credits_line": "Credit line",
                    "questions_or_gaps": ["Confirm the exact year."],
                    "display_format_recommendation": "touchscreen_story_card",
                    "themes": ["migration"],
                    "community_labels": ["Vietnamese"],
                },
            )

            result = SiteBuilder(config, box_client).build(source_mode="approved")

            self.assertEqual(result["story_count"], 1)
            stories_payload = (config.site_output_path / "data" / "stories.json").read_text(encoding="utf-8")
            self.assertIn("Market Memories", stories_payload)
            self.assertTrue((config.site_output_path / "media" / "SUB-20260312-EEEEEE" / "photo.jpg").exists())

    def test_build_site_exports_airtable_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            box_client = FilesystemBoxClient(config)
            fake_client = FakeAirtableClient(
                submissions=[
                    {
                        "id": "recSubmission1",
                        "createdTime": "2026-04-03T10:00:00.000Z",
                        "fields": {
                            "Submission ID": "SUB-AIRTABLE-1",
                            "Story Title": "Original River Story",
                            "Summary": "Submission summary",
                            "Narrative": "Submission narrative",
                            "AI Generated": "Yes",
                            "Theme": "Labor",
                            "Keywords": ["River", "Trade"],
                            "New Orleans Connection": "Mississippi waterfront",
                            "Tulane Connection": "Research project",
                            "Global Community Connection": "Port networks",
                            "Context and Connections": "New Orleans, Tulane, and port networks shaped this story.",
                        "References": "Author. Title. 2026.",
                        "Response QR": [
                            {
                                "url": "https://assets.example/qr.png",
                                "filename": "qr.png",
                            }
                        ],
                        "Response Link": "https://example.com/react",
                        "Avg Rating": 4.2,
                        "Number of Responses": 12,
                        "Workflow Status": "Approved and Published",
                    },
                }
                ],
                assets=[
                    {
                        "id": "recAsset1",
                        "fields": {
                            "Linked Submission": ["recSubmission1"],
                            "Filename": "river.png",
                            "Attachment": [
                                {
                                    "url": "https://assets.example/river.png",
                                    "filename": "river.png",
                                }
                            ],
                            "Caption": "River image",
                            "MLA Citation": "Archive. River image. 2026.",
                        },
                    }
                ],
                display_queue=[],
            )

            builder = SiteBuilder(
                config,
                box_client,
                airtable_client=fake_client,
                downloader=lambda _: b"fake-image-bytes",
            )

            result = builder.build(source_mode="airtable")

            self.assertEqual(result["story_count"], 1)
            stories_payload = json.loads((config.site_output_path / "data" / "stories.json").read_text(encoding="utf-8"))
            self.assertEqual(stories_payload["source_mode"], "airtable")
            self.assertEqual(stories_payload["source_label"], "Approved stories")
            self.assertEqual(stories_payload["stories"][0]["headline"], "Original River Story")
            self.assertEqual(stories_payload["stories"][0]["keywords"], ["River", "Trade"])
            self.assertEqual(stories_payload["stories"][0]["ai_generated"], "Yes")
            self.assertEqual(stories_payload["stories"][0]["workflow_status"], "Approved and Published")
            self.assertEqual(
                stories_payload["stories"][0]["context_connections"],
                "New Orleans, Tulane, and port networks shaped this story.",
            )
            self.assertEqual(
                stories_payload["stories"][0]["context_sections"],
                [
                    {"label": "Context and Connections", "text": "New Orleans, Tulane, and port networks shaped this story."},
                    {"label": "New Orleans Connection", "text": "Mississippi waterfront"},
                    {"label": "Tulane Connection", "text": "Research project"},
                    {"label": "Global Community Connection", "text": "Port networks"},
                ],
            )
            self.assertEqual(
                stories_payload["stories"][0]["references"],
                ["Author. Title. 2026."],
            )
            self.assertEqual(
                stories_payload["stories"][0]["ai_copy"],
                "Submission summary",
            )
            self.assertEqual(stories_payload["stories"][0]["response_qr"], "https://assets.example/qr.png")
            self.assertEqual(stories_payload["stories"][0]["response_link"], "https://example.com/react")
            self.assertEqual(stories_payload["stories"][0]["avg_rating"], 4.2)
            self.assertEqual(stories_payload["stories"][0]["number_of_responses"], 12)
            self.assertEqual(stories_payload["stories"][0]["clicks"], 0)
            self.assertNotIn("contributor_name", stories_payload["stories"][0])
            self.assertTrue((config.site_output_path / "media" / "SUB-AIRTABLE-1" / "river.png").exists())

    def test_build_site_omits_non_published_airtable_records_and_generates_pdf_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            box_client = FilesystemBoxClient(config)
            fake_client = FakeAirtableClient(
                submissions=[
                    {
                        "id": "recPublished",
                        "createdTime": "2026-04-03T10:00:00.000Z",
                        "fields": {
                            "Submission ID": "SUB-PDF-1",
                            "Story Title": "PDF Story",
                            "Theme": "Migration",
                            "Keywords": ["Archive"],
                            "Summary": "Summary",
                            "Narrative": "Narrative",
                            "Workflow Status": "Approved and Published",
                        },
                    },
                    {
                        "id": "recDraft",
                        "createdTime": "2026-04-03T11:00:00.000Z",
                        "fields": {
                            "Submission ID": "SUB-DRAFT-1",
                            "Story Title": "Draft Story",
                            "Workflow Status": "Under Human Review",
                        },
                    },
                ],
                assets=[
                    {
                        "id": "recAssetPdf",
                        "fields": {
                            "Linked Submission": ["recPublished"],
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
                display_queue=[],
            )

            def fake_preview(source_path: Path, preview_path: Path):
                del source_path
                preview_path.write_bytes(b"preview")
                return preview_path

            builder = SiteBuilder(
                config,
                box_client,
                airtable_client=fake_client,
                downloader=lambda _: b"%PDF fake pdf bytes",
                pdf_preview_generator=fake_preview,
            )

            result = builder.build(source_mode="airtable")

            self.assertEqual(result["story_count"], 1)
            stories_payload = json.loads((config.site_output_path / "data" / "stories.json").read_text(encoding="utf-8"))
            story = stories_payload["stories"][0]
            self.assertEqual(story["headline"], "PDF Story")
            self.assertEqual(story["media_assets"][0]["kind"], "pdf")

    def test_build_site_uses_existing_snapshot_when_airtable_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            box_client = FilesystemBoxClient(config)

            snapshot = {
                "generated_at": "2026-04-16T00:00:00Z",
                "source_mode": "airtable",
                "source_label": "Approved stories",
                "public_publish_ready": True,
                "story_count": 1,
                "stories": [
                    {
                        "story_slug": "existing-story",
                        "headline": "Existing Story",
                        "summary": "Snapshot summary",
                        "narrative": "",
                        "ai_generated": "No",
                        "themes": ["Labor"],
                        "keywords": [],
                        "context_connections": "",
                        "context_sections": [],
                        "references": [],
                        "ai_copy": "Snapshot summary",
                        "media_assets": [],
                        "date_received": "2026-04-16T00:00:00Z",
                        "source_status": "airtable",
                        "workflow_status": "Approved and Published",
                    }
                ],
            }
            dump_json(config.site_output_path / "data" / "stories.json", snapshot)

            result = SiteBuilder(
                config,
                box_client,
                airtable_client=FailingAirtableClient(),
            ).build(source_mode="airtable")

            self.assertTrue(result["used_existing_snapshot"])
            self.assertEqual(result["story_count"], 1)
            stories_payload = json.loads((config.site_output_path / "data" / "stories.json").read_text(encoding="utf-8"))
            self.assertEqual(stories_payload["stories"][0]["headline"], "Existing Story")

    def test_build_site_adds_submission_video_url_to_public_media(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            builder = SiteBuilder(
                config,
                FilesystemBoxClient(config),
                airtable_client=FakeAirtableClient(
                    submissions=[
                        {
                            "id": "recVideo",
                            "createdTime": "2026-04-03T10:00:00.000Z",
                            "fields": {
                                "Submission ID": "SUB-VIDEO-1",
                                "Story Title": "Video Story",
                                "Theme": "Culture",
                                "Keywords": ["music"],
                                "Summary": "Summary",
                                "Narrative": "Narrative",
                                "Workflow Status": "Approved",
                                "Video URL": "https://www.youtube.com/watch?v=abc123xyz89",
                            },
                        }
                    ],
                    assets=[],
                    display_queue=[],
                ),
            )

            result = builder.build(source_mode="airtable")

            self.assertEqual(result["story_count"], 1)
            stories_payload = json.loads((config.site_output_path / "data" / "stories.json").read_text(encoding="utf-8"))
            self.assertEqual(stories_payload["stories"][0]["ai_copy"], "Summary")
            asset = stories_payload["stories"][0]["media_assets"][0]
            self.assertEqual(asset["kind"], "video_embed")
            self.assertEqual(asset["url"], "https://www.youtube.com/embed/abc123xyz89")

    def test_build_site_falls_back_when_ai_copy_contains_error_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            builder = SiteBuilder(
                config,
                FilesystemBoxClient(config),
                airtable_client=FakeAirtableClient(
                    submissions=[
                        {
                            "id": "recAiCopy",
                            "createdTime": "2026-04-16T10:00:00.000Z",
                            "fields": {
                                "Submission ID": "SUB-AI-COPY-1",
                                "Story Title": "AI Copy Story",
                                "Summary": "Summary fallback",
                                "Narrative": "Narrative",
                                "Workflow Status": "Approved",
                                "AI Copy": "error\nattachmentFailedToExtract\nFalse",
                            },
                        }
                    ],
                    assets=[],
                    display_queue=[],
                ),
            )

            result = builder.build(source_mode="airtable")

            self.assertEqual(result["story_count"], 1)
            stories_payload = json.loads((config.site_output_path / "data" / "stories.json").read_text(encoding="utf-8"))
            self.assertEqual(stories_payload["stories"][0]["ai_copy"], "Summary fallback")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
