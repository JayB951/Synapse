import unittest

from agora_news_selection import (
    INTERNATIONAL_NEWS_SYSTEM,
    select_hungarian_news_event,
    select_international_news_event,
)
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
            {"id": "interpretation", "draft_text": "A politikai intézmények működését a hatalmi viszonyok felől értelmezi, mert a válságok idején különösen láthatóvá válik, hogy a szabályok mennyire korlátozzák a vezetőket. A közösség biztonsága nem pusztán a döntéshozók szándékától függ, hanem attól is, hogy az intézmények képesek-e ellenőrizni egymást. Amikor a felelősségi körök világosak, a hibák feltárása gyorsabbá válik, és a közbizalom is könnyebben helyreáll. Ezért a történelmi tanulság az, hogy a rend tartósságát nem az erő, hanem az elszámoltatható intézményrendszer biztosítja.",
             "evidence_notes": ["A politikai intézményekről szóló elemzéshez kapcsolódik."],
             "source_titles": ["A fejedelem"]},
            {"id": "consequences", "draft_text": "A következményeket a hatalom stabilitása és az intézmények ellenálló képessége felől vizsgálja, mert egyetlen rossz döntés hatása messze túlterjedhet az adott eseményen. Ha a felelősség elmosódik, akkor a hibák ismétlődnek, miközben a polgárok egyre kevésbé bíznak a közös szabályokban. A válság így nemcsak közvetlen károkat okoz, hanem az intézményi együttműködést is gyengítheti. Ugyanakkor a következmények mérsékelhetők, ha a döntések indokai nyilvánosak, és a korrekció lehetősége minden érintett számára biztosított.",
             "evidence_notes": ["A fejedelemségek és politikai rend elemzése releváns."],
             "source_titles": ["A fejedelem"]},
            {"id": "response", "draft_text": "A megoldásnál a politikai célokat az intézményi korlátokkal együtt kell mérlegelni, mert a gyors cselekvés önmagában még nem garantál jó eredményt. A vezetőknek világos felelősséget kell vállalniuk, miközben független ellenőrzésnek is működnie kell. Az intézmények akkor őrzik meg hitelességüket, ha a szabályokat a nehéz helyzetekben is következetesen alkalmazzák, és a hibák kijavítása nem válik politikai presztízskérdéssé. Ezért a tartós megoldás az átláthatóság, az együttműködés és a számonkérhetőség összehangolása lehet.",
             "evidence_notes": ["A mű politikai cselekvésről szóló gondolatmenete releváns."],
             "source_titles": ["Beszélgetések"]},
        ],
        "historical_disclosure": "Hipotetikus rekonstrukció.",
        "direct_quote_used": False,
    }


class InternationalNewsSelectionTests(unittest.TestCase):
    def test_selects_only_an_id_from_the_candidate_list(self):
        candidates = [
            {"event_id": "sport", "scope": "international",
             "representative_title": "Champions League final result",
             "articles": [{"title": "The final", "summary": "A football result."}]},
            {"event_id": "world", "scope": "international",
             "representative_title": "Major international climate agreement",
             "articles": [{"title": "Countries reach climate agreement",
                           "summary": "A multi-country agreement changes emissions commitments."}]},
        ]
        client = FakeClient([{
            "selected_event_id": "world",
            "internal_rationale": "Nemzetközi, hosszú távú következményekkel járó fejlemény.",
            "excluded_candidates": [{"event_id": "sport", "reason": "Sporthír."}],
        }])
        result = select_international_news_event(candidates, client)
        self.assertEqual(result["selected_event_id"], "world")
        self.assertEqual(result["status"], "selected")
        self.assertIn("Sport minden formája", client.calls[0][0])
        self.assertIn("Duran Duran", client.calls[0][0])
        self.assertIn("Budapest XII. kerület", client.calls[0][0])
        self.assertIn("kizárólag magyarországi", client.calls[0][0].lower())

    def test_empty_selection_is_a_valid_editorial_decision(self):
        client = FakeClient([{
            "selected_event_id": "",
            "internal_rationale": "A jelöltek egyike sem éri el a hírértékküszöböt.",
            "excluded_candidates": [],
        }])
        result = select_international_news_event(
            [{"event_id": "local", "scope": "international",
              "representative_title": "Budapest district council meeting"}],
            client,
        )
        self.assertEqual(result["status"], "no_qualifying_news")
        self.assertEqual(result["selected_event_id"], "")

    def test_rejects_an_event_id_not_in_the_candidate_list(self):
        client = FakeClient([{
            "selected_event_id": "invented",
            "internal_rationale": "not allowed",
            "excluded_candidates": [],
        }])
        with self.assertRaises(GeminiError):
            select_international_news_event(
                [{"event_id": "real", "representative_title": "Real event"}],
                client,
            )

    def test_empty_candidate_list_does_not_call_gemini(self):
        client = FakeClient([])
        result = select_international_news_event([], client)
        self.assertEqual(result["status"], "no_candidates")
        self.assertEqual(client.calls, [])


class HungarianNewsSelectionTests(unittest.TestCase):
    def test_selects_hungarian_event_using_editorial_merit_not_political_quota(self):
        client = FakeClient([{
            "selected_event_id": "hu-story",
            "internal_rationale": "Közérdekű, több forrásból megerősített fejlemény.",
            "excluded_candidates": [],
        }])
        result = select_hungarian_news_event([
            {"event_id": "hu-story", "scope": "hungary",
             "representative_title": "Jelentős egészségügyi fejlesztés"},
        ], client)
        self.assertEqual(result["status"], "selected")
        self.assertIn("Nincs politikai kvóta", client.calls[0][0])
        self.assertIn("jelentős magyar vonatkozású", client.calls[0][0])


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

    def test_simulator_regenerates_short_commentary_before_failing(self):
        invalid = simulation_response()
        invalid["sections"][0]["draft_text"] = "Ez egy túl rövid mondat."
        client = FakeClient([invalid, simulation_response()])
        result = simulate_historical_figure(EVENT, PROFILE, client)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(result["sections"]), 3)

    def test_simulator_uses_second_repair_when_first_repair_is_still_short(self):
        invalid_first = simulation_response()
        invalid_first["sections"][0]["draft_text"] = "Ez egy túl rövid mondat."
        invalid_second = simulation_response()
        invalid_second["sections"][1]["draft_text"] = (
            "A következményeket azért vizsgálja, mert a döntések hatással vannak az intézményekre. "
            "A közösség biztonsága az együttműködéstől is függ. "
            "A felelősségi körök akkor világosak, ha minden szereplő elszámoltatható. "
            "Ezért a bizalom helyreállítása hosszú folyamat."
        )
        client = FakeClient([invalid_first, invalid_second, simulation_response()])
        result = simulate_historical_figure(EVENT, PROFILE, client)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(len(result["sections"]), 3)

    def test_news_source_urls_keep_valid_http_and_https_links(self):
        event = {
            **EVENT,
            "articles": EVENT["articles"] + [{
                "source_name": "Másik kiadó",
                "title": "Második forrás",
                "url": "http://news.example/second",
                "published_at": "2026-11-26T10:00:00Z",
                "summary": "Második ellenőrző forrás.",
            }],
        }
        result = simulate_historical_figure(event, PROFILE, FakeClient([simulation_response()]))
        self.assertIn("http://news.example/second", result["sections"][0]["news_source_urls"])

    def test_simulator_derives_missing_evidence_notes_from_catalogue(self):
        response = simulation_response()
        response["sections"][0]["evidence_notes"] = []
        response["sections"][0]["source_titles"] = []
        client = FakeClient([response])
        result = simulate_historical_figure(EVENT, PROFILE, client)
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(result["sections"][0]["evidence_notes"])
        self.assertTrue(result["sections"][0]["source_urls"])

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
