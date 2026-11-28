import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import publish_edition


class PublishEditionSafetyTests(unittest.TestCase):
    def test_expected_edition_contains_sixteen_items(self):
        self.assertEqual(publish_edition.EXPECTED_TOTAL, 16)
        self.assertEqual(sum(publish_edition.EXPECTED_COUNTS.values()), 16)
        self.assertEqual(publish_edition.EXPECTED_COUNTS["research_frontier"], 7)
        self.assertNotIn("agora", publish_edition.EXPECTED_COUNTS)

    def test_target_date_uses_budapest_timezone(self):
        value = publish_edition.get_target_edition_date()
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}$")

    def test_validated_edition_is_archived_before_status_update(self):
        supabase = MagicMock()
        (
            supabase.table.return_value
            .select.return_value
            .in_.return_value
            .execute.return_value.data
        ) = [{
            "id": "content-1",
            "source_name": "Example source",
            "source_url": "https://example.org/article",
            "image_url": None,
            "metadata": {"edition_date": "2026-11-28"},
        }]
        edition = {
            "id": "edition-1",
            "edition_date": "2026-11-28",
            "title": "WORLD SHARDS",
            "status": "draft",
        }
        items = [{
            "id": "item-1",
            "content_item_id": "content-1",
            "section_code": "research_frontier",
            "position": 1,
            "processing_status": "completed",
            "display_title": "Title",
            "display_summary": "Summary",
            "display_body": "Body",
        }]

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"WORLD_SHARDS_ARCHIVE_DIR": directory}
        ):
            archive_path = publish_edition.save_local_archive(edition, items, supabase)
            with open(archive_path, encoding="utf-8") as archive_file:
                archive = json.load(archive_file)

        self.assertEqual(archive["schema_version"], 1)
        self.assertEqual(archive["archive_type"], "world_shards_edition")
        self.assertEqual(archive["edition"]["status"], "draft")
        self.assertEqual(len(archive["items"]), 1)
        self.assertEqual(
            archive["source_by_id"]["content-1"]["source_name"],
            "Example source",
        )

    def test_no_draft_for_today_fails_closed_without_publishing(self):
        supabase = MagicMock()
        (
            supabase.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .order.return_value
            .limit.return_value
            .execute.return_value.data
        ) = []

        with patch.object(publish_edition, "get_client", return_value=supabase):
            with self.assertRaisesRegex(RuntimeError, "Nincs publikálásra váró draft"):
                publish_edition.main()

        supabase.table.return_value.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
