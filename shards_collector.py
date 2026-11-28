
"""
WORLD SHARDS – Tartalomgyűjtő motor
Verzió: M1.2 / 0.1.0

Első bekötött adatforrások:
- Research Frontier: SYNAPSE publications
- Art of the Day: Art Institute of Chicago API

A program nem módosítja a SYNAPSE rekordokat.
"""

import os
import re
import html
import json
import time
from datetime import datetime, timezone

import requests
from resilient_storage import create_resilient_client
# ============================================================
# BEÁLLÍTÁSOK
# ============================================================

VERSION = "M1.2 / 0.1.0"

# Per-run target and bounded keyless pagination through the publication table.
SYNAPSE_LIMIT = 100
SYNAPSE_PAGE_SIZE = 100
SYNAPSE_MAX_SCAN = 1000
ART_LIMIT = 50
ART_SEARCH_QUERIES_PER_RUN = 2
REQUEST_TIMEOUT = 30

ART_API_URL = "https://api.artic.edu/api/v1/artworks/search"

ART_SEARCH_TERMS = [
    "painting", "sculpture", "landscape", "portrait", "still life",
    "architecture", "mythology", "religion", "animals", "flowers",
    "city", "history", "daily life", "abstract", "printmaking",
    "textile", "ceramics", "drawing", "decorative arts", "seascape",
]


# ============================================================
# KAPCSOLATOK
# ============================================================

def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")
    return create_resilient_client(url, key)

def clean_html(value):
    if not value:
        return None

    value = re.sub(r"<[^>]+>", " ", str(value))
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)

    return value.strip() or None


def now_utc():
    return datetime.now(timezone.utc)


# ============================================================
# DUPLIKÁCIÓVÉDELEM
# ============================================================

def content_exists(client, source_url):
    if not source_url:
        return False

    response = (
        client.table("shard_content_items")
        .select("id")
        .eq("source_url", source_url)
        .limit(1)
        .execute()
    )

    return bool(response.data)


def save_content(client, item):
    source_url = item.get("source_url")

    if source_url and content_exists(client, source_url):
        return "skipped"

    client.table("shard_content_items").insert(
        item
    ).execute()

    return "inserted"


# ============================================================
# RESEARCH FRONTIER – SYNAPSE
# ============================================================

def score_research_publication(publication):
    """
    Rank editorial readiness, not scientific merit.
    The score rewards a usable abstract and verifiable bibliographic context.
    """
    score = 0
    abstract = clean_html(publication.get("abstract")) or ""
    abstract_length = len(abstract)

    if abstract_length >= 120:
        score += 20
    if abstract_length >= 300:
        score += 10
    if abstract_length >= 700:
        score += 5

    if publication.get("doi"):
        score += 8
    if publication.get("journal"):
        score += 6
    if publication.get("publication_type") == "journal-article":
        score += 6

    metadata = publication.get("metadata") or {}
    if isinstance(metadata, dict):
        authors = metadata.get("author_source_ids") or []
        topics = metadata.get("topics") or []
        subjects = metadata.get("subjects") or []
        if authors:
            score += 4
        if topics:
            score += 6
        if subjects:
            score += 3

    return score


def research_publication_exists(client, publication):
    """Deduplicate by DOI / stable SYNAPSE ID, not only by landing-page URL."""
    metadata = {}
    doi = publication.get("doi")
    publication_id = publication.get("id")

    if doi:
        metadata["doi"] = doi
    elif publication_id:
        metadata["synapse_publication_id"] = publication_id

    if metadata:
        response = (
            client.table("shard_content_items")
            .select("id")
            .eq("section_code", "research_frontier")
            .contains("metadata", metadata)
            .limit(1)
            .execute()
        )
        if response.data:
            return True

    source_url = publication.get("url") or (
        f"https://doi.org/{doi}" if doi else None
    )
    return content_exists(client, source_url)


def get_research_publication_page(client, offset):
    """Fetch one deterministic window from the SYNAPSE publication table."""
    response = (
        client.table("publications")
        .select(
            "id,title,abstract,doi,publication_date,"
            "publication_year,publication_type,language,"
            "journal,publisher,url,metadata"
        )
        .order("publication_date", desc=True)
        .range(offset, offset + SYNAPSE_PAGE_SIZE - 1)
        .execute()
    )
    return response.data or []


def collect_research(client):
    print()
    print("=" * 65)
    print("RESEARCH FRONTIER – SYNAPSE")
    print("=" * 65)

    inserted = 0
    skipped = 0
    scanned = 0
    offset = 0
    pages = 0

    # Do not stop at the newest 100 database rows: already-imported or
    # unusable records must not hide older, still-unseen publications.
    while scanned < SYNAPSE_MAX_SCAN and inserted < SYNAPSE_LIMIT:
        publications = get_research_publication_page(client, offset)
        if not publications:
            break

        pages += 1
        offset += len(publications)

        for publication in publications:
            scanned += 1
            doi = publication.get("doi")

            source_url = (
                publication.get("url")
                or (f"https://doi.org/{doi}" if doi else None)
            )
            abstract = clean_html(publication.get("abstract"))

            if not publication.get("title") or len(abstract or "") < 120:
                skipped += 1
                continue

            if not source_url:
                skipped += 1
                continue

            if research_publication_exists(client, publication):
                skipped += 1
                continue

            item = {
                "section_code": "research_frontier",
                "title": publication["title"],
                "summary": abstract,
                "source_name": "SYNAPSE",
                "source_url": source_url,
                "source_published_at": publication.get(
                    "publication_date"
                ),
                "source_language": publication.get("language"),
                "status": "candidate",
                "relevance_score": score_research_publication(publication),
                "metadata": {
                    "origin": "SYNAPSE",
                    "synapse_publication_id": publication["id"],
                    "doi": doi,
                    "publication_year": publication.get(
                        "publication_year"
                    ),
                    "publication_type": publication.get(
                        "publication_type"
                    ),
                    "journal": publication.get("journal"),
                    "publisher": publication.get("publisher"),
                    "synapse_metadata": publication.get(
                        "metadata"
                    ) or {},
                },
            }

            result = save_content(client, item)

            if result == "inserted":
                inserted += 1
                print("ÚJ:", publication["title"][:85])
            else:
                skipped += 1

            if inserted >= SYNAPSE_LIMIT or scanned >= SYNAPSE_MAX_SCAN:
                break

        if len(publications) < SYNAPSE_PAGE_SIZE:
            break

    print("SYNAPSE átvizsgált rekord:", scanned)
    print("SYNAPSE oldalak:", pages)
    print("Új tartalom:", inserted)
    print("Már létezett / kihagyva / érvénytelen:", skipped)

    return {
        "inserted": inserted,
        "skipped": skipped,
        "scanned": scanned,
        "pages": pages,
    }


# ============================================================
# ART OF THE DAY – ART INSTITUTE OF CHICAGO
# ============================================================

def get_art_search_terms():
    """Return two rotating themes; the offset cycles through each theme's results."""
    day_number = now_utc().timetuple().tm_yday
    first = (day_number - 1) % len(ART_SEARCH_TERMS)
    second = (first + 7) % len(ART_SEARCH_TERMS)
    return [ART_SEARCH_TERMS[first], ART_SEARCH_TERMS[second]]


def get_art_search_term():
    """Backward-compatible single daily theme."""
    return get_art_search_terms()[0]


def score_artwork(artwork):
    """Rank records by the completeness and editorial usefulness of their metadata."""
    score = 0
    title = str(artwork.get("title") or "").strip().casefold()
    if title and title not in {"untitled", "unknown", "no title"}:
        score += 12
    if artwork.get("artist_display") or artwork.get("artist_title"):
        score += 18
    if artwork.get("date_display"):
        score += 10
    if artwork.get("medium_display") or artwork.get("medium"):
        score += 10
    description = clean_html(
        artwork.get("description") or artwork.get("short_description")
    ) or ""
    if len(description) >= 300:
        score += 22
    elif len(description) >= 100:
        score += 16
    elif description:
        score += 8
    if artwork.get("place_of_origin"):
        score += 7
    if artwork.get("style_title"):
        score += 7
    if artwork.get("classification_title"):
        score += 7
    if artwork.get("dimensions"):
        score += 3
    return score


def build_artwork_record(artwork, search_term):
    """Convert one Art Institute API result into a complete, image-ready candidate."""
    if not isinstance(artwork, dict) or artwork.get("is_public_domain") is not True:
        return None

    artwork_id = artwork.get("id")
    title = clean_html(artwork.get("title"))
    image_id = artwork.get("image_id")
    if not artwork_id or not title or not image_id:
        return None

    artist = clean_html(
        artwork.get("artist_display") or artwork.get("artist_title")
    )
    date_display = clean_html(artwork.get("date_display"))
    medium = clean_html(
        artwork.get("medium_display") or artwork.get("medium")
    )
    description = clean_html(
        artwork.get("description") or artwork.get("short_description")
    )
    place_of_origin = clean_html(artwork.get("place_of_origin"))
    style = clean_html(artwork.get("style_title"))
    classification = clean_html(artwork.get("classification_title"))
    dimensions = clean_html(artwork.get("dimensions"))
    image_url = (
        f"https://www.artic.edu/iiif/2/{image_id}/full/843,/0/default.jpg"
    )
    source_url = f"https://www.artic.edu/artworks/{artwork_id}"

    summary_parts = []
    if artist:
        summary_parts.append(f"Művész: {artist}")
    if date_display:
        summary_parts.append(f"Keletkezés: {date_display}")
    if place_of_origin:
        summary_parts.append(f"Eredet: {place_of_origin}")
    if medium:
        summary_parts.append(f"Technika és anyag: {medium}")
    if description:
        summary_parts.append(description)

    quality_score = score_artwork(artwork)
    return {
        "section_code": "art_of_the_day",
        "title": title,
        "summary": " ".join(summary_parts) or None,
        "image_url": image_url,
        "source_name": "Art Institute of Chicago",
        "source_url": source_url,
        "source_language": "en",
        "status": "candidate",
        "relevance_score": quality_score,
        "metadata": {
            "origin": "Art Institute of Chicago API",
            "artwork_id": artwork_id,
            "artist": artist,
            "date_display": date_display,
            "medium": medium,
            "description": description,
            "place_of_origin": place_of_origin,
            "style_title": style,
            "classification_title": classification,
            "dimensions": dimensions,
            "image_id": image_id,
            "image_url": image_url,
            "is_public_domain": True,
            "metadata_license": "CC0",
            "description_license": "CC BY 4.0",
            "search_term": search_term,
            "quality_score": quality_score,
        },
    }


def collect_art(client):
    print()
    print("=" * 65)
    print("ART OF THE DAY – ART INSTITUTE OF CHICAGO")
    print("=" * 65)

    day_number = now_utc().timetuple().tm_yday
    search_terms = get_art_search_terms()
    page_offset = (((day_number - 1) // len(ART_SEARCH_TERMS)) % 10) * ART_LIMIT
    print("Keresési témák:", ", ".join(search_terms))
    print("Keresési offset:", page_offset)

    fields = (
        "id,title,artist_title,artist_display,date_display,medium_display,"
        "description,short_description,image_id,is_public_domain,"
        "place_of_origin,style_title,classification_title,dimensions,thumbnail"
    )
    public_domain_with_image = {
        "bool": {
            "filter": [
                {"term": {"is_public_domain": True}},
                {"exists": {"field": "image_id"}},
            ]
        }
    }

    inserted = 0
    skipped = 0
    seen_ids = set()
    total_returned = 0

    for term_index, search_term in enumerate(search_terms):
        if term_index:
            # The museum asks API consumers to self-throttle requests.
            time.sleep(1)

        params = {
            "q": search_term,
            "from": page_offset,
            "size": ART_LIMIT,
            "fields": fields,
            "query": json.dumps(public_domain_with_image, separators=(",", ":")),
        }
        response = requests.get(
            ART_API_URL,
            params=params,
            headers={"AIC-User-Agent": "WORLD-SHARDS/1.0"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        artworks = response.json().get("data", [])
        total_returned += len(artworks)

        for artwork in artworks:
            item = build_artwork_record(artwork, search_term)
            if not item:
                skipped += 1
                continue
            artwork_id = item["metadata"]["artwork_id"]
            if artwork_id in seen_ids:
                skipped += 1
                continue
            seen_ids.add(artwork_id)

            result = save_content(client, item)
            if result == "inserted":
                inserted += 1
                print("ÚJ:", item["title"][:85], f"(minőségi pont: {item['relevance_score']})")
            else:
                skipped += 1

    print("API által visszaadott művek:", total_returned)
    print("Új, képpel rendelkező közkincs művek:", inserted)
    print("Már létezett / hiányos / kihagyva:", skipped)
    return {"inserted": inserted, "skipped": skipped}


# ============================================================
# FŐPROGRAM
# ============================================================

def main():
    print("=" * 65)
    print("WORLD SHARDS – TARTALOMGYŰJTŐ MOTOR")
    print("Verzió:", VERSION)
    print("=" * 65)

    client = get_supabase_client()

    if client.remote is not None:
        print("Adattár: Supabase (elsődleges) + SQLite tartalék")
    else:
        print("Adattár: SQLite-only tartalék üzemmód")

    results = {}
    errors = []

    collectors = {
        "research_frontier": collect_research,
        "art_of_the_day": collect_art,
    }

    for section, collector in collectors.items():
        try:
            results[section] = collector(client)
        except Exception as error:
            errors.append(f"{section}: {error}")
            print()
            print("GYŰJTÉSI HIBA:", section, error)

    total_inserted = sum(
        result["inserted"]
        for result in results.values()
    )

    total_skipped = sum(
        result["skipped"]
        for result in results.values()
    )

    print()
    print("=" * 65)
    print("WORLD SHARDS – GYŰJTÉSI EREDMÉNY")
    print("=" * 65)

    print("Új tartalmak:", total_inserted)
    print("Kihagyott tartalmak:", total_skipped)
    print("Hibás rovatok:", len(errors))

    for error in errors:
        print("HIBA:", error)

    print("=" * 65)

    if errors:
        raise SystemExit(1)

    if total_inserted == 0:
        print(
            "FIGYELEM: Nem került be új tartalom. "
            "Lehet, hogy minden rekord már szerepelt."
        )


if __name__ == "__main__":
    main()
