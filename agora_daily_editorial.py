"""AGORA M3-M4: daily historical figure selection and commentary generation."""
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
from agora_gemini_engine import (
    DEFAULT_MODEL,
    GeminiClient,
    build_gemini_commentary_package,
    select_historical_figures as gemini_select_historical_figures,
)
from agora_news_selection import (
    select_hungarian_news_event,
    select_international_news_event,
)

ENGINE_VERSION = "AGORA_DAILY_EDITORIAL_M4.3"


def build_editorial_output(pipeline, catalog, figure_limit=3, gemini_client=None):
    validate_catalog(catalog)
    groups = {item.get("event_id"): item for item in pipeline.get("groups", [])}
    result = {}
    for scope in ("hungary", "international"):
        selection = pipeline.get("daily_selection", {}).get(scope, {})
        news_selection = None

        # Both AGORA sections receive an independent Gemini newsworthiness gate.
        if gemini_client is not None:
            shortlist = pipeline.get("shortlists", {}).get(scope, {}).get("events")
            if shortlist is not None:
                candidates = [
                    item for item in shortlist
                    if item.get("eligible_for_daily_proposal") is True
                ][:10]
            else:
                fallback_id = selection.get("event_id")
                candidates = [groups[fallback_id]] if fallback_id in groups else []
            selector = (
                select_hungarian_news_event
                if scope == "hungary"
                else select_international_news_event
            )
            news_selection = selector(candidates, gemini_client)
            event_id = news_selection["selected_event_id"] or None
            selection = {
                **selection,
                "event_id": event_id,
                "status": news_selection["status"],
                "editorial_review_required": False,
            }

        event_id = selection.get("event_id")
        if not event_id:
            result[scope] = {
                "status": (
                    "no_qualifying_international_news"
                    if scope == "international" and news_selection is not None
                    else "no_event_selected"
                ),
                "news_selection": news_selection,
                "historical_selection": None,
                "commentary_package": None,
            }
            continue

        event = groups.get(event_id)
        if event is None:
            raise ValueError(f"A kiválasztott esemény nem található a pipeline-ban: {event_id}")

        if gemini_client is not None:
            historical = gemini_select_historical_figures(event, catalog, gemini_client)
            package = build_gemini_commentary_package(event, historical, gemini_client)
            status = package["status"]
        else:
            historical = select_historical_figures(event, catalog, limit=figure_limit)
            package = build_commentary_package(event, historical)
            status = "editorial_research_required"
        result[scope] = {
            "status": status,
            "news_selection": news_selection,
            "historical_selection": historical,
            "commentary_package": package,
        }

    return {
        "engine": ENGINE_VERSION,
        "model_provider": "google_gemini" if gemini_client is not None else "offline_keyword_preview",
        "model": getattr(gemini_client, "model", None) or (DEFAULT_MODEL if gemini_client is not None else None),
        "matcher": MATCHER_VERSION if gemini_client is None else "GEMINI_DOCUMENTED_PROFILE_RELEVANCE_M1.0",
        "generated_at": pipeline.get("generated_at"),
        "event_pipeline": pipeline.get("pipeline"),
        "figure_catalog_version": catalog.get("schema_version"),
        "daily_editorial": result,
        "quality_gates": {
            "international_newsworthiness_review_required": True,
            "international_edition_may_have_no_story": True,
            "three_figures_per_item_target": 3,
            "no_forced_historical_matches": True,
            "three_commentary_dimensions_per_figure": 3,
            "hypothetical_reconstruction_disclosure_required": True,
            "direct_quotes_must_be_verified": True,
            "human_editorial_review_required": False,
            "publishing_performed": False,
        },
        "status": "generated" if gemini_client is not None else "editorial_research_required",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="JSON output from agora_pipeline.py")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--output")
    parser.add_argument("--figure-limit", type=int, default=3)
    parser.add_argument("--use-gemini", action="store_true", help="Use Gemini for news selection, historical selection and simulations.")
    args = parser.parse_args()
    if args.figure_limit < 1:
        parser.error("--figure-limit must be positive")

    pipeline = json.loads(Path(args.input).read_text(encoding="utf-8"))
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    client = GeminiClient() if args.use_gemini else None
    result = build_editorial_output(pipeline, catalog, args.figure_limit, client)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
