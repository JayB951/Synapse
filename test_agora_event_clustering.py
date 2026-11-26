import unittest

from agora_event_clustering import (
    cluster_candidates,
    normalize_title,
    same_event_candidate,
    title_similarity,
)


def article(source, title, url, scope="hungary", language="hu",
            published_at="2026-11-26T10:00:00+00:00"):
    return {
        "source_code": source,
        "source_name": source,
        "title": title,
        "url": url,
        "scope": scope,
        "language": language,
        "published_at": published_at,
    }


class AgoraEventClusteringTests(unittest.TestCase):

    def test_similar_titles_from_independent_publishers_are_grouped(self):
        items = [
            article("telex", "Súlyos árvíz fenyegeti a Duna menti településeket",
                    "https://telex.hu/a/1"),
            article("hvg", "Árvíz veszélyezteti a Duna-parti településeket",
                    "https://hvg.hu/a/2"),
        ]
        result = cluster_candidates(items, similarity_threshold=0.45)
        self.assertEqual(result["group_count"], 1)
        self.assertEqual(result["groups"][0]["independent_source_count"], 2)

    def test_unrelated_titles_are_not_grouped(self):
        items = [
            article("telex", "A kormány új költségvetést nyújtott be",
                    "https://telex.hu/a/1"),
            article("hvg", "Magyar kutatók új bolygót fedeztek fel",
                    "https://hvg.hu/a/2"),
        ]
        self.assertEqual(cluster_candidates(items)["group_count"], 2)

    def test_hungarian_and_international_pools_never_merge(self):
        items = [
            article("telex", "Major earthquake strikes the region",
                    "https://telex.hu/a/1", scope="hungary", language="hu"),
            article("bbc", "Major earthquake strikes the region",
                    "https://bbc.com/a/2", scope="international", language="en"),
        ]
        self.assertEqual(cluster_candidates(items)["group_count"], 2)

    def test_same_url_from_two_sources_preserves_both_sources(self):
        items = [
            article("telex", "Azonos hír", "https://example.hu/story"),
            article("hvg", "Másik cím", "https://example.hu/story"),
        ]
        result = cluster_candidates(items)
        self.assertEqual(result["group_count"], 1)
        self.assertEqual(result["groups"][0]["article_count"], 2)
        self.assertEqual(result["groups"][0]["independent_source_count"], 2)

    def test_distant_dates_do_not_fuzzy_merge(self):
        items = [
            article("telex", "Árvíz fenyegeti a Duna mentét",
                    "https://telex.hu/a/1"),
            article("hvg", "Árvíz fenyegeti a Duna mentét",
                    "https://hvg.hu/a/2",
                    published_at="2026-12-01T10:00:00+00:00"),
        ]
        self.assertEqual(cluster_candidates(items)["group_count"], 2)

    def test_missing_dates_do_not_allow_fuzzy_merge(self):
        items = [
            article("telex", "Árvíz fenyegeti a Duna mentét",
                    "https://telex.hu/a/1", published_at=None),
            article("hvg", "Árvíz fenyegeti a Duna mentét",
                    "https://hvg.hu/a/2", published_at=None),
        ]
        self.assertEqual(cluster_candidates(items)["group_count"], 2)

    def test_output_is_deterministic(self):
        items = [
            article("telex", "Azonos című hír", "https://telex.hu/a/1"),
            article("hvg", "Azonos című hír", "https://hvg.hu/a/2"),
        ]
        self.assertEqual(cluster_candidates(items), cluster_candidates(items))

    def test_normalization_and_similarity(self):
        self.assertEqual(normalize_title("  Árvíz: HELYZET!  "), "árvíz helyzet")
        self.assertGreater(
            title_similarity(
                {"title": "Árvíz fenyegeti a Duna menti településeket", "language": "hu"},
                {"title": "Árvízveszély a Duna mentén: települések készülnek", "language": "hu"},
            ),
            0.3,
        )


if __name__ == "__main__":
    unittest.main()
