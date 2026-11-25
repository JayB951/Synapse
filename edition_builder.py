
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from supabase import create_client


VERSION = "0.1.0"
TIMEZONE = ZoneInfo("Europe/Budapest")

SECTION_LIMITS = {
    "research_frontier": 5,
    "art_of_the_day": 1,
    "the_thinker": 1,
    "battlefield": 1,
    "fundamentals": 1,
    "world_explorer": 1,
    "unsolved": 1,
    "music_of_the_day": 1,
}

CLOSING_LIMIT = 2

CONTENT_FIELDS = (
    "id,section_code,title,summary,body,source_name,source_url,"
    "source_published_at,collected_at,status,relevance_score,metadata"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("world-shards-edition-builder")


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url or not key:
        raise RuntimeError(
            "Hiányzó SUPABASE_URL vagy SUPABASE_SECRET_KEY."
        )

    return create_client(url, key)


def get_candidates(supabase, section_code, limit=100):
    response = (
        supabase.table("shard_content_items")
        .select(CONTENT_FIELDS)
        .eq("section_code", section_code)
        .eq("status", "candidate")
        .order("relevance_score", desc=True)
        .order("collected_at", desc=True)
        .limit(limit)
        .execute()
    )

    return response.data or []


def select_closing_items(supabase):
    candidates = get_candidates(
        supabase,
        "closing",
        limit=100,
    )

    xkcd_item = None
    joke_item = None

    for item in candidates:
        metadata = item.get("metadata") or {}

        if not isinstance(metadata, dict):
            continue

        if xkcd_item is None and metadata.get("comic_number") is not None:
            xkcd_item = item

        if joke_item is None and metadata.get("joke_id") is not None:
            joke_item = item

        if xkcd_item and joke_item:
            break

    selected = []

    if xkcd_item:
        selected.append(xkcd_item)
        logger.info("Closing: xkcd kiválasztva: %s", xkcd_item["title"])
    else:
        logger.warning("Closing: nincs elérhető xkcd jelölt.")

    if joke_item:
        selected.append(joke_item)
        logger.info("Closing: JokeAPI-vicc kiválasztva: %s", joke_item["title"])
    else:
        logger.warning("Closing: nincs elérhető JokeAPI-vicc jelölt.")

    return selected


def select_edition_items(supabase):
    selected_items = []

    for section_code, limit in SECTION_LIMITS.items():
        candidates = get_candidates(
            supabase,
            section_code,
            limit=limit,
        )

        chosen = candidates[:limit]
        selected_items.extend(chosen)

        logger.info(
            "%s: %s / %s tartalom kiválasztva.",
            section_code,
            len(chosen),
            limit,
        )

    closing_items = select_closing_items(supabase)
    selected_items.extend(closing_items)

    return selected_items


def get_existing_edition(supabase, edition_date):
    response = (
        supabase.table("shard_editions")
        .select("id,status")
        .eq("edition_date", edition_date)
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def create_edition(supabase, edition_date):
    date_object = datetime.strptime(edition_date, "%Y-%m-%d").date()
    formatted_date = date_object.strftime("%Y. %m. %d.")

    edition_data = {
        "edition_date": edition_date,
        "title": f"WORLD SHARDS – {formatted_date}",
        "introduction": (
            "A világ legérdekesebb tudományos, kulturális, "
            "történelmi és gondolati felfedezései egyetlen napi kiadványban."
        ),
        "status": "draft",
        "metadata": {
            "builder_version": VERSION,
            "selection_method": "automatic",
            "planned_item_count": 14,
        },
    }

    response = (
        supabase.table("shard_editions")
        .insert(edition_data)
        .execute()
    )

    if not response.data:
        raise RuntimeError("A napi kiadvány létrehozása nem sikerült.")

    edition = response.data[0]
    logger.info("Napi kiadvány létrehozva: %s", edition["id"])

    return edition


def create_edition_items(supabase, edition_id, selected_items):
    edition_items = []

    for position, item in enumerate(selected_items, start=1):
        edition_items.append({
            "edition_id": edition_id,
            "content_item_id": item["id"],
            "section_code": item["section_code"],
            "position": position,
            "editor_note": "Automatikusan kiválasztva.",
        })

    if not edition_items:
        raise RuntimeError("Nincs kiválasztott tartalom a kiadványhoz.")

    response = (
        supabase.table("shard_edition_items")
        .insert(edition_items)
        .execute()
    )

    logger.info(
        "%s tartalom hozzárendelve a napi kiadványhoz.",
        len(response.data or []),
    )


def mark_items_as_selected(supabase, selected_items):
    item_ids = [item["id"] for item in selected_items]

    if not item_ids:
        return

    (
        supabase.table("shard_content_items")
        .update({"status": "selected"})
        .in_("id", item_ids)
        .execute()
    )

    logger.info("%s tartalom státusza selected lett.", len(item_ids))


def main():
    logger.info("WORLD SHARDS Edition Builder v%s indul.", VERSION)

    supabase = get_supabase_client()

    edition_date = datetime.now(TIMEZONE).date().isoformat()

    existing = get_existing_edition(supabase, edition_date)

    if existing:
        logger.info(
            "A mai kiadvány már létezik (%s, státusz: %s). "
            "Nem készül második példány.",
            existing["id"],
            existing["status"],
        )
        return

    selected_items = select_edition_items(supabase)

    if not selected_items:
        raise RuntimeError(
            "Egyetlen tartalom sem választható ki. "
            "A napi kiadvány nem jött létre."
        )

    edition = create_edition(supabase, edition_date)

    create_edition_items(
        supabase,
        edition["id"],
        selected_items,
    )

    mark_items_as_selected(supabase, selected_items)

    logger.info("----------------------------------------")
    logger.info("NAPI KIADVÁNY SIKERESEN ELKÉSZÜLT")
    logger.info("Dátum: %s", edition_date)
    logger.info("Kiválasztott tartalmak: %s", len(selected_items))
    logger.info("Kiadvány azonosító: %s", edition["id"])
    logger.info("----------------------------------------")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("A napi kiadvány összeállítása sikertelen.")
        raise
