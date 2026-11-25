
"""
SYNAPSE – Adatbázis-író
Verzió: M2.7.5 / 0.1.0

Feladat:
- Supabase-kapcsolat
- Adatforrások azonosítása
- Publikációk beszúrása és frissítése
- Forráskapcsolatok mentése
- Szerzők és szerzőkapcsolatok mentése
- Gyűjtési futások naplózása
"""

import os
from datetime import datetime, timezone

from supabase import create_client

import database_mapper as mapper


# ============================================================
# SEGÉDFÜGGVÉNYEK
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url or not key:
        raise RuntimeError(
            "Hiányzó SUPABASE_URL vagy SUPABASE_SECRET_KEY."
        )

    return create_client(url, key)


def get_active_sources(client):
    response = (
        client.table("sources")
        .select("id,code,is_active")
        .eq("is_active", True)
        .execute()
    )

    result = {}

    for source in response.data or []:
        result[source["code"]] = {
            "id": source["id"],
            "is_active": True,
        }

    return result


def start_collection_run(client, records_found):
    response = (
        client.table("collection_runs")
        .insert({
            "started_at": now_iso(),
            "status": "running",
            "records_found": records_found,
            "records_inserted": 0,
            "records_updated": 0,
            "records_skipped": 0,
            "run_metadata": {
                "application": "SYNAPSE",
                "version": "M2.7.5",
            },
        })
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Nem sikerült létrehozni a gyűjtési futást."
        )

    return response.data[0]["id"]


def finish_collection_run(
    client,
    run_id,
    status,
    inserted,
    updated,
    skipped,
    errors,
):
    client.table("collection_runs").update({
        "finished_at": now_iso(),
        "status": status,
        "records_inserted": inserted,
        "records_updated": updated,
        "records_skipped": skipped,
        "error_message": (
            "\n".join(errors[:20]) if errors else None
        ),
        "run_metadata": {
            "application": "SYNAPSE",
            "version": "M2.7.5",
            "error_count": len(errors),
        },
    }).eq("id", run_id).execute()


# ============================================================
# PUBLIKÁCIÓ AZONOSÍTÁSA
# ============================================================

def find_publication(client, publication, source_links):
    """
    Meglévő publikáció keresése.

    Elsődleges: DOI.
    DOI nélkül: valamelyik meglévő forráskapcsolat.
    """

    doi = publication.get("doi")

    if doi:
        response = (
            client.table("publications")
            .select("id")
            .eq("doi", doi)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]["id"]

    for link in source_links:
        response = (
            client.table("publication_sources")
            .select("publication_id")
            .eq("source_id", link["source_id"])
            .eq("external_id", link["external_id"])
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]["publication_id"]

    return None


def save_publication(client, publication, source_links):
    """Publikáció beszúrása vagy frissítése."""

    existing_id = find_publication(
        client,
        publication,
        source_links,
    )

    payload = {
        "title": publication["title"],
        "abstract": publication.get("abstract"),
        "doi": publication.get("doi"),
        "publication_date": publication.get("publication_date"),
        "publication_year": publication.get("publication_year"),
        "publication_type": publication.get("publication_type"),
        "language": publication.get("language"),
        "journal": publication.get("journal"),
        "publisher": publication.get("publisher"),
        "url": publication.get("url"),
        "metadata": publication.get("metadata") or {},
        "last_updated_at": now_iso(),
    }

    if existing_id:
        client.table("publications").update(
            payload
        ).eq("id", existing_id).execute()

        return existing_id, "updated"

    payload["first_seen_at"] = now_iso()

    response = (
        client.table("publications")
        .insert(payload)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "A publikáció beszúrása nem sikerült."
        )

    return response.data[0]["id"], "inserted"


# ============================================================
# FORRÁSKAPCSOLATOK
# ============================================================

def save_source_links(client, publication_id, links):
    """Forráskapcsolatok mentése."""

    for link in links:
        payload = {
            "publication_id": publication_id,
            "source_id": link["source_id"],
            "external_id": link["external_id"],
            "original_url": link.get("original_url"),
            "retrieved_at": now_iso(),
            "source_metadata": link.get("source_metadata") or {},
        }

        client.table("publication_sources").upsert(
            payload,
            on_conflict="source_id,external_id",
        ).execute()


# ============================================================
# SZERZŐK
# ============================================================

def save_author(client, author, author_cache):
    """
    Szerző mentése.

    ORCID esetén a meglévő szerzőt keresi.
    ORCID nélkül a mapper által létrehozott
    publikációhoz kötött author_key alapján
    csak az adott futásban használja újra.
    """

    author_key = author["author_key"]

    if author_key in author_cache:
        return author_cache[author_key]

    orcid = author.get("orcid")

    if orcid:
        response = (
            client.table("authors")
            .select("id")
            .eq("orcid", orcid)
            .limit(1)
            .execute()
        )

        if response.data:
            author_id = response.data[0]["id"]

            client.table("authors").update({
                "full_name": author["full_name"],
            }).eq("id", author_id).execute()

            author_cache[author_key] = author_id

            return author_id

    response = (
        client.table("authors")
        .insert({
            "full_name": author["full_name"],
            "orcid": orcid,
        })
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            f"Szerző mentése sikertelen: {author['full_name']}"
        )

    author_id = response.data[0]["id"]

    author_cache[author_key] = author_id

    return author_id


def save_publication_authors(
    client,
    publication_id,
    publication_key,
    authors,
    author_links,
    author_cache,
):
    """Szerzők és publikációs kapcsolataik mentése."""

    author_ids = {}

    for author in authors:
        author_id = save_author(
            client,
            author,
            author_cache,
        )

        author_ids[author["author_key"]] = author_id

    for link in author_links:
        if link["publication_key"] != publication_key:
            continue

        author_id = author_ids.get(link["author_key"])

        if not author_id:
            continue

        client.table("publication_authors").upsert(
            {
                "publication_id": publication_id,
                "author_id": author_id,
                "author_position": link["author_position"],
            },
            on_conflict="publication_id,author_id",
        ).execute()


# ============================================================
# TELJES MENTÉSI FOLYAMAT
# ============================================================

def save_records(client, records):
    """Publikációs rekordok leképezése és mentése."""

    source_map = get_active_sources(client)

    mapped = mapper.map_records(
        records,
        source_map,
    )

    run_id = start_collection_run(
        client,
        len(records),
    )

    inserted = 0
    updated = 0
    skipped = mapped["invalid_records"]

    errors = []

    for item in mapped["errors"]:
        errors.append(
            f"Rekord {item['record_number']}: "
            + "; ".join(item["errors"])
        )

    tables = mapped["tables"]

    authors_by_key = {
        author["author_key"]: author
        for author in tables["authors"]
    }

    links_by_publication = {}

    for link in tables["publication_sources"]:
        links_by_publication.setdefault(
            link["publication_key"], []
        ).append(link)

    author_links_by_publication = {}

    for link in tables["publication_authors"]:
        author_links_by_publication.setdefault(
            link["publication_key"], []
        ).append(link)

    author_cache = {}

    for publication in tables["publications"]:
        publication_key = publication["publication_key"]

        try:
            source_links = links_by_publication.get(
                publication_key, []
            )

            publication_id, action = save_publication(
                client,
                publication,
                source_links,
            )

            save_source_links(
                client,
                publication_id,
                source_links,
            )

            save_publication_authors(
                client,
                publication_id,
                publication_key,
                list(authors_by_key.values()),
                author_links_by_publication.get(
                    publication_key, []
                ),
                author_cache,
            )

            if action == "inserted":
                inserted += 1
            else:
                updated += 1

            print(
                f"{action.upper()}: "
                f"{publication['title'][:90]}"
            )

        except Exception as error:
            skipped += 1

            message = (
                f"{publication_key}: {error}"
            )

            errors.append(message)

            print("MENTÉSI HIBA:", message)

    if errors and (inserted or updated):
        status = "partial"
    elif errors:
        status = "failed"
    else:
        status = "completed"

    finish_collection_run(
        client,
        run_id,
        status,
        inserted,
        updated,
        skipped,
        errors,
    )

    return {
        "status": status,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }
