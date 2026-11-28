import edition_processor


def source(alt_text="A scientist explains a surprising result.", transcript=""):
    return {
        "section_code": "closing",
        "title": "xkcd #3330: Test comic",
        "summary": alt_text,
        "body": "Comic title: Test comic",
        "source_name": "xkcd",
        "source_url": "https://xkcd.com/3330/",
        "source_language": "en",
        "metadata": {
            "source_provider": "xkcd",
            "comic_number": 3330,
            "comic_title": "Test comic",
            "alt_text": alt_text,
            "transcript": transcript,
        },
    }


def test_xkcd_prompt_requires_faithful_hungarian_alt_and_no_invention():
    prompt = edition_processor.build_prompt("closing", source(transcript="Scientist: It worked."))
    assert "KÉP LEÍRÁSA" in prompt
    assert "ÁTIRAT" in prompt
    assert "Ne írj hosszú magazincikket" in prompt
    assert "ne találj ki" in prompt.lower()
    assert "Randall Munroe" not in prompt  # attribution is rendered from source metadata


def test_xkcd_translation_requires_alt_description_and_transcript_when_available():
    item = source(transcript="Scientist: It worked.")
    generated = {
        "title": "A meglepő eredmény",
        "summary": "Egy tudományos magyarázat váratlan fordulattal.",
        "body": "KÉP LEÍRÁSA:\nEgy tudós egy meglepő eredményt magyaráz.\n\nÁTIRAT:\nTudós: Sikerült.",
    }
    assert edition_processor.validate_xkcd_translation(item, generated)
    generated["body"] = "KÉP LEÍRÁSA:\nEgy tudós egy meglepő eredményt magyaráz."
    try:
        edition_processor.validate_xkcd_translation(item, generated)
    except RuntimeError as error:
        assert "transcript" in str(error).lower()
    else:
        raise AssertionError("Missing translated transcript must be rejected")


def test_xkcd_prompt_preserves_transcript_speaker_lines():
    item = source(transcript="Scientist 1: First line.\nScientist 2: Second line.")
    prompt = edition_processor.build_prompt("closing", item)
    assert "Scientist 1: First line.\nScientist 2: Second line." in prompt


def test_xkcd_translation_rejects_flattened_transcript_lines():
    item = source(transcript="Scientist 1: First line.\nScientist 2: Second line.")
    generated = {
        "title": "Két tudós",
        "summary": "Két megszólalás.",
        "body": "KÉP LEÍRÁSA:\nKét tudós beszél.\n\nÁTIRAT:\nKutató 1: Első sor. Kutató 2: Második sor.",
    }
    try:
        edition_processor.validate_xkcd_translation(item, generated)
    except RuntimeError as error:
        assert "tagolása" in str(error).lower()
    else:
        raise AssertionError("Flattened transcript speaker lines must be rejected")


def test_xkcd_translation_rejects_invented_transcript():
    item = source(transcript="")
    generated = {
        "title": "A meglepő eredmény",
        "summary": "Egy tudományos magyarázat váratlan fordulattal.",
        "body": "KÉP LEÍRÁSA:\nEgy tudós egy meglepő eredményt magyaráz.\n\nÁTIRAT:\nTudós: Sikerült.",
    }
    try:
        edition_processor.validate_xkcd_translation(item, generated)
    except RuntimeError as error:
        assert "kitalálta" in str(error).lower()
    else:
        raise AssertionError("Invented transcript must be rejected")
