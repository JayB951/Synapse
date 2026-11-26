
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
# Both AGORA sections are required for every new 16-item edition.
AGORA_SECTION_LIMITS = {
    "agora_hungary": 1,
    "agora_world": 1,
}
BASE_EXPECTED_ITEMS = sum(SECTION_LIMITS.values()) + CLOSING_LIMIT
EXPECTED_ITEMS = BASE_EXPECTED_ITEMS + sum(AGORA_SECTION_LIMITS.values())

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


def get_candidates(supabase, section_code, limit=100, edition_date=None):
    query = (
        supabase.table("shard_content_items")
        .select(CONTENT_FIELDS)
        .eq("section_code", section_code)
        .eq("status", "candidate")
    )

    if edition_date:
        query = query.contains("metadata", {"edition_date": edition_date})

    response = (
        query
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


def select_edition_items(supabase, edition_date):
    selected_items = []

    for section_code, limit in SECTION_LIMITS.items():
        candidates = get_candidates(
            supabase,
            section_code,
            limit=limit,
            edition_date=(
                edition_date
                if section_code == "music_of_the_day"
                else None
            ),
        )

        chosen = candidates[:limit]
        selected_items.extend(chosen)

        logger.info(
            "%s: %s / %s tartalom kiválasztva.",
            section_code,
            len(chosen),
            limit,
        )

    for section_code, limit in AGORA_SECTION_LIMITS.items():
        candidates = get_candidates(
            supabase, section_code, limit=limit, edition_date=edition_date
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
        .select("id,status,metadata")
        .eq("edition_date", edition_date)
        .limit(1)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def add_music_to_existing_edition(supabase, edition, edition_date):
    """
    Egyszeri, idempotens visszatöltés: a meglévő draft kiadványhoz
    hozzáadja a mai Music of the Day rekordot a záróelemek elé.
    """
    edition_id = edition["id"]

    response = (
        supabase.table("shard_edition_items")
        .select("id,section_code,position,content_item_id")
        .eq("edition_id", edition_id)
        .order("position")
        .execute()
    )
    existing_items = response.data or []

    music_links = [
        item for item in existing_items
        if item.get("section_code") == "music_of_the_day"
    ]

    if music_links:
        logger.info("A mai kiadványban már szerepel a Music of the Day.")
        return

    if edition.get("status") != "draft":
        raise RuntimeError(
            "A mai kiadvány nem draft státuszú; automatikus módosítás leállítva."
        )

    allowed_existing_counts = {BASE_EXPECTED_ITEMS - 1, BASE_EXPECTED_ITEMS}
    if len(existing_items) not in allowed_existing_counts:
        raise RuntimeError(
            f"A meglévő kiadvány {len(existing_items)} elemet tartalmaz; "
            f"a biztonságos visszatöltéshez {sorted(allowed_existing_counts)} "
            "egyikének kell teljesülnie."
        )

    closing_items = [
        item for item in existing_items
        if item.get("section_code") == "closing"
    ]
    if len(closing_items) != CLOSING_LIMIT:
        raise RuntimeError(
            "A két záróelem nem azonosítható egyértelműen; "
            "a kiadványt nem módosítottam."
        )

    music_candidates = get_candidates(
        supabase,
        "music_of_the_day",
        limit=10,
        edition_date=edition_date,
    )
    if not music_candidates:
        raise RuntimeError(
            "Nem található mai Music of the Day jelölt; a kiadvány változatlan maradt."
        )

    music_item = music_candidates[0]
    insert_position = min(item["position"] for item in closing_items)

    # A pozíciókat hátulról előre toljuk, így nem ütköznek a még
    # el nem mozdított rekordokkal akkor sem, ha egyedi pozíciókorlát van.
    shifted = []
    try:
        for item in sorted(
            [row for row in existing_items if row["position"] >= insert_position],
            key=lambda row: row["position"],
            reverse=True,
        ):
            new_position = item["position"] + 1
            (
                supabase.table("shard_edition_items")
                .update({"position": new_position})
                .eq("id", item["id"])
                .execute()
            )
            shifted.append((item["id"], item["position"]))

        (
            supabase.table("shard_edition_items")
            .insert({
                "edition_id": edition_id,
                "content_item_id": music_item["id"],
                "section_code": "music_of_the_day",
                "position": insert_position,
                "editor_note": "A napi kiadvány utólagos, automatikus kiegészítése.",
                "processing_status": "pending",
            })
            .execute()
        )
    except Exception:
        # Hiba esetén visszaállítjuk az eltolásokat, ha az új rekord
        # még nem került be.
        check = (
            supabase.table("shard_edition_items")
            .select("id")
            .eq("edition_id", edition_id)
            .eq("content_item_id", music_item["id"])
            .limit(1)
            .execute()
        )
        if not check.data:
            for item_id, old_position in sorted(
                shifted, key=lambda pair: pair[1]
            ):
                (
                    supabase.table("shard_edition_items")
                    .update({"position": old_position})
                    .eq("id", item_id)
                    .execute()
                )
        raise

    (
        supabase.table("shard_content_items")
        .update({"status": "selected"})
        .eq("id", music_item["id"])
        .execute()
    )

    metadata = edition.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.update({
        "planned_item_count": len(existing_items) + 1,
        "music_backfill": True,
    })
    (
        supabase.table("shard_editions")
        .update({"metadata": metadata})
        .eq("id", edition_id)
        .execute()
    )

    logger.info(
        "Music of the Day hozzáadva a mai kiadványhoz: %s (pozíció: %s).",
        music_item.get("title"),
        insert_position,
    )


def add_agora_to_existing_edition(supabase, edition, edition_date):
    """Idempotently append the two AGORA sections to today's existing edition."""
    edition_id = edition["id"]
    existing_response = (
        supabase.table("shard_edition_items")
        .select("id,section_code,position,content_item_id")
        .eq("edition_id", edition_id)
        .order("position")
        .execute()
    )
    existing_items = existing_response.data or []
    present = {item.get("section_code") for item in existing_items}
    missing = []
    for section_code in AGORA_SECTION_LIMITS:
        if section_code in present:
            continue
        candidates = get_candidates(
            supabase, section_code, limit=1, edition_date=edition_date
        )
        if not candidates:
            raise RuntimeError(
                f"Hiányzik a(z) {section_code} napi AGORA-tartalma; "
                "a meglévő kiadvány változatlan maradt."
            )
        missing.append((section_code, candidates[0]))

    if not missing:
        logger.info("Mindkét AGORA-rovat már szerepel a meglévő kiadványban.")
        return

    if edition.get("status") not in {"draft", "published"}:
        raise RuntimeError("AGORA csak draft vagy published kiadványhoz illeszthető.")

    closing_positions = [
        item["position"] for item in existing_items
        if item.get("section_code") == "closing"
    ]
    insert_position = min(closing_positions) if closing_positions else (
        max((item["position"] for item in existing_items), default=0) + 1
    )
    shifted = []
    try:
        for item in sorted(
            [row for row in existing_items if row["position"] >= insert_position],
            key=lambda row: row["position"],
            reverse=True,
        ):
            new_position = item["position"] + len(missing)
            supabase.table("shard_edition_items").update(
                {"position": new_position}
            ).eq("id", item["id"]).execute()
            shifted.append((item["id"], item["position"]))

        links = []
        for offset, (section_code, content) in enumerate(missing):
            links.append({
                "edition_id": edition_id,
                "content_item_id": content["id"],
                "section_code": section_code,
                "position": insert_position + offset,
                "editor_note": "Automatikusan hozzáadott AGORA-rovat.",
                "processing_status": "pending",
            })
        response = supabase.table("shard_edition_items").insert(links).execute()
        if len(response.data or []) != len(links):
            raise RuntimeError("Nem minden AGORA-rovat került a kiadványhoz.")
    except Exception:
        inserted_ids = [
            row.get("id") for row in (response.data or [])
        ] if "response" in locals() else []
        if inserted_ids:
            supabase.table("shard_edition_items").delete().in_("id", inserted_ids).execute()
        for item_id, old_position in sorted(shifted, key=lambda pair: pair[1]):
            supabase.table("shard_edition_items").update(
                {"position": old_position}
            ).eq("id", item_id).execute()
        raise

    content_ids = [content["id"] for _, content in missing]
    supabase.table("shard_content_items").update(
        {"status": "selected"}
    ).in_("id", content_ids).execute()

    metadata = edition.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    metadata.update({
        "planned_item_count": len(existing_items) + len(missing),
        "agora_backfilled": True,
    })
    supabase.table("shard_editions").update(
        {"metadata": metadata}
    ).eq("id", edition_id).execute()
    logger.info(
        "AGORA hozzáadva a meglévő kiadványhoz: %s rovat.",
        len(missing),
    )


def create_edition(supabase, edition_date, planned_item_count=EXPECTED_ITEMS):
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
            "planned_item_count": planned_item_count,
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

    edition_date = os.getenv("EDITION_DATE") or datetime.now(TIMEZONE).date().isoformat()

    # A workflow a GITHUB_OUTPUT-on keresztül jelzi, ha a mai
    # kiadás már publikált; ilyenkor a feldolgozás és az e-mail is kimarad.
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output:
            output.write("already_published=false\n")

    existing = get_existing_edition(supabase, edition_date)

    if existing:
        status = existing.get("status")
        logger.info(
            "A mai kiadvány már létezik (%s, státusz: %s).",
            existing["id"],
            status,
        )

        if status == "published":
            add_agora_to_existing_edition(supabase, existing, edition_date)
            logger.info(
                "A mai kiadás már publikált; az esetleges hiányzó AGORA-rovatok "
                "hozzáadása megtörtént, újrapublikálás nem történik."
            )
            if github_output:
                with open(github_output, "a", encoding="utf-8") as output:
                    output.write("already_published=true\n")
            return

        if status != "draft":
            raise RuntimeError(
                f"A mai kiadás ismeretlen vagy nem kezelhető státuszú: {status!r}. "
                "Automatikus módosítás nem történt."
            )

        add_music_to_existing_edition(
            supabase,
            existing,
            edition_date,
        )
        add_agora_to_existing_edition(supabase, existing, edition_date)
        return

    selected_items = select_edition_items(supabase, edition_date)

    if len(selected_items) < EXPECTED_ITEMS:
        raise RuntimeError(
            f"A napi kiadványhoz legalább {EXPECTED_ITEMS} elem szükséges, "
            f"de csak {len(selected_items)} választható ki. "
            "Ellenőrizd, hogy a napi Music of the Day gyűjtés lefutott-e, "
            "és minden rovatban van-e jelölt. A kiadvány nem jött létre."
        )

    edition = create_edition(
        supabase,
        edition_date,
        planned_item_count=len(selected_items),
    )

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
