import unittest
from datetime import datetime, timezone

from agora_editorial_qa import build_review_template, evaluate_quality
from agora_world_shards_adapter import build_content_item

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
DIMENSIONS = ("interpretation", "consequences", "response")
SCOPES = ("hungary", "international")


def make_package(scope, event_id, keyword):
    figures = []
    for i in range(3):
        figure_id = f"{scope}_figure_{i}"
        figures.append({
            "figure_id": figure_id,
            "name": f"Historical Figure {scope} {i}",
            "sections": [
                {"id": dimension, "label": dimension.title(),
                 "draft_text": f"Reviewed {dimension} text for {keyword}.",
                 "evidence_notes": ["Primary source checked."],
                 "source_urls": ["https://example.org/history"]}
                for dimension in DIMENSIONS
            ],
        })
    return {
        "status": "editorial_research_required",
        "historical_selection": {
            "event_id": event_id,
            "selected_count": 3,
            "figures": [{"figure_id": f["figure_id"], "name": f["name"]} for f in figures],
        },
        "commentary_package": {"briefs": figures},
    }


def complete_review(editorial):
    review = build_review_template(editorial)
    review["approved"] = True
    review["editor_name"] = "Test Editor"
    review["reviewed_at"] = NOW.isoformat()
    review["checks"] = {key: True for key in review["checks"]}
    for scope in SCOPES:
        for figure in review["scope_reviews"][scope]["figure_reviews"]:
            for section in figure["sections"].values():
                section["text_completed"] = True
                section["historical_claims_cited"] = True
                section["present_day_claims_cited"] = True
    return review


def fixture():
    groups = []
    for scope, event_id, title, keyword in (
        ("hungary", "hu1", "Alkotmányos vita és hatalommegosztás", "alkotmány"),
        ("international", "int1", "Nemzetközi gazdasági válság", "gazdaság"),
    ):
        groups.append({
            "event_id": event_id, "scope": scope, "representative_title": title,
            "latest_published_at": NOW.isoformat(), "score": 90,
            "articles": [
                {"source_code": "publisher_a", "source_name": "Publisher A",
                 "title": title, "url": "https://example.org/a", "published_at": NOW.isoformat(),
                 "summary": f"Verified summary about {keyword}."},
                {"source_code": "publisher_b", "source_name": "Publisher B",
                 "title": title, "url": "https://example.net/b", "published_at": NOW.isoformat(),
                 "summary": f"Independent summary about {keyword}."},
            ],
        })
    pipeline = {"generated_at": NOW.isoformat(), "groups": groups}
    editorial = {"daily_editorial": {
        "hungary": make_package("hungary", "hu1", "alkotmány"),
        "international": make_package("international", "int1", "gazdaság"),
    }}
    return pipeline, editorial


class EditorialQATests(unittest.TestCase):
    def test_complete_editorial_and_human_review_approves(self):
        pipeline, editorial = fixture()
        review = complete_review(editorial)
        result = evaluate_quality(pipeline, editorial, review, now=NOW)
        self.assertTrue(result["approved"])
        self.assertEqual(result["status"], "approved")

    def test_single_source_blocks_approval(self):
        pipeline, editorial = fixture()
        pipeline["groups"][0]["articles"] = pipeline["groups"][0]["articles"][:1]
        review = complete_review(editorial)
        result = evaluate_quality(pipeline, editorial, review, now=NOW)
        self.assertFalse(result["approved"])
        self.assertIn("independent_sources_min_2",
                      [item["code"] for item in result["checks"] if not item["passed"]])

    def test_blank_review_template_cannot_approve(self):
        pipeline, editorial = fixture()
        result = evaluate_quality(pipeline, editorial, build_review_template(editorial), now=NOW)
        self.assertFalse(result["approved"])
        self.assertEqual(result["status"], "blocked")

    def test_adapter_refuses_unapproved_qa(self):
        pipeline, editorial = fixture()
        with self.assertRaises(ValueError):
            build_content_item(pipeline, editorial, {"approved": False}, "2026-11-26")

    def test_adapter_emits_world_shards_content_item_contract(self):
        pipeline, editorial = fixture()
        review = complete_review(editorial)
        qa = evaluate_quality(pipeline, editorial, review, now=NOW)
        record = build_content_item(pipeline, editorial, qa, "2026-11-26")
        for field in ("section_code", "title", "summary", "body", "source_name",
                      "source_url", "source_published_at", "collected_at", "status",
                      "relevance_score", "metadata"):
            self.assertIn(field, record)
        self.assertEqual(record["section_code"], "agora")
        self.assertEqual(record["status"], "candidate")
        self.assertEqual(len(record["metadata"]["news_items"]), 2)
        self.assertEqual(len(record["metadata"]["historical_figures"]), 6)
        self.assertFalse(record["metadata"]["publishing_performed"])


if __name__ == "__main__":
    unittest.main()
