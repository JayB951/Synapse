"""Supabase-compatible SQLite fallback for the WORLD SHARDS daily pipeline.

Remote Supabase remains the primary store. Successful reads are cached locally;
failed writes are persisted in SQLite and merged into subsequent reads. Pending
local writes are synchronized back to Supabase when connectivity/capacity returns.
"""
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

LOGGER = logging.getLogger("world-shards-resilient-storage")
SUPPORTED_TABLES = {
    "shard_content_items",
    "shard_editions",
    "shard_edition_items",
    "publications",
}


def _json_contains(value, expected):
    if isinstance(expected, dict):
        if not isinstance(value, dict):
            return False
        return all(
            key in value and _json_contains(value[key], nested)
            for key, nested in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(value, list) and all(item in value for item in expected)
    return value == expected


class SQLiteFallbackStore:
    def __init__(self, path=None):
        self.path = Path(path or os.getenv(
            "WORLD_SHARDS_SQLITE_PATH", "world-shards-fallback.sqlite3"
        ))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    table_name TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    pending INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (table_name, record_id)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS tombstones (
                    table_name TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    PRIMARY KEY (table_name, record_id)
                )
            """)
        self._prune_old_cache()

    def _prune_old_cache(self, retention_days=120):
        """Keep pending writes, but bound the age of ordinary local cache rows."""
        cutoff = date.today() - timedelta(days=retention_days)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT table_name, record_id, payload, pending FROM records"
            ).fetchall()
            edition_dates = {}
            for row in rows:
                if row["table_name"] == "shard_editions":
                    payload = json.loads(row["payload"])
                    edition_dates[str(payload.get("id", row["record_id"]))] = payload.get("edition_date")

            stale_ids = []
            for row in rows:
                if row["pending"]:
                    continue
                payload = json.loads(row["payload"])
                if row["table_name"] == "shard_edition_items":
                    raw_date = (
                        edition_dates.get(str(payload.get("edition_id")))
                        or payload.get("created_at")
                    )
                elif row["table_name"] == "shard_content_items":
                    raw_date = payload.get("collected_at") or payload.get("created_at")
                elif row["table_name"] == "publications":
                    raw_date = payload.get("publication_date") or payload.get("created_at")
                elif row["table_name"] == "shard_editions":
                    raw_date = payload.get("edition_date")
                else:
                    raw_date = None
                if not raw_date:
                    continue
                try:
                    record_date = date.fromisoformat(str(raw_date)[:10])
                except ValueError:
                    continue
                if record_date < cutoff:
                    stale_ids.append((row["table_name"], row["record_id"]))

            for table_name, record_id in stale_ids:
                connection.execute(
                    "DELETE FROM records WHERE table_name=? AND record_id=? AND pending=0",
                    (table_name, record_id),
                )
        if stale_ids:
            LOGGER.info(
                "SQLite cache takarítás: %s régi, nem függő rekord eltávolítva.",
                len(stale_ids),
            )

    def cache_remote(self, table_name, rows):
        with self._connect() as connection:
            for row in rows or []:
                if not isinstance(row, dict) or row.get("id") is None:
                    continue
                record_id = str(row["id"])
                existing = connection.execute(
                    "SELECT payload, pending FROM records WHERE table_name=? AND record_id=?",
                    (table_name, record_id),
                ).fetchone()
                deleted = connection.execute(
                    "SELECT 1 FROM tombstones WHERE table_name=? AND record_id=?",
                    (table_name, record_id),
                ).fetchone()
                if deleted:
                    continue
                previous = json.loads(existing["payload"]) if existing else {}
                pending = int(existing["pending"]) if existing else 0
                merged = ({**row, **previous} if pending else {**previous, **row})
                connection.execute(
                    """
                    INSERT INTO records(table_name, record_id, payload, pending)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(table_name, record_id) DO UPDATE SET
                        payload=excluded.payload,
                        pending=MAX(records.pending, excluded.pending)
                    """,
                    (table_name, record_id, json.dumps(merged, ensure_ascii=False, default=str), pending),
                )

    def save_local(self, table_name, row, pending=True):
        if not isinstance(row, dict):
            raise TypeError("A helyi tárolás csak objektum rekordot fogad.")
        record = dict(row)
        record.setdefault("id", str(uuid.uuid4()))
        record_id = str(record["id"])
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload FROM records WHERE table_name=? AND record_id=?",
                (table_name, record_id),
            ).fetchone()
            previous = json.loads(existing["payload"]) if existing else {}
            merged = {**previous, **record}
            connection.execute(
                """
                INSERT INTO records(table_name, record_id, payload, pending)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(table_name, record_id) DO UPDATE SET
                    payload=excluded.payload,
                    pending=MAX(records.pending, excluded.pending)
                """,
                (
                    table_name,
                    record_id,
                    json.dumps(merged, ensure_ascii=False, default=str),
                    int(bool(pending)),
                ),
            )
            connection.execute(
                "DELETE FROM tombstones WHERE table_name=? AND record_id=?",
                (table_name, record_id),
            )
        return merged

    def rows(self, table_name):
        with self._connect() as connection:
            records = connection.execute(
                "SELECT record_id, payload FROM records WHERE table_name=?",
                (table_name,),
            ).fetchall()
            deleted = {
                row["record_id"] for row in connection.execute(
                    "SELECT record_id FROM tombstones WHERE table_name=?",
                    (table_name,),
                ).fetchall()
            }
        return [
            json.loads(row["payload"])
            for row in records
            if row["record_id"] not in deleted
        ]

    def exclude_tombstones(self, table_name, rows):
        with self._connect() as connection:
            deleted = {
                row["record_id"] for row in connection.execute(
                    "SELECT record_id FROM tombstones WHERE table_name=?",
                    (table_name,),
                ).fetchall()
            }
        return [
            row for row in (rows or [])
            if row.get("id") is None or str(row["id"]) not in deleted
        ]

    def pending_rows(self, table_name):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_id, payload FROM records WHERE table_name=? AND pending=1",
                (table_name,),
            ).fetchall()
            deleted = {
                row["record_id"] for row in connection.execute(
                    "SELECT record_id FROM tombstones WHERE table_name=?",
                    (table_name,),
                ).fetchall()
            }
        return [
            json.loads(row["payload"])
            for row in rows
            if row["record_id"] not in deleted
        ]

    def mark_deleted(self, table_name, record_ids):
        with self._connect() as connection:
            for record_id in record_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO tombstones(table_name, record_id) VALUES (?, ?)",
                    (table_name, str(record_id)),
                )

    def pending_records(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT table_name, record_id, payload FROM records WHERE pending=1"
            ).fetchall()
            deleted = connection.execute(
                "SELECT table_name, record_id FROM tombstones"
            ).fetchall()
        return (
            [
                {
                    "table_name": row["table_name"],
                    "record_id": row["record_id"],
                    "payload": json.loads(row["payload"]),
                }
                for row in rows
            ],
            [
                {"table_name": row["table_name"], "record_id": row["record_id"]}
                for row in deleted
            ],
        )

    def mark_synced(self, table_name, record_id, row=None):
        with self._connect() as connection:
            if row:
                existing = connection.execute(
                    "SELECT payload FROM records WHERE table_name=? AND record_id=?",
                    (table_name, str(record_id)),
                ).fetchone()
                previous = json.loads(existing["payload"]) if existing else {}
                merged = {**previous, **row}
                connection.execute(
                    """
                    INSERT INTO records(table_name, record_id, payload, pending)
                    VALUES (?, ?, ?, 0)
                    ON CONFLICT(table_name, record_id) DO UPDATE SET
                        payload=excluded.payload, pending=0
                    """,
                    (
                        table_name,
                        str(record_id),
                        json.dumps(merged, ensure_ascii=False, default=str),
                    ),
                )
            else:
                connection.execute(
                    "UPDATE records SET pending=0 WHERE table_name=? AND record_id=?",
                    (table_name, str(record_id)),
                )
            connection.execute(
                "DELETE FROM tombstones WHERE table_name=? AND record_id=?",
                (table_name, str(record_id)),
            )

    def mark_delete_synced(self, table_name, record_id):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM records WHERE table_name=? AND record_id=?",
                (table_name, str(record_id)),
            )
            connection.execute(
                "DELETE FROM tombstones WHERE table_name=? AND record_id=?",
                (table_name, str(record_id)),
            )


class ResilientQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.operation = "select"
        self.fields = "*"
        self.payload = None
        self.filters = []
        self.orders = []
        self.row_limit = None

    def select(self, fields="*"):
        self.operation = "select"
        self.fields = fields or "*"
        return self

    def insert(self, values):
        self.operation = "insert"
        self.payload = values
        return self

    def upsert(self, values):
        self.operation = "upsert"
        self.payload = values
        return self

    def update(self, values):
        self.operation = "update"
        self.payload = values
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def neq(self, field, value):
        self.filters.append(("neq", field, value))
        return self

    def gte(self, field, value):
        self.filters.append(("gte", field, value))
        return self

    def gt(self, field, value):
        self.filters.append(("gt", field, value))
        return self

    def lte(self, field, value):
        self.filters.append(("lte", field, value))
        return self

    def lt(self, field, value):
        self.filters.append(("lt", field, value))
        return self

    def in_(self, field, values):
        self.filters.append(("in", field, list(values)))
        return self

    def contains(self, field, value):
        self.filters.append(("contains", field, value))
        return self

    def order(self, field, desc=False, **kwargs):
        self.orders.append((field, bool(desc)))
        return self

    def limit(self, value):
        self.row_limit = int(value)
        return self

    def _matches(self, row):
        for operation, field, expected in self.filters:
            actual = row.get(field)
            try:
                if operation == "eq" and actual != expected:
                    return False
                if operation == "neq" and actual == expected:
                    return False
                if operation == "in" and actual not in expected:
                    return False
                if operation == "contains" and not _json_contains(actual, expected):
                    return False
                if operation == "gte" and (actual is None or actual < expected):
                    return False
                if operation == "gt" and (actual is None or actual <= expected):
                    return False
                if operation == "lte" and (actual is None or actual > expected):
                    return False
                if operation == "lt" and (actual is None or actual >= expected):
                    return False
            except TypeError:
                return False
        return True

    def _prepare_rows(self, rows, project=True):
        selected = [dict(row) for row in rows if self._matches(row)]
        for field, descending in reversed(self.orders):
            selected.sort(
                key=lambda row: (row.get(field) is None, row.get(field)),
                reverse=descending,
            )
        if self.row_limit is not None:
            selected = selected[:self.row_limit]
        if project and self.fields.strip() != "*":
            fields = [part.strip().split(":")[-1] for part in self.fields.split(",")]
            selected = [
                {field: row.get(field) for field in fields}
                for row in selected
            ]
        return selected

    def _remote_query(self, operation=None, fields=None):
        operation = operation or self.operation
        query = self.client.remote.table(self.table_name)
        if operation == "select":
            query = query.select(fields or self.fields)
        elif operation == "insert":
            query = query.insert(self.payload)
        elif operation == "upsert":
            query = query.upsert(self.payload)
        elif operation == "update":
            query = query.update(self.payload)
        elif operation == "delete":
            query = query.delete()
        for name, field, value in self.filters:
            query = getattr(query, "in_" if name == "in" else name)(field, value)
        for field, descending in self.orders:
            query = query.order(field, desc=descending)
        if self.row_limit is not None:
            query = query.limit(self.row_limit)
        return query

    def _fetch_remote_matching_rows(self):
        if self.client.remote is None:
            return None
        try:
            query = self._remote_query(operation="select", fields="*")
            response = query.execute()
            rows = self.client.store.exclude_tombstones(
                self.table_name, response.data or []
            )
            self.client.store.cache_remote(self.table_name, rows)
            return rows
        except Exception:
            return None

    def execute(self):
        if self.operation == "select":
            remote_rows = []
            remote_read_succeeded = False
            if self.client.remote is not None:
                try:
                    response = self._remote_query().execute()
                    remote_rows = self.client.store.exclude_tombstones(
                        self.table_name, response.data or []
                    )
                    self.client.store.cache_remote(self.table_name, remote_rows)
                    remote_read_succeeded = True
                except Exception:
                    self.client.local_fallback_used = True
                    LOGGER.exception(
                        "Supabase-olvasási hiba (%s); SQLite tartalék használata.",
                        self.table_name,
                    )
            if remote_read_succeeded:
                merged = {
                    str(row["id"]): dict(row)
                    for row in remote_rows if row.get("id") is not None
                }
                for row in self.client.store.pending_rows(self.table_name):
                    record_id = str(row.get("id"))
                    merged[record_id] = {**merged.get(record_id, {}), **row}
                rows = list(merged.values())
            else:
                rows = self.client.store.rows(self.table_name)
            return SimpleNamespace(data=self._prepare_rows(rows))

        if self.operation in {"insert", "upsert"}:
            values = self.payload if isinstance(self.payload, list) else [self.payload]
            records = []
            for value in values:
                record = dict(value)
                if not record.get("id"):
                    record["id"] = str(uuid.uuid4())
                records.append(record)
            if self.client.remote is not None:
                try:
                    query = self.client.remote.table(self.table_name)
                    query = query.insert(records) if self.operation == "insert" else query.upsert(records)
                    response = query.execute()
                    saved = response.data or records
                    self.client.store.cache_remote(self.table_name, saved)
                    for row in saved:
                        self.client.store.mark_synced(self.table_name, row["id"], row)
                    return SimpleNamespace(data=saved)
                except Exception:
                    self.client.local_fallback_used = True
                    LOGGER.exception(
                        "Supabase-%s hiba (%s); rekordok helyi SQLite-ba mentve.",
                        self.operation, self.table_name,
                    )
            saved = [
                self.client.store.save_local(self.table_name, row, pending=True)
                for row in records
            ]
            return SimpleNamespace(data=saved)

        if self.operation == "update":
            if self.client.remote is not None:
                try:
                    response = self._remote_query().execute()
                    rows = response.data or self._fetch_remote_matching_rows() or []
                    self.client.store.cache_remote(self.table_name, rows)
                    for row in rows:
                        self.client.store.mark_synced(self.table_name, row["id"], row)
                    return SimpleNamespace(data=rows)
                except Exception:
                    self.client.local_fallback_used = True
                    LOGGER.exception(
                        "Supabase-update hiba (%s); módosítás helyi SQLite-ba kerül.",
                        self.table_name,
                    )
                    remote_matches = self._fetch_remote_matching_rows()
                else:
                    remote_matches = []
            else:
                remote_matches = None
            if remote_matches is None:
                base_rows = self.client.store.rows(self.table_name)
            else:
                by_id = {
                    str(row.get("id")): dict(row)
                    for row in remote_matches if row.get("id") is not None
                }
                for row in self.client.store.pending_rows(self.table_name):
                    by_id[str(row.get("id"))] = {**by_id.get(str(row.get("id")), {}), **row}
                base_rows = list(by_id.values())
            rows = self._prepare_rows(base_rows, project=False)
            updated = []
            for row in rows:
                changed = self.client.store.save_local(
                    self.table_name, {**row, **self.payload}, pending=True
                )
                updated.append(changed)
            return SimpleNamespace(data=updated)

        if self.operation == "delete":
            if self.client.remote is not None:
                try:
                    response = self._remote_query().execute()
                    rows = response.data or self._prepare_rows(
                        self.client.store.rows(self.table_name), project=False
                    )
                    ids = [row["id"] for row in rows if row.get("id") is not None]
                    self.client.store.mark_deleted(self.table_name, ids)
                    for record_id in ids:
                        self.client.store.mark_delete_synced(self.table_name, record_id)
                    return SimpleNamespace(data=rows)
                except Exception:
                    self.client.local_fallback_used = True
                    LOGGER.exception(
                        "Supabase-delete hiba (%s); törlési jelölés helyben rögzítve.",
                        self.table_name,
                    )
                    remote_matches = self._fetch_remote_matching_rows()
                else:
                    remote_matches = []
            else:
                remote_matches = None
            if remote_matches is None:
                base_rows = self.client.store.rows(self.table_name)
            else:
                by_id = {
                    str(row.get("id")): dict(row)
                    for row in remote_matches if row.get("id") is not None
                }
                for row in self.client.store.pending_rows(self.table_name):
                    by_id[str(row.get("id"))] = {**by_id.get(str(row.get("id")), {}), **row}
                base_rows = list(by_id.values())
            rows = self._prepare_rows(base_rows, project=False)
            ids = [row["id"] for row in rows if row.get("id") is not None]
            self.client.store.mark_deleted(self.table_name, ids)
            return SimpleNamespace(data=rows)

        raise RuntimeError(f"Nem támogatott Supabase-művelet: {self.operation}")


class ResilientSupabaseClient:
    def __init__(self, remote=None, store=None):
        self.remote = remote
        self.store = store or SQLiteFallbackStore()
        self.local_fallback_used = remote is None
        if self.remote is not None:
            self.sync_pending()

    def table(self, table_name):
        if table_name not in SUPPORTED_TABLES:
            raise ValueError(f"Nem támogatott WORLD SHARDS tábla: {table_name}")
        return ResilientQuery(self, table_name)

    def sync_pending(self):
        """Best-effort replay of writes persisted during earlier DB capacity failures."""
        if self.remote is None:
            return
        pending, deleted = self.store.pending_records()
        table_order = {
            "shard_content_items": 0,
            "shard_editions": 1,
            "shard_edition_items": 2,
            "publications": 3,
        }
        pending.sort(
            key=lambda item: (
                table_order.get(item["table_name"], 99),
                item["record_id"],
            )
        )
        deleted.sort(
            key=lambda item: (
                -table_order.get(item["table_name"], 99),
                item["record_id"],
            )
        )
        for item in pending:
            try:
                self.remote.table(item["table_name"]).upsert(item["payload"]).execute()
                self.store.mark_synced(
                    item["table_name"], item["record_id"], item["payload"]
                )
                LOGGER.info(
                    "Korábbi helyi rekord visszaszinkronizálva: %s/%s",
                    item["table_name"], item["record_id"],
                )
            except Exception:
                self.local_fallback_used = True
                LOGGER.warning(
                    "Helyi rekord visszaszinkronizálása még nem sikerült: %s/%s",
                    item["table_name"], item["record_id"],
                )
                break
        for item in deleted:
            try:
                self.remote.table(item["table_name"]).delete().eq(
                    "id", item["record_id"]
                ).execute()
                self.store.mark_delete_synced(item["table_name"], item["record_id"])
            except Exception:
                self.local_fallback_used = True
                LOGGER.warning(
                    "Helyi törlés visszaszinkronizálása még nem sikerült: %s/%s",
                    item["table_name"], item["record_id"],
                )
                break


def create_resilient_client(url=None, key=None):
    """Create a remote-primary client, or a local-only client when credentials are absent."""
    remote = None
    if url and key:
        try:
            from supabase import create_client
            remote = create_client(url, key)
        except Exception:
            LOGGER.exception("Supabase-kliens nem hozható létre; SQLite-only mód aktiválva.")
    else:
        LOGGER.warning(
            "Supabase-hitelesítő adat hiányzik; a napi folyamat SQLite-only módban indul."
        )
    return ResilientSupabaseClient(remote=remote)
