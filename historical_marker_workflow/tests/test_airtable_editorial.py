from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from marker_workflow.adapters.airtable_client import AirtableClient
from marker_workflow.adapters.box_client import FilesystemBoxClient
from marker_workflow.adapters.extractor_registry import ExtractorRegistry
from marker_workflow.services.airtable_editorial import AirtableEditorialWorkflow

from support import build_config


class FakeAirtableClient(AirtableClient):
    def __init__(self, config, submissions):
        super().__init__(config)
        self.submissions = submissions
        self.updates = []

    def list_all_records(self, table_name: str, **_: object):
        if table_name == self.config.airtable_submissions_table:
            return list(self.submissions)
        return []

    def update_record(self, table_name: str, record_id: str, fields: dict[str, object]):
        self.updates.append((table_name, record_id, fields))
        return {"id": record_id, "fields": fields}


class FakeAIClient:
    def __init__(self, decision: str) -> None:
        self.decision = decision

    def review_story_dossier(self, prompt: str, payload: dict):
        del prompt, payload
        if self.decision == "pass":
            return {
                "decision": "pass",
                "ai_notes": "Looks mission-aligned and safe.",
                "mission_fit": True,
                "unsafe_or_inappropriate": False,
                "risk_flags": [],
            }
        return {
            "decision": "reject",
            "ai_notes": "The dossier does not clearly fit the mission.",
            "mission_fit": False,
            "unsafe_or_inappropriate": False,
            "risk_flags": [],
        }


class AirtableEditorialWorkflowTests(unittest.TestCase):
    def test_passing_submission_moves_directly_to_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            box_client = FilesystemBoxClient(config)
            submission = {
                "id": "rec123",
                "fields": {
                    "Submission ID": "SUB-123",
                    "Story Title": "River Story",
                    "Theme": "Migration",
                    "Keywords": ["port", "trade"],
                    "Summary": "Summary text",
                    "Narrative": "Narrative text",
                    "Context and Connections": "New Orleans and Tulane connect through global trade routes.",
                    "Story Dossier Doc": [{"url": "https://example.com/dossier.txt", "filename": "dossier.txt"}],
                    "AI Review Status": "waiting",
                    "Workflow Status": "",
                },
            }
            airtable = FakeAirtableClient(config, [submission])
            workflow = AirtableEditorialWorkflow(
                config=config,
                box_client=box_client,
                airtable_client=airtable,
                ai_client=FakeAIClient("pass"),
                extractor_registry=ExtractorRegistry(config),
                downloader=lambda _: b"New Orleans and Tulane are linked to global migration.\n",
            )

            result = workflow.process_pending()

            self.assertEqual(result["queued_for_human_review"], 1)
            self.assertEqual(
                airtable.updates,
                [
                    ("Submissions", "rec123", {"Workflow Status": "Under Human Review", "AI Notes": ""}),
                ],
            )

    def test_rejected_submission_writes_ai_notes_and_rejected_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            config = build_config(workspace)
            submission = {
                "id": "rec999",
                "fields": {
                    "Submission ID": "SUB-999",
                    "Story Title": "Off Topic Story",
                    "Story Dossier Doc": [{"url": "https://example.com/dossier.txt", "filename": "dossier.txt"}],
                    "AI Review Status": "",
                    "Workflow Status": "",
                },
            }
            airtable = FakeAirtableClient(config, [submission])
            workflow = AirtableEditorialWorkflow(
                config=config,
                box_client=FilesystemBoxClient(config),
                airtable_client=airtable,
                ai_client=FakeAIClient("reject"),
                extractor_registry=ExtractorRegistry(config),
                downloader=lambda _: b"Off-topic dossier text.",
            )

            result = workflow.process_pending()

            self.assertEqual(result["rejected_submissions"], 1)
            self.assertEqual(
                airtable.updates,
                [
                    (
                        "Submissions",
                        "rec999",
                        {
                            "Workflow Status": "AI Rejected",
                            "AI Notes": "The dossier does not clearly fit the mission.",
                        },
                    )
                ],
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
