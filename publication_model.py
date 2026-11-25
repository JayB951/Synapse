
"""
SYNAPSE – Egységes publikációs adatmodell
Verzió: M2.7.2.1 / 0.3.1

Feladat:
- OpenAlex rekordok egységesítése
- Crossref rekordok egységesítése
- DOI normalizálása
- Szerzők és szerzőazonosítók kinyerése
- Dátumok és publikációs év kezelése
- Folyóirat, kiadó és URL kinyerése
- Absztraktok és témakörök kinyerése
- Forrásspecifikus azonosítók megőrzése
- Eredeti témaköri adatok megőrzése
- Témakörök és tárgyszavak közös listába rendezése
- Témaköri források visszakövethetősége

Nincs hálózati kapcsolat.
Nincs Supabase kapcsolat.
Nincs adatbázisba írás.
"""

import re
import html
from datetime import date


MODEL_VERSION = "0.3.1"


# ============================================================
# ALAPVETŐ NORMALIZÁLÁS
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

    return value.strip() or None


def clean_text(value):
    """HTML és felesleges szóközök eltávolítása."""

    if value is None:
        return None

    text = html.unescape(str(value))
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip() or None


# ============================================================
# SZERZŐK
# ============================================================

def normalize_authors(authors):
    """
    Egyszerű szerzőnévlista normalizálása.

    Kompatibilitási okból a korábbi authors mező
    továbbra is szöveges névlistát tartalmaz.
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
    Strukturált szerzői rekordok normalizálása.

    A sorrend megmarad.
    Az azonos nevű szerzőket nem vonjuk össze,
    mert azonos nevű kutatók külön személyek is lehetnek.
    """

    if not isinstance(authors, list):
        return []

    result = []

    for position, author in enumerate(authors, start=1):
        if not isinstance(author, dict):
            continue

        name = clean_text(
            author.get("name")
            or author.get("display_name")
        )

        if not name:
            continue

        orcid = normalize_orcid(
            author.get("orcid")
        )

        openalex_id = normalize_openalex_id(
            author.get("openalex_id")
            or author.get("id")
        )

        raw_position = author.get("position", position)

        try:
            normalized_position = int(raw_position)
            if normalized_position < 1:
                normalized_position = position
        except (ValueError, TypeError):
            normalized_position = position

        result.append({
            "name": name,
            "orcid": orcid,
            "openalex_id": openalex_id,
            "position": normalized_position,
        })

    return result


def get_author_identity(author):
    """
    Stabil szerzőazonosító meghatározása.

    Elsődleges azonosító: ORCID.
    Másodlagos azonosító: OpenAlex author ID.

    Név alapján nem képezünk személyazonosságot.
    """

    if not isinstance(author, dict):
        return None

    orcid = normalize_orcid(
        author.get("orcid")
    )

    if orcid:
        return ("orcid", orcid.casefold())

    openalex_id = normalize_openalex_id(
        author.get("openalex_id")
    )

    if openalex_id:
        return ("openalex", openalex_id.casefold())

    return None


def merge_author_records(first, second):
    """
    Két szerzőlista összevonása.

    Összevonás kizárólag stabil azonosító alapján:
    - ORCID
    - OpenAlex author ID

    Ha egyik rekordban sincs stabil azonosító,
    a szerzőket külön rekordként tartjuk meg.

    Azonos nevű szerzőket nem vonunk össze pusztán
    a névegyezés alapján.
    """

    result = []
    positions = {}

    for author in (first or []) + (second or []):
        if not isinstance(author, dict):
            continue

        name = clean_text(author.get("name"))

        if not name:
            continue

        orcid = normalize_orcid(
            author.get("orcid")
        )

        openalex_id = normalize_openalex_id(
            author.get("openalex_id")
        )

        if orcid:
            key = ("orcid", orcid.casefold())

        elif openalex_id:
            key = ("openalex", openalex_id.casefold())

        else:
            # Stabil azonosító nélkül nem vonunk össze.
            result.append({
                "name": name,
                "orcid": None,
                "openalex_id": None,
                "position": len(result) + 1,
            })
            continue

        if key not in positions:
            positions[key] = len(result)

            result.append({
                "name": name,
                "orcid": orcid,
                "openalex_id": openalex_id,
                "position": len(result) + 1,
            })

        else:
            index = positions[key]
            existing = result[index]

            if not existing.get("orcid") and orcid:
                existing["orcid"] = orcid

            if (
                not existing.get("openalex_id")
                and openalex_id
            ):
                existing["openalex_id"] = openalex_id

            if not existing.get("name") and name:
                existing["name"] = name

    return result


def author_names_from_records(author_records):
    """
    Szerzőnevek előállítása a strukturált listából.

    Nem végzünk név szerinti deduplikációt:
    különböző személyek neve lehet azonos.
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
# DÁTUMOK
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
    """Publikációs év meghatározása a publikációs dátumból."""

    normalized = normalize_date(publication_date)

    if not normalized:
        return None

    return int(normalized[:4])


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
# ABSZTRAKT
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
# TÉMAKÖRÖK
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

    Az azonos normalizált szövegű elemek egy rekordba
    kerülnek, a források megjelölésével.
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
    """Két közös témaköri lista összevonása."""

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
# FORRÁSSPECIFIKUS BIBLIOGRÁFIAI ADATOK
# ============================================================

def get_openalex_source(item):
    """OpenAlex folyóirat- és kiadói adatok kinyerése."""

    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") or {}

    journal = clean_text(
        source.get("display_name")
    )

    publisher = clean_text(
        source.get("host_organization_name")
    )

    url = clean_text(
        primary_location.get("landing_page_url")
    )

    if not url:
        url = clean_text(item.get("doi"))

    return {
        "journal": journal,
        "publisher": publisher,
        "url": url,
    }


def get_crossref_source(item):
    """Crossref folyóirat- és kiadói adatok kinyerése."""

    container_titles = item.get("container-title") or []

    journal = clean_text(
        container_titles[0] if container_titles else None
    )

    publisher = clean_text(
        item.get("publisher")
    )

    url = clean_text(
        item.get("URL")
    )

    return {
        "journal": journal,
        "publisher": publisher,
        "url": url,
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

    record["doi"] = normalize_doi(
        item.get("doi")
    )

    record["openalex_id"] = normalize_openalex_id(
        item.get("id")
    )

    record["title"] = clean_text(
        item.get("title")
    )

    author_records = []

    for position, authorship in enumerate(
        item.get("authorships") or [],
        start=1,
    ):
        author = authorship.get("author") or {}

        author_records.append({
            "name": author.get("display_name"),
            "orcid": author.get("orcid"),
            "openalex_id": author.get("id"),
            "position": position,
        })

    record["author_records"] = normalize_author_records(
        author_records
    )

    record["authors"] = author_names_from_records(
        record["author_records"]
    )

    record["publication_date"] = normalize_date(
        item.get("publication_date")
    )

    record["publication_year"] = get_publication_year(
        record["publication_date"]
    )

    original_type = item.get("type")

    record["publication_type"] = normalize_publication_type(
        original_type
    )

    if original_type:
        record["source_types"]["openalex"] = original_type

    record["language"] = clean_text(
        item.get("language")
    )

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
        "topics": item.get("topics") or [],
        "type": original_type,
        "primary_location": item.get("primary_location"),
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

    author_records = []

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

        author_records.append({
            "name": name,
            "orcid": author.get("ORCID"),
            "openalex_id": None,
            "position": position,
        })

    record["author_records"] = normalize_author_records(
        author_records
    )

    record["authors"] = author_names_from_records(
        record["author_records"]
    )

    record["publication_date"] = get_crossref_date(item)

    record["publication_year"] = get_publication_year(
        record["publication_date"]
    )

    original_type = item.get("type")

    record["publication_type"] = normalize_publication_type(
        original_type
    )

    if original_type:
        record["source_types"]["crossref"] = original_type

    record["language"] = clean_text(
        item.get("language")
    )

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
        "subjects": item.get("subject") or [],
        "type": original_type,
        "container_title": item.get("container-title") or [],
    }

    record["classification"] = classification

    return record


# ============================================================
# REKORDVALIDÁCIÓ
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

        if not isinstance(author.get("position"), int):
            return False

        if author.get("orcid") is not None and not isinstance(
            author.get("orcid"), str
        ):
            return False

        if author.get("openalex_id") is not None and not isinstance(
            author.get("openalex_id"), str
        ):
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

    if record["publication_date"]:
        if normalize_date(record["publication_date"]) is None:
            return False

    if record["publication_year"] is not None:
        if not isinstance(record["publication_year"], int):
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

    # OpenAlex ID
    assert normalize_openalex_id(
        "https://openalex.org/W123456/"
    ) == "https://openalex.org/W123456"

    # ORCID
    assert normalize_orcid(
        "https://orcid.org/0000-0000-0000-0000"
    ) == "0000-0000-0000-0000"

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

    # Szerzőnormalizálás
    normalized_authors = normalize_author_records([
        {
            "name": "John Smith",
            "orcid": None,
            "openalex_id": None,
        },
        {
            "name": "John Smith",
            "orcid": None,
            "openalex_id": None,
        },
    ])

    assert len(normalized_authors) == 2

    # Azonos ORCID: összevonás
    same_orcid = merge_author_records(
        [
            {
                "name": "John Smith",
                "orcid": "0000-0001-1111-1111",
                "openalex_id": None,
            }
        ],
        [
            {
                "name": "John Smith",
                "orcid": "0000-0001-1111-1111",
                "openalex_id": "https://openalex.org/A123",
            }
        ],
    )

    assert len(same_orcid) == 1
    assert same_orcid[0]["openalex_id"] == (
        "https://openalex.org/A123"
    )

    # Azonos OpenAlex ID: összevonás
    same_openalex = merge_author_records(
        [
            {
                "name": "John Smith",
                "orcid": None,
                "openalex_id": "https://openalex.org/A123",
            }
        ],
        [
            {
                "name": "John Smith",
                "orcid": None,
                "openalex_id": "https://openalex.org/A123",
            }
        ],
    )

    assert len(same_openalex) == 1

    # Azonos név, eltérő ORCID: külön rekord
    different_orcids = merge_author_records(
        [
            {
                "name": "John Smith",
                "orcid": "0000-0001-1111-1111",
                "openalex_id": None,
            }
        ],
        [
            {
                "name": "John Smith",
                "orcid": "0000-0002-2222-2222",
                "openalex_id": None,
            }
        ],
    )

    assert len(different_orcids) == 2

    # Azonos név, azonosító nélkül: külön rekord
    no_identifiers = merge_author_records(
        [
            {
                "name": "John Smith",
                "orcid": None,
                "openalex_id": None,
            }
        ],
        [
            {
                "name": "John Smith",
                "orcid": None,
                "openalex_id": None,
            }
        ],
    )

    assert len(no_identifiers) == 2

    # OpenAlex rekord
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
                    "orcid": "https://orcid.org/0000-0000-0000-0000",
                    "id": "https://openalex.org/A123456",
                }
            }
        ],
        "topics": [
            {
                "display_name": "Artificial Intelligence"
            }
        ],
        "primary_location": {
            "landing_page_url": "https://example.org/article",
            "source": {
                "display_name": "Example Journal",
                "host_organization_name": "Example Publisher",
            },
        },
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
    assert openalex_record["author_records"][0]["orcid"] == (
        "0000-0000-0000-0000"
    )
    assert openalex_record["publication_year"] == 2026
    assert openalex_record["journal"] == "Example Journal"
    assert openalex_record["publisher"] == "Example Publisher"

    # Crossref rekord
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
                "ORCID": "https://orcid.org/0000-0000-0000-0000",
            }
        ],
        "subject": [
            "Artificial Intelligence",
            "Computer Science",
        ],
        "container-title": ["Example Journal"],
        "publisher": "Example Publisher",
        "URL": "https://doi.org/10.1234/ABC",
        "abstract": "<jats:p>Example abstract.</jats:p>",
    })

    assert validate_record(crossref_record)
    assert crossref_record["doi"] == "10.1234/abc"
    assert crossref_record["sources"] == ["crossref"]
    assert crossref_record["authors"] == ["John Smith"]
    assert crossref_record["author_records"][0]["orcid"] == (
        "0000-0000-0000-0000"
    )
    assert crossref_record["journal"] == "Example Journal"
    assert crossref_record["publisher"] == "Example Publisher"

    # Témakörök összevonása
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
    print("OpenAlex azonosító normalizálása: SIKERES")
    print("ORCID normalizálása: SIKERES")
    print("Dátumkezelés: SIKERES")
    print("Publikációs év meghatározása: SIKERES")
    print("Publikációtípus-egységesítés: SIKERES")
    print("Strukturált szerzői adatok: SIKERES")
    print("Szerzők ORCID szerinti összevonása: SIKERES")
    print("Szerzők OpenAlex ID szerinti összevonása: SIKERES")
    print("Azonos nevű szerzők elkülönítése: SIKERES")
    print("OpenAlex átalakítás: SIKERES")
    print("Crossref átalakítás: SIKERES")
    print("Folyóirat és kiadó kinyerése: SIKERES")
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
    print("M2.7.2.1 / 0.3.1 – MODELL ELŐKÉSZÍTVE")
    print("Adatbázis-módosítás: NINCS")
    print("Hálózati kapcsolat: NINCS")
    print("=" * 60)
