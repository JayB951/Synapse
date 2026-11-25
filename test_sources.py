
"""
SYNAPSE – Adatforrások tesztelése és publikációk egységesítése
Verzió: M2.7.3 / 0.4

Adatforrások:
- OpenAlex
- Crossref

Feladatok:
- Publikációk lekérése
- Dátumszűrés
- Angol nyelv ellenőrzése
- Publikációtípus ellenőrzése
- Egységes adatmodell előállítása
- DOI-alapú duplikációkezelés
- Strukturált szerzői adatok megőrzése
- Forrásspecifikus metaadatok megőrzése
- Egységesített rekordok megjelenítése

Fontos:
- Nincs Supabase-kapcsolat.
- Nincs adatbázisba írás.
- Nincs adatbázis-módosítás.
"""

import os
import sys
import re
import calendar
from datetime import date, timedelta
from collections import Counter

import requests
import publication_model as model


# ============================================================
# BEÁLLÍTÁSOK
# ============================================================

OPENALEX_API_URL = "https://api.openalex.org/works"
CROSSREF_API_URL = "https://api.crossref.org/works"

RECORD_LIMIT = 50
DISPLAY_LIMIT = 10

REQUEST_TIMEOUT = 30

END_DATE = date.today()
START_DATE = END_DATE - timedelta(days=365)

OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY")
CROSSREF_MAILTO = os.getenv("CROSSREF_MAILTO")

USER_AGENT = (
    "SYNAPSE/0.4 "
    "(scientific publication collection and research project)"
)


# ============================================================
# PUBLIKÁCIÓTÍPUSOK
# ============================================================

# Csak ismert, értelmezhető publikációtípusokat fogadunk el.
# Az ismeretlen típus automatikusan kizárásra kerül.

ACCEPTED_PUBLICATION_TYPES = {
    "article",
    "journal-article",
    "proceedings-article",
    "book",
    "book-chapter",
    "book-section",
    "book-part",
    "dissertation",
    "thesis",
    "preprint",
    "posted-content",
    "report",
    "report-series",
    "monograph",
    "edited-book",
    "reference-entry",
    "review",
    "peer-review",
    "standard",
}


# ============================================================
# SEGÉDFÜGGVÉNYEK
# ============================================================

def print_section(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def clean_string(value):
    """Szöveg alapvető tisztítása."""

    if value is None:
        return None

    value = str(value).strip()

    return value or None


def get_record_date(record):
    """Publikációs dátum kinyerése a modellből."""

    publication_date = record.get("publication_date")

    if not publication_date:
        return None

    try:
        return date.fromisoformat(
            str(publication_date)[:10]
        )

    except (ValueError, TypeError):
        return None


def is_within_date_range(record):
    """Publikáció dátumának ellenőrzése."""

    publication_date = get_record_date(record)

    if not publication_date:
        return False

    return START_DATE <= publication_date <= END_DATE


def is_accepted_publication_type(record):
    """Publikációtípus ellenőrzése."""

    publication_type = record.get("publication_type")

    if not publication_type:
        return False

    return (
        str(publication_type).strip().lower()
        in ACCEPTED_PUBLICATION_TYPES
    )


# ============================================================
# NYELVELLENŐRZÉS
# ============================================================

def reconstruct_text(record):
    """A cím és absztrakt egyesítése a nyelvi ellenőrzéshez."""

    title = clean_string(record.get("title"))
    abstract = clean_string(record.get("abstract"))

    return " ".join(
        value for value in [title, abstract] if value
    )


def is_english_by_text(record):
    """
    Szabályalapú angol nyelvi ellenőrzés.

    A cím és az absztrakt együttes szövegében
    a következő szavak mindegyikének legalább
    háromszor kell szerepelnie:

    - the
    - and
    - of

    A vizsgálat különálló szavakat számol.
    """

    text = reconstruct_text(record)

    if not text:
        return False

    words = re.findall(
        r"\b[a-z]+\b",
        text.lower()
    )

    word_counts = Counter(words)

    required_words = [
        "the",
        "and",
        "of",
    ]

    return all(
        word_counts[word] >= 3
        for word in required_words
    )


def is_english(record):
    """
    Nyelvi ellenőrzés.

    Ha a forrás egyértelműen megadja a nyelvet:
    - angol: elfogadás
    - nem angol: kizárás

    Ha a nyelv nem ismert:
    - cím + absztrakt szövegalapú ellenőrzése.
    """

    language = clean_string(
        record.get("language")
    )

    if language:
        normalized_language = language.lower()

        if normalized_language in {
            "en",
            "eng",
            "english",
        }:
            return True

        return False

    return is_english_by_text(record)


# ============================================================
# OPENALEX LEKÉRDEZÉS
# ============================================================

def fetch_openalex():
    """Legfeljebb 50 OpenAlex rekord lekérése."""

    params = {
        "filter": (
            f"from_publication_date:{START_DATE.isoformat()},"
            f"to_publication_date:{END_DATE.isoformat()},"
            "language:en"
        ),
        "per-page": RECORD_LIMIT,
        "sort": "publication_date:desc",
    }

    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY

    headers = {
        "User-Agent": USER_AGENT,
    }

    print_section("OPENALEX LEKÉRDEZÉS")

    print(
        f"Időszak: {START_DATE} – {END_DATE}"
    )
    print(
        f"Rekordlimit: {RECORD_LIMIT}"
    )

    try:
        response = requests.get(
            OPENALEX_API_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        records = data.get("results", [])

        print(
            f"OpenAlex által visszaadott rekordok: "
            f"{len(records)}"
        )

        return records

    except requests.RequestException as error:
        print(
            f"OPENALEX API HIBA: {error}"
        )

        return []

    except ValueError as error:
        print(
            f"OPENALEX JSON HIBA: {error}"
        )

        return []


# ============================================================
# CROSSREF LEKÉRDEZÉS
# ============================================================

def fetch_crossref():
    """Legfeljebb 50 Crossref rekord lekérése."""

    params = {
        "filter": (
            f"from-pub-date:{START_DATE.isoformat()},"
            f"until-pub-date:{END_DATE.isoformat()}"
        ),
        "rows": RECORD_LIMIT,
        "sort": "published",
        "order": "desc",
    }

    if CROSSREF_MAILTO:
        params["mailto"] = CROSSREF_MAILTO

    headers = {
        "User-Agent": USER_AGENT,
    }

    print_section("CROSSREF LEKÉRDEZÉS")

    print(
        f"Időszak: {START_DATE} – {END_DATE}"
    )
    print(
        f"Rekordlimit: {RECORD_LIMIT}"
    )

    try:
        response = requests.get(
            CROSSREF_API_URL,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        message = data.get("message", {})

        records = message.get("items", [])

        print(
            f"Crossref által visszaadott rekordok: "
            f"{len(records)}"
        )

        return records

    except requests.RequestException as error:
        print(
            f"CROSSREF API HIBA: {error}"
        )

        return []

    except ValueError as error:
        print(
            f"CROSSREF JSON HIBA: {error}"
        )

        return []


# ============================================================
# REKORDOK FELDOLGOZÁSA
# ============================================================

def process_records(records, source_name, converter):
    """
    Forrásrekordok feldolgozása.

    Sorrend:
    1. Átalakítás egységes modellre.
    2. Dátumellenőrzés.
    3. Nyelvellenőrzés.
    4. Publikációtípus ellenőrzése.
    5. Cím meglétének ellenőrzése.
    """

    accepted = []

    rejected_reasons = Counter()

    print_section(
        f"{source_name.upper()} REKORDOK FELDOLGOZÁSA"
    )

    for item in records:
        try:
            record = converter(item)

        except Exception as error:
            rejected_reasons["modellhiba"] += 1

            print(
                f"Modellhiba ({source_name}): {error}"
            )

            continue

        if not record.get("title"):
            rejected_reasons["hiányzó cím"] += 1
            continue

        if not is_within_date_range(record):
            rejected_reasons["dátumszűrés"] += 1
            continue

        if not is_english(record):
            rejected_reasons["nem angol nyelv"] += 1
            continue

        if not is_accepted_publication_type(record):
            rejected_reasons["ismeretlen publikációtípus"] += 1
            continue

        if not model.validate_record(record):
            rejected_reasons["hibás modellrekord"] += 1
            continue

        accepted.append(record)

    print(
        f"Lekért rekordok: {len(records)}"
    )

    print(
        f"Elfogadott rekordok: {len(accepted)}"
    )

    print(
        f"Kizárt rekordok: "
        f"{sum(rejected_reasons.values())}"
    )

    if rejected_reasons:
        print()
        print("Kizárási okok:")

        for reason, count in rejected_reasons.items():
            print(
                f"  - {reason}: {count}"
            )

    return accepted, rejected_reasons


def process_openalex(records):
    """OpenAlex rekordok feldolgozása."""

    return process_records(
        records,
        "OpenAlex",
        model.from_openalex,
    )


def process_crossref(records):
    """Crossref rekordok feldolgozása."""

    return process_records(
        records,
        "Crossref",
        model.from_crossref,
    )


# ============================================================
# LISTÁK ÖSSZEFŰZÉSE
# ============================================================

def merge_unique_values(first, second):
    """Két lista egyedi elemeinek stabil sorrendű összevonása."""

    result = []

    for value in (first or []) + (second or []):
        if value is None:
            continue

        if value not in result:
            result.append(value)

    return result


# ============================================================
# PUBLIKÁCIÓS REKORDOK ÖSSZEVONÁSA
# ============================================================

def merge_publication_records(first, second):
    """
    Két azonos DOI-jú publikáció összevonása.

    Az első rekord szolgál alapként.
    A második rekordból hiányzó bibliográfiai adatok
    kiegészítésre kerülnek.

    A forrásadatokat és az eredeti metaadatokat megőrizzük.
    """

    merged = dict(first)

    # --------------------------------------------------------
    # Egyszerű mezők
    # --------------------------------------------------------

    simple_fields = [
        "title",
        "publication_date",
        "publication_year",
        "publication_type",
        "language",
        "abstract",
        "journal",
        "publisher",
        "url",
        "classification",
        "openalex_id",
    ]

    for field in simple_fields:
        if not merged.get(field) and second.get(field):
            merged[field] = second[field]

    # --------------------------------------------------------
    # Strukturált szerzők
    # --------------------------------------------------------

    merged["author_records"] = model.merge_author_records(
        first.get("author_records", []),
        second.get("author_records", []),
    )

    # A szerzőneveket a strukturált adatokból építjük újra.
    # Név szerinti deduplikáció nincs.
    merged["authors"] = model.author_names_from_records(
        merged["author_records"]
    )

    # --------------------------------------------------------
    # Témakörök és tárgyszavak
    # --------------------------------------------------------

    merged["topics"] = merge_unique_values(
        first.get("topics", []),
        second.get("topics", []),
    )

    merged["subjects"] = merge_unique_values(
        first.get("subjects", []),
        second.get("subjects", []),
    )

    merged["topic_terms"] = model.merge_topic_terms(
        first.get("topic_terms", []),
        second.get("topic_terms", []),
    )

    # --------------------------------------------------------
    # Források
    # --------------------------------------------------------

    merged["sources"] = merge_unique_values(
        first.get("sources", []),
        second.get("sources", []),
    )

    # --------------------------------------------------------
    # Forrástípusok
    # --------------------------------------------------------

    merged["source_types"] = dict(
        first.get("source_types") or {}
    )

    merged["source_types"].update(
        second.get("source_types") or {}
    )

    # --------------------------------------------------------
    # Forrásazonosítók
    # --------------------------------------------------------

    merged["source_ids"] = dict(
        first.get("source_ids") or {}
    )

    merged["source_ids"].update(
        second.get("source_ids") or {}
    )

    # --------------------------------------------------------
    # Forrásmetaadatok
    # --------------------------------------------------------

    merged["source_metadata"] = dict(
        first.get("source_metadata") or {}
    )

    for source_name, metadata in (
        second.get("source_metadata") or {}
    ).items():

        if source_name not in merged["source_metadata"]:
            merged["source_metadata"][source_name] = metadata

        elif isinstance(metadata, dict):
            existing = merged["source_metadata"][source_name]

            if isinstance(existing, dict):
                combined = dict(existing)
                combined.update(metadata)

                merged["source_metadata"][source_name] = combined

    return merged


# ============================================================
# DOI ALAPÚ DEDUPLIKÁCIÓ
# ============================================================

def deduplicate_records(records):
    """
    Publikációk deduplikálása DOI alapján.

    DOI-val rendelkező rekordok:
    - azonos DOI esetén összevonásra kerülnek.

    DOI nélküli rekordok:
    - külön rekordként maradnak meg.
    """

    unique_records = []
    doi_positions = {}

    duplicate_count = 0

    for record in records:
        doi = model.normalize_doi(
            record.get("doi")
        )

        if not doi:
            unique_records.append(record)
            continue

        if doi not in doi_positions:
            doi_positions[doi] = len(unique_records)
            unique_records.append(record)

        else:
            position = doi_positions[doi]

            unique_records[position] = (
                merge_publication_records(
                    unique_records[position],
                    record,
                )
            )

            duplicate_count += 1

    return unique_records, duplicate_count


# ============================================================
# EGYSÉGES REKORD MEGJELENÍTÉSE
# ============================================================

def print_unified_record(record, index):
    """Egy egységes publikációs rekord megjelenítése."""

    print()
    print("-" * 70)

    print(
        f"REKORD #{index}"
    )

    print(
        f"Cím: {record.get('title')}"
    )

    print(
        f"DOI: {record.get('doi') or 'Nincs'}"
    )

    print(
        f"OpenAlex ID: "
        f"{record.get('openalex_id') or 'Nincs'}"
    )

    print(
        f"Dátum: "
        f"{record.get('publication_date') or 'Nincs'}"
    )

    print(
        f"Publikációs év: "
        f"{record.get('publication_year') or 'Nincs'}"
    )

    print(
        f"Típus: "
        f"{record.get('publication_type') or 'Nincs'}"
    )

    print(
        f"Nyelv: "
        f"{record.get('language') or 'Nincs'}"
    )

    print(
        f"Folyóirat: "
        f"{record.get('journal') or 'Nincs'}"
    )

    print(
        f"Kiadó: "
        f"{record.get('publisher') or 'Nincs'}"
    )

    print(
        f"URL: "
        f"{record.get('url') or 'Nincs'}"
    )

    print(
        f"Források: "
        f"{', '.join(record.get('sources') or []) or 'Nincs'}"
    )

    print(
        f"Forrásazonosítók: "
        f"{record.get('source_ids') or {}}"
    )

    print(
        f"Szerzők száma: "
        f"{len(record.get('author_records') or [])}"
    )

    for author in record.get("author_records") or []:
        print(
            "  - "
            f"{author.get('position')}. "
            f"{author.get('name')} "
            f"| ORCID: {author.get('orcid') or '-'} "
            f"| OpenAlex ID: "
            f"{author.get('openalex_id') or '-'}"
        )

    print(
        f"Témakörök: "
        f"{', '.join(record.get('topics') or []) or 'Nincs'}"
    )

    print(
        f"Tárgyszavak: "
        f"{', '.join(record.get('subjects') or []) or 'Nincs'}"
    )

    print(
        f"Egységesített témakörök: "
        f"{len(record.get('topic_terms') or [])}"
    )

    print(
        f"Forrástípusok: "
        f"{record.get('source_types') or {}}"
    )

    print(
        f"Forrásmetaadatok: "
        f"{list((record.get('source_metadata') or {}).keys())}"
    )

    abstract = record.get("abstract")

    if abstract:
        print(
            f"Absztrakt: {abstract[:500]}"
        )

        if len(abstract) > 500:
            print("...")
    else:
        print("Absztrakt: Nincs")


# ============================================================
# ÖSSZESÍTÉS
# ============================================================

def print_summary(
    openalex_records,
    crossref_records,
    unified_records,
    duplicate_count,
):
    """A teszt eredményének összesítése."""

    print_section("ÖSSZESÍTETT EREDMÉNY")

    total_downloaded = (
        len(openalex_records)
        + len(crossref_records)
    )

    total_accepted = (
        len(openalex_records)
        + len(crossref_records)
    )

    print(
        f"OpenAlex elfogadott rekordok: "
        f"{len(openalex_records)}"
    )

    print(
        f"Crossref elfogadott rekordok: "
        f"{len(crossref_records)}"
    )

    print(
        f"Összes elfogadott rekord: "
        f"{total_accepted}"
    )

    print(
        f"DOI alapján összevont duplikációk: "
        f"{duplicate_count}"
    )

    print(
        f"Egységes rekordok száma: "
        f"{len(unified_records)}"
    )

    print(
        f"Rekordok csökkenése deduplikáció után: "
        f"{total_downloaded - len(unified_records)}"
    )

    print()
    print("Adatbázisba írás: NINCS")
    print("Supabase-kapcsolat: NINCS")
    print("Adatbázis-módosítás: NINCS")


# ============================================================
# FŐPROGRAM
# ============================================================

def main():
    """A teljes adatforrás-teszt végrehajtása."""

    print_section(
        "SYNAPSE – ADATFORRÁSOK ÉS REKORDÖSSZEVONÁS"
    )

    print(
        "Verzió: M2.7.3 / 0.4"
    )

    print(
        f"Gyűjtési időszak: {START_DATE} – {END_DATE}"
    )

    print(
        f"Forrásonkénti limit: {RECORD_LIMIT}"
    )

    print(
        f"Megjelenített rekordok maximuma: {DISPLAY_LIMIT}"
    )

    print(
        "Adatbázisba mentés: NINCS"
    )

    # --------------------------------------------------------
    # 1. Lekérdezés
    # --------------------------------------------------------

    openalex_raw = fetch_openalex()
    crossref_raw = fetch_crossref()

    if not openalex_raw and not crossref_raw:
        print()
        print(
            "HIBA: Egyik adatforrásból sem érkezett rekord."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # 2. Feldolgozás
    # --------------------------------------------------------

    openalex_records, openalex_rejected = (
        process_openalex(openalex_raw)
    )

    crossref_records, crossref_rejected = (
        process_crossref(crossref_raw)
    )

    # --------------------------------------------------------
    # 3. Közös lista
    # --------------------------------------------------------

    all_records = (
        openalex_records
        + crossref_records
    )

    # --------------------------------------------------------
    # 4. DOI-alapú deduplikáció
    # --------------------------------------------------------

    unified_records, duplicate_count = (
        deduplicate_records(all_records)
    )

    # --------------------------------------------------------
    # 5. Modellvalidáció
    # --------------------------------------------------------

    invalid_records = []

    for record in unified_records:
        if not model.validate_record(record):
            invalid_records.append(record)

    if invalid_records:
        print_section("MODELLVALIDÁCIÓS HIBA")

        print(
            f"Hibás rekordok száma: {len(invalid_records)}"
        )

        sys.exit(1)

    # --------------------------------------------------------
    # 6. Összesítés
    # --------------------------------------------------------

    print_summary(
        openalex_records,
        crossref_records,
        unified_records,
        duplicate_count,
    )

    # --------------------------------------------------------
    # 7. Rekordok megjelenítése
    # --------------------------------------------------------

    print_section(
        f"EGYSÉGESÍTETT REKORDOK – ELSŐ {DISPLAY_LIMIT}"
    )

    for index, record in enumerate(
        unified_records[:DISPLAY_LIMIT],
        start=1,
    ):
        print_unified_record(record, index)

    # --------------------------------------------------------
    # 8. Végállapot
    # --------------------------------------------------------

    print_section("TESZT BEFEJEZVE")

    print(
        "OpenAlex feldolgozás: KÉSZ"
    )

    print(
        "Crossref feldolgozás: KÉSZ"
    )

    print(
        "DOI-alapú deduplikáció: KÉSZ"
    )

    print(
        "Strukturált szerzők kezelése: KÉSZ"
    )

    print(
        "Forrásmetaadatok megőrzése: KÉSZ"
    )

    print(
        "Egységes modell validációja: SIKERES"
    )

    print(
        "Supabase-írás: NEM TÖRTÉNT"
    )


if __name__ == "__main__":
    main()
