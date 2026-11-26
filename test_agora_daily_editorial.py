import unittest

from agora_daily_editorial import _has_source_url, build_editorial_output
from agora_historical_figures_testdata import CATALOG


class IndependentCoverageTests(unittest.TestCase):
    def test_accepts_one_verified_article_url(self):
        event = {"articles": [
            {"source_code": "a", "url": "https://a.example/story"},
            {"source_code": "b", "url": "http://b.example/story"},
        ]}
        self.assertTrue(_has_source_url(event))

    def test_multiple_publishers_remain_a_valid_quality_signal(self):
        event = {"articles": [
            {"source_code": "a", "url": "https://wire.example/story"},
            {"source_code": "b", "url": "https://wire.example/story"},
        ]}
        self.assertTrue(_has_source_url(event))

    def test_one_publisher_with_one_url_is_accepted(self):
        event = {"articles": [
            {"source_code": "a", "url": "https://wire.example/story"},
        ]}
        self.assertTrue(_has_source_url(event))

    def test_missing_article_url_is_rejected(self):
        event = {"articles": [
            {"source_code": "a", "title": "Cikk URL nélkül"},
        ]}
        self.assertFalse(_has_source_url(event))


class DailyEditorialIntegrationTests(unittest.TestCase):
    def test_builds_two_scoped_outputs_and_commentary_briefs(self):
        pipeline = {
            "pipeline": "AGORA_PIPELINE_M2.4",
            "generated_at": "2026-11-26T12:00:00+00:00",
            "groups": [
                {"event_id": "hu1", "scope": "hungary",
                 "representative_title": "Vita az alkotmányos hatalommegosztásról",
                 "articles": [{"summary": "A jogállam és a hatalmi ágak ellenőrzése."}]},
                {"event_id": "int1", "scope": "international",
                 "representative_title": "Infláció és munkanélküliség nő",
                 "articles": [{"summary": "A gazdasági visszaesés és a költségvetési válasz."}]}
            ],
            "daily_selection": {
                "hungary": {"event_id": "hu1"},
                "international": {"event_id": "int1"}
            }
        }
        result = build_editorial_output(pipeline, CATALOG)
        self.assertIn("hungary", result["daily_editorial"])
        self.assertIn("international", result["daily_editorial"])
        self.assertGreater(result["daily_editorial"]["hungary"]["historical_selection"]["selected_count"], 0)
        self.assertGreater(result["daily_editorial"]["international"]["historical_selection"]["selected_count"], 0)
        self.assertFalse(result["quality_gates"]["publishing_performed"])

    def test_missing_event_does_not_invent_person_or_brief(self):
        pipeline = {"daily_selection": {"hungary": {"event_id": None},
                                        "international": {"event_id": None}}}
        result = build_editorial_output(pipeline, CATALOG)
        self.assertEqual(result["daily_editorial"]["hungary"]["status"], "no_event_selected")
        self.assertIsNone(result["daily_editorial"]["hungary"]["commentary_package"])


if __name__ == "__main__":
    unittest.main()
