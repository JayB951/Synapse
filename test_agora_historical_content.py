import unittest

from agora_historical_matching import match_figure, select_historical_figures, validate_catalog
from agora_commentary_briefs import build_commentary_package


CATALOG = {
    "figures": [
        {
            "id": "montesquieu", "name": "Montesquieu", "topics": ["rule_of_law"],
            "keywords": ["hatalmi ágak", "alkotmány", "separation of powers"],
            "core_ideas": ["A hatalom megosztása."],
            "works": [{"title": "A törvények szelleméről", "url": "https://example.org/work"}],
            "limits": "Történeti kontextus szükséges."
        },
        {
            "id": "keynes", "name": "John Maynard Keynes", "topics": ["economics"],
            "keywords": ["infláció", "munkanélküliség", "inflation"],
            "core_ideas": ["Makrogazdasági stabilizáció."],
            "works": [{"title": "Általános elmélet", "url": "https://example.org/keynes"}],
            "limits": "A körülmények számítanak."
        }
    ]
}


class HistoricalMatchingTests(unittest.TestCase):
    def test_catalog_validation(self):
        self.assertTrue(validate_catalog(CATALOG))

    def test_match_uses_title_and_article_summary(self):
        event = {
            "representative_title": "Vita a hatalmi ágak szétválasztásáról",
            "articles": [{"summary": "Az alkotmányos intézmények szerepe."}]
        }
        result = match_figure(event, CATALOG["figures"][0])
        self.assertIsNotNone(result)
        self.assertIn("hatalmi ágak", result["matched_keywords"])

    def test_unrelated_person_is_not_forced_into_selection(self):
        event = {"representative_title": "Helyi sporteredmény", "articles": []}
        result = select_historical_figures(event, CATALOG)
        self.assertEqual(result["selected_count"], 0)
        self.assertEqual(result["status"], "no_relevant_figure_found")

    def test_maximum_three_and_deterministic_order(self):
        event = {"representative_title": "Infláció és munkanélküliség"}
        result = select_historical_figures(event, CATALOG, limit=3)
        self.assertEqual(result["selected_count"], 1)
        self.assertEqual(result["figures"][0]["figure_id"], "keynes")

    def test_profile_requires_source_urls(self):
        invalid = {"figures": [{"id": "bad", "name": "Bad", "topics": ["x"],
            "keywords": ["x"], "core_ideas": ["x"], "works": [{"title": "x", "url": "http://bad"}],
            "limits": "x"}]}
        with self.assertRaises(ValueError):
            validate_catalog(invalid)


class CommentaryBriefTests(unittest.TestCase):
    def test_three_sections_and_hypothetical_disclosure(self):
        event = {"event_id": "e1", "representative_title": "Alkotmányos vita"}
        selection = select_historical_figures(
            event, CATALOG
        )
        package = build_commentary_package(event, selection)
        self.assertEqual(package["commentary_count"], 3)
        brief = package["briefs"][0]
        self.assertEqual([s["id"] for s in brief["sections"]],
                         ["interpretation", "consequences", "response"])
        self.assertTrue(brief["mandatory_disclosures"]["hypothetical_reconstruction"])
        self.assertFalse(brief["mandatory_disclosures"]["direct_quote_used"])
        self.assertEqual(brief["publication_status"], "not_ready")

    def test_no_match_produces_no_commentary(self):
        event = {"event_id": "e2", "representative_title": "Sport"}
        package = build_commentary_package(event, select_historical_figures(event, CATALOG))
        self.assertEqual(package["figure_count"], 0)
        self.assertEqual(package["commentary_count"], 0)


if __name__ == "__main__":
    unittest.main()
