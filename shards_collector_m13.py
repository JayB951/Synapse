
"""
WORLD SHARDS - M1.3 Content Collector
Version: 0.1.0

Sections:
- the_thinker
- battlefield
- fundamentals
- world_explorer

Source:
- English Wikipedia / MediaWiki Action API

The collector stores source material as candidate records.
It does not generate or translate editorial content.
"""

import os
import re
import html
import logging
from datetime import date
from urllib.parse import quote

import requests
from supabase import create_client


VERSION = "0.1.0"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
REQUEST_TIMEOUT = 30
ITEMS_PER_SECTION = 5

HEADERS = {
    "User-Agent": "WorldShardsCollector/0.1.0 (content research project; contact via GitHub repository)"
}

SECTION_CONFIG = {
    "the_thinker": {
        "name": "The Thinker",
        "queries": [
            "philosophy ethics thought experiment paradox",
            "philosophy of mind consciousness free will",
            "moral philosophy ethical dilemma",
            "logic epistemology theory of knowledge",
            "political philosophy justice freedom",
            "philosophical paradoxes and thought experiments",
            "existentialism meaning of life philosophy",
            "philosophy of science scientific method",
        ],
    },
    "battlefield": {
        "name": "Battlefield",
        "queries": [
            "decisive battles in military history",
            "ancient battles military history",
            "medieval battles siege warfare",
            "World War II battles military history",
            "Napoleonic Wars battles",
            "naval battles in history",
            "military campaigns historical warfare",
            "famous military sieges in history",
        ],
    },
    "fundamentals": {
        "name": "Fundamentals",
        "queries": [
            "fundamental concepts in physics",
            "fundamental concepts in biology",
            "mathematical concepts and principles",
            "fundamental concepts in chemistry",
            "principles of astronomy and cosmology",
            "scientific theories and natural laws",
            "fundamental concepts in psychology",
            "basic concepts in economics",
        ],
    },
    "world_explorer": {
        "name": "World Explorer",
        "queries": [
            "natural wonders of the world",
            "unusual geological formations",
            "famous waterfalls canyons and caves",
            "unique islands and remote places",
            "national parks natural landmarks",
            "volcanic landscapes and geological wonders",
            "deserts mountains and natural formations",
            "unusual lakes rivers and landscapes",
        ],
    },
}


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def get_supabase_client():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")

    if not url or not key:
        raise RuntimeError(
            "Missing SUPABASE_URL or SUPABASE_SECRET_KEY environment variable."
        )

    return create_client(url, key)


def clean_text(value):
    if not value:
        return ""

    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def get_daily_query(section_code):
    queries = SECTION_CONFIG[section_code]["queries"]
    day_number = date.today().toordinal()
    return queries[day_number % len(queries)]


def fetch_wikipedia_pages(search_query):
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": search_query,
        "gsrnamespace": 0,
        "gsrlimit": 12,
        "prop": "extracts|info|coordinates",
        "exintro": 1,
        "explaintext": 1,
        "inprop": "url",
        "colimit": 1,
        "format": "json",
        "formatversion": 2,
    }

    response = requests.get(
        WIKIPEDIA_API,
        params=params,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(
            f"Wikipedia API error: {data['error'].get('info', 'Unknown error')}"
        )

    pages = data.get("query", {}).get("pages", [])

    return pages


def is_valid_article(page):
    title = page.get("title", "").strip()
    extract = clean_text(page.get("extract", ""))

    if not title or not extract:
        return False

    if "(disambiguation)" in title.lower():
        return False

    if len(extract) < 250:
        return False

    if extract.lower().startswith("this article is about"):
        return False

    return True


def get_coordinates(page):
    coordinates = page.get("coordinates", [])

    if not coordinates:
        return None

    first = coordinates[0]

    return {
        "latitude": first.get("lat"),
        "longitude": first.get("lon"),
    }


def content_exists(supabase, source_url):
    result = (
        supabase.table("shard_content_items")
        .select("id")
        .eq("source_url", source_url)
        .limit(1)
        .execute()
    )

    return bool(result.data)


def build_record(section_code, page, search_query):
    title = clean_text(page.get("title", ""))
    extract = clean_text(page.get("extract", ""))
    source_url = page.get("fullurl")

    if not source_url:
        source_url = (
            "https://en.wikipedia.org/wiki/"
            + quote(title.replace(" ", "_"))
        )

    summary = extract[:900]

    if len(extract) > 900:
        summary = summary.rsplit(" ", 1)[0] + "..."

    metadata = {
        "collector": "WORLD_SHARDS_M1.3",
        "collector_version": VERSION,
        "source_provider": "Wikipedia",
        "source_language": "en",
        "source_license": "CC BY-SA 4.0",
        "source_license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution_required": True,
        "search_query": search_query,
        "wikipedia_page_id": page.get("pageid"),
        "wikipedia_title": title,
        "coordinates": get_coordinates(page),
    }

    return {
        "section_code": section_code,
        "title": title,
        "summary": summary,
        "body": extract,
        "source_name": "Wikipedia",
        "source_url": source_url,
        "source_language": "en",
        "status": "candidate",
        "metadata": metadata,
    }


def collect_section(supabase, section_code):
    config = SECTION_CONFIG[section_code]
    search_query = get_daily_query(section_code)

    logging.info(
        "%s: searching Wikipedia for '%s'",
        config["name"],
        search_query,
    )

    pages = fetch_wikipedia_pages(search_query)

    collected = 0
    skipped = 0

    for page in pages:
        if collected >= ITEMS_PER_SECTION:
            break

        if not is_valid_article(page):
            skipped += 1
            continue

        record = build_record(section_code, page, search_query)

        if content_exists(supabase, record["source_url"]):
            skipped += 1
            continue

        supabase.table("shard_content_items").insert(record).execute()

        collected += 1

        logging.info(
            "%s: saved '%s'",
            config["name"],
            record["title"],
        )

    logging.info(
        "%s finished: %s saved, %s skipped",
        config["name"],
        collected,
        skipped,
    )

    return {
        "section": section_code,
        "saved": collected,
        "skipped": skipped,
    }


def main():
    setup_logging()

    logging.info("WORLD SHARDS M1.3 collector starting.")
    logging.info("Version: %s", VERSION)

    supabase = get_supabase_client()

    results = []
    errors = []

    for section_code in SECTION_CONFIG:
        try:
            result = collect_section(supabase, section_code)
            results.append(result)

        except Exception as error:
            logging.exception(
                "%s collector failed: %s",
                section_code,
                error,
            )
            errors.append(section_code)

    total_saved = sum(item["saved"] for item in results)

    logging.info("------------------------------------")
    logging.info("M1.3 COLLECTION SUMMARY")
    logging.info("Total saved: %s", total_saved)

    for result in results:
        logging.info(
            "%s: %s saved, %s skipped",
            result["section"],
            result["saved"],
            result["skipped"],
        )

    if errors:
        logging.error("Failed sections: %s", ", ".join(errors))
        raise SystemExit(1)

    logging.info("WORLD SHARDS M1.3 completed successfully.")


if __name__ == "__main__":
    main()
