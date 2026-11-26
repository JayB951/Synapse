
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
import time
from datetime import date
from urllib.parse import quote

import requests
from supabase import create_client


VERSION = "0.1.0"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
REQUEST_TIMEOUT = 30
MIN_REQUEST_INTERVAL = 10.0
MAX_REQUEST_ATTEMPTS = 3
WIKIMEDIA_BLOCKED = False
ITEMS_PER_SECTION = 5
LAST_WIKIMEDIA_REQUEST = 0.0

HEADERS = {
    "User-Agent": "WORLD-SHARDS/0.1 (https://github.com/JayB951/Synapse; Wikimedia API use for a non-commercial research project)"
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
            '"Battle of the Bulge" OR "Normandy landings" OR "D-Day"',
            '"Operation Overlord" OR "Operation Market Garden" OR "Operation Bagration"',
            'intitle:"Battle of" World War II',
            'intitle:"Battle of" ancient OR medieval OR Napoleonic',
            'intitle:"Siege of" historical siege',
            'specific naval battles and amphibious landings',
            'major battles of the American Civil War and World War I',
            'named historical battles and military campaigns',
        ],
    },
    "fundamentals": {
        "name": "Fundamentals",
        "queries": [
            "Newton's laws of motion OR conservation of energy OR entropy",
            "DNA replication OR natural selection OR cell division",
            "prime number OR probability theory OR Pythagorean theorem",
            "chemical bond OR pH OR oxidation and reduction",
            "gravity OR electromagnetic spectrum OR plate tectonics",
            "evolution OR photosynthesis OR immune system",
            "memory psychology OR classical conditioning OR perception",
            "supply and demand OR inflation OR opportunity cost",
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


class WikimediaPolicyBlock(RuntimeError):
    """Wikimedia has rejected automated access; stop all Wikimedia calls this run."""


def wikimedia_get_json(url, params):
    """Respect Wikimedia throttling and stop immediately on an access block."""
    global LAST_WIKIMEDIA_REQUEST, WIKIMEDIA_BLOCKED

    if WIKIMEDIA_BLOCKED:
        raise WikimediaPolicyBlock(
            "Wikimedia access was blocked earlier in this run; no further requests will be made."
        )

    for attempt in range(MAX_REQUEST_ATTEMPTS):
        elapsed = time.monotonic() - LAST_WIKIMEDIA_REQUEST
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)

        response = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        LAST_WIKIMEDIA_REQUEST = time.monotonic()

        # Wikimedia's 429 response may indicate an automated-access block,
        # not a transient rate limit. Do not retry or attempt to work around it.
        if response.status_code in (403, 429):
            WIKIMEDIA_BLOCKED = True
            raise WikimediaPolicyBlock(
                f"Wikimedia denied this request with HTTP {response.status_code}; "
                "the API will remain disabled for the rest of this run."
            )

        if response.status_code in (500, 502, 503, 504):
            if attempt == MAX_REQUEST_ATTEMPTS - 1:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After")
            try:
                delay = max(10.0, float(retry_after)) if retry_after else 30.0 * (2 ** attempt)
            except (TypeError, ValueError):
                delay = 30.0 * (2 ** attempt)
            logging.warning(
                "Temporary Wikimedia API HTTP %s; retrying in %.0f seconds (%s/%s).",
                response.status_code, delay, attempt + 1, MAX_REQUEST_ATTEMPTS,
            )
            time.sleep(delay)
            continue

        response.raise_for_status()
        return response.json()

    raise RuntimeError("Wikimedia API request failed after all retry attempts.")


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
        "prop": "extracts|info|coordinates|pageimages",
        "piprop": "thumbnail",
        "pithumbsize": 1600,
        "exintro": 1,
        "explaintext": 1,
        "inprop": "url",
        "colimit": 1,
        "format": "json",
        "formatversion": 2,
    }

    data = wikimedia_get_json(WIKIPEDIA_API, params)

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


def is_valid_battle_article(page):
    """Accept specific battles, sieges, landings and named military operations."""
    title = clean_text(page.get("title", ""))
    extract = clean_text(page.get("extract", ""))
    if not title or not extract:
        return False
    if re.search(r"\b(book|film|novel|video game|board game|album|song|documentary)\b", title, re.I):
        return False
    named_event = re.search(
        r"\b(battle|siege|landings?|invasion|campaign|operation)\b|^D-Day$|^Normandy$",
        title, re.I,
    )
    military_context = re.search(
        r"\b(battle|siege|military campaign|military operation|amphibious landing|"
        r"invasion|offensive|fought|forces landed|allied landings|German counteroffensive)\b",
        extract[:1800], re.I,
    )
    return bool(named_event and military_context)


def is_valid_fundamentals_article(page):
    """Accept a specific teachable concept, not broad subject overviews."""
    title = clean_text(page.get("title", ""))
    extract = clean_text(page.get("extract", ""))
    if not title or len(extract) < 250:
        return False
    if title.casefold() in {
        "physics", "biology", "chemistry", "mathematics", "economics",
        "psychology", "astronomy", "science", "natural science",
    }:
        return False
    concept = re.search(
        r"\b(law|theory|principle|effect|equation|theorem|force|energy|entropy|prime|ph|oxidation|natural selection|cell division|pythagorean|"
        r"gravity|evolution|photosynthesis|replication|probability|number|bond|"
        r"inflation|supply|demand|memory|conditioning|tectonics|spectrum)\b",
        title, re.I,
    )
    definition = re.search(
        r"\b(is|are|refers to|describes|defined as|the process by which|"
        r"the principle that|states that|is the tendency|is a measure of)\b",
        extract[:1200], re.I,
    )
    return bool(concept and definition)


def get_coordinates(page):
    coordinates = page.get("coordinates", [])

    if not coordinates:
        return None

    first = coordinates[0]

    return {
        "latitude": first.get("lat"),
        "longitude": first.get("lon"),
    }


def backfill_world_explorer_images(supabase):
    """Fill image_url for existing World Explorer records using Wikipedia pageimages."""
    result = (
        supabase.table("shard_content_items")
        .select("id,title,image_url,gallery_images")
        .eq("section_code", "world_explorer")
        .limit(500)
        .execute()
    )
    rows = result.data or []
    if not rows:
        logging.info("World Explorer image backfill: no missing images.")
        return

    updated = 0
    for offset in range(0, len(rows), 50):
        batch = rows[offset:offset + 50]
        titles = [row["title"] for row in batch if row.get("title")]
        if not titles:
            continue

        params = {
            "action": "query",
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": 1600,
            "titles": "|".join(titles),
            "format": "json",
            "formatversion": 2,
        }
        data = wikimedia_get_json(WIKIPEDIA_API, params)
        if "error" in data:
            raise RuntimeError(
                f"Wikipedia image API error: {data['error'].get('info', 'Unknown error')}"
            )

        image_by_title = {
            page.get("title", "").casefold(): (page.get("thumbnail") or {}).get("source")
            for page in data.get("query", {}).get("pages", [])
        }

        for row in batch:
            image_url = image_by_title.get((row.get("title") or "").casefold())
            gallery_images = row.get("gallery_images") or []
            update_data = {}
            if not row.get("image_url") and image_url:
                update_data["image_url"] = image_url
            if len(gallery_images) < 3:
                try:
                    gallery_images = fetch_commons_gallery_images(row["title"])
                    if gallery_images:
                        update_data["gallery_images"] = gallery_images
                except WikimediaPolicyBlock:
                    raise
                except Exception as error:
                    logging.warning(
                        "World Explorer gallery lookup failed for '%s': %s",
                        row["title"], error,
                    )
            if update_data:
                supabase.table("shard_content_items").update(
                    update_data
                ).eq("id", row["id"]).execute()
                updated += 1
                logging.info("World Explorer images backfilled: %s", row["title"])

    logging.info(
        "World Explorer image backfill: %s/%s records updated.",
        updated,
        len(rows),
    )


def backfill_battlefield_images(supabase):
    """Populate lead images for existing Battlefield source records."""
    result = (
        supabase.table("shard_content_items")
        .select("id,title,image_url")
        .eq("section_code", "battlefield")
        .limit(500)
        .execute()
    )
    rows = result.data or []
    if not rows:
        logging.info("Battlefield image backfill: no records found.")
        return

    updated = 0
    for offset in range(0, len(rows), 50):
        batch = rows[offset:offset + 50]
        titles = [row["title"] for row in batch if row.get("title")]
        if not titles:
            continue

        params = {
            "action": "query",
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": 1600,
            "titles": "|".join(titles),
            "format": "json",
            "formatversion": 2,
        }
        data = wikimedia_get_json(WIKIPEDIA_API, params)
        if "error" in data:
            raise RuntimeError(
                f"Wikipedia image API error: {data['error'].get('info', 'Unknown error')}"
            )

        image_by_title = {
            page.get("title", "").casefold(): (page.get("thumbnail") or {}).get("source")
            for page in data.get("query", {}).get("pages", [])
        }

        for row in batch:
            image_url = image_by_title.get((row.get("title") or "").casefold())
            if image_url and not row.get("image_url"):
                supabase.table("shard_content_items").update(
                    {"image_url": image_url}
                ).eq("id", row["id"]).execute()
                updated += 1
                logging.info("Battlefield image backfilled: %s", row["title"])

    logging.info("Battlefield image backfill: %s/%s records updated.", updated, len(rows))


def fetch_commons_gallery_images(place_title):
    """Find up to three additional Wikimedia Commons photographs for a place."""
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f'"{place_title}"',
        "gsrnamespace": 6,
        "gsrlimit": 12,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 1400,
        "format": "json",
        "formatversion": 2,
    }
    data = wikimedia_get_json("https://commons.wikimedia.org/w/api.php", params)
    if "error" in data:
        raise RuntimeError(
            f"Wikimedia Commons API error: {data['error'].get('info', 'Unknown error')}"
        )

    gallery = []
    seen_urls = set()
    for page in data.get("query", {}).get("pages", []):
        image_info = (page.get("imageinfo") or [{}])[0]
        image_url = image_info.get("thumburl") or image_info.get("url")
        if not image_url or image_url in seen_urls:
            continue
        metadata = image_info.get("extmetadata") or {}
        license_name = (metadata.get("LicenseShortName") or {}).get("value", "")
        description_url = image_info.get("descriptionurl", "")
        caption = clean_text(
            page.get("title", "").replace("File:", "").replace("_", " ")
        ) or place_title
        gallery.append({
            "url": image_url,
            "caption": caption,
            "source_url": description_url,
            "license": clean_text(license_name),
        })
        seen_urls.add(image_url)
        if len(gallery) == 3:
            break
    return gallery


def get_existing_content(supabase, source_url):
    result = (
        supabase.table("shard_content_items")
        .select("id,image_url")
        .eq("source_url", source_url)
        .limit(1)
        .execute()
    )

    return result.data[0] if result.data else None


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
        "image_url": (page.get("thumbnail") or {}).get("source"),
        "image_source": "Wikipedia page thumbnail",
    }

    gallery_images = []
    if section_code == "world_explorer":
        try:
            gallery_images = fetch_commons_gallery_images(title)
        except WikimediaPolicyBlock:
            raise
        except Exception as exc:
            # The Commons gallery is optional: ordinary gallery errors must
            # never prevent saving the main Wikipedia article and lead image.
            logging.warning(
                "World Explorer gallery unavailable for '%s'; continuing "
                "without additional images: %s",
                title,
                exc,
            )

    return {
        "section_code": section_code,
        "title": title,
        "summary": summary,
        "body": extract,
        "image_url": (page.get("thumbnail") or {}).get("source") if section_code in ("world_explorer", "battlefield") else None,
        "gallery_images": gallery_images if section_code == "world_explorer" else [],
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

        if section_code == "battlefield" and not is_valid_battle_article(page):
            skipped += 1
            logging.info("Battlefield: '%s' skipped; not a specific military event.", page.get("title", ""))
            continue

        if section_code == "fundamentals" and not is_valid_fundamentals_article(page):
            skipped += 1
            logging.info("Fundamentals: '%s' skipped; not a concrete basic concept.", page.get("title", ""))
            continue

        record = build_record(section_code, page, search_query)

        # A World Explorer-helyszín csak tényleges képpel kerülhet be.
        if section_code in ("world_explorer", "battlefield") and not record.get("image_url"):
            skipped += 1
            logging.info(
                "%s: '%s' kihagyva, mert nincs elérhető kép.",
                config["name"], record["title"],
            )
            continue

        existing = get_existing_content(supabase, record["source_url"])

        if existing:
            # Korábban gyűjtött helyszínek képének utólagos pótlása.
            if (
                section_code in ("world_explorer", "battlefield")
                and not existing.get("image_url")
                and record.get("image_url")
            ):
                supabase.table("shard_content_items").update({
                    "image_url": record["image_url"]
                }).eq("id", existing["id"]).execute()
                logging.info(
                    "%s kép pótolva: '%s'",
                    config["name"], record["title"],
                )
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

    # Backfills are optional maintenance. A Wikimedia denial must not abort
    # independent workflow stages, and must suppress every later Wikimedia call.
    for backfill_name, backfill in (
        ("World Explorer", backfill_world_explorer_images),
        ("Battlefield", backfill_battlefield_images),
    ):
        if WIKIMEDIA_BLOCKED:
            logging.warning("%s image backfill skipped: Wikimedia access is blocked.", backfill_name)
            continue
        try:
            backfill(supabase)
        except WikimediaPolicyBlock as error:
            logging.warning("%s image backfill skipped: %s", backfill_name, error)
        except Exception as error:
            logging.exception("%s image backfill failed; continuing: %s", backfill_name, error)

    results = []
    errors = []

    for section_code in SECTION_CONFIG:
        if WIKIMEDIA_BLOCKED:
            logging.warning(
                "%s collection skipped: Wikimedia access was denied earlier in this run.",
                section_code,
            )
            continue
        try:
            result = collect_section(supabase, section_code)
            results.append(result)

        except WikimediaPolicyBlock as error:
            logging.warning(
                "%s collection stopped because Wikimedia denied automated access: %s",
                section_code,
                error,
            )
            # All M1.3 sections use Wikimedia. Do not repeat the denied call.
            continue

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

    if WIKIMEDIA_BLOCKED:
        logging.warning(
            "WORLD SHARDS M1.3 completed with Wikimedia sections skipped after an access denial. "
            "The workflow may continue, but this run did not collect M1.3 content."
        )
        return

    logging.info("WORLD SHARDS M1.3 completed successfully.")


if __name__ == "__main__":
    main()
