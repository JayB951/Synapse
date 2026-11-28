import unittest
from unittest.mock import patch

import edition_builder
import shards_collector_m14


class FakeQuery:
    def __init__(self, database):
        self.database = database
        self.filters = {}
        self.action = "select"
        self.payload = None
        self.limit_value = None

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.filters[field] = value
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.action = "insert"
        self.payload = payload
        return self

    def execute(self):
        matches = [
            row for row in self.database.rows
            if all(row.get(key) == value for key, value in self.filters.items())
        ]

        if self.action == "select":
            return type("Response", (), {"data": matches[:self.limit_value]})()

        if self.action == "update":
            for row in matches:
                row.update(self.payload)
            return type("Response", (), {"data": matches})()

        if self.action == "insert":
            row = dict(self.payload)
            row["id"] = f"new-{len(self.database.rows) + 1}"
            self.database.rows.append(row)
            return type("Response", (), {"data": [row]})()

        raise AssertionError(f"Unknown action: {self.action}")


class FakeSupabase:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def table(self, _name):
        return FakeQuery(self)


def comic(number):
    return {
        "num": number,
        "img": f"https://imgs.xkcd.com/comics/{number}.png",
        "title": f"Test comic {number}",
        "alt": f"Alt text {number}",
        "transcript": "",
        "year": "2026",
        "month": "11",
        "day": "27",
    }


class XkcdNoRepeatTests(unittest.TestCase):
    def test_used_latest_comic_is_skipped_for_newest_unused(self):
        database = FakeSupabase([{
            "id": "used-3329",
            "source_url": "https://xkcd.com/3329/",
            "status": "selected",
            "image_url": "https://imgs.xkcd.com/comics/3329.png",
        }])

        with patch.object(
            shards_collector_m14,
            "fetch_xkcd_comic",
            side_effect=lambda number=None: comic(3329 if number is None else number),
        ) as fetch:
            result = shards_collector_m14.collect_xkcd(database)

        self.assertEqual(result["comic_number"], 3328)
        self.assertEqual(result["saved"], 1)
        self.assertEqual(database.rows[0]["status"], "selected")
        self.assertEqual(database.rows[1]["source_url"], "https://xkcd.com/3328/")
        self.assertEqual(fetch.call_count, 2)

    def test_unused_candidate_is_reused_without_changing_its_status(self):
        database = FakeSupabase([{
            "id": "candidate-3329",
            "source_url": "https://xkcd.com/3329/",
            "status": "candidate",
            "image_url": "old-image.png",
        }])

        with patch.object(
            shards_collector_m14,
            "fetch_xkcd_comic",
            return_value=comic(3329),
        ) as fetch:
            result = shards_collector_m14.collect_xkcd(database)

        self.assertEqual(result["comic_number"], 3329)
        self.assertEqual(result["reactivated"], 1)
        self.assertEqual(database.rows[0]["status"], "candidate")
        self.assertEqual(database.rows[0]["image_url"], comic(3329)["img"])
        fetch.assert_called_once_with()

    def test_xkcd_record_preserves_alt_transcript_and_license_metadata(self):
        record = shards_collector_m14.build_xkcd_record({
            **comic(3330),
            "alt": "A precise visual description.",
            "transcript": "Character 1: Hello.\nCharacter 2: Goodbye.",
        })
        metadata = record["metadata"]
        self.assertEqual(metadata["alt_text"], "A precise visual description.")
        self.assertEqual(metadata["transcript"], "Character 1: Hello.\nCharacter 2: Goodbye.")
        self.assertEqual(metadata["source_license"], "CC BY-NC 2.5")
        self.assertEqual(metadata["source_license_url"], "https://creativecommons.org/licenses/by-nc/2.5/")

    def test_xkcd_record_rejects_missing_title_or_alt_text(self):
        for invalid in (
            {**comic(3331), "title": ""},
            {**comic(3332), "alt": ""},
        ):
            with self.assertRaises(RuntimeError):
                shards_collector_m14.build_xkcd_record(invalid)

    def test_xkcd_record_rejects_untrusted_image_host(self):
        with self.assertRaises(RuntimeError):
            shards_collector_m14.build_xkcd_record({
                **comic(3333),
                "img": "https://example.com/comic.png",
            })

    def test_builder_prefers_highest_unused_comic_number(self):
        candidates = [
            {"id": "older", "title": "xkcd 3328", "metadata": {"comic_number": 3328}},
            {"id": "joke", "title": "A joke", "metadata": {"joke_id": 77}},
            {"id": "newer", "title": "xkcd 3329", "metadata": {"comic_number": 3329}},
        ]

        with patch.object(edition_builder, "get_candidates", return_value=candidates):
            selected = edition_builder.select_closing_items(object())

        self.assertEqual([item["id"] for item in selected], ["newer", "joke"])


if __name__ == "__main__":
    unittest.main()
