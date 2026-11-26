import unittest

from agora_gemini_engine import (
    GeminiError,
    build_gemini_commentary_package,
    select_historical_figures,
    simulate_historical_figure,
)


class FakeClient:
    model = "gemini-3.8-flash"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_json(self, system, payload, schema):
        self.calls.append((system, payload, schema))
        return self.responses.pop(0)


PROFILE = {
    "id": "machiavelli",
    "name": "Niccolò Machiavelli",
    "lifespan": "1469–1527",
    "era": "reneszánsz Itália",
    "domains": ["political_theory", "statecraft"],
    "topics": ["power", "governance", "diplomacy"],
    "core_ideas": ["A politikai cselekvést a hatalom és az intézmények összefüggésében vizsgálta."],
    "works": [
        {"title": "A fejedelem", "url": "https://example.org/prince", "type": "primary_text"},
        {"title": "Beszélgetések", "url": "https://example.org/discourses", "type": "primary_text"},
    ],
    "limits": "Nem egyszerűsíthető egyetlen közhelyre.",
}
EVENT = {
    "event_id": "event-1",
    "scope": "hungary",
    "representative_title": "Alkotmányos és hatalmi válság",
    "articles": [{"source_name": "Hírforrás", "title": "A mai esemény", "url": "https://news.example/item",
                  "published_at": "2026-11-26T10:00:00Z", "summary": "Ellenőrzött tényösszefoglaló."}],
}


def simulation_response():
    return {
        "sections": [
            {"id": "interpretation", "draft_text": "Az intézmények és a hatalmi viszonyok felől értelmezi az eseményt.",
             "evidence_notes": ["A politikai intézményekről szóló elemzéshez kapcsolódik."],
             "source_titles": ["A fejedelem"]},
            {"id": "consequences", "draft_text": "A következményeket a hatalom stabilitása és az intézmények ellenálló képessége felől vizsgálja.",
             "evidence_notes": ["A fejedelemségek és politikai rend elemzése releváns."],
             "source_titles": ["A fejedelem"]},
            {"id": "response", "draft_text": "A megoldásnál a politikai célok és az intézményi korlátok együttes mérlegelését javasolja.",
             "evidence_notes": ["A mű politikai cselekvésről szóló gondolatmenete releváns."],
             "source_titles": ["Beszélgetések"]},
        ],
        "historical_disclosure": "Hipotetikus rekonstrukció.",
        "direct_quote_used": False,
    }


class GeminiEngineTests(unittest.TestCase):
    def test_selector_uses_catalog_ids_and_internal_rationale(self):
        client = FakeClient([{
            "selected_figure_ids": ["machiavelli", "aristotle", "cicero"],
            "internal_rationale": "A releváns intézményi és hatalmi gondolkodás miatt.",
        }])
        catalog = {"figures": [PROFILE, {**PROFILE, "id": "aristotle", "name": "Arisztotelész"},
                               {**PROFILE, "id": "cicero", "name": "Cicero"}]}
        result = select_historical_figures(EVENT, catalog, client)
        self.assertEqual(result["selected_count"], 3)
        self.assertEqual(result["figures"][0]["figure_id"], "machiavelli")
        self.assertEqual(result["figures"][0]["selection_rationale_internal"], "A releváns intézményi és hatalmi gondolkodás miatt.")

    def test_selector_rejects_duplicate_or_unknown_ids(self):
        client = FakeClient([{"selected_figure_ids": ["machiavelli", "machiavelli"],
                              "internal_rationale": "duplicate"}])
        with self.assertRaises(GeminiError):
            select_historical_figures(EVENT, {"figures": [PROFILE]}, client)

    def test_simulator_returns_three_coherent_dimensions_with_catalog_sources(self):
        client = FakeClient([simulation_response()])
        result = simulate_historical_figure(EVENT, PROFILE, client)
        self.assertEqual([item["id"] for item in result["sections"]],
                         ["interpretation", "consequences", "response"])
        self.assertTrue(all(item["source_urls"] for item in result["sections"]))
        self.assertTrue(result["mandatory_disclosures"]["hypothetical_reconstruction"])
        self.assertFalse(result["mandatory_disclosures"]["direct_quote_used"])

    def test_simulator_rejects_unlisted_historical_source(self):
        response = simulation_response()
        response["sections"][0]["source_titles"] = ["Kitalált mű"]
        with self.assertRaises(GeminiError):
            simulate_historical_figure(EVENT, PROFILE, FakeClient([response]))

    def test_simulator_rejects_direct_quote(self):
        response = simulation_response()
        response["direct_quote_used"] = True
        with self.assertRaises(GeminiError):
            simulate_historical_figure(EVENT, PROFILE, FakeClient([response]))

    def test_package_runs_one_separate_call_per_figure(self):
        selection = {"figures": [PROFILE, {**PROFILE, "id": "figure2"}, {**PROFILE, "id": "figure3"}]}
        client = FakeClient([simulation_response(), simulation_response(), simulation_response()])
        package = build_gemini_commentary_package(EVENT, selection, client)
        self.assertEqual(package["figure_count"], 3)
        self.assertEqual(package["commentary_count"], 9)
        self.assertEqual(len(client.calls), 3)


if __name__ == "__main__":
    unittest.main()
