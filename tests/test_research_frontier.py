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

    def test_prompt_requires_source_bounded_scientific_reporting(self):
        prompt = processor.build_prompt("research_frontier", research_source())

        self.assertIn("ne találd ki", prompt.lower())
        self.assertIn("teljes tanulmányt elolvastad", prompt.lower())
        self.assertIn("korrelációt ne nevezz oksági kapcsolatnak", prompt.lower())
        self.assertIn("Szerzők: A. Scientist; B. Researcher", prompt)
        self.assertIn("Journal of Climate Research", prompt)

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
