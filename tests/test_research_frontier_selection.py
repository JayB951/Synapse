import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load_module("research_frontier_collector", "shards_collector.py")
builder = load_module("research_frontier_builder", "edition_builder.py")


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, existing_doi):
        self.existing_doi = existing_doi
        self.filters = {}

    def select(self, value):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def contains(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, value):
        return self

    def execute(self):
        requested = (self.filters.get("metadata") or {}).get("doi")
        return FakeResponse([{"id": "existing"}] if requested == self.existing_doi else [])


class FakeClient:
    def __init__(self, existing_doi):
        self.query = FakeQuery(existing_doi)

    def table(self, name):
        return self.query


class ResearchFrontierSelectionTests(unittest.TestCase):
    def test_deduplication_uses_doi_even_when_landing_urls_differ(self):
        client = FakeClient("10.1234/same-paper")
        publication = {
            "id": "synapse-new-id",
            "doi": "10.1234/same-paper",
            "url": "https://publisher.example/article/updated-url",
        }
        self.assertTrue(
            collector.research_publication_exists(client, publication)
        )

    def test_candidate_score_rewards_editorial_readiness_not_empty_metadata(self):
        weak = {"title": "A paper", "abstract": "Short", "metadata": {}}
        strong = {
            "title": "A substantive paper",
            "abstract": "A" * 900,
            "doi": "10.1234/example",
            "journal": "Journal of Example Research",
            "publication_type": "journal-article",
            "metadata": {
                "author_source_ids": [{"name": "A. Author"}],
                "topics": [{"display_name": "Climate science"}],
                "subjects": ["Oceanography"],
            },
        }
        self.assertGreater(
            collector.score_research_publication(strong),
            collector.score_research_publication(weak),
        )

    def test_candidate_score_does_not_claim_to_measure_citation_impact(self):
        publication = {"abstract": "A" * 500, "cited_by_count": 100000}
        self.assertEqual(collector.score_research_publication(publication), 30)

    def test_research_selection_spreads_papers_across_topics(self):
        candidates = [
            {"id": "a", "relevance_score": 50, "metadata": {"synapse_metadata": {"topics": ["Physics"]}}},
            {"id": "b", "relevance_score": 48, "metadata": {"synapse_metadata": {"topics": ["Physics"]}}},
            {"id": "c", "relevance_score": 45, "metadata": {"synapse_metadata": {"topics": ["Biology"]}}},
            {"id": "d", "relevance_score": 43, "metadata": {"synapse_metadata": {"topics": ["History"]}}},
        ]
        chosen = builder.choose_research_candidates(candidates, limit=3)
        self.assertEqual([item["id"] for item in chosen], ["a", "c", "d"])

    def test_research_topic_parser_accepts_openalex_topic_objects(self):
        item = {
            "metadata": {
                "synapse_metadata": {
                    "topics": [{"display_name": "Climate science"}],
                    "subjects": ["Oceanography"],
                }
            }
        }
        self.assertEqual(
            builder.research_topic_keys(item),
            ["climate science", "oceanography"],
        )


if __name__ == "__main__":
    unittest.main()