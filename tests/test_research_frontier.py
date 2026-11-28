import importlib.util
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


def test_research_frontier_source_text_includes_bibliography_and_topics():
    source_text = processor.build_source_text(research_source())

    assert "DOI: 10.1234/example.2026" in source_text
    assert "Megjelenés éve: 2026" in source_text
    assert "Publikáció típusa: article" in source_text
    assert "Folyóirat: Journal of Climate Research" in source_text
    assert "Kiadó: Example Academic Press" in source_text
    assert "Szerzők: A. Scientist; B. Researcher" in source_text
    assert "Tudományterületi témák: Oceanography; Climate science" in source_text
    assert "Tárgyszavak: Ocean heat content" in source_text
    assert "Témaköri kifejezések: ocean warming" in source_text


def test_research_frontier_prompt_requires_source_bounded_scientific_reporting():
    prompt = processor.build_prompt("research_frontier", research_source())

    assert "ne találd ki" in prompt.lower()
    assert "teljes tanulmányt elolvastad" in prompt.lower()
    assert "korrelációt ne nevezz oksági kapcsolatnak" in prompt.lower()
    assert "Szerzők: A. Scientist; B. Researcher" in prompt
    assert "Journal of Climate Research" in prompt


def test_non_research_prompt_does_not_use_research_frontier_template():
    prompt = processor.build_prompt(
        "the_thinker",
        {
            "section_code": "the_thinker",
            "title": "A philosophical question",
            "summary": "A short source summary with enough detail.",
            "source_name": "Example",
        },
    )

    assert "A WORLD SHARDS magyar tudományos szerkesztője vagy" not in prompt
