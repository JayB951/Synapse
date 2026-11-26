"""AGORA M3: explainable matching of current events to historical figures.

This module uses curated keyword/topic metadata only. It does not generate
historical claims, infer political affinity, or call an external AI service.
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_CATALOG = ROOT / "agora_historical_figures.json"
MATCHER_VERSION = "AGORA_HISTORICAL_MATCHER_M3.1"


def normalize(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)).strip()


def event_text(event):
    return normalize(" ".join([
        str(event.get("representative_title") or event.get("title") or ""),
        " ".join(str(a.get("title") or "") for a in event.get("articles", [])),
        " ".join(str(a.get("summary") or "") for a in event.get("articles", [])),
    ]))


def validate_catalog(catalog):
    figures = catalog.get("figures")
    if not isinstance(figures, list) or not figures:
        raise ValueError("Catalog must contain a non-empty figures list")
    seen = set()
    for figure in figures:
        required = ("id", "name", "topics", "keywords", "core_ideas", "works", "limits")
        if any(not figure.get(key) for key in required):
            raise ValueError(f"Incomplete historical figure profile: {figure.get('id', 'unknown')}")
        if figure["id"] in seen:
            raise ValueError(f"Duplicate historical figure id: {figure['id']}")
        seen.add(figure["id"])
        for work in figure["works"]:
            if not work.get("title") or not str(work.get("url", "")).startswith("https://"):
                raise ValueError(f"Invalid source reference in profile: {figure['id']}")
    return True


def match_figure(event, figure):
    text = event_text(event)
    matches = sorted({
        keyword for keyword in figure.get("keywords", [])
        if len(normalize(keyword)) >= 3 and normalize(keyword) in text
    }, key=lambda value: (-len(normalize(value)), normalize(value)))
    if not matches:
        return None
    topics = sorted(set(figure.get("topics", [])))
    # Score is transparent: exact phrase hits, capped to prevent keyword stuffing.
    score = min(100, 25 * min(len(matches), 4))
    return {
        "figure_id": figure["id"],
        "name": figure["name"],
        "score": score,
        "matched_keywords": matches[:8],
        "relevant_topics": topics,
        "core_ideas": figure["core_ideas"],
        "works": figure["works"],
        "limits": figure["limits"],
        "source_verification_required": True,
        "historical_relevance_human_review_required": True,
    }


def select_historical_figures(event, catalog, limit=3, excluded_ids=None):
    validate_catalog(catalog)
    excluded_ids = set(excluded_ids or [])
    matches = []
    for figure in catalog["figures"]:
        if figure["id"] in excluded_ids:
            continue
        result = match_figure(event, figure)
        if result:
            matches.append(result)
    matches.sort(key=lambda item: (-item["score"], item["figure_id"]))
    selected = matches[:max(0, limit)]
    return {
        "matcher": MATCHER_VERSION,
        "event_id": event.get("event_id"),
        "candidate_count": len(matches),
        "selected_count": len(selected),
        "figures": selected,
        "selection_policy": {
            "method": "exact_keyword_phrase_overlap",
            "political_affinity_used": False,
            "forced_fill": False,
            "human_review_required": True,
        },
        "status": "matched" if selected else "no_relevant_figure_found",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="AGORA pipeline JSON")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--output")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    selections = {}
    for scope, item in payload.get("daily_selection", {}).items():
        if item.get("event_id"):
            event = next((g for g in payload.get("groups", []) if g.get("event_id") == item["event_id"]), item)
            selections[scope] = select_historical_figures(event, catalog, args.limit)
        else:
            selections[scope] = {"status": "no_event_selected", "figures": []}
    output = {"matcher": MATCHER_VERSION, "generated_at": payload.get("generated_at"), "selections": selections}
    rendered = json.dumps(output, ensure_ascii=False, indent=2) + "\\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
