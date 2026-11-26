import unittest
from datetime import datetime, timezone

from agora_pipeline import (
    build_daily_selection,
    build_pipeline_result,
    freshness_points,
    rank_events,
    score_event,
)


NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def event(event_id, scope="hungary", hours_old=2, sources=None, articles=None):
    from datetime import timedelta
    published = (NOW - timedelta(hours=hours_old)).isoformat()
    sources = sources or ["telex"]
    articles = articles or [{
        "source_code": source,
        "url": "https://example.com/" + source,
        "published_at": published,
        "summary": "A short factual summary.",
    } for source in sources]
    return {
        "event_id": event_id,
        "scope": scope,
        "representative_title": event_id,
        "latest_published_at": published,
        "independent_source_count": len(sources),
        "source_codes": sources,
        "articles": articles,
    }


class AgoraPipelineTests(unittest.TestCase):

    def test_freshness_bands_and_stale_events(self):
        self.assertEqual(freshness_points((NOW).isoformat(), NOW), 40)
        from datetime import timedelta
        self.assertEqual(freshness_points((NOW - timedelta(hours=12)).isoformat(), NOW), 35)
        self.assertEqual(freshness_points((NOW - timedelta(hours=36)).isoformat(), NOW), 25)
        self.assertEqual(freshness_points((NOW - timedelta(hours=60)).isoformat(), NOW), 15)
        self.assertEqual(freshness_points((NOW - timedelta(hours=80)).isoformat(), NOW), 0)
        self.assertEqual(freshness_points(None, NOW), 0)

    def test_more_independent_sources_improve_score(self):
        one = score_event(event("one", sources=["telex"]), NOW)["score"]
        three = score_event(event("three", sources=["telex", "hvg", "bbc"]), NOW)["score"]
        self.assertGreater(three, one)

    def test_political_orientation_is_not_a_score_input(self):
        item = event("neutral")
        first = score_event(item, NOW)["score"]
        item["political_orientation"] = "anything"
        self.assertEqual(first, score_event(item, NOW)["score"])

    def test_hungary_and_international_shortlists_are_separate(self):
        result = rank_events([
            event("hu", "hungary"),
            event("world", "international"),
        ], now=NOW)
        self.assertEqual(result["hungary"]["events"][0]["event_id"], "hu")
        self.assertEqual(result["international"]["events"][0]["event_id"], "world")

    def test_stale_event_is_not_eligible_for_daily_proposal(self):
        ranked = rank_events([event("old", hours_old=90)], now=NOW)
        self.assertFalse(ranked["hungary"]["events"][0]["eligible_for_daily_proposal"])

    def test_daily_selection_proposes_one_per_scope_and_requires_review(self):
        lists = rank_events([
            event("hu-1", "hungary", sources=["telex", "hvg"]),
            event("hu-2", "hungary"),
            event("world-1", "international", sources=["bbc", "dw"]),
        ], now=NOW)
        chosen = build_daily_selection(lists)
        self.assertEqual(chosen["hungary"]["event_id"], "hu-1")
        self.assertEqual(chosen["international"]["event_id"], "world-1")
        self.assertTrue(chosen["hungary"]["editorial_review_required"])

    def test_pipeline_never_publishes(self):
        payload = {
            "candidate_count": 1,
            "source_count": 1,
            "failed_sources": [],
            "candidates": [{
                "source_code": "telex",
                "source_name": "Telex",
                "scope": "hungary",
                "language": "hu",
                "title": "Árvízvédelmi készültség",
                "url": "https://example.com/a",
                "summary": "A short summary",
                "published_at": NOW.isoformat(),
            }],
        }
        result = build_pipeline_result(payload, now=NOW)
        self.assertFalse(result["publishing"]["performed"])
        self.assertEqual(result["publishing"]["status"], "candidate_generation_only")
        self.assertIn("hungary", result["shortlists"])
        self.assertIn("international", result["shortlists"])


if __name__ == "__main__":
    unittest.main()
