from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from marker_workflow.models import BoxItem
from marker_workflow.services.grouper import SubmissionGrouper

from support import build_config


class SubmissionGrouperTests(unittest.TestCase):
    def test_groups_items_from_same_intake_subfolder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_config(Path(temp_dir))
            grouper = SubmissionGrouper(config)
            items = [
                BoxItem(
                    item_id="intake/batch-1/story.txt",
                    name="story.txt",
                    source_path="intake/batch-1/story.txt",
                    parent_path="intake/batch-1",
                    created_at="2026-03-12T14:00:00Z",
                    modified_at="2026-03-12T14:00:00Z",
                    size_bytes=42,
                    extension=".txt",
                ),
                BoxItem(
                    item_id="intake/batch-1/photo.jpg",
                    name="photo.jpg",
                    source_path="intake/batch-1/photo.jpg",
                    parent_path="intake/batch-1",
                    created_at="2026-03-12T14:02:00Z",
                    modified_at="2026-03-12T14:02:00Z",
                    size_bytes=84,
                    extension=".jpg",
                ),
            ]

            groups = grouper.build(items)

            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].confidence, 1.0)
            self.assertEqual(len(groups[0].items), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
