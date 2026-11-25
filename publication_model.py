
"""
SYNAPSE – Egységes publikációs adatmodell
Verzió: 0.3

Feladat:
- OpenAlex rekordok egységesítése
- Crossref rekordok egységesítése
- DOI és forrásazonosítók normalizálása
- Strukturált szerzői adatok megőrzése
- Publikációs dátum és év kezelése
- Folyóirat, kiadó és URL megőrzése
- Absztraktok és témakörök kinyerése
- Forrásspecifikus metaadatok megőrzése
- Témaköri források visszakövethetősége

Nincs hálózati kapcsolat.
Nincs Supabase kapcsolat.
Nincs adatbázisba írás.
"""

import re
import html
from datetime import date


MODEL_VERSION = "0.3"


# ============================================================
# ALAPVETŐ NORMALIZÁLÓ FÜGGVÉNYEK
# ============================================================

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


def normalize_orcid(orcid):
    """ORCID azonosító egységesítése."""

    if not orcid:
        return None

    value = str(orcid).strip()

    value = re.sub(
        r"^https?://orcid\.org/",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = value.strip()

    return value or None


def clean_text(value):
    """HTML és felesleges szóközök eltávolítása."""

    if value is None:
        return None

    text = html.unescape(str(value))
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip() or None


# ============================================================
# SZERZŐK KEZELÉSE
# ============================================================

def normalize_authors(authors):
    """
    Egyszerű szerzőnévlista normalizálása.

    A strukturált szerzői adatok megőrzésére a
    normalize_author_records() szolgál.

    Itt a korábbi kompatibilitás érdekében a névlista
    azonos szövegű elemeit egyetlen elemként kezeli.
    """

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


def normalize_author_records(authors):
    """
    Strukturált szerzői lista létrehozása.

    Egy szerző rekordja:
    {
        "name": str,
        "orcid": str | None,
        "openalex_id": str | None,
        "position": int | None
    }

    Fontos:
    - Azonos név alapján nem történik összevonás.
    - ORCID és OpenAlex ID megőrzése.
    - Azonosító nélküli szerzők külön maradnak.
    """

    if not isinstance(authors, list):
        return []

    result = []
    seen_ids = set()

    for index, author in enumerate(authors, start=1):

        if isinstance(author, str):
            name = clean_text(author)
            orcid = None
            openalex_id = None
            position = index

        elif isinstance(author, dict):
            name = clean_text(
                author.get("name")
                or author.get("display_name")
            )

            orcid = normalize_orcid(
                author.get("orcid")
            )

            openalex_id = normalize_openalex_id(
                author.get("openalex_id")
                or author.get("id")
            )

            raw_position = author.get("position", index)

            try:
                position = int(raw_position)
                if position < 1:
                    position = index
            except (ValueError, TypeError):
                position = index

        else:
            continue

        if not name:
            continue

        record = {
            "name": name,
            "orcid": orcid,
            "openalex_id": openalex_id,
            "position": position,
        }

        # Csak stabil azonosító alapján deduplikálunk.
        identity = None

        if orcid:
            identity = ("orcid", orcid)

        elif openalex_id:
            identity = ("openalex", openalex_id)

        if identity is not None:
            if identity in seen_ids:
                continue

            seen_ids.add(identity)

        result.append(record)

    return result


def get_author_identity(author):
    """
    Stabil szerzőazonosító előállítása.

    Név alapján soha nem képezünk azonosságot.
    """

    if not isinstance(author, dict):
        return None

    orcid = normalize_orcid(author.get("orcid"))

    if orcid:
        return ("orcid", orcid)

    openalex_id = normalize_openalex_id(
        author.get("openalex_id")
    )

    if openalex_id:
        return ("openalex", openalex_id)

    return None


def merge_author_records(first, second):
    """
    Két strukturált szerzőlista összevonása.

    Összevonás kizárólag azonos ORCID vagy azonos
    OpenAlex author ID alapján történik.

    Azonos nevű, de azonosító nélküli szerzők
    külön rekordként maradnak meg.
    """

    result = []
    positions = {}

    for author in (first or []) + (second or []):

        if not isinstance(author, dict):
            continue

        name = clean_text(author.get("name"))

        if not name:
            continue

        normalized = {
            "name": name,
            "orcid": normalize_orcid(
                author.get("orcid")
            ),
            "openalex_id": normalize_openalex_id(
                author.get("openalex_id")
            ),
            "position": author.get("position"),
        }

        identity = get_author_identity(normalized)

        if identity is None:
            # Stabil azonosító nélkül nem vonjuk össze.
            result.append(normalized)
            continue

        if identity not in positions:
            positions[identity] = len(result)
            result.append(normalized)
            continue

        existing = result[positions[identity]]

        if not existing.get("name") and normalized.get("name"):
            existing["name"] = normalized["name"]

        if not existing.get("orcid") and normalized.get("orcid"):
            existing["orcid"] = normalized["orcid"]

        if (
            not existing.get("openalex_id")
            and normalized.get("openalex_id")
        ):
            existing["openalex_id"] = normalized["openalex_id"]

        old_position = existing.get("position")
        new_position = normalized.get("position")

        try:
            if old_position is None:
                existing["position"] = int(new_position)
            elif new_position is not None:
                existing["position"] = min(
                    int(old_position),
                    int(new_position),
                )
        except (ValueError, TypeError):
            pass

    return result


def author_names_from_records(author_records):
    """
    Szerzőnevek előállítása a strukturált listából.

    Itt szándékosan nincs név szerinti deduplikáció:
    két különböző szerzőnek lehet azonos neve.
    """

    result = []

    for author in author_records or []:
        if not isinstance(author, dict):
            continue

        name = clean_text(author.get("name"))

        if name:
            result.append(name)

    return result


# ============================================================
# DÁTUMKEZELÉS
# ============================================================

def normalize_date(value):
    """Dátum ellenőrzése és ISO-formátumra alakítása."""

    if not value:
        return None

    try:
        parsed = date.fromisoformat(str(value)[:10])
        return parsed.isoformat()

    except (ValueError, TypeError):
        return None


def get_publication_year(publication_date):
    """Publikációs év kinyerése a dátumból."""

    normalized = normalize_date(publication_date)

    if not normalized:
        return None

    try:
        return int(normalized[:4])
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


# ============================================================
# ABSZTRAKT KEZELÉSE
# ============================================================

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


# ============================================================
# TÉMAKÖRÖK ÉS TÁRGYSZAVAK
# ============================================================

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


# ============================================================
# PUBLIKÁCIÓTÍPUS
# ============================================================

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


# ============================================================
# FORRÁSSPECIFIKUS ADATOK
# ============================================================

def get_openalex_source(item):
    """OpenAlex folyóirat- és kiadói adatok kinyerése."""

    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") or {}

    return {
        "journal": clean_text(
            source.get("display_name")
        ),
        "publisher": clean_text(
            source.get("host_organization_name")
        ),
        "url": clean_text(
            primary_location.get("landing_page_url")
            or item.get("doi")
        ),
    }


def get_crossref_source(item):
    """Crossref folyóirat- és kiadói adatok kinyerése."""

    container_titles = item.get("container-title") or []

    journal = (
        clean_text(container_titles[0])
        if container_titles
        else None
    )

    return {
        "journal": journal,
        "publisher": clean_text(item.get("publisher")),
        "url": clean_text(item.get("URL")),
    }


# ============================================================
# ALAPREKORD
# ============================================================

def create_base_record():
    """Üres, egységes publikációs rekord."""

    return {
        "model_version": MODEL_VERSION,
        "doi": None,
        "openalex_id": None,
        "title": None,
        "authors": [],
        "author_records": [],
        "publication_date": None,
        "publication_year": None,
        "publication_type": None,
        "source_types": {},
        "language": None,
        "abstract": None,
        "journal": None,
        "publisher": None,
        "url": None,
        "topics": [],
        "subjects": [],
        "topic_terms": [],
        "sources": [],
        "source_ids": {},
        "source_metadata": {},
        "classification": None,
    }


# ============================================================
# OPENALEX ÁTALAKÍTÁS
# ============================================================

def from_openalex(item, classification=None):
    """OpenAlex rekord átalakítása közös adatmodellre."""

    record = create_base_record()

    if not isinstance(item, dict):
        raise TypeError(
            "Az OpenAlex rekordnak szótárnak kell lennie."
        )

    record["doi"] = normalize_doi(item.get("doi"))

    record["openalex_id"] = normalize_openalex_id(
        item.get("id")
    )

    record["title"] = clean_text(
        item.get("title")
    )

    authors = []

    for position, authorship in enumerate(
        item.get("authorships") or [],
        start=1,
    ):
        author = authorship.get("author") or {}

        authors.append({
            "name": author.get("display_name"),
            "orcid": author.get("orcid"),
            "openalex_id": author.get("id"),
            "position": position,
        })

    record["author_records"] = normalize_author_records(
        authors
    )

    record["authors"] = author_names_from_records(
        record["author_records"]
    )

    record["publication_date"] = normalize_date(
        item.get("publication_date")
    )

    record["publication_year"] = (
        get_publication_year(
            record["publication_date"]
        )
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

    source_data = get_openalex_source(item)

    record["journal"] = source_data["journal"]
    record["publisher"] = source_data["publisher"]
    record["url"] = source_data["url"]

    record["sources"] = ["openalex"]

    if record["openalex_id"]:
        record["source_ids"]["openalex"] = (
            record["openalex_id"]
        )

    record["source_metadata"]["openalex"] = {
        "work_id": record["openalex_id"],
        "type": original_type,
        "primary_location": source_data,
    }

    record["classification"] = classification

    return record


# ============================================================
# CROSSREF ÁTALAKÍTÁS
# ============================================================

def from_crossref(item, classification=None):
    """Crossref rekord átalakítása közös adatmodellre."""

    record = create_base_record()

    if not isinstance(item, dict):
        raise TypeError(
            "A Crossref rekordnak szótárnak kell lennie."
        )

    record["doi"] = normalize_doi(
        item.get("DOI")
    )

    titles = item.get("title") or []

    record["title"] = clean_text(
        titles[0] if titles else None
    )

    authors = []

    for position, author in enumerate(
        item.get("author") or [],
        start=1,
    ):
        name = " ".join(
            part for part in [
                author.get("given", ""),
                author.get("family", ""),
            ]
            if part
        )

        authors.append({
            "name": name,
            "orcid": author.get("ORCID"),
            "openalex_id": None,
            "position": position,
        })

    record["author_records"] = normalize_author_records(
        authors
    )

    record["authors"] = author_names_from_records(
        record["author_records"]
    )

    record["publication_date"] = get_crossref_date(item)

    record["publication_year"] = (
        get_publication_year(
            record["publication_date"]
        )
    )

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

    source_data = get_crossref_source(item)

    record["journal"] = source_data["journal"]
    record["publisher"] = source_data["publisher"]
    record["url"] = source_data["url"]

    record["sources"] = ["crossref"]

    if record["doi"]:
        record["source_ids"]["crossref"] = record["doi"]

    record["source_metadata"]["crossref"] = {
        "type": original_type,
        "container_title": source_data["journal"],
        "publisher": source_data["publisher"],
        "url": source_data["url"],
    }

    record["classification"] = classification

    return record


# ============================================================
# REKORD ELLENŐRZÉSE
# ============================================================

def validate_record(record):
    """Az egységes rekord alapvető szerkezeti ellenőrzése."""

    required_fields = {
        "model_version",
        "doi",
        "openalex_id",
        "title",
        "authors",
        "author_records",
        "publication_date",
        "publication_year",
        "publication_type",
        "source_types",
        "language",
        "abstract",
        "journal",
        "publisher",
        "url",
        "topics",
        "subjects",
        "topic_terms",
        "sources",
        "source_ids",
        "source_metadata",
        "classification",
    }

    if not isinstance(record, dict):
        return False

    if not required_fields.issubset(record.keys()):
        return False

    for field in [
        "authors",
        "author_records",
        "topics",
        "subjects",
        "topic_terms",
        "sources",
    ]:
        if not isinstance(record[field], list):
            return False

    for field in [
        "source_ids",
        "source_types",
        "source_metadata",
    ]:
        if not isinstance(record[field], dict):
            return False

    for author in record["author_records"]:
        if not isinstance(author, dict):
            return False

        if not isinstance(author.get("name"), str):
            return False

        if "orcid" not in author:
            return False

        if "openalex_id" not in author:
            return False

        if "position" not in author:
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


# ============================================================
# MODELLTESZTEK
# ============================================================

def run_model_tests():
    """Hálózat nélküli önellenőrzés."""

    # DOI
    assert normalize_doi(
        "https://doi.org/10.1234/ABC"
    ) == "10.1234/abc"

    assert normalize_doi(
        "doi:10.1234/ABC"
    ) == "10.1234/abc"

    assert normalize_doi("invalid") is None

    # ORCID
    assert normalize_orcid(
        "https://orcid.org/0000-0001-2345-6789"
    ) == "0000-0001-2345-6789"

    # Dátum
    assert normalize_date(
        "2026-11-25"
    ) == "2026-11-25"

    assert normalize_date(
        "hibás dátum"
    ) is None

    assert get_publication_year(
        "2026-11-25"
    ) == 2026

    # Publikációtípus
    assert normalize_publication_type(
        "article"
    ) == "journal-article"

    # Strukturált szerzők
    authors = normalize_author_records([
        {
            "name": "John Smith",
            "orcid": "0000-0001-2345-6789",
            "openalex_id": "https://openalex.org/A123",
            "position": 1,
        },
        {
            "name": "John Smith",
            "orcid": None,
            "openalex_id": None,
            "position": 2,
        },
        {
            "name": "John Smith",
            "orcid": None,
            "openalex_id": None,
            "position": 3,
        },
    ])

    assert len(authors) == 3

    # Azonos ORCID összevonása
    merged_authors = merge_author_records(
        [
            {
                "name": "John Smith",
                "orcid": "0000-0001-2345-6789",
                "openalex_id": None,
                "position": 1,
            }
        ],
        [
            {
                "name": "John Smith",
                "orcid": "0000-0001-2345-6789",
                "openalex_id": "https://openalex.org/A123",
                "position": 2,
            }
        ],
    )

    assert len(merged_authors) == 1
    assert merged_authors[0]["openalex_id"] == (
        "https://openalex.org/A123"
    )

    # Azonos név, különböző ORCID: nem vonható össze
    different_authors = merge_author_records(
        [
            {
                "name": "John Smith",
                "orcid": "0000-0001-1111-1111",
                "openalex_id": None,
                "position": 1,
            }
        ],
        [
            {
                "name": "John Smith",
                "orcid": "0000-0002-2222-2222",
                "openalex_id": None,
                "position": 2,
            }
        ],
    )

    assert len(different_authors) == 2

    # Azonos név, azonosító nélkül: nem vonható össze
    anonymous_authors = merge_author_records(
        [
            {
                "name": "John Smith",
                "orcid": None,
                "openalex_id": None,
                "position": 1,
            }
        ],
        [
            {
                "name": "John Smith",
                "orcid": None,
                "openalex_id": None,
                "position": 2,
            }
        ],
    )

    assert len(anonymous_authors) == 2

    # OpenAlex
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
                    "display_name": "John Smith",
                    "id": "https://openalex.org/A123",
                    "orcid": "https://orcid.org/0000-0001-2345-6789",
                }
            }
        ],
        "primary_location": {
            "landing_page_url": "https://example.com/article",
            "source": {
                "display_name": "Example Journal",
                "host_organization_name": "Example Publisher",
            },
        },
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
    assert openalex_record["publication_year"] == 2026
    assert openalex_record["journal"] == "Example Journal"
    assert openalex_record["publisher"] == "Example Publisher"
    assert openalex_record["author_records"][0]["orcid"] == (
        "0000-0001-2345-6789"
    )

    # Crossref
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
                "ORCID": "https://orcid.org/0000-0001-2345-6789",
            }
        ],
        "container-title": ["Example Journal"],
        "publisher": "Example Publisher",
        "URL": "https://example.com/article",
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
    assert crossref_record["publication_year"] == 2026
    assert crossref_record["journal"] == "Example Journal"
    assert crossref_record["publisher"] == "Example Publisher"

    # Témakörök
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
    print("ORCID normalizálás: SIKERES")
    print("Dátumkezelés: SIKERES")
    print("Publikációs év kezelése: SIKERES")
    print("Publikációtípus-egységesítés: SIKERES")
    print("Strukturált szerzők: SIKERES")
    print("Szerzők stabil azonosító szerinti összevonása: SIKERES")
    print("Azonos nevű szerzők elkülönítése: SIKERES")
    print("OpenAlex átalakítás: SIKERES")
    print("Crossref átalakítás: SIKERES")
    print("Folyóirat- és kiadóadatok: SIKERES")
    print("Témakörök egységesítése: SIKERES")
    print("Témaköri források megőrzése: SIKERES")
    print("Rekordstruktúra ellenőrzése: SIKERES")


# ============================================================
# FUTTATÁS
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("SYNAPSE – EGYSÉGES ADATMODELL")
    print("=" * 60)

    run_model_tests()

    print("=" * 60)
    print("M2.7.2 – MODEL 0.3 ELŐKÉSZÍTVE")
    print("Adatbázis-módosítás: NINCS")
    print("=" * 60)
