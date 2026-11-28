import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m13 = load_module("collector_m13", "shards_collector_m13.py")
m14 = load_module("collector_m14", "shards_collector_m14.py")
music = load_module("music_collector", "music_collector.py")
processor = load_module("edition_processor", "edition_processor.py")
builder = load_module("edition_builder", "edition_builder.py")


def page(title, extract):
    return {"title": title, "extract": extract}


def test_battlefield_accepts_bulge_and_d_day_but_rejects_general_topics():
    assert m13.is_valid_battle_article(page(
        "Battle of the Bulge",
        "The Battle of the Bulge was a major German offensive campaign fought "
        "on the Western Front during World War II."
    ))
    assert m13.is_valid_battle_article(page(
        "D-Day",
        "The Normandy landings were the Allied amphibious landing operations "
        "during the invasion of Normandy in World War II."
    ))
    assert m13.is_valid_battle_article(page(
        "Normandy landings",
        "The Normandy landings were the Allied amphibious landing operations "
        "during the invasion of Normandy."
    ))
    assert not m13.is_valid_battle_article(page(
        "History of World War II",
        "This article surveys the military history and major events of the war."
    ))


def test_fundamentals_requires_a_concrete_concept():
    assert m13.is_valid_fundamentals_article(page(
        "Conservation of energy",
        "In physics, conservation of energy is the principle that the total "
        "energy of an isolated system remains constant."
    ))
    assert not m13.is_valid_fundamentals_article(page(
        "Physics",
        "Physics is the natural science that studies matter, its motion and behavior."
    ))


def test_unsolved_requires_a_specific_case_not_a_general_mystery_topic():
    assert m14.is_unsolved_candidate(page(
        "The Wow! signal",
        "The Wow! signal is a strong narrowband radio signal detected in 1977. "
        "Its origin remains unexplained and it has not been observed again."
    ))
    assert not m14.is_unsolved_candidate(page(
        "Historical mysteries",
        "Historical mysteries have fascinated people for centuries. "
        "Many events, objects and people from the past remain debated."
    ))
    assert not m14.is_unsolved_candidate(page(
        "A general history article",
        "The identity of one minor participant is unknown, but the subject "
        "of this article is otherwise well documented and resolved."
    ))


def test_joke_record_has_a_valid_id_range_source_and_full_two_part_body():
    record = m14.build_joke_record({
        "id": 42,
        "category": "Programming",
        "type": "twopart",
        "setup": "Why did the programmer quit?",
        "delivery": "Because they didn't get arrays.",
    })
    assert "idRange=42-42" in record["source_url"]
    assert "Why did the programmer quit?" in record["body"]
    assert "Because they didn't get arrays." in record["body"]


def test_joke_prompt_explicitly_preserves_the_punchline():
    prompt = processor.build_prompt("closing", {
        "title": "Why did the programmer quit?",
        "summary": "Why did the programmer quit?",
        "body": "Why did the programmer quit?\n\nBecause they didn't get arrays.",
        "source_name": "JokeAPI",
        "source_url": "https://v2.jokeapi.dev/joke/Any?idRange=42-42",
        "source_language": "en",
        "metadata": {"source_provider": "JokeAPI", "joke_id": 42, "joke_type": "twopart"},
    })
    assert "CSATTANÓT" in prompt
    assert "teljes vicc" in prompt.lower()



def test_joke_record_rejects_missing_id_and_uses_stable_id_source():
    assert m14.build_joke_record({
        "category": "Misc",
        "type": "single",
        "joke": "A complete joke.",
    }) is None
    record = m14.build_joke_record({
        "id": 314,
        "category": "Misc",
        "type": "single",
        "joke": "A complete joke.",
    })
    assert record["source_url"].endswith("idRange=314-314")
    assert record["metadata"]["joke_id"] == 314


def test_joke_candidate_selection_prefers_less_recently_used_category():
    candidates = [
        {"metadata": {"joke_id": 1, "category": "Programming"}, "title": "A"},
        {"metadata": {"joke_id": 2, "category": "Misc"}, "title": "B"},
        {"metadata": {"joke_id": 3, "category": "Dark"}, "title": "C"},
    ]
    chosen = builder.choose_joke_candidate(
        candidates,
        recent_categories=["Programming", "Programming", "Misc"],
    )
    assert chosen["title"] == "C"


def test_joke_translation_review_requires_natural_complete_punchline():
    source = {
        "metadata": {"joke_type": "twopart"},
    }
    generated = {
        "title": "Programozói felmondás",
        "summary": "Egy technikai félreértés története",
        "body": "Miért mondott fel a programozó?\n\nMert nem kapott tömböket.",
    }
    accepted = {
        "complete": True,
        "meaning_preserved": True,
        "punchline_preserved": True,
        "natural_hungarian": True,
        "joke_logic_preserved": True,
        "reason": "A felvezetés és a csattanó kapcsolata megmaradt.",
    }
    assert processor.joke_translation_passes(source, generated, accepted)
    accepted["punchline_preserved"] = False
    assert not processor.joke_translation_passes(source, generated, accepted)
    accepted["punchline_preserved"] = True
    generated["body"] = "Miért mondott fel a programozó? Mert nem kapott tömböket."
    assert not processor.joke_translation_passes(source, generated, accepted)


def test_joke_prompt_requests_humor_adaptation_and_non_repeating_teaser():
    prompt = processor.build_prompt("closing", {
        "title": "Why did the programmer quit?",
        "summary": "Why did the programmer quit?",
        "body": "Why did the programmer quit?\n\nBecause they didn't get arrays.",
        "source_name": "JokeAPI",
        "source_url": "https://v2.jokeapi.dev/joke/Any?idRange=42-42",
        "source_language": "en",
        "metadata": {"source_provider": "JokeAPI", "joke_id": 42, "joke_type": "twopart"},
    })
    assert "természetes" in prompt.lower()
    assert "ne ismételje" in prompt.lower()
    assert "két külön bekezdésben" in prompt.lower()

def test_music_picker_can_exclude_recent_tracks():
    topic = {"title": "The Bulge campaign", "summary": "Battle of the Bulge"}
    tracks = [
        {"trackId": 1, "trackName": "Bulge", "artistName": "Artist",
         "collectionName": "The Bulge", "trackViewUrl": "https://example.com/1"},
        {"trackId": 2, "trackName": "Bulge", "artistName": "Artist",
         "collectionName": "The Bulge", "trackViewUrl": "https://example.com/2"},
    ]
    chosen = music.choose_best_track(tracks, [topic], excluded_track_ids={"1"})
    assert chosen is not None
    assert chosen["track"]["trackId"] == 2


def test_the_thinker_collector_accepts_specific_philosophical_problems_only():
    assert m13.is_valid_thinker_article(page(
        "The Trolley Problem",
        "The trolley problem is a thought experiment in ethics. It asks whether "
        "one may redirect a runaway trolley to kill one person rather than five. "
        "The case is used in moral philosophy to examine consequentialist and "
        "deontological reasoning, including the distinction between doing and allowing harm."
    ))
    assert m13.is_valid_thinker_article(page(
        "The Ship of Theseus",
        "The ship of Theseus is a thought experiment about identity and persistence. "
        "It is discussed in metaphysics and philosophy, asking whether an object "
        "that has had all its parts replaced remains the same object."
    ))
    assert not m13.is_valid_thinker_article(page(
        "Plato",
        "Plato was an ancient Greek philosopher who founded the Academy and wrote "
        "philosophical dialogues. His life and works influenced Western philosophy."
    ))
    assert not m13.is_valid_thinker_article(page(
        "History of Philosophy",
        "The history of philosophy is the study of philosophical ideas across "
        "different periods, traditions and thinkers."
    ))
    assert not m13.is_valid_thinker_article(page(
        "The Theory of Everything",
        "The theory of everything is a hypothetical framework in physics that "
        "would explain all fundamental interactions and particles."
    ))


def test_the_thinker_prompt_requires_argument_counterargument_and_grounding():
    prompt = processor.build_prompt("the_thinker", {
        "title": "The Trolley Problem",
        "summary": "A moral thought experiment.",
        "body": (
            "The trolley problem is a thought experiment in ethics. It asks "
            "whether one may redirect a runaway trolley to kill one person "
            "rather than five. Philosophers use it to examine moral reasoning."
        ),
        "source_name": "Wikipedia",
        "source_url": "https://en.wikipedia.org/wiki/Trolley_problem",
        "source_language": "en",
        "metadata": {},
    })
    assert "legerősebb releváns ellenérvet" in prompt
    assert "Ne találj ki idézetet" in prompt
    assert "5–7 tartalmas" in prompt


def test_the_thinker_editorial_gate_requires_every_quality_dimension():
    accepted = {
        "specific_philosophical_subject": True,
        "central_question_explained": True,
        "reasoning_reconstructed": True,
        "positions_fairly_distinguished": True,
        "counterargument_present": True,
        "contemporary_relevance_reasoned": True,
        "factual_and_historical_grounding": True,
        "substantive_hungarian_article": True,
    }
    assert processor.thinker_content_passes(accepted)
    accepted["counterargument_present"] = False
    assert not processor.thinker_content_passes(accepted)
    assert not processor.thinker_content_passes(None)

