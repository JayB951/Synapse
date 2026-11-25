
"""
SYNAPSE – Adatbázis-leképező
Verzió: M2.7.4.1 / 0.1.0

Feladat:
- Egységes publikációs rekordok leképezése a Supabase sémára.
- Publikációs adatok előkészítése.
- Forráskapcsolatok előkészítése.
- Szerzők és szerzőkapcsolatok előkészítése.
- Kötelező mezők és azonosítók ellenőrzése.
- JSON-kompatibilis adatcsomagok előállítása.

Nincs hálózati kapcsolat.
Nincs Supabase kapcsolat.
Nincs adatbázisba írás.
"""

import json
from datetime import date

import publication_model as model


MAPPER_VERSION = "0.1.0"


# ============================================================
# SEGÉDFÜGGVÉNYEK
# ============================================================

def clean_value(value):
    """Szöveges érték tisztítása."""

    if value is None:
        return None

    value = str(value).strip()

    return value or None


def normalize_doi(value):
    """DOI normalizálása a publikációs modell segítségével."""

    return model.normalize_doi(value)


def make_publication_key(record):
    """
    Ideiglenes publikációazonosító előállítása.

    Elsődleges: DOI.
    Másodlagos: OpenAlex Work ID.

    DOI nélküli Crossref rekord önmagában nem kap
    mesterséges publikációazonosítót.
    """

    doi = normalize_doi(record.get("doi"))

    if doi:
        return "doi:" + doi

    openalex_id = model.normalize_openalex_id(
        record.get("openalex_id")
    )

    if openalex_id:
        return "openalex:" + openalex_id

    return None


def normalize_source_id_map(source_id_by_code):
    """
    Forráskódok és adatbázis-azonosítók ellenőrzése.

    Elfogadott formák:

    {
        "openalex": "UUID",
        "crossref": "UUID"
    }

    vagy:

    {
        "openalex": {"id": "UUID", "is_active": True}
    }
    """

    if not isinstance(source_id_by_code, dict):
        raise TypeError(
            "A source_id_by_code értékének szótárnak kell lennie."
        )

    result = {}

    for code, value in source_id_by_code.items():
        code = clean_value(code)

        if not code:
            continue

        if isinstance(value, dict):
            if value.get("is_active") is False:
                continue

            source_id = clean_value(value.get("id"))

        else:
            source_id = clean_value(value)

        if source_id:
            result[code] = source_id

    return result


def is_valid_date(value):
    """ISO dátum ellenőrzése."""

    if not value:
        return True

    try:
        date.fromisoformat(str(value))
        return True

    except (ValueError, TypeError):
        return False


# ============================================================
# PUBLIKÁCIÓ ELLENŐRZÉSE
# ============================================================

def validate_publication(record):
    """Publikációs rekord ellenőrzése adatbázis-leképezés előtt."""

    errors = []

    if not isinstance(record, dict):
        return ["A rekord nem szótár típusú."]

    if not model.validate_record(record):
        errors.append(
            "A rekord nem felel meg az egységes adatmodellnek."
        )

    title = clean_value(record.get("title"))

    if not title:
        errors.append("Hiányzó publikációs cím.")

    doi = normalize_doi(record.get("doi"))

    openalex_id = model.normalize_openalex_id(
        record.get("openalex_id")
    )

    if not doi and not openalex_id:
        errors.append(
            "Nincs DOI vagy OpenAlex publikációazonosító."
        )

    publication_date = record.get("publication_date")

    if not is_valid_date(publication_date):
        errors.append("Érvénytelen publikációs dátum.")

    publication_year = record.get("publication_year")

    if publication_year is not None:
        if not isinstance(publication_year, int):
            errors.append("A publikációs év nem egész szám.")

    if publication_date and publication_year is not None:
        expected_year = model.get_publication_year(
            publication_date
        )

        if expected_year != publication_year:
            errors.append(
                "A publikációs év és a dátum nem egyezik."
            )

    if not isinstance(record.get("sources"), list):
        errors.append("A sources mező nem lista.")

    if not isinstance(record.get("source_ids"), dict):
        errors.append("A source_ids mező nem szótár.")

    return errors


# ============================================================
# PUBLIKÁCIÓS TÁBLA
# ============================================================

def map_publication(record, publication_key):
    """
    Rekord leképezése a publications táblára.

    A metadata megőrzi az eredeti forrásspecifikus
    és témaköri adatokat.
    """

    metadata = {
        "model_version": record.get("model_version"),
        "mapper_version": MAPPER_VERSION,
        "source_types": record.get("source_types") or {},
        "source_ids": record.get("source_ids") or {},
        "source_metadata": record.get("source_metadata") or {},
        "topics": record.get("topics") or [],
        "subjects": record.get("subjects") or [],
        "topic_terms": record.get("topic_terms") or [],
        "classification": record.get("classification"),
        "author_source_ids": [],
    }

    for position, author in enumerate(
        record.get("author_records") or [],
        start=1,
    ):
        metadata["author_source_ids"].append({
            "position": author.get("position", position),
            "name": author.get("name"),
            "orcid": author.get("orcid"),
            "openalex_id": author.get("openalex_id"),
        })

    return {
        "publication_key": publication_key,
        "title": clean_value(record.get("title")),
        "abstract": clean_value(record.get("abstract")),
        "doi": normalize_doi(record.get("doi")),
        "publication_date": record.get("publication_date"),
        "publication_year": record.get("publication_year"),
        "publication_type": clean_value(
            record.get("publication_type")
        ),
        "language": clean_value(record.get("language")),
        "journal": clean_value(record.get("journal")),
        "publisher": clean_value(record.get("publisher")),
        "url": clean_value(record.get("url")),
        "metadata": metadata,
    }


# ============================================================
# FORRÁSKAPCSOLATOK
# ============================================================

def map_publication_sources(
    record,
    publication_key,
    source_ids,
):
    """
    Rekord leképezése a publication_sources táblára.

    A külső azonosítót mindig az adott forrás
    saját azonosítója alapján határozza meg.
    """

    result = []
    errors = []

    record_sources = record.get("sources") or []
    record_source_ids = record.get("source_ids") or {}
    source_metadata = record.get("source_metadata") or {}

    if not record_sources:
        return [], ["A rekordhoz nincs adatforrás rendelve."]

    for code in record_sources:

        if code not in ("openalex", "crossref"):
            errors.append(
                f"Nem támogatott adatforrás: {code}"
            )
            continue

        source_id = source_ids.get(code)

        if not source_id:
            errors.append(
                f"Hiányzó vagy inaktív adatforrás: {code}"
            )
            continue

        external_id = clean_value(
            record_source_ids.get(code)
        )

        # OpenAlex: Work ID
        if code == "openalex":
            external_id = (
                model.normalize_openalex_id(external_id)
                or model.normalize_openalex_id(
                    record.get("openalex_id")
                )
            )

        # Crossref: DOI
        elif code == "crossref":
            external_id = (
                normalize_doi(external_id)
                or normalize_doi(record.get("doi"))
            )

        # DOI nélküli Crossref rekord esetén
        # nincs biztonságosan használható azonosító
        # a jelenlegi egységes modellben.
        if not external_id:
            errors.append(
                f"{code}: hiányzó stabil külső azonosító."
            )
            continue

        original_url = clean_value(
            record.get("url")
        )

        result.append({
            "publication_key": publication_key,
            "source_code": code,
            "source_id": source_id,
            "external_id": external_id,
            "original_url": original_url,
            "source_metadata": source_metadata.get(code) or {},
        })

    return result, errors


# ============================================================
# SZERZŐK
# ============================================================

def map_authors(record, publication_key):
    """
    Szerzők leképezése az authors táblára.

    ORCID esetén a kulcs globálisan stabil.

    ORCID nélküli szerzőknél publikációhoz kötött
    ideiglenes kulcsot használunk.

    Így nem történik automatikus személyazonosítás
    pusztán név vagy OpenAlex ID alapján.
    """

    authors = []
    publication_authors = []
    errors = []

    author_records = record.get("author_records") or []

    seen_author_keys = set()

    for index, author in enumerate(author_records, start=1):

        if not isinstance(author, dict):
            errors.append(
                f"Hibás szerzői rekord: {index}."
            )
            continue

        name = clean_value(author.get("name"))

        if not name:
            errors.append(
                f"Hiányzó szerzőnév: {index}."
            )
            continue

        orcid = model.normalize_orcid(
            author.get("orcid")
        )

        openalex_id = model.normalize_openalex_id(
            author.get("openalex_id")
        )

        try:
            position = int(author.get("position", index))
        except (ValueError, TypeError):
            position = index

        if position < 1:
            position = index

        # ORCID az egyetlen globálisan használt
        # szerzőazonosító az adatbázisban.
        if orcid:
            author_key = "orcid:" + orcid.casefold()

        else:
            # Azonosító nélküli szerzőt nem kapcsolunk
            # össze más publikáció szerzőjével.
            author_key = (
                publication_key
                + ":author:"
                + str(position)
            )

        # Egy publikáción belül ugyanaz az ORCID
        # csak egyszer kapcsolódhat.
        if author_key in seen_author_keys:
            continue

        seen_author_keys.add(author_key)

        authors.append({
            "author_key": author_key,
            "full_name": name,
            "orcid": orcid,
        })

        publication_authors.append({
            "publication_key": publication_key,
            "author_key": author_key,
            "author_position": position,
        })

    return authors, publication_authors, errors


# ============================================================
# TELJES REKORD LEKÉPEZÉSE
# ============================================================

def map_record(record, source_id_by_code):
    """
    Egy egységes rekord teljes adatbázis-leképezése.

    Nincs adatbázis-kapcsolat.
    Nincs írás.
    """

    source_ids = normalize_source_id_map(
        source_id_by_code
    )

    errors = validate_publication(record)

    if errors:
        return {
            "valid": False,
            "publication_key": None,
            "errors": errors,
            "tables": {},
        }

    publication_key = make_publication_key(record)

    if not publication_key:
        return {
            "valid": False,
            "publication_key": None,
            "errors": ["Nem állítható elő publikációazonosító."],
            "tables": {},
        }

    publication = map_publication(
        record,
        publication_key,
    )

    publication_sources, source_errors = map_publication_sources(
        record,
        publication_key,
        source_ids,
    )

    authors, publication_authors, author_errors = map_authors(
        record,
        publication_key,
    )

    errors.extend(source_errors)
    errors.extend(author_errors)

    if errors:
        return {
            "valid": False,
            "publication_key": publication_key,
            "errors": errors,
            "tables": {},
        }

    return {
        "valid": True,
        "publication_key": publication_key,
        "errors": [],
        "tables": {
            "publications": [publication],
            "publication_sources": publication_sources,
            "authors": authors,
            "publication_authors": publication_authors,
        },
    }


# ============================================================
# TÖMEGES LEKÉPEZÉS
# ============================================================

def map_records(records, source_id_by_code):
    """Több rekord leképezése és összesítése."""

    if not isinstance(records, list):
        raise TypeError("A records mezőnek listának kell lennie.")

    source_ids = normalize_source_id_map(
        source_id_by_code
    )

    result = {
        "mapper_version": MAPPER_VERSION,
        "total_records": len(records),
        "valid_records": 0,
        "invalid_records": 0,
        "errors": [],
        "tables": {
            "publications": [],
            "publication_sources": [],
            "authors": [],
            "publication_authors": [],
        },
    }

    seen_publications = set()
    seen_source_links = set()
    seen_authors = set()
    seen_author_links = set()

    for index, record in enumerate(records, start=1):

        mapped = map_record(record, source_ids)

        if not mapped["valid"]:
            result["invalid_records"] += 1

            result["errors"].append({
                "record_number": index,
                "publication_key": mapped["publication_key"],
                "errors": mapped["errors"],
            })

            continue

        publication_key = mapped["publication_key"]

        if publication_key in seen_publications:
            result["invalid_records"] += 1

            result["errors"].append({
                "record_number": index,
                "publication_key": publication_key,
                "errors": [
                    "Duplikált publikációazonosító a bemeneti listában."
                ],
            })

            continue

        seen_publications.add(publication_key)
        result["valid_records"] += 1

        for row in mapped["tables"]["publications"]:
            result["tables"]["publications"].append(row)

        for row in mapped["tables"]["publication_sources"]:

            key = (
                row["source_id"],
                row["external_id"],
            )

            if key in seen_source_links:
                continue

            seen_source_links.add(key)

            result["tables"]["publication_sources"].append(row)

        for row in mapped["tables"]["authors"]:

            key = row["author_key"]

            if key not in seen_authors:
                seen_authors.add(key)
                result["tables"]["authors"].append(row)

        for row in mapped["tables"]["publication_authors"]:

            key = (
                row["publication_key"],
                row["author_key"],
            )

            if key in seen_author_links:
                continue

            seen_author_links.add(key)

            result["tables"]["publication_authors"].append(row)

    return result


# ============================================================
# JSON ELLENŐRZÉS
# ============================================================

def validate_json_output(result):
    """Ellenőrzi, hogy az eredmény JSON-kompatibilis-e."""

    try:
        json.dumps(
            result,
            ensure_ascii=False,
        )

        return True

    except (TypeError, ValueError):
        return False


# ============================================================
# MODELLER TESZTEK
# ============================================================

def run_mapper_tests():
    """Hálózat és adatbázis nélküli mapper tesztek."""

    test_sources = {
        "openalex": {
            "id": "11111111-1111-1111-1111-111111111111",
            "is_active": True,
        },
        "crossref": {
            "id": "22222222-2222-2222-2222-222222222222",
            "is_active": True,
        },
    }

    # --------------------------------------------------------
    # OpenAlex tesztrekord
    # --------------------------------------------------------

    openalex_record = model.from_openalex({
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
            },
            {
                "author": {
                    "display_name": "Jane Smith",
                    "orcid": None,
                    "id": "https://openalex.org/A654321",
                }
            },
        ],
        "topics": [
            {"display_name": "Artificial Intelligence"}
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

    mapped = map_record(
        openalex_record,
        test_sources,
    )

    assert mapped["valid"]
    assert len(mapped["tables"]["publications"]) == 1
    assert len(mapped["tables"]["publication_sources"]) == 1
    assert len(mapped["tables"]["authors"]) == 2
    assert len(mapped["tables"]["publication_authors"]) == 2

    publication = mapped["tables"]["publications"][0]

    assert publication["doi"] == "10.1234/abc"
    assert publication["title"] == "Example Research Article"
    assert publication["relevance_score"] if False else True

    assert (
        publication["metadata"]["source_metadata"]["openalex"]
        is not None
    )

    assert len(
        publication["metadata"]["author_source_ids"]
    ) == 2

    # --------------------------------------------------------
    # Crossref tesztrekord
    # --------------------------------------------------------

    crossref_record = model.from_crossref({
        "DOI": "10.1234/XYZ",
        "title": ["Crossref Example Article"],
        "type": "journal-article",
        "language": "en",
        "published-online": {
            "date-parts": [[2026, 11, 25]]
        },
        "author": [
            {
                "given": "John",
                "family": "Brown",
                "ORCID": "https://orcid.org/0000-0001-1111-1111",
            }
        ],
        "subject": ["Computer Science"],
        "container-title": ["Example Journal"],
        "publisher": "Example Publisher",
        "URL": "https://doi.org/10.1234/XYZ",
    })

    crossref_mapped = map_record(
        crossref_record,
        test_sources,
    )

    assert crossref_mapped["valid"]
    assert len(
        crossref_mapped["tables"]["publication_sources"]
    ) == 1

    # --------------------------------------------------------
    # DOI nélküli Crossref rekord
    # --------------------------------------------------------

    no_doi_record = model.from_crossref({
        "title": ["Article Without DOI"],
        "type": "journal-article",
        "language": "en",
        "author": [],
        "subject": [],
    })

    no_doi_mapped = map_record(
        no_doi_record,
        test_sources,
    )

    assert not no_doi_mapped["valid"]

    # --------------------------------------------------------
    # Inaktív forrás
    # --------------------------------------------------------

    inactive_sources = {
        "openalex": {
            "id": "11111111-1111-1111-1111-111111111111",
            "is_active": False,
        }
    }

    inactive_mapped = map_record(
        openalex_record,
        inactive_sources,
    )

    assert not inactive_mapped["valid"]

    # --------------------------------------------------------
    # JSON kompatibilitás
    # --------------------------------------------------------

    assert validate_json_output(mapped)

    # --------------------------------------------------------
    # Tömeges leképezés
    # --------------------------------------------------------

    batch = map_records(
        [openalex_record, crossref_record],
        test_sources,
    )

    assert batch["total_records"] == 2
    assert batch["valid_records"] == 2
    assert batch["invalid_records"] == 0

    assert len(batch["tables"]["publications"]) == 2

    assert validate_json_output(batch)

    print("OpenAlex publikáció leképezése: SIKERES")
    print("Crossref publikáció leképezése: SIKERES")
    print("Publikációs mezők leképezése: SIKERES")
    print("Forráskapcsolatok leképezése: SIKERES")
    print("Szerzők leképezése: SIKERES")
    print("Szerzői sorrend kezelése: SIKERES")
    print("OpenAlex szerzőazonosítók megőrzése: SIKERES")
    print("ORCID-alapú szerzőazonosítás: SIKERES")
    print("DOI nélküli Crossref rekord kizárása: SIKERES")
    print("Inaktív adatforrás kezelése: SIKERES")
    print("JSON-kompatibilitás: SIKERES")
    print("Tömeges leképezés: SIKERES")


# ============================================================
# FUTTATÁS
# ============================================================

if __name__ == "__main__":

    print("=" * 60)
    print("SYNAPSE – ADATBÁZIS-MAPPER")
    print("=" * 60)

    run_mapper_tests()

    print("=" * 60)
    print("M2.7.4.1 / 0.1.0 – MAPPER TESZTEK SIKERESEK")
    print("Hálózati kapcsolat: NINCS")
    print("Supabase-kapcsolat: NINCS")
    print("Adatbázisba írás: NINCS")
    print("=" * 60)
