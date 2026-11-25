import os
import sys
import calendar
import re
import html
from datetime import date
from collections import Counter

import requests


OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"

FETCH_LIMIT = 50
DISPLAY_LIMIT = 10
TIMEOUT_SECONDS = 30

# Az OpenAlex eredeti angol nyelvi API-szűrője megmarad.
# A szövegalapú tartalékellenőrzés a hiányzó/bizonytalan
# nyelvi metaadatú, ténylegesen lekért rekordokra vonatkozik.

ACCEPTED_OPENALEX_TYPES = {
    "article",
    "book",
    "book-chapter",
    "dissertation",
    "preprint",
    "proceedings-article",
    "conference-paper",
    "report",
}

ACCEPTED_CROSSREF_TYPES = {
    "journal-article",
    "proceedings-article",
    "book",
    "book-chapter",
    "posted-content",
    "dissertation",
    "report",
    "monograph",
    "edited-book",
    "reference-entry",
}

EXCLUDED_TYPES = {
    "dataset",
    "software",
    "component",
    "paratext",
    "editorial",
    "journal-editorial",
    "book-review",
    "peer-review",
    "journal-issue",
    "journal-volume",
    "proceedings",
    "journal",
    "book-series",
    "study-registration",
}

REVIEW_TITLES = {
    "index",
    "chronology",
    "contents",
    "table of contents",
    "foreword",
    "preface",
    "acknowledgements",
    "acknowledgments",
}

EXCLUDED_TITLE_PREFIXES = (
    "code for ",
    "software for ",
)

LANGUAGE_WORDS = ("the", "and", "of")
LANGUAGE_WORD_MINIMUM = 3


def get_start_date():
    """A mai naphoz képest 12 hónappal korábbi dátum."""
    today = date.today()
    year = today.year - 1
    day = min(
        today.day,
        calendar.monthrange(year, today.month)[1]
    )
    return date(year, today.month, day)


def print_header(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def request_openalex(start_date, end_date):
    api_key = os.getenv("OPENALEX_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Hiányzik az OPENALEX_API_KEY GitHub Secret."
        )

    params = {
        "api_key": api_key,
        "filter": (
            f"from_publication_date:{start_date},"
            f"to_publication_date:{end_date},"
            "language:en"
        ),
        "per_page": FETCH_LIMIT,
        "sort": "publication_date:desc",
    }

    response = requests.get(
        OPENALEX_URL,
        params=params,
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def request_crossref(start_date, end_date):
    mailto = os.getenv("CROSSREF_MAILTO")

    if not mailto:
        raise RuntimeError(
            "Hiányzik a CROSSREF_MAILTO GitHub Secret."
        )

    params = {
        "filter": (
            f"from-pub-date:{start_date},"
            f"until-pub-date:{end_date}"
        ),
        "rows": FETCH_LIMIT,
        "sort": "published",
        "order": "desc",
        "mailto": mailto,
    }

    headers = {
        "User-Agent": f"SYNAPSE/0.1 (mailto:{mailto})"
    }

    response = requests.get(
        CROSSREF_URL,
        params=params,
        headers=headers,
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json().get("message", {}).get("items", [])


def reconstruct_openalex_abstract(inverted_index):
    """Az OpenAlex pozícióalapú absztraktját normál szöveggé alakítja."""
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""

    positioned_words = []

    for word, positions in inverted_index.items():
        for position in positions:
            try:
                positioned_words.append((int(position), word))
            except (TypeError, ValueError):
                continue

    if not positioned_words:
        return ""

    max_position = max(position for position, _ in positioned_words)

    # Hibás vagy rendellenesen nagy index ne foglalhasson túl sok memóriát.
    if max_position > 20000:
        return ""

    words = [""] * (max_position + 1)

    for position, word in positioned_words:
        words[position] = word

    return " ".join(word for word in words if word)


def clean_abstract(abstract):
    """HTML/XML jelölések és HTML-entitások eltávolítása."""
    if not abstract:
        return ""

    text = html.unescape(str(abstract))
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_language_metadata_status(language):
    """
    Visszatérési érték:
    - 'english': a metaadat egyértelműen angol.
    - 'non_english': a metaadat más nyelvet jelöl.
    - 'unknown': hiányzó vagy nem eldönthető metaadat.
    """
    if language is None:
        return "unknown"

    normalized = str(language).strip().lower().replace("_", "-")

    if not normalized or normalized in {
        "und", "mul", "zxx", "unknown", "undetermined",
        "not specified", "not available",
    }:
        return "unknown"

    if normalized in {"en", "eng", "english"}:
        return "english"

    if normalized.startswith("en-"):
        return "english"

    return "non_english"


def count_language_words(text):
    """A három keresett szót különálló szóként számolja."""
    normalized = (text or "").lower()
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    words = normalized.split()
    counts = Counter(words)

    return {
        word: counts[word]
        for word in LANGUAGE_WORDS
    }


def check_language(language, title="", abstract=""):
    """
    Elsődlegesen a nyelvi metaadat dönt.
    Hiányzó/bizonytalan metaadat esetén a cím + absztrakt
    szövegében mindhárom kulcsszónak legalább háromszor
    kell szerepelnie.
    """
    metadata_status = get_language_metadata_status(language)

    if metadata_status == "english":
        return "ANGOL – METAADAT ALAPJÁN", True

    if metadata_status == "non_english":
        return (
            f"NEM ANGOL – METAADAT ALAPJÁN ({language})",
            False,
        )

    combined_text = f"{title or ''} {abstract or ''}"
    counts = count_language_words(combined_text)

    accepted = all(
        counts[word] >= LANGUAGE_WORD_MINIMUM
        for word in LANGUAGE_WORDS
    )

    count_summary = ", ".join(
        f"{word}={counts[word]}"
        for word in LANGUAGE_WORDS
    )

    if accepted:
        return (
            f"ANGOL – SZÖVEG ALAPJÁN ({count_summary})",
            True,
        )

    return (
        f"NEM ANGOL – SZÖVEGES SZŰRÉS ({count_summary})",
        False,
    )


def run_language_filter_tests():
    """Gyors, hálózat nélküli ellenőrzés a nyelvi szabályokra."""
    valid_text = "the and of " * 3

    assert check_language("en", "Short title", "")[1] is True
    assert check_language("fr", valid_text, "")[1] is False
    assert check_language(None, valid_text, "")[1] is True
    assert check_language("und", valid_text, "")[1] is True
    assert check_language("unknown", valid_text, "")[1] is True
    assert check_language(None, "theory android office " * 5, "")[1] is False
    assert check_language(None, "the and of", "")[1] is False

    reconstructed = reconstruct_openalex_abstract({
        "the": [0, 3, 6],
        "and": [1, 4, 7],
        "of": [2, 5, 8],
    })
    assert reconstructed == valid_text.strip()

    print("Nyelvi szűrő önellenőrzése: SIKERES")


def classify_record(publication_type, accepted_types, title):
    """A rekord típusának és címének együttes értékelése."""
    normalized_title = (title or "").strip().lower()
    normalized_type = (publication_type or "").strip().lower()

    if not normalized_title:
        return "KIZÁRVA – HIÁNYZÓ CÍM"

    if normalized_title.startswith(EXCLUDED_TITLE_PREFIXES):
        return "KIZÁRVA – KÓD VAGY SZOFTVER"

    if normalized_title in REVIEW_TITLES:
        return "ELLENŐRZENDŐ – ÁLTALÁNOS CÍM"

    if normalized_type in EXCLUDED_TYPES:
        return "KIZÁRVA – NEM KÍVÁNT TÍPUS"

    if normalized_type in accepted_types:
        return "ELFOGADHATÓ"

    return "ELLENŐRZENDŐ – ISMERETLEN TÍPUS"


def check_topics(topics):
    if not topics:
        return "HIÁNYZIK – KÉSŐBBI TÉMAAZONOSÍTÁS SZÜKSÉGES"

    return "VAN TÉMAKÖRI ADAT"


def get_crossref_publication_date(item):
    """
    A rendelkezésre álló publikációs dátumok közül
    a legkorábbi érvényes dátum kiválasztása.
    A Crossref rekord létrehozási dátumát nem használjuk.
    """
    date_fields = [
        "published-online",
        "published-print",
        "published",
        "posted",
    ]

    available_dates = []

    for field in date_fields:
        date_parts = (
            item.get(field, {}).get("date-parts") or []
        )

        if not date_parts or not date_parts[0]:
            continue

        parts = date_parts[0]

        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            day = int(parts[2]) if len(parts) > 2 else 1

            available_dates.append(date(year, month, day))
        except (ValueError, TypeError, IndexError):
            continue

    if not available_dates:
        return None

    return min(available_dates).isoformat()


def print_record(index, record):
    print(f"\n{index}. {record['title']}")
    print("Dátum:", record["date"] or "Nincs adat")
    print("Típus:", record["type"] or "Nincs adat")
    print("Besorolás:", record["classification"])
    print("Nyelv:", record["language_status"])
    print("Témák:", check_topics(record["topics"]))

    print(
        "Témakörök:",
        ", ".join(record["topics"][:3])
        if record["topics"]
        else "Nincs adat"
    )

    print(
        "Szerzők:",
        ", ".join(record["authors"][:3])
        if record["authors"]
        else "Nincs adat"
    )

    print(
        "Absztrakt:",
        "Van" if record["abstract"] else "Nincs"
    )


def print_summary(records, source_name):
    counts = Counter(
        record["classification"].split(" – ")[0]
        for record in records
    )

    print("Lekért rekordok:", len(records))
    print("Elfogadható publikáció:", counts["ELFOGADHATÓ"])
    print("Kizárt rekord:", counts["KIZÁRVA"])
    print("Ellenőrzendő rekord:", counts["ELLENŐRZENDŐ"])

    print_header(
        f"{source_name} – ELFOGADHATÓ PUBLIKÁCIÓK MINTÁJA"
    )

    accepted = [
        record for record in records
        if record["classification"] == "ELFOGADHATÓ"
    ]

    if not accepted:
        print("Nem találtunk elfogadható rekordot.")
    else:
        for index, record in enumerate(
            accepted[:DISPLAY_LIMIT],
            start=1
        ):
            print_record(index, record)

    print_header(f"{source_name} – KIZÁRT REKORDOK")

    excluded = [
        record for record in records
        if record["classification"].startswith("KIZÁRVA")
    ]

    if not excluded:
        print("Nincs kizárt rekord.")
    else:
        for index, record in enumerate(excluded[:10], start=1):
            print(
                f"{index}. {record['title']} "
                f"| {record['type']} "
                f"| {record['classification']}"
            )

    print_header(f"{source_name} – ELLENŐRZENDŐ REKORDOK")

    review = [
        record for record in records
        if record["classification"].startswith("ELLENŐRZENDŐ")
    ]

    if not review:
        print("Nincs ellenőrzendő rekord.")
    else:
        for index, record in enumerate(review[:10], start=1):
            print(
                f"{index}. {record['title']} "
                f"| Típus: {record['type']} "
                f"| {record['classification']}"
            )


def apply_language_decision(classification, language_status, is_english):
    """A nyelvi kizárás minden publikációtípus-besorolást megelőz."""
    if not is_english:
        return "KIZÁRVA – NEM ANGOL"

    return classification


def process_openalex(records):
    print_header("OPENALEX – ADATMINŐSÉGI ELLENŐRZÉS")

    classified = []

    for item in records:
        publication_type = item.get("type") or ""
        title = item.get("title") or ""
        abstract_text = reconstruct_openalex_abstract(
            item.get("abstract_inverted_index")
        )

        topics = [
            topic.get("display_name", "")
            for topic in (item.get("topics") or [])
            if topic.get("display_name")
        ]

        authors = [
            authorship.get("author", {}).get("display_name", "")
            for authorship in (item.get("authorships") or [])
            if authorship.get("author", {}).get("display_name")
        ]

        base_classification = classify_record(
            publication_type,
            ACCEPTED_OPENALEX_TYPES,
            title,
        )

        language_status, is_english = check_language(
            item.get("language"),
            title,
            abstract_text,
        )

        classification = apply_language_decision(
            base_classification,
            language_status,
            is_english,
        )

        classified.append({
            "title": title,
            "date": item.get("publication_date"),
            "type": publication_type,
            "language": item.get("language"),
            "language_status": language_status,
            "topics": topics,
            "authors": authors,
            "abstract": abstract_text,
            "classification": classification,
        })

    print_summary(classified, "OPENALEX")
    return classified


def process_crossref(records):
    print_header("CROSSREF – ADATMINŐSÉGI ELLENŐRZÉS")

    classified = []

    for item in records:
        titles = item.get("title") or []
        title = titles[0] if titles else ""

        publication_type = item.get("type") or ""
        subjects = item.get("subject") or []
        abstract_text = clean_abstract(item.get("abstract"))

        authors = []

        for author in item.get("author") or []:
            name = " ".join(
                part for part in [
                    author.get("given", ""),
                    author.get("family", ""),
                ]
                if part
            )

            if name:
                authors.append(name)

        base_classification = classify_record(
            publication_type,
            ACCEPTED_CROSSREF_TYPES,
            title,
        )

        language_status, is_english = check_language(
            item.get("language"),
            title,
            abstract_text,
        )

        classification = apply_language_decision(
            base_classification,
            language_status,
            is_english,
        )

        classified.append({
            "title": title,
            "date": get_crossref_publication_date(item),
            "type": publication_type,
            "language": item.get("language"),
            "language_status": language_status,
            "topics": subjects,
            "authors": authors,
            "abstract": abstract_text,
            "classification": classification,
        })

    print_summary(classified, "CROSSREF")
    return classified


def main():
    print_header("SYNAPSE – ADATMINŐSÉGI TESZT")

    run_language_filter_tests()

    start_date = get_start_date()
    end_date = date.today()

    print("Gyűjtési időszak:", start_date, "-", end_date)
    print("Forrásonkénti lekérési limit:", FETCH_LIMIT)
    print("Megjelenített elfogadható rekordok:", DISPLAY_LIMIT)
    print("Adatbázisba mentés: NINCS")
    print("OpenAlex language:en API-szűrés: MEGTARTVA")
    print("Bizonytalan nyelvű rekord: szövegalapú szűrés")
    print("Szöveges feltétel: the, and, of – mindegyik legalább 3x")

    try:
        openalex_records = request_openalex(start_date, end_date)
        crossref_records = request_crossref(start_date, end_date)

        openalex_classified = process_openalex(openalex_records)
        crossref_classified = process_crossref(crossref_records)

        print_header("SYNAPSE – ÖSSZESÍTÉS")

        print("OpenAlex rekordok:", len(openalex_classified))
        print("Crossref rekordok:", len(crossref_classified))
        print(
            "Összes lekért rekord:",
            len(openalex_classified) + len(crossref_classified),
        )
        print("Supabase adatbázis módosítása: NEM")

    except requests.exceptions.HTTPError as error:
        status_code = (
            error.response.status_code
            if error.response is not None
            else "ismeretlen"
        )
        print("API HTTP HIBA:", status_code)
        print("Az API nem fogadta el a lekérdezést.")
        sys.exit(1)

    except requests.exceptions.RequestException as error:
        print("HÁLÓZATI HIBA:", str(error))
        sys.exit(1)

    except (RuntimeError, ValueError) as error:
        print("BEÁLLÍTÁSI HIBA:", str(error))
        sys.exit(1)


if __name__ == "__main__":
    main()
