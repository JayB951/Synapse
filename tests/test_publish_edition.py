import unittest
from unittest.mock import MagicMock, patch

import publish_edition


class PublishEditionSafetyTests(unittest.TestCase):
    def test_expected_edition_contains_fourteen_items(self):
        self.assertEqual(publish_edition.EXPECTED_TOTAL, 14)
        self.assertEqual(sum(publish_edition.EXPECTED_COUNTS.values()), 14)

    def test_target_date_uses_budapest_timezone(self):
        value = publish_edition.get_target_edition_date()
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2}$")

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
