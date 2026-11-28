"""Detect an already-published daily issue before running collectors again."""
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from resilient_storage import create_resilient_client

LOGGER = logging.getLogger("world-shards-published-check")
TIMEZONE = ZoneInfo("Europe/Budapest")


def is_published_today(client, edition_date):
    response = (
        client.table("shard_editions")
        .select("id,status")
        .eq("edition_date", edition_date)
        .limit(1)
        .execute()
    )
    if not response.data:
        return False
    status = str(response.data[0].get("status") or "").strip().lower()
    LOGGER.info(
        "Mai kiadás azonosítva: %s; státusz=%s",
        response.data[0].get("id"),
        status or "ismeretlen",
    )
    return status == "published"


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    today = datetime.now(TIMEZONE).date().isoformat()
    client = create_resilient_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SECRET_KEY"),
    )
    published = is_published_today(client, today)
    if published:
        LOGGER.info(
            "A mai kiadás már publikált; a gyűjtés és újragenerálás idempotensen kihagyva."
        )
    else:
        LOGGER.info("A mai kiadás még nem publikált; a napi pipeline folytatódik.")

    output_path = os.getenv("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"already_published={str(published).lower()}\n")


if __name__ == "__main__":
    main()
