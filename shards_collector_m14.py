
"""
WORLD SHARDS - M1.4 Content Collector
Version: 0.3.0

Sections:
- unsolved
- closing

Sources:
- English Wikipedia / MediaWiki Action API
- xkcd JSON API
- JokeAPI

JokeAPI content filtering: DISABLED
All records are stored as candidates.
"""

import os
import re
import html
import logging
from datetime import date
from urllib.parse import quote

import requests
from supabase import create_client


VERSION = "0.3.0"

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
XKCD_API = "https://xkcd.com/info.0.json"
JOKE_API = "https://v2.jokeapi.dev/joke/Any"

REQUEST_TIMEOUT = 30

UNSOLVED_LIMIT = 5
XKCD_LIMIT = 1
JOKE_LIMIT = 5

HEADERS = {
    "User-Agent": (
        "WorldShardsCollector/0.3.0 "
        "(content research project; contact via GitHub repository)"
    )
}

UNSOLVED_QUERIES = [
    "unsolved problems in mathematics",
    "unsolved problems in physics",
    "historical mysteries unsolved",
    "unexplained phenomena",
    "unsolved archaeological mysteries",
    "open problems in science",
    "historical enigmas and mysteries",
    "unexplained events in history",
]

UNSOLVED_TITLE_TERMS = (
    "mystery", "mysterious", "unsolved", "unexplained",
    "open problem", "unresolved",
)

UNSOLVED_EVIDENCE_PATTERNS = (
    r"\bremains? unexplained\b",
    r"\bhas not been (?:solved|explained|identified)\b",
    r"\bremain(?:s)? unsolved\b",
    r"\bthe (?:cause|origin) (?:is|remain|remains) unknown\b",
    r"\bno (?:consensus|definitive explanation|conclusive evidence)\b",
    r"\bopen problem in (?:mathematics|physics|science)\b",
    r"\bwhose (?:cause|origin|identity) is unknown\b",
    r"\bthe question of .{3,100} remains open\b",
)


# --------------------------------------------------
# GENERAL
# --------------------------------------------------

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
            "Missing SUPABASE_URL or SUPABASE_SECRET_KEY."
        )

    return create_client(url, key)


def clean_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def content_exists_by_url(supabase, source_url):
    result = (
        supabase.table("shard_content_items")
        .select("id")
        .eq("source_url", source_url)
        .limit(1)
        .execute()
    )

    return bool(result.data)


def content_exists_by_title(supabase, section_code, title):
    result = (
        supabase.table("shard_content_items")
        .select("id")
        .eq("section_code", section_code)
        .eq("title", title)
        .limit(1)
        .execute()
    )

    return bool(result.data)


def save_record(supabase, record):
    supabase.table("shard_content_items").insert(
        record
    ).execute()


# --------------------------------------------------
# UNSOLVED - WIKIPEDIA
# --------------------------------------------------

def get_daily_unsolved_query():
    index = date.today().toordinal() % len(UNSOLVED_QUERIES)
    return UNSOLVED_QUERIES[index]


def fetch_wikipedia_pages(search_query):
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": search_query,
        "gsrnamespace": 0,
        "gsrlimit": 20,
        "prop": "extracts|info",
        "exintro": 1,
        "explaintext": 1,
        "inprop": "url",
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
            "Wikipedia API error: "
            + data["error"].get("info", "Unknown error")
        )

    return data.get("query", {}).get("pages", [])


def is_unsolved_candidate(page):
    title = clean_text(page.get("title", ""))
    extract = clean_text(page.get("extract", ""))
    if not title or len(extract) < 250:
        return False
    if "(disambiguation)" in title.lower():
        return False

    title_matches = any(term in title.casefold() for term in UNSOLVED_TITLE_TERMS)
    evidence_text = extract[:2200].casefold()
    explicit_evidence = any(
        re.search(pattern, evidence_text, re.IGNORECASE)
        for pattern in UNSOLVED_EVIDENCE_PATTERNS
    )
    # A casual mention of "unknown" is not evidence that the topic itself is unresolved.
    return title_matches or explicit_evidence


def build_unsolved_record(page, search_query):
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

    return {
        "section_code": "unsolved",
        "title": title,
        "summary": summary,
        "body": extract,
        "source_name": "Wikipedia",
        "source_url": source_url,
        "source_language": "en",
        "status": "candidate",
        "metadata": {
            "collector": "WORLD_SHARDS_M1.4",
            "collector_version": VERSION,
            "source_provider": "Wikipedia",
            "source_license": "CC BY-SA",
            "source_license_url": (
                "https://creativecommons.org/licenses/by-sa/4.0/"
            ),
            "attribution_required": True,
            "search_query": search_query,
            "wikipedia_page_id": page.get("pageid"),
            "candidate_review_required": True,
            "note": (
                "Search result candidate only. "
                "Unsolved status has not been independently verified."
            ),
        },
    }


def collect_unsolved(supabase):
    search_query = get_daily_unsolved_query()

    logging.info(
        "UNSOLVED: searching Wikipedia for '%s'",
        search_query,
    )

    pages = fetch_wikipedia_pages(search_query)

    saved = 0
    skipped = 0

    for page in pages:
        if saved >= UNSOLVED_LIMIT:
            break

        if not is_unsolved_candidate(page):
            skipped += 1
            continue

        record = build_unsolved_record(page, search_query)

        if content_exists_by_url(supabase, record["source_url"]):
            skipped += 1
            continue

        save_record(supabase, record)
        saved += 1

        logging.info(
            "UNSOLVED: saved '%s'",
            record["title"],
        )

    logging.info(
        "UNSOLVED finished: %s saved, %s skipped",
        saved,
        skipped,
    )

    return {
        "section": "unsolved",
        "saved": saved,
        "skipped": skipped,
    }


# --------------------------------------------------
# CLOSING - XKCD
# --------------------------------------------------

def fetch_xkcd_comic():
    response = requests.get(
        XKCD_API,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("num") or not data.get("img"):
        raise RuntimeError("Invalid xkcd API response.")

    return data


def build_xkcd_record(comic):
    comic_number = comic.get("num")
    title = clean_text(comic.get("title", ""))

    alt_text = clean_text(comic.get("alt", ""))
    transcript = clean_text(comic.get("transcript", ""))

    image_url = comic.get("img", "")
    source_url = f"https://xkcd.com/{comic_number}/"

    body_parts = [
        f"Comic title: {title}",
    ]

    if alt_text:
        body_parts.extend([
            "",
            "Alternative text:",
            alt_text,
        ])

    if transcript:
        body_parts.extend([
            "",
            "Transcript:",
            transcript,
        ])

    return {
        "section_code": "closing",
        "title": f"xkcd #{comic_number}: {title}",
        "summary": alt_text[:900] or title,
        "body": "\n".join(body_parts),
        "source_name": "xkcd",
        "source_url": source_url,
        "image_url": image_url,
        "source_language": "en",
        "status": "candidate",
        "metadata": {
            "collector": "WORLD_SHARDS_M1.4",
            "collector_version": VERSION,
            "source_provider": "xkcd",
            "source_license": "CC BY-NC 2.5",
            "source_license_url": (
                "https://creativecommons.org/licenses/by-nc/2.5/"
            ),
            "attribution_required": True,
            "comic_number": comic_number,
            "comic_title": title,
            "publication_year": comic.get("year"),
            "publication_month": comic.get("month"),
            "publication_day": comic.get("day"),
            "image_url": image_url,
            "alt_text": alt_text,
            "transcript": transcript,
        },
    }


def collect_xkcd(supabase):
    logging.info("CLOSING: fetching latest xkcd comic.")

    comic = fetch_xkcd_comic()
    record = build_xkcd_record(comic)

    existing = (
        supabase.table("shard_content_items")
        .select("id,image_url")
        .eq("source_url", record["source_url"])
        .limit(1)
        .execute()
    )

    if existing.data:
        existing_item = existing.data[0]
        if record.get("image_url") and existing_item.get("image_url") != record["image_url"]:
            (
                supabase.table("shard_content_items")
                .update({"image_url": record["image_url"]})
                .eq("id", existing_item["id"])
                .execute()
            )
            logging.info("xkcd #%s image URL updated.", comic.get("num"))
        else:
            logging.info(
                "xkcd #%s already exists. Skipping.",
                comic.get("num"),
            )

        return {
            "source": "xkcd",
            "saved": 0,
            "skipped": 1,
        }

    save_record(supabase, record)

    logging.info(
        "xkcd saved: #%s - %s",
        comic.get("num"),
        record["title"],
    )

    return {
        "source": "xkcd",
        "saved": 1,
        "skipped": 0,
    }


# --------------------------------------------------
# CLOSING - JOKEAPI (NO FILTERING)
# --------------------------------------------------

def fetch_jokes():
    params = {
        "amount": JOKE_LIMIT,
        "format": "json",
    }

    # Intentionally no blacklistFlags or safe-mode.
    # All JokeAPI categories and content flags are allowed.

    response = requests.get(
        JOKE_API,
        params=params,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("error"):
        raise RuntimeError(
            "JokeAPI error: "
            + str(data.get("message", "Unknown error"))
        )

    if "jokes" in data:
        return data["jokes"]

    if "joke" in data or "setup" in data:
        return [data]

    return []


def build_joke_record(joke):
    category = clean_text(joke.get("category", "Any"))
    joke_id = joke.get("id")
    joke_type = joke.get("type", "single")

    if joke_type == "twopart":
        setup = clean_text(joke.get("setup", ""))
        delivery = clean_text(joke.get("delivery", ""))

        if not setup or not delivery:
            return None

        title = setup
        summary = setup
        body = setup + "\n\n" + delivery

    else:
        joke_text = clean_text(joke.get("joke", ""))

        if not joke_text:
            return None

        title = joke_text
        summary = joke_text[:500]
        body = joke_text

    source_url = (
        f"https://v2.jokeapi.dev/joke/Any?idRange={joke_id}-{joke_id}"
    )

    flags = joke.get("flags", {})

    return {
        "section_code": "closing",
        "title": title,
        "summary": summary,
        "body": body,
        "source_name": "JokeAPI",
        "source_url": source_url,
        "source_language": "en",
        "status": "candidate",
        "metadata": {
            "collector": "WORLD_SHARDS_M1.4",
            "collector_version": VERSION,
            "source_provider": "JokeAPI",
            "source_license": "Provider terms apply",
            "attribution_required": False,
            "joke_id": joke_id,
            "category": category,
            "joke_type": joke_type,
            "flags": flags,
            "content_filtering": False,
        },
    }


def collect_jokes(supabase):
    logging.info(
        "CLOSING: fetching unfiltered jokes from JokeAPI."
    )

    jokes = fetch_jokes()

    saved = 0
    skipped = 0

    for joke in jokes:
        if saved >= JOKE_LIMIT:
            break

        record = build_joke_record(joke)

        if not record:
            skipped += 1
            continue

        if content_exists_by_title(
            supabase,
            "closing",
            record["title"],
        ):
            skipped += 1
            continue

        save_record(supabase, record)
        saved += 1

        logging.info(
            "JokeAPI saved: %s",
            record["title"][:100],
        )

    logging.info(
        "JokeAPI finished: %s saved, %s skipped",
        saved,
        skipped,
    )

    return {
        "source": "JokeAPI",
        "saved": saved,
        "skipped": skipped,
    }


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():
    setup_logging()

    logging.info("WORLD SHARDS M1.4 starting.")
    logging.info("Version: %s", VERSION)

    supabase = get_supabase_client()

    results = []
    errors = []

    collectors = [
        ("unsolved", collect_unsolved),
        ("xkcd", collect_xkcd),
        ("JokeAPI", collect_jokes),
    ]

    for collector_name, collector in collectors:
        try:
            result = collector(supabase)
            results.append(result)

        except Exception as error:
            logging.exception(
                "%s collector failed: %s",
                collector_name,
                error,
            )
            errors.append(collector_name)

    total_saved = sum(
        result["saved"] for result in results
    )

    logging.info("------------------------------------")
    logging.info("M1.4 COLLECTION SUMMARY")
    logging.info("Total saved: %s", total_saved)

    for result in results:
        logging.info(
            "%s: %s saved, %s skipped",
            result.get("section", result.get("source")),
            result["saved"],
            result["skipped"],
        )

    if errors:
        logging.error(
            "Failed collectors: %s",
            ", ".join(errors),
        )
        raise SystemExit(1)

    logging.info("WORLD SHARDS M1.4 completed successfully.")


if __name__ == "__main__":
    main()
