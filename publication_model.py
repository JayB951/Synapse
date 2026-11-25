
"""
SYNAPSE – Egységes publikációs adatmodell
Verzió: M2.6 / 0.2

Feladat:
- OpenAlex rekordok egységesítése
- Crossref rekordok egységesítése
- DOI normalizálása
- Szerzők, dátumok, absztraktok és témakörök kinyerése
- Forrásspecifikus azonosítók megőrzése
- Témakörök és tárgyszavak közös listába rendezése
- Témaköri források visszakövethetősége

Nincs hálózati kapcsolat.
Nincs Supabase kapcsolat.
Nincs adatbázisba írás.
"""

import re
import html
from datetime import date


MODEL_VERSION = "0.2"


def normalize_doi(doi):
    """DOI egységesítése."""

    if not doi:
        return None

    value = str(doi).strip()

    value = re.sub(
        r"^https?://(dx\.)?doi\.org/",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^doi:\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = value.strip().lower()

    if not value or not value.startswith("10."):
        return None

    return value


def normalize_openalex_id(openalex_id):
    """OpenAlex azonosító egységesítése."""

    if not openalex_id:
        return None

    value = str(openalex_id).strip().rstrip("/")

    return value or None


def clean_text(value):
    """HTML és felesleges szóközök eltávolítása."""

    if not value:
        return None

    text = html.unescape(str(value))
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip() or None


def normalize_authors(authors):
    """Szerzőlista egységesítése."""

    if not isinstance(authors, list):
        return []

    result = []

    for author in authors:
        if isinstance(author, str):
            name = clean_text(author)

        elif isinstance(author, dict):
            name = clean_text(
                author.get("name")
                or author.get("display_name")
            )

        else:
            name = None

        if name and name not in result:
            result.append(name)

    return result


def normalize_date(value):
    """Dátum ellenőrzése és ISO-formátumra alakítása."""

    if not value:
        return None

    try:
        parsed = date.fromisoformat(str(value)[:10])
        return parsed.isoformat()

    except (ValueError, TypeError):
        return None


def get_crossref_date(item):
    """Crossref publikációs dátumának kinyerése."""

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

            available_dates.append(
                date(year, month, day)
            )

        except (ValueError, TypeError, IndexError):
            continue

    if not available_dates:
        return None

    return min(available_dates).isoformat()


def reconstruct_abstract(inverted_index):
    """OpenAlex pozícióalapú absztrakt visszaállítása."""

    if not isinstance(inverted_index, dict):
        return None

    positioned_words = []

    for word, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue

        for position in positions:
            try:
                positioned_words.append(
                    (int(position), word)
                )
            except (ValueError, TypeError):
                continue

    if not positioned_words:
        return None

    max_position = max(
        position for position, _ in positioned_words
    )

    if max_position > 20000:
        return None

    words = [""] * (max_position + 1)

    for position, word in positioned_words:
        words[position] = str(word)

    result = " ".join(
        word for word in words if word
    )

    return clean_text(result)


def normalize_topics(topics):
    """OpenAlex témakörök kinyerése."""

    if not isinstance(topics, list):
        return []

    result = []

    for topic in topics:
        if isinstance(topic, str):
            name = clean_text(topic)

        elif isinstance(topic, dict):
            name = clean_text(
                topic.get("display_name")
                or topic.get("name")
            )

        else:
            name = None

        if name and name not in result:
            result.append(name)

    return result


def normalize_subjects(subjects):
    """Crossref tárgyszavak kinyerése."""

    if not isinstance(subjects, list):
        return []

    result = []

    for subject in subjects:
        value = clean_text(subject)

        if value and value not in result:
            result.append(value)

    return result


def normalize_topic_name(value):
    """
    Témakör egységesített összehasonlítási alakja.

    Csak kis- és nagybetű, illetve szóközkülönbségeket
    normalizál. Szemantikai összevonást nem végez.
    """

    cleaned = clean_text(value)

    if not cleaned:
        return None

    return " ".join(cleaned.casefold().split())


def build_topic_terms(topics=None, subjects=None):
    """
    Közös témaköri lista létrehozása.

    A topics az OpenAlex, a subjects a Crossref adatait
    tartalmazza. Az azonos normalizált szövegű elemek
    egy rekordba kerülnek, a források megjelölésével.
    """

    result = []
    positions = {}

    sources = [
        ("openalex", topics or []),
        ("crossref", subjects or []),
    ]

    for source_name, values in sources:
        for value in values:
            name = clean_text(value)
            normalized = normalize_topic_name(name)

            if not name or not normalized:
                continue

            if normalized not in positions:
                positions[normalized] = len(result)

                result.append({
                    "name": name,
                    "normalized": normalized,
                    "sources": [source_name],
                })

            else:
                index = positions[normalized]

                if source_name not in result[index]["sources"]:
                    result[index]["sources"].append(source_name)

    return result


def merge_topic_terms(first, second):
    """
    Két közös témaköri lista összevonása.
    Az azonos normalizált nevű elemek forrásai egyesülnek.
    """

    result = []
    positions = {}

    for term in (first or []) + (second or []):
        if not isinstance(term, dict):
            continue

        name = clean_text(term.get("name"))
        normalized = (
            normalize_topic_name(name)
            or normalize_topic_name(term.get("normalized"))
        )

        if not name or not normalized:
            continue

        sources = term.get("sources") or []

        if normalized not in positions:
            positions[normalized] = len(result)

            result.append({
                "name": name,
                "normalized": normalized,
                "sources": [],
            })

        index = positions[normalized]

        for source in sources:
            if source not in result[index]["sources"]:
                result[index]["sources"].append(source)

    return result


def normalize_publication_type(publication_type):
    """Publikációtípus egységesítése."""

    if not publication_type:
        return None

    value = str(publication_type).strip().lower()

    type_mapping = {
        "article": "journal-article",
        "journal-article": "journal-article",
        "conference-paper": "proceedings-article",
        "proceedings-article": "proceedings-article",
        "book-chapter": "book-chapter",
        "book": "book",
        "dissertation": "dissertation",
        "preprint": "preprint",
        "posted-content": "posted-content",
        "report": "report",
        "monograph": "monograph",
        "edited-book": "edited-book",
        "reference-entry": "reference-entry",
    }

    return type_mapping.get(value, value)


def create_base_record():
    """Üres, egységes publikációs rekord."""

    return {
        "model_version": MODEL_VERSION,
        "doi": None,
        "openalex_id": None,
        "title": None,
        "authors": [],
        "publication_date": None,
        "publication_type": None,
        "source_types": {},
        "language": None,
        "abstract": None,
        "topics": [],
        "subjects": [],
        "topic_terms": [],
        "sources": [],
        "source_ids": {},
        "classification": None,
    }


def from_openalex(item, classification=None):
    """OpenAlex rekord átalakítása közös adatmodellre."""

    record = create_base_record()

    if not isinstance(item, dict):
        raise TypeError("Az OpenAlex rekordnak szótárnak kell lennie.")

    record["doi"] = normalize_doi(item.get("doi"))

    record["openalex_id"] = normalize_openalex_id(
        item.get("id")
    )

    record["title"] = clean_text(item.get("title"))

    authors = []

    for authorship in item.get("authorships") or []:
        author = authorship.get("author") or {}

        name = clean_text(
            author.get("display_name")
        )

        if name:
            authors.append(name)

    record["authors"] = normalize_authors(authors)

    record["publication_date"] = normalize_date(
        item.get("publication_date")
    )

    original_type = item.get("type")

    record["publication_type"] = normalize_publication_type(
        original_type
    )

    if original_type:
        record["source_types"]["openalex"] = original_type

    record["language"] = item.get("language")

    record["abstract"] = reconstruct_abstract(
        item.get("abstract_inverted_index")
    )

    record["topics"] = normalize_topics(
        item.get("topics")
    )

    record["topic_terms"] = build_topic_terms(
        topics=record["topics"]
    )

    record["sources"] = ["openalex"]

    if record["openalex_id"]:
        record["source_ids"]["openalex"] = (
            record["openalex_id"]
        )

    record["classification"] = classification

    return record


def from_crossref(item, classification=None):
    """Crossref rekord átalakítása közös adatmodellre."""

    record = create_base_record()

    if not isinstance(item, dict):
        raise TypeError("A Crossref rekordnak szótárnak kell lennie.")

    record["doi"] = normalize_doi(
        item.get("DOI")
    )

    titles = item.get("title") or []

    record["title"] = clean_text(
        titles[0] if titles else None
    )

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

    record["authors"] = normalize_authors(authors)

    record["publication_date"] = get_crossref_date(item)

    original_type = item.get("type")

    record["publication_type"] = normalize_publication_type(
        original_type
    )

    if original_type:
        record["source_types"]["crossref"] = original_type

    record["language"] = item.get("language")

    record["abstract"] = clean_text(
        item.get("abstract")
    )

    record["subjects"] = normalize_subjects(
        item.get("subject")
    )

    record["topic_terms"] = build_topic_terms(
        subjects=record["subjects"]
    )

    record["sources"] = ["crossref"]

    if record["doi"]:
        record["source_ids"]["crossref"] = record["doi"]

    record["classification"] = classification

    return record


def validate_record(record):
    """Az egységes rekord alapvető szerkezeti ellenőrzése."""

    required_fields = {
        "model_version",
        "doi",
        "openalex_id",
        "title",
        "authors",
        "publication_date",
        "publication_type",
        "source_types",
        "language",
        "abstract",
        "topics",
        "subjects",
        "topic_terms",
        "sources",
        "source_ids",
        "classification",
    }

    if not isinstance(record, dict):
        return False

    if not required_fields.issubset(record.keys()):
        return False

    for field in [
        "authors",
        "topics",
        "subjects",
        "topic_terms",
        "sources",
    ]:
        if not isinstance(record[field], list):
            return False

    if not isinstance(record["source_ids"], dict):
        return False

    if not isinstance(record["source_types"], dict):
        return False

    for term in record["topic_terms"]:
        if not isinstance(term, dict):
            return False

        if not isinstance(term.get("name"), str):
            return False

        if not isinstance(term.get("normalized"), str):
            return False

        if not isinstance(term.get("sources"), list):
            return False

    return True


def run_model_tests():
    """Hálózat nélküli önellenőrzés."""

    assert normalize_doi(
        "https://doi.org/10.1234/ABC"
    ) == "10.1234/abc"

    assert normalize_doi(
        "doi:10.1234/ABC"
    ) == "10.1234/abc"

    assert normalize_doi("invalid") is None

    assert normalize_date(
        "2026-11-25"
    ) == "2026-11-25"

    assert normalize_date(
        "hibás dátum"
    ) is None

    assert normalize_publication_type(
        "article"
    ) == "journal-article"

    openalex_record = from_openalex({
        "id": "https://openalex.org/W123456",
        "doi": "https://doi.org/10.1234/ABC",
        "title": "Example Research Article",
        "publication_date": "2026-11-25",
        "type": "article",
        "language": "en",
        "authorships": [
            {
                "author": {
                    "display_name": "John Smith"
                }
            }
        ],
        "topics": [
            {
                "display_name": "Artificial Intelligence"
            }
        ],
        "abstract_inverted_index": {
            "The": [0],
            "research": [1],
            "is": [2],
            "important": [3],
        },
    })

    assert validate_record(openalex_record)
    assert openalex_record["doi"] == "10.1234/abc"
    assert openalex_record["sources"] == ["openalex"]
    assert openalex_record["authors"] == ["John Smith"]

    crossref_record = from_crossref({
        "DOI": "10.1234/ABC",
        "title": ["Example Research Article"],
        "type": "journal-article",
        "language": "en",
        "published-online": {
            "date-parts": [[2026, 11, 25]]
        },
        "author": [
            {
                "given": "John",
                "family": "Smith",
            }
        ],
        "subject": [
            "Artificial Intelligence",
            "Computer Science",
        ],
        "abstract": "<jats:p>Example abstract.</jats:p>",
    })

    assert validate_record(crossref_record)
    assert crossref_record["doi"] == "10.1234/abc"
    assert crossref_record["sources"] == ["crossref"]
    assert crossref_record["authors"] == ["John Smith"]

    merged_terms = merge_topic_terms(
        openalex_record["topic_terms"],
        crossref_record["topic_terms"],
    )

    assert len(merged_terms) == 2
    assert merged_terms[0]["sources"] == [
        "openalex",
        "crossref",
    ]

    print("DOI normalizálás: SIKERES")
    print("Dátumkezelés: SIKERES")
    print("Publikációtípus-egységesítés: SIKERES")
    print("OpenAlex átalakítás: SIKERES")
    print("Crossref átalakítás: SIKERES")
    print("Témakörök egységesítése: SIKERES")
    print("Témaköri források megőrzése: SIKERES")
    print("Rekordstruktúra ellenőrzése: SIKERES")


if __name__ == "__main__":
    print("=" * 60)
    print("SYNAPSE – EGYSÉGES ADATMODELL")
    print("=" * 60)

    run_model_tests()

    print("=" * 60)
    print("M2.6 / 0.2 – MODELL ELŐKÉSZÍTVE")
    print("Adatbázis-módosítás: NINCS")
    print("=" * 60)
