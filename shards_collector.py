
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
from datetime import datetime, timezone

import requests
from resilient_storage import create_resilient_client
# ============================================================
# BEÁLLÍTÁSOK
# ============================================================

VERSION = "M1.2 / 0.1.0"

SYNAPSE_LIMIT = 25
ART_LIMIT = 20
REQUEST_TIMEOUT = 30

ART_API_URL = "https://api.artic.edu/api/v1/artworks/search"

ART_SEARCH_TERMS = [
    "landscape",
    "portrait",
    "still life",
    "architecture",
    "nature",
    "mythology",
    "animal",
    "abstract",
]


# ============================================================
# KAPCSOLATOK
# ============================================================

def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url or not key:
        raise RuntimeError(
            "Hiányzó SUPABASE_URL vagy SUPABASE_SECRET_KEY."
        )

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

def collect_research(client):
    print()
    print("=" * 65)
    print("RESEARCH FRONTIER – SYNAPSE")
    print("=" * 65)

    response = (
        client.table("publications")
        .select(
            "id,title,abstract,doi,publication_date,"
            "publication_year,publication_type,language,"
            "journal,url,metadata"
        )
        .order("publication_date", desc=True)
        .limit(SYNAPSE_LIMIT)
        .execute()
    )

    publications = response.data or []

    inserted = 0
    skipped = 0

    for publication in publications:
        doi = publication.get("doi")

        source_url = (
            publication.get("url")
            or (f"https://doi.org/{doi}" if doi else None)
        )

        if not source_url:
            skipped += 1
            continue

        item = {
            "section_code": "research_frontier",
            "title": publication["title"],
            "summary": publication.get("abstract"),
            "source_name": "SYNAPSE",
            "source_url": source_url,
            "source_published_at": publication.get(
                "publication_date"
            ),
            "source_language": publication.get("language"),
            "status": "candidate",
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

    print("SYNAPSE rekord:", len(publications))
    print("Új tartalom:", inserted)
    print("Már létezett / kihagyva:", skipped)

    return {
        "inserted": inserted,
        "skipped": skipped,
    }


# ============================================================
# ART OF THE DAY – ART INSTITUTE OF CHICAGO
# ============================================================

def get_art_search_term():
    day_number = now_utc().timetuple().tm_yday
    return ART_SEARCH_TERMS[day_number % len(ART_SEARCH_TERMS)]


def collect_art(client):
    print()
    print("=" * 65)
    print("ART OF THE DAY – ART INSTITUTE OF CHICAGO")
    print("=" * 65)

    search_term = get_art_search_term()

    print("Keresési téma:", search_term)

    params = {
        "q": search_term,
        "limit": ART_LIMIT,
        "fields": (
            "id,title,artist_title,date_display,medium,"
            "description,image_id,is_public_domain"
        ),
        "query[term][is_public_domain]": "true",
    }

    headers = {
        "AIC-User-Agent": "WORLD-SHARDS/0.1",
    }

    response = requests.get(
        ART_API_URL,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    artworks = response.json().get("data", [])

    inserted = 0
    skipped = 0

    for artwork in artworks:
        if not artwork.get("is_public_domain"):
            skipped += 1
            continue

        artwork_id = artwork.get("id")
        title = artwork.get("title")

        if not artwork_id or not title:
            skipped += 1
            continue

        source_url = (
            f"https://www.artic.edu/artworks/{artwork_id}"
        )

        image_id = artwork.get("image_id")

        image_url = (
            f"https://www.artic.edu/iiif/2/{image_id}"
            "/full/843,/0/default.jpg"
            if image_id else None
        )

        description = clean_html(
            artwork.get("description")
        )

        artist = artwork.get("artist_title")

        summary_parts = []

        if artist:
            summary_parts.append(f"Művész: {artist}")

        if artwork.get("date_display"):
            summary_parts.append(
                f"Keletkezés: {artwork['date_display']}"
            )

        if artwork.get("medium"):
            summary_parts.append(
                f"Technika: {artwork['medium']}"
            )

        if description:
            summary_parts.append(description)

        item = {
            "section_code": "art_of_the_day",
            "title": title,
            "summary": " ".join(summary_parts) or None,
            "image_url": image_url,
            "source_name": "Art Institute of Chicago",
            "source_url": source_url,
            "source_language": "en",
            "status": "candidate",
            "metadata": {
                "origin": "Art Institute of Chicago API",
                "artwork_id": artwork_id,
                "artist": artist,
                "date_display": artwork.get("date_display"),
                "medium": artwork.get("medium"),
                "image_url": image_url,
                "is_public_domain": True,
                "metadata_license": "CC0",
                "description_license": "CC BY 4.0",
                "search_term": search_term,
            },
        }

        result = save_content(client, item)

        if result == "inserted":
            inserted += 1
            print("ÚJ:", title[:85])
        else:
            skipped += 1

    print("API által visszaadott művek:", len(artworks))
    print("Új tartalom:", inserted)
    print("Már létezett / kihagyva:", skipped)

    return {
        "inserted": inserted,
        "skipped": skipped,
    }


# ============================================================
# FŐPROGRAM
# ============================================================

def main():
    print("=" * 65)
    print("WORLD SHARDS – TARTALOMGYŰJTŐ MOTOR")
    print("Verzió:", VERSION)
    print("=" * 65)

    client = get_supabase_client()

    print("Supabase-kapcsolat: SIKERES")

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
