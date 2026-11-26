"""AGORA M1.2: validate candidate RSS/Atom feeds without storing or publishing items."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from agora_rss_collector import (
    REGISTRY_PATH,
    TIMEOUT_SECONDS,
    USER_AGENT,
    extract_entries,
    load_registry,
)


def validate_source(source, session):
    result = {
        "code": source["code"],
        "name": source["name"],
        "scope": source["scope"],
        "feed_url": source["feed_url"],
        "status": "failed",
        "http_status": None,
        "item_count": 0,
        "usable_url_count": 0,
        "dated_item_count": 0,
        "error": None,
    }
    try:
        response = session.get(
            source["feed_url"],
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            },
            timeout=TIMEOUT_SECONDS,
        )
        result["http_status"] = response.status_code
        response.raise_for_status()
        items = extract_entries(response.text)
        result["item_count"] = len(items)
        result["usable_url_count"] = sum(bool(item.get("url")) for item in items)
        result["dated_item_count"] = sum(bool(item.get("published_at")) for item in items)
        if not items:
            result["error"] = "A feed elérhető, de nem tartalmaz feldolgozható, címmel és cikk-URL-lel rendelkező elemet."
        elif result["dated_item_count"] == 0:
            result["error"] = "A feed feldolgozható, de egyik elemhez sem találtunk használható publikálási dátumot."
        else:
            result["status"] = "passed"
    except (requests.RequestException, ValueError, KeyError) as exc:
        result["error"] = str(exc)[:500]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
    return result


def main():
    sources = load_registry(REGISTRY_PATH)
    results = []
    with requests.Session() as session:
        for source in sources:
            results.append(validate_source(source, session))

    output = {
        "validator": "AGORA_FEED_VALIDATION_M1.2",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(results),
        "passed_count": sum(r["status"] == "passed" for r in results),
        "failed_count": sum(r["status"] != "passed" for r in results),
        "results": results,
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if output["failed_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
