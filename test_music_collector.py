import unittest
from unittest.mock import Mock

from music_collector import (
    build_music_record,
    choose_best_track,
    deduplicate_tracks,
    fetch_itunes_tracks,
    music_record_exists_for_date,
    score_track,
    is_valid_music_record,
)


class MusicCollectorTests(unittest.TestCase):

    def setUp(self):
        self.topic = {
            "id": "topic-1",
            "section_code": "research_frontier",
            "title": "Quantum Computing Breakthrough",
            "summary": "Researchers demonstrate a new quantum processor.",
            "body": "Quantum computing processor research.",
        }
        self.track = {
            "trackId": 123,
            "trackName": "Quantum",
            "artistName": "Example Artist",
            "collectionName": "Quantum Computing",
            "releaseDate": "2020-01-01T00:00:00Z",
            "trackViewUrl": "https://music.apple.com/us/album/quantum/123",
            "previewUrl": "https://example.org/preview",
        }

    def test_offline_mock_itunes_response(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"resultCount": 1, "results": [self.track]}
        http_get = Mock(return_value=response)

        result = fetch_itunes_tracks("quantum computing", http_get=http_get)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["trackId"], 123)
        http_get.assert_called_once()

    def test_track_ranking_prefers_title_match(self):
        direct = dict(self.track)
        unrelated = dict(
            self.track,
            trackId=456,
            trackName="Love Song",
            collectionName="Greatest Hits",
            artistName="Quantum",
        )

        self.assertGreater(
            score_track(direct, self.topic),
            score_track(unrelated, self.topic),
        )
        chosen = choose_best_track([unrelated, direct], [self.topic])
        self.assertEqual(chosen["track"]["trackId"], 123)

    def test_duplicate_tracks_are_removed(self):
        duplicate = dict(self.track)
        self.assertEqual(
            len(deduplicate_tracks([self.track, duplicate])),
            1,
        )

    def test_missing_listening_link_is_rejected(self):
        missing_link = dict(self.track)
        missing_link.pop("trackViewUrl")
        self.assertIsNone(choose_best_track([missing_link], [self.topic]))

    def test_record_keeps_original_listening_link_and_metadata(self):
        selection = {
            "track": self.track,
            "topic": self.topic,
            "score": 4,
        }
        record = build_music_record(selection, "2026-11-25")

        self.assertEqual(record["section_code"], "music_of_the_day")
        self.assertEqual(record["source_url"], self.track["trackViewUrl"])
        self.assertEqual(record["metadata"]["edition_date"], "2026-11-25")
        self.assertFalse(record["metadata"]["full_track_downloaded"])

    def test_flag_code_placeholder_is_rejected_as_music(self):
        bad_record = {
            "title": "Heard Island and McDonald Islands – Flag098",
            "source_url": "https://music.apple.com/us/album/example/123",
            "metadata": {
                "track_name": "Flag098",
                "artist_name": "Heard Island and McDonald Islands",
                "edition_date": "2026-11-27",
            },
        }
        good_record = {
            "title": "Queen – Bohemian Rhapsody",
            "source_url": "https://music.apple.com/us/album/bohemian-rhapsody/123",
            "metadata": {
                "track_name": "Bohemian Rhapsody",
                "artist_name": "Queen",
                "edition_date": "2026-11-27",
            },
        }
        self.assertFalse(is_valid_music_record(bad_record))
        self.assertTrue(is_valid_music_record(good_record))

    def test_idempotency_lookup_uses_edition_date(self):
        class FakeResponse:
            data = [{"id": "existing-1", "title": "Existing song", "status": "candidate"}]

        class FakeQuery:
            def __init__(self):
                self.calls = []

            def select(self, value):
                self.calls.append(("select", value))
                return self

            def eq(self, key, value):
                self.calls.append(("eq", key, value))
                return self

            def contains(self, key, value):
                self.calls.append(("contains", key, value))
                return self

            def neq(self, key, value):
                self.calls.append(("neq", key, value))
                return self

            def limit(self, value):
                self.calls.append(("limit", value))
                return self

            def execute(self):
                return FakeResponse()

        class FakeSupabase:
            def __init__(self):
                self.query = FakeQuery()

            def table(self, name):
                self.table_name = name
                return self.query

        client = FakeSupabase()
        result = music_record_exists_for_date(client, "2026-11-25")

        self.assertEqual(result["id"], "existing-1")
        self.assertEqual(client.table_name, "shard_content_items")
        self.assertIn(
            ("contains", "metadata", {"edition_date": "2026-11-25"}),
            client.query.calls,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
