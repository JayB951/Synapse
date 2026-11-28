import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = load_module("art_collector", "shards_collector.py")
processor = load_module("art_processor", "edition_processor.py")
builder = load_module("art_builder", "edition_builder.py")


def artwork(**overrides):
    record = {
        "id": 123,
        "title": "A Garden in Spring",
        "is_public_domain": True,
        "image_id": "image-123",
        "artist_title": "Example Artist",
        "artist_display": "Example Artist (1870–1940)",
        "date_display": "1902",
        "medium_display": "Oil on canvas",
        "description": "A detailed museum description of the artwork and its historical context. " * 5,
        "place_of_origin": "France",
        "style_title": "Impressionism",
        "classification_title": "Painting",
        "dimensions": "50 × 70 cm",
    }
    record.update(overrides)
    return record


def test_art_candidate_requires_public_domain_and_a_real_image():
    assert collector.build_artwork_record(
        artwork(image_id=None), "painting"
    ) is None
    assert collector.build_artwork_record(
        artwork(is_public_domain=False), "painting"
    ) is None
    assert collector.build_artwork_record(
        artwork(id=None), "painting"
    ) is None


def test_art_record_uses_official_medium_field_and_keeps_editorial_metadata():
    item = collector.build_artwork_record(artwork(), "painting")
    assert item is not None
    assert item["image_url"] == (
        "https://www.artic.edu/iiif/2/image-123/full/843,/0/default.jpg"
    )
    assert item["relevance_score"] >= 80
    assert item["metadata"]["medium"] == "Oil on canvas"
    assert item["metadata"]["artist"] == "Example Artist (1870–1940)"
    assert item["metadata"]["style_title"] == "Impressionism"
    assert "Keletkezés: 1902" in item["summary"]


def test_art_quality_score_rewards_complete_museum_metadata():
    complete = collector.score_artwork(artwork())
    sparse = collector.score_artwork({
        "title": "Untitled",
        "image_id": "image-sparse",
    })
    assert complete > sparse
    assert complete <= 100


def test_art_search_rotation_uses_two_distinct_themes(monkeypatch):
    monkeypatch.setattr(collector, "now_utc", lambda: __import__("datetime").datetime(
        2026, 11, 28, tzinfo=__import__("datetime").timezone.utc
    ))
    terms = collector.get_art_search_terms()
    assert len(terms) == 2
    assert terms[0] != terms[1]
    assert all(term in collector.ART_SEARCH_TERMS for term in terms)


def test_collect_art_queries_public_domain_image_records_and_saves_unique_items(monkeypatch):
    calls = []
    saved = []

    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": self.data}

    def fake_get(url, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        if len(calls) == 1:
            return Response([artwork(), artwork(id=124, title="Another Garden")])
        return Response([artwork(), artwork(id=125, title="A Sculpture")])

    monkeypatch.setattr(collector.requests, "get", fake_get)
    monkeypatch.setattr(collector.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        collector, "save_content",
        lambda client, item: saved.append(item) or "inserted"
    )
    result = collector.collect_art(object())

    assert len(calls) == 2
    assert len(saved) == 3
    assert result == {"inserted": 3, "skipped": 1}
    query = json.loads(calls[0][1]["query"])
    filters = query["bool"]["filter"]
    assert {"term": {"is_public_domain": True}} in filters
    assert {"exists": {"field": "image_id"}} in filters
    assert "medium_display" in calls[0][1]["fields"]
    assert calls[0][1]["size"] == collector.ART_LIMIT
    assert calls[0][2]["AIC-User-Agent"]


def test_art_candidate_selection_balances_quality_with_recent_artist_and_style():
    candidates = [
        {
            "title": "High score but repeated",
            "relevance_score": 92,
            "metadata": {"artist": "Known Artist", "style_title": "Impressionism"},
        },
        {
            "title": "Fresh artist and style",
            "relevance_score": 75,
            "metadata": {"artist": "Different Artist", "style_title": "Baroque"},
        },
    ]
    chosen = builder.choose_art_candidate(
        candidates,
        recent_styles=["Impressionism"],
        recent_artists=["Known Artist"],
    )
    assert chosen["title"] == "Fresh artist and style"


def test_art_candidate_selection_returns_none_for_empty_candidates():
    assert builder.choose_art_candidate([]) is None


def test_art_prompt_is_specific_long_form_and_rejects_invented_facts():
    prompt = processor.build_prompt("art_of_the_day", {
        "title": "A Garden in Spring",
        "summary": "Artist: Example Artist; Date: 1902; Oil on canvas.",
        "body": "",
        "source_name": "Art Institute of Chicago",
        "source_url": "https://www.artic.edu/artworks/123",
        "source_language": "en",
        "metadata": {
            "artist": "Example Artist",
            "date_display": "1902",
            "medium": "Oil on canvas",
            "style_title": "Impressionism",
        },
    })
    assert "legalább 4" in prompt
    assert "Ne találj ki dátumot" in prompt
    assert "vizuális" in prompt
    assert "üres általánosságokat" not in prompt


def test_art_editorial_gate_requires_every_quality_dimension():
    verdict = {
        "source_fidelity": True,
        "artist_context_grounded": True,
        "creation_and_technique_grounded": True,
        "visual_analysis_responsible": True,
        "significance_explained": True,
        "specific_and_substantive": True,
        "reason": "A cikk pontos és kellően részletes.",
    }
    assert processor.art_content_passes(verdict)
    verdict["source_fidelity"] = False
    assert not processor.art_content_passes(verdict)
    assert not processor.art_content_passes(None)


def test_art_review_uses_structured_editorial_verdict(monkeypatch):
    verdict = {
        "source_fidelity": True,
        "artist_context_grounded": True,
        "creation_and_technique_grounded": True,
        "visual_analysis_responsible": True,
        "significance_explained": True,
        "specific_and_substantive": True,
        "reason": "Részletes, forráshű elemzés.",
    }
    monkeypatch.setattr(processor, "call_gemini", lambda prompt, response_schema=None: json.dumps(verdict))
    source = {
        "title": "A Garden in Spring",
        "summary": "A museum artwork.",
        "source_name": "Art Institute of Chicago",
        "source_language": "en",
        "metadata": {"artist": "Example Artist", "date_display": "1902"},
    }
    generated = {
        "title": "Tavaszi kert",
        "summary": "Egy festmény a természet átalakulásáról.",
        "body": "Első bekezdés. " * 20,
    }
    assert processor.art_content_passes(processor.review_art_content(source, generated))
