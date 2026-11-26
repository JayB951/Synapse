"""AGORA M3-M4: daily historical figure selection and commentary brief assembly."""
import argparse
import json
import sys
from pathlib import Path

from agora_commentary_briefs import build_commentary_package
from agora_historical_matching import (
    DEFAULT_CATALOG,
    MATCHER_VERSION,
    select_historical_figures,
    validate_catalog,
)

ENGINE_VERSION = "AGORA_DAILY_EDITORIAL_M4.1"


def build_editorial_output(pipeline, catalog, figure_limit=3):
    validate_catalog(catalog)
    groups = {item.get("event_id"): item for item in pipeline.get("groups", [])}
    result = {}
    for scope in ("hungary", "international"):
        selection = pipeline.get("daily_selection", {}).get(scope, {})
        event_id = selection.get("event_id")
        if not event_id:
            result[scope] = {
                "status": "no_event_selected",
                "historical_selection": None,
                "commentary_package": None,
            }
            continue

        event = groups.get(event_id, selection)
        historical = select_historical_figures(event, catalog, limit=figure_limit)
        package = build_commentary_package(event, historical)
        result[scope] = {
            "status": "editorial_research_required",
            "historical_selection": historical,
            "commentary_package": package,
        }

    return {
        "engine": ENGINE_VERSION,
        "matcher": MATCHER_VERSION,
        "generated_at": pipeline.get("generated_at"),
        "event_pipeline": pipeline.get("pipeline"),
        "figure_catalog_version": catalog.get("schema_version"),
        "daily_editorial": result,
        "quality_gates": {
            "exactly_two_news_items_required": True,
            "three_figures_per_item_target": 3,
            "no_forced_historical_matches": True,
            "three_commentary_dimensions_per_figure": 3,
            "hypothetical_reconstruction_disclosure_required": True,
            "direct_quotes_must_be_verified": True,
            "human_editorial_review_required": True,
            "publishing_performed": False,
        },
        "status": "editorial_research_required",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="JSON output from agora_pipeline.py")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--output")
    parser.add_argument("--figure-limit", type=int, default=3)
    args = parser.parse_args()
    if args.figure_limit < 1:
        parser.error("--figure-limit must be positive")

    pipeline = json.loads(Path(args.input).read_text(encoding="utf-8"))
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    result = build_editorial_output(pipeline, catalog, args.figure_limit)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
