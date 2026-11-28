import tempfile
import unittest

from resilient_storage import ResilientSupabaseClient, SQLiteFallbackStore


class FakeRemoteQuery:
    def __init__(self, remote, table):
        self.remote = remote
        self.table_name = table
        self.operation = "select"
        self.payload = None
        self.filters = []

    def select(self, fields="*"):
        self.operation = "select"
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def upsert(self, payload):
        self.operation = "upsert"
        self.payload = payload
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, list(values)))
        return self

    def contains(self, field, value):
        self.filters.append(("contains", field, value))
        return self

    def order(self, field, desc=False):
        return self

    def limit(self, value):
        return self

    def _matches(self, row):
        for operation, field, value in self.filters:
            if operation == "eq" and row.get(field) != value:
                return False
            if operation == "in" and row.get(field) not in value:
                return False
            if operation == "contains":
                actual = row.get(field) or {}
                if not all(actual.get(key) == item for key, item in value.items()):
                    return False
        return True

    def execute(self):
        self.remote.calls.append((self.table_name, self.operation))
        if self.remote.fail_reads and self.operation == "select":
            raise RuntimeError("database unavailable")
        if self.remote.fail_writes and self.operation != "select":
            raise RuntimeError("database storage full")

        rows = self.remote.tables.setdefault(self.table_name, [])
        if self.operation == "select":
            return type("Response", (), {
                "data": [dict(row) for row in rows if self._matches(row)]
            })()

        if self.operation in {"insert", "upsert"}:
            values = self.payload if isinstance(self.payload, list) else [self.payload]
            saved = []
            for value in values:
                record = dict(value)
                existing = next((row for row in rows if row.get("id") == record["id"]), None)
                if existing:
                    existing.update(record)
                    saved.append(dict(existing))
                else:
                    rows.append(record)
                    saved.append(dict(record))
            return type("Response", (), {
                "data": [] if self.remote.return_minimal else saved
            })()

        if self.operation == "update":
            changed = []
            for row in rows:
                if self._matches(row):
                    row.update(self.payload)
                    changed.append(dict(row))
            return type("Response", (), {
                "data": [] if self.remote.return_minimal else changed
            })()

        if self.operation == "delete":
            removed = [row for row in rows if self._matches(row)]
            self.remote.tables[self.table_name] = [
                row for row in rows if not self._matches(row)
            ]
            return type("Response", (), {
                "data": [] if self.remote.return_minimal else removed
            })()


class FakeRemote:
    def __init__(self):
        self.tables = {}
        self.calls = []
        self.fail_reads = False
        self.fail_writes = False
        self.return_minimal = False

    def table(self, table_name):
        return FakeRemoteQuery(self, table_name)


class ResilientStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SQLiteFallbackStore(f"{self.temp.name}/fallback.sqlite3")
        self.remote = FakeRemote()
        self.client = ResilientSupabaseClient(remote=self.remote, store=self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_insert_falls_back_to_sqlite_and_is_readable(self):
        self.remote.fail_writes = True
        inserted = self.client.table("shard_content_items").insert({
            "title": "Local candidate",
            "status": "candidate",
            "source_url": "https://example.org/a",
        }).execute().data[0]

        result = (
            self.client.table("shard_content_items")
            .select("id,title,status")
            .eq("id", inserted["id"])
            .execute()
        )
        self.assertEqual(len(result.data), 1)
        self.assertEqual(result.data[0]["title"], "Local candidate")
        self.assertEqual(result.data[0]["status"], "candidate")
        self.assertTrue(self.client.local_fallback_used)

    def test_update_fallback_overrides_stale_remote_reads(self):
        self.remote.tables["shard_content_items"] = [{
            "id": "row-1",
            "title": "Existing",
            "status": "candidate",
        }]
        self.remote.fail_writes = True

        updated = (
            self.client.table("shard_content_items")
            .update({"status": "selected"})
            .eq("id", "row-1")
            .execute()
        )
        self.assertEqual(updated.data[0]["status"], "selected")

        selected = (
            self.client.table("shard_content_items")
            .select("id,status")
            .eq("id", "row-1")
            .execute()
        )
        self.assertEqual(selected.data[0]["status"], "selected")
        self.assertTrue(self.client.local_fallback_used)

    def test_live_remote_results_do_not_reintroduce_stale_cached_candidates(self):
        self.remote.tables["shard_content_items"] = [{
            "id": "row-stale",
            "title": "Already selected",
            "status": "candidate",
        }]
        self.client.table("shard_content_items").select("*").execute()
        self.remote.tables["shard_content_items"][0]["status"] = "selected"

        result = (
            self.client.table("shard_content_items")
            .select("*")
            .eq("status", "candidate")
            .execute()
        )
        self.assertEqual(result.data, [])

    def test_minimal_return_update_reloads_updated_remote_row(self):
        self.remote.tables["shard_content_items"] = [{
            "id": "minimal-update",
            "title": "Original",
            "status": "candidate",
        }]
        self.remote.return_minimal = True

        result = (
            self.client.table("shard_content_items")
            .update({"status": "selected"})
            .eq("id", "minimal-update")
            .execute()
        )
        self.assertEqual(len(result.data), 1)
        self.assertEqual(result.data[0]["status"], "selected")

    def test_minimal_return_delete_removes_cached_row(self):
        self.remote.tables["shard_content_items"] = [{
            "id": "minimal-delete",
            "title": "Temporary",
        }]
        self.client.table("shard_content_items").select("*").execute()
        self.remote.return_minimal = True

        self.client.table("shard_content_items").delete().eq(
            "id", "minimal-delete"
        ).execute()
        result = self.client.table("shard_content_items").select("*").execute()
        self.assertEqual(result.data, [])

    def test_local_reads_continue_when_remote_is_unavailable(self):
        self.store.save_local("shard_content_items", {
            "id": "cached-1",
            "title": "Cached",
            "status": "candidate",
        })
        self.remote.fail_reads = True

        result = self.client.table("shard_content_items").select("*").execute()
        self.assertEqual(result.data[0]["id"], "cached-1")
        self.assertTrue(self.client.local_fallback_used)

    def test_pending_writes_sync_when_remote_recovers(self):
        self.remote.fail_writes = True
        inserted = self.client.table("shard_content_items").insert({
            "title": "Retry later",
            "status": "candidate",
        }).execute().data[0]
        self.remote.fail_writes = False

        self.client.sync_pending()

        self.assertEqual(
            self.remote.tables["shard_content_items"][0]["id"],
            inserted["id"],
        )
        pending, deleted = self.store.pending_records()
        self.assertEqual(pending, [])
        self.assertEqual(deleted, [])

    def test_local_delete_hides_remote_row_until_sync(self):
        self.remote.tables["shard_content_items"] = [{
            "id": "delete-me",
            "title": "Temporary",
        }]
        self.client.table("shard_content_items").select("*").execute()
        self.remote.fail_writes = True

        self.client.table("shard_content_items").delete().eq("id", "delete-me").execute()
        result = self.client.table("shard_content_items").select("*").execute()
        self.assertEqual(result.data, [])

    def test_pending_writes_replay_in_foreign_key_safe_order(self):
        self.store.save_local("shard_edition_items", {
            "id": "item-1",
            "edition_id": "edition-1",
            "content_item_id": "content-1",
        })
        self.store.save_local("shard_editions", {
            "id": "edition-1",
            "edition_date": "2026-11-28",
        })
        self.store.save_local("shard_content_items", {
            "id": "content-1",
            "source_url": "https://example.org/source",
        })

        self.client.sync_pending()
        write_order = [
            table for table, operation in self.remote.calls
            if operation == "upsert"
        ]
        self.assertEqual(
            write_order,
            ["shard_content_items", "shard_editions", "shard_edition_items"],
        )

    def test_cache_pruning_removes_old_cache_but_keeps_pending_writes(self):
        self.store.cache_remote("shard_content_items", [{
            "id": "old-cache",
            "title": "Old cached row",
            "collected_at": "2020-01-01T00:00:00+00:00",
            "status": "selected",
        }])
        self.store.save_local("shard_content_items", {
            "id": "old-pending",
            "title": "Pending write",
            "collected_at": "2020-01-01T00:00:00+00:00",
            "status": "candidate",
        }, pending=True)

        self.store._prune_old_cache(retention_days=30)
        remaining = {row["id"] for row in self.store.rows("shard_content_items")}
        self.assertNotIn("old-cache", remaining)
        self.assertIn("old-pending", remaining)

    def test_json_contains_filter_works_in_local_mode(self):
        self.store.save_local("shard_content_items", {
            "id": "agora-1",
            "section_code": "research_frontier",
            "metadata": {"edition_date": "2026-11-28", "content_type": "hungary"},
        })
        result = (
            ResilientSupabaseClient(remote=None, store=self.store)
            .table("shard_content_items")
            .select("*")
            .contains("metadata", {"edition_date": "2026-11-28"})
            .execute()
        )
        self.assertEqual([row["id"] for row in result.data], ["agora-1"])


if __name__ == "__main__":
    unittest.main()
