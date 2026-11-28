import tempfile
import unittest

from resilient_storage import ResilientSupabaseClient, SQLiteFallbackStore
from skip_published_edition import is_published_today


class PublishedEditionCheckTests(unittest.TestCase):
    def test_detects_already_published_local_edition(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteFallbackStore(f"{directory}/state.sqlite3")
            store.save_local("shard_editions", {
                "id": "edition-1",
                "edition_date": "2026-11-28",
                "status": "published",
            })
            client = ResilientSupabaseClient(remote=None, store=store)
            self.assertTrue(is_published_today(client, "2026-11-28"))

    def test_does_not_skip_draft_edition(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteFallbackStore(f"{directory}/state.sqlite3")
            store.save_local("shard_editions", {
                "id": "edition-2",
                "edition_date": "2026-11-28",
                "status": "draft",
            })
            client = ResilientSupabaseClient(remote=None, store=store)
            self.assertFalse(is_published_today(client, "2026-11-28"))


if __name__ == "__main__":
    unittest.main()
