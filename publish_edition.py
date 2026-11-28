"""
WORLD SHARDS – Automatic publication gate
Only publishes today's Budapest-local draft when all 16 expected items are complete.
"""
import json
import logging
import os
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from resilient_storage import create_resilient_client
EXPECTED_COUNTS = {
    "research_frontier": 7,
    "art_of_the_day": 1,
    "the_thinker": 1,
    "battlefield": 1,
    "fundamentals": 1,
    "world_explorer": 1,
    "unsolved": 1,
    "music_of_the_day": 1,
    "closing": 2,
}
EXPECTED_TOTAL = sum(EXPECTED_COUNTS.values())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("world-shards-publisher")
TIMEZONE = ZoneInfo("Europe/Budapest")


def get_target_edition_date():
    """Return the Budapest-local date; never publish an older leftover draft."""
    return os.getenv("EDITION_DATE") or datetime.now(TIMEZONE).date().isoformat()


def get_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")
    return create_resilient_client(url, key)

def write_github_output(**values):
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def save_local_archive(edition, items, supabase):
    """Persist the complete validated edition before attempting the DB status change."""
    content_ids = list(dict.fromkeys(
        item["content_item_id"] for item in items if item.get("content_item_id")
    ))
    source_by_id = {}
    if content_ids:
        try:
            response = (
                supabase.table("shard_content_items")
                .select("id,source_name,source_url,image_url,metadata")
                .in_("id", content_ids)
                .execute()
            )
            source_by_id = {str(row["id"]): row for row in (response.data or [])}
        except Exception:
            # Article bodies remain complete in shard_edition_items. Missing source
            # decoration must not prevent preserving or emailing the edition.
            logger.exception(
                "A forrás-metaadatok lekérése nem sikerült; "
                "a tartalmi archívum ezek nélkül is elkészül."
            )

    archive = {
        "schema_version": 1,
        "archive_type": "world_shards_edition",
        "archived_at": datetime.now(TIMEZONE).isoformat(),
        "edition": edition,
        "items": items,
        "source_by_id": source_by_id,
    }
    archive_dir = Path(os.getenv("WORLD_SHARDS_ARCHIVE_DIR", "world-shards-archive"))
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"edition-{edition['edition_date']}.json"
    temporary_path = archive_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(archive, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(archive_path)
    logger.info("A teljes, ellenőrzött kiadás helyi archívumba mentve: %s", archive_path)
    return str(archive_path)


def main():
    supabase = get_client()

    target_date = get_target_edition_date()
    logger.info("Publikálási cél dátuma (Europe/Budapest): %s", target_date)

    edition_response = (
        supabase.table("shard_editions")
        .select("id,edition_date,title,status")
        .eq("edition_date", target_date)
        .eq("status", "draft")
        .order("edition_date", desc=True)
        .limit(1)
        .execute()
    )
    if not edition_response.data:
        raise RuntimeError("Nincs publikálásra váró draft kiadás.")

    edition = edition_response.data[0]
    edition_id = edition["id"]
    logger.info("Ellenőrzött kiadás: %s (%s)", edition["title"], edition["edition_date"])

    items_response = (
        supabase.table("shard_edition_items")
        .select(
            "id,section_code,position,processing_status,editor_note,"
            "display_title,display_summary,display_body"
        )
        .eq("edition_id", edition_id)
        .order("position")
        .execute()
    )
    items = items_response.data or []

    if len(items) != EXPECTED_TOTAL:
        raise RuntimeError(
            f"Biztonsági leállás: {len(items)}/{EXPECTED_TOTAL} elem található. "
            "A kiadás draft marad."
        )

    actual_counts = Counter(item.get("section_code") for item in items)
    if dict(actual_counts) != EXPECTED_COUNTS:
        raise RuntimeError(
            f"Rovateloszlás hibás. Elvárt: {EXPECTED_COUNTS}; tényleges: {dict(actual_counts)}. "
            "A kiadás draft marad."
        )

    editor_notes = Counter(item.get("editor_note") for item in items)
    for required_note in ("MAGYAR AGORA", "WORLD AGORA"):
        if editor_notes.get(required_note, 0) != 1:
            raise RuntimeError(
                f"Hiányzó vagy duplikált AGORA-rovat: {required_note}. A kiadás draft marad."
            )

    positions = sorted(item.get("position") for item in items)
    if positions != list(range(1, EXPECTED_TOTAL + 1)):
        raise RuntimeError("A pozíciók nem folytonosak 1–16 között. A kiadás draft marad.")

    incomplete = []
    for item in items:
        required = (
            item.get("processing_status") == "completed"
            and bool(item.get("display_title"))
            and bool(item.get("display_summary"))
            and bool(item.get("display_body"))
        )
        if not required:
            incomplete.append(
                f"pozíció={item.get('position')}, rovat={item.get('section_code')}, "
                f"státusz={item.get('processing_status')}"
            )

    if incomplete:
        raise RuntimeError(
            "Nem minden tartalom teljes: " + "; ".join(incomplete)
            + ". A kiadás draft marad."
        )

    # A teljes, ellenőrzött kiadás előbb helyi archívumba kerül.
    # Így a DB-státuszváltás hibája nem semmisíti meg a kész magazint.
    archive_path = save_local_archive(edition, items, supabase)
    write_github_output(archive_ready=True, archive_path=archive_path)

    try:
        update_response = (
            supabase.table("shard_editions")
            .update({"status": "published"})
            .eq("id", edition_id)
            .eq("status", "draft")
            .execute()
        )
        if not update_response.data:
            raise RuntimeError("A publikálási státuszváltás nem igazolható.")

        verify_response = (
            supabase.table("shard_editions")
            .select("id,status,edition_date,title")
            .eq("id", edition_id)
            .limit(1)
            .execute()
        )
        if not verify_response.data or verify_response.data[0].get("status") != "published":
            raise RuntimeError("A publikálás utáni visszaellenőrzés sikertelen.")
    except Exception as exc:
        logger.exception(
            "A Supabase publikációs státuszváltása nem sikerült; "
            "a teljes helyi archívum megmaradt, e-mailes tartalék útvonal használható: %s",
            exc,
        )
        write_github_output(archive_ready=True, archive_path=archive_path, published=False)
        return

    if getattr(supabase, "local_fallback_used", False):
        logger.warning(
            "A kiadás teljes egészében elkészült és helyben megőrződött, "
            "de a Supabase szinkron még függőben van; a frontend publikáció később áll helyre."
        )
        write_github_output(
            archive_ready=True,
            archive_path=archive_path,
            published=False,
            db_degraded=True,
        )
        return

    logger.info(
        "AUTOMATIKUS PUBLIKÁLÁS SIKERES: %s – %s (%s/%s elem).",
        edition["title"], edition["edition_date"], len(items), EXPECTED_TOTAL
    )
    write_github_output(archive_ready=True, archive_path=archive_path, published=True)

if __name__ == "__main__":
    main()
