import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "research_frontier_processor",
    ROOT / "edition_processor.py",
)
processor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(processor)


def research_source():
    return {
        "section_code": "research_frontier",
        "title": "A study of ocean heat uptake",
        "summary": (
            "We investigate ocean heat uptake using a global observational "
            "dataset and compare regional trends."
        ),
        "source_name": "SYNAPSE",
        "source_language": "en",
        "source_url": "https://doi.org/10.1234/example.2026",
        "metadata": {
            "doi": "10.1234/example.2026",
            "publication_year": 2026,
            "publication_type": "article",
            "journal": "Journal of Climate Research",
            "publisher": "Example Academic Press",
            "synapse_metadata": {
                "author_source_ids": [
                    {"position": 2, "name": "B. Researcher"},
                    {"position": 1, "name": "A. Scientist"},
                ],
                "topics": ["Oceanography", "Climate science"],
                "subjects": ["Ocean heat content"],
                "topic_terms": [{"term": "ocean warming"}],
            },
        },
    }


class ResearchFrontierTests(unittest.TestCase):
    def test_source_text_includes_bibliography_and_topics(self):
        source_text = processor.build_source_text(research_source())

        self.assertIn("DOI: 10.1234/example.2026", source_text)
        self.assertIn("Megjelenés éve: 2026", source_text)
        self.assertIn("Publikáció típusa: article", source_text)
        self.assertIn("Folyóirat: Journal of Climate Research", source_text)
        self.assertIn("Kiadó: Example Academic Press", source_text)
        self.assertIn("Szerzők: A. Scientist; B. Researcher", source_text)
        self.assertIn("Tudományterületi témák: Oceanography; Climate science", source_text)
        self.assertIn("Tárgyszavak: Ocean heat content", source_text)
        self.assertIn("Témaköri kifejezések: ocean warming", source_text)

    def test_prompt_requires_significance_novelty_challenge_and_synthesis(self):
        prompt = processor.build_prompt("research_frontier", research_source())

        self.assertIn("miért jelentős", prompt.lower())
        self.assertIn("novelty", prompt.lower())
        self.assertIn("challenge", prompt.lower())
        self.assertIn("synthesis", prompt.lower())
        self.assertIn("teljes tanulmányt elolvastad", prompt.lower())
        self.assertIn("korrelációt ne nevezz oksági kapcsolatnak", prompt.lower())
        self.assertIn("Szerzők: A. Scientist; B. Researcher", prompt)
        self.assertIn("Journal of Climate Research", prompt)

    def test_research_frontier_parser_accepts_only_the_five_part_contract(self):
        generated = {
            "title": "Az óceáni hőfelvétel új vizsgálata",
            "summary": "A kutatás új megfigyelési adatokkal pontosítja az óceáni hőfelvétel regionális mintázatait.",
            "novelty": (
                "A tanulmány globális megfigyelési adatokat kapcsol össze regionális elemzéssel. "
                "Ez a megközelítés a korábbi általános trendeknél részletesebb képet ad. "
                "Az absztrakt nem nevez meg közvetlenül összehasonlított korábbi tanulmányt."
            ),
            "challenge": (
                "Az absztrakt nem ismerteti kellő részletességgel, hogyan választották ki "
                "a megfigyelési adatokat, ezért a regionális különbségek robusztussága nem ítélhető meg."
            ),
            "synthesis": (
                "Az eredmények fontos regionális mintázatokat jeleznek, de az absztrakt alapján "
                "azok módszertani stabilitása még nem ellenőrizhető."
            )
        }
        parsed = processor.parse_generated_content(
            json.dumps(generated, ensure_ascii=False),
            section_code="research_frontier"
        )
        self.assertEqual(parsed["summary"], generated["summary"])
        self.assertIn("novelty", parsed)
        self.assertIn("challenge", parsed)
        self.assertIn("synthesis", parsed)
        self.assertNotIn("body", parsed)

    def test_research_frontier_rejects_overlong_critical_challenge(self):
        generated = {
            "title": "Az óceáni hőfelvétel új vizsgálata",
            "summary": "A kutatás új megfigyelési adatokkal pontosítja az óceáni hőfelvétel regionális mintázatait.",
            "novelty": (
                "A tanulmány globális megfigyelési adatokat kapcsol össze regionális elemzéssel. "
                "Ez a megközelítés a korábbi általános trendeknél részletesebb képet ad. "
                "Az absztrakt nem nevez meg közvetlenül összehasonlított korábbi tanulmányt."
            ),
            "challenge": " ".join(["Ez a kritika túl hosszú."] * 4),
            "synthesis": "Az eredmények fontos regionális mintázatokat jeleznek, de az absztrakt alapján a stabilitásuk nem ellenőrizhető."
        }
        with self.assertRaisesRegex(RuntimeError, "1–3 mondat"):
            processor.parse_generated_content(
                json.dumps(generated, ensure_ascii=False),
                section_code="research_frontier"
            )

    def test_non_research_prompt_does_not_use_research_frontier_template(self):
        prompt = processor.build_prompt(
            "the_thinker",
            {
                "section_code": "the_thinker",
                "title": "A philosophical question",
                "summary": "A short source summary with enough detail.",
                "source_name": "Example",
            },
        )

        self.assertNotIn(
            "A WORLD SHARDS magyar tudományos szerkesztője vagy",
            prompt,
        )
