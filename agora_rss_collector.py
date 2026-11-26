"""
WORLD SHARDS / AGORA - RSS candidate collector
M1.1 - fetches and normalizes RSS/Atom items.
No database writes, no publishing, no AI calls.
"""

import hashlib
import html
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests


ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "agora_sources.json"
TIMEOUT_SECONDS = 20
USER_AGENT = "WORLD-SHARDS-AGORA/0.1 (+https://github.com/JayB951/Synapse)"
MAX_ITEMS_PER_FEED = 50


def local_name(tag):
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element, names):
    wanted = {name.lower() for name in names}
    for child in list(element):
        if local_name(child.tag) in wanted:
            if local_name(child.tag) == "link":
                href = child.attrib.get("href")
                if href:
                    return href.strip()
            value = "".join(child.itertext()).strip()
            if value:
                return value
    return ""


def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]*>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    # HTML tag removal can leave a gap before punctuation (e.g. </b>.).
    return re.sub(r"\s+([.,!?;:])", r"\1", value)


def parse_timestamp(value):
    if not value:
        return None

    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc).isoformat()


def normalize_url(value):
    value = html.unescape((value or "").strip())
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    # Keep query strings: some publishers require them for valid article URLs.
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path,
        parsed.params,
        parsed.query,
        "",
    ))


def extract_entries(xml_text):
    root = ET.fromstring(xml_text)
    root_name = local_name(root.tag)

    if root_name == "feed":
        entries = [node for node in list(root) if local_name(node.tag) == "entry"]
    else:
        entries = [
            node
            for parent in root.iter()
            if local_name(parent.tag) == "channel"
            for node in list(parent)
            if local_name(node.tag) == "item"
        ]

    records = []
    for entry in entries[:MAX_ITEMS_PER_FEED]:
        title = clean_text(child_text(entry, ("title",)))
        link = normalize_url(child_text(entry, ("link",)))
        summary = clean_text(child_text(
            entry, ("description", "summary", "content", "encoded")
        ))
        published = child_text(
            entry, ("pubdate", "published", "updated", "date")
        )
        guid = child_text(entry, ("guid", "id"))

        if not title or not link:
            continue

        records.append({
            "title": title,
            "url": link,
            "summary": summary[:2000] or None,
            "published_at": parse_timestamp(published),
            "guid": guid or None,
        })

    return records


def candidate_id(source_code, item):
    identity = item.get("url") or (
        item.get("title", "").casefold()
    )
    raw = (source_code + "|" + identity).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def fetch_feed(source, session=None):
    session = session or requests.Session()
    response = session.get(
        source["feed_url"],
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    items = extract_entries(response.text)
    fetched_at = datetime.now(timezone.utc).isoformat()

    output = []
    for item in items:
        output.append({
            "candidate_id": candidate_id(source["code"], item),
            "source_code": source["code"],
            "source_name": source["name"],
            "scope": source["scope"],
            "language": source["language"],
            "title": item["title"],
            "url": item["url"],
            "summary": item["summary"],
            "published_at": item["published_at"],
            "guid": item["guid"],
            "fetched_at": fetched_at,
            "status": "candidate",
        })
    return output


def load_registry(path=REGISTRY_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        source for source in data["sources"]
        if source.get("status") == "candidate"
    ]


def collect_all(sources=None, pause_seconds=0.5):
    sources = sources if sources is not None else load_registry()
    all_items = []
    errors = []

    with requests.Session() as session:
        for index, source in enumerate(sources):
            try:
                items = fetch_feed(source, session=session)
                all_items.extend(items)
                print(
                    f"OK {source['code']}: {len(items)} jelölt",
                    file=sys.stderr,
                )
            except (requests.RequestException, ET.ParseError, KeyError, ValueError) as error:
                errors.append({
                    "source_code": source.get("code", "unknown"),
                    "error": str(error)[:500],
                })
                print(
                    f"HIBA {source.get('code', 'unknown')}: {error}",
                    file=sys.stderr,
                )

            if index < len(sources) - 1 and pause_seconds:
                time.sleep(pause_seconds)

    # Stable deduplication by normalized publisher article URL.
    unique = {}
    for item in all_items:
        unique.setdefault(item["url"], item)

    return {
        "collector": "AGORA_RSS_M1.1",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(unique),
        "source_count": len(sources),
        "failed_sources": errors,
        "candidates": list(unique.values()),
    }


def main():
    result = collect_all()
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if result["failed_sources"] and not result["candidates"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
