"""AGORA M2.2-M2.4: RSS -> event groups -> transparent ranking -> daily proposals.

The ranking is an evidence/recency score, not an automated judgment of public
importance. Every daily proposal requires human editorial review.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agora_event_clustering import cluster_candidates
from agora_rss_collector import collect_all


PIPELINE_VERSION = "AGORA_PIPELINE_M2.4"
FRESHNESS_HOURS = 72
MINIMUM_PROPOSAL_SCORE = 35

# Maximum 100 points. Political orientation is deliberately not a feature.
SCORE_WEIGHTS = {
    "freshness": 40,
    "independent_sources": 30,
    "coverage": 15,
    "metadata_completeness": 15,
}


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def freshness_points(latest_published_at, now):
    published = parse_datetime(latest_published_at)
    if published is None:
        return 0
    age_hours = max(0.0, (now - published).total_seconds() / 3600)
    if age_hours > FRESHNESS_HOURS:
        return 0
    if age_hours <= 6:
        return 40
    if age_hours <= 24:
        return 35
    if age_hours <= 48:
        return 25
    return 15


def score_event(event, now=None):
    """Score observable evidence only; never infer political or social importance."""
    now = now or datetime.now(timezone.utc)
    sources = int(event.get("independent_source_count") or 0)
    articles = event.get("articles") or []

    freshness = freshness_points(event.get("latest_published_at"), now)
    source_points = min(sources, 3) * 10
    coverage_points = min(len(articles), 3) * 5

    has_date = any(parse_datetime(item.get("published_at")) for item in articles)
    has_url = any(str(item.get("url") or "").startswith(("http://", "https://")) for item in articles)
    has_summary = any(str(item.get("summary") or "").strip() for item in articles)
    metadata_points = 5 * sum((has_date, has_url, has_summary))

    components = {
        "freshness": freshness,
        "independent_sources": source_points,
        "coverage": coverage_points,
        "metadata_completeness": metadata_points,
    }
    score = sum(components.values())
    age = None
    latest = parse_datetime(event.get("latest_published_at"))
    if latest:
        age = round(max(0.0, (now - latest).total_seconds() / 3600), 2)

    return {
        "score": score,
        "score_components": components,
        "age_hours": age,
        "independent_source_count": sources,
        "article_count": len(articles),
        "evidence_flags": {
            "multiple_independent_sources": sources >= 2,
            "publication_date_available": has_date,
            "article_url_available": has_url,
            "summary_available": has_summary,
            "fresh_within_72_hours": freshness > 0,
        },
        "editorial_importance_assessed": False,
        "editorial_review_required": True,
    }


def rank_events(groups, now=None, shortlist_limit=10):
    now = now or datetime.now(timezone.utc)
    ranked = []
    for group in groups:
        item = dict(group)
        item.update(score_event(group, now=now))
        item["eligible_for_daily_proposal"] = (
            item.get("scope") in {"hungary", "international"}
            and item["score"] >= MINIMUM_PROPOSAL_SCORE
            and item["evidence_flags"]["fresh_within_72_hours"]
        )
        ranked.append(item)

    ranked.sort(key=lambda item: (
        -item["score"],
        -(parse_datetime(item.get("latest_published_at")).timestamp()
          if parse_datetime(item.get("latest_published_at")) else 0),
        str(item.get("event_id") or ""),
    ))

    shortlists = {}
    for scope in ("hungary", "international"):
        scoped = [item for item in ranked if item.get("scope") == scope]
        shortlists[scope] = {
            "candidate_count": len(scoped),
            "eligible_count": sum(item["eligible_for_daily_proposal"] for item in scoped),
            "events": scoped[:shortlist_limit],
        }
    return shortlists


def build_daily_selection(shortlists):
    selection = {}
    for scope in ("hungary", "international"):
        eligible = [
            event for event in shortlists[scope]["events"]
            if event["eligible_for_daily_proposal"]
        ]
        if eligible:
            event = eligible[0]
            selection[scope] = {
                "status": "proposed_for_editorial_review",
                "event_id": event["event_id"],
                "title": event.get("representative_title"),
                "score": event["score"],
                "source_codes": event.get("source_codes", []),
                "article_urls": [
                    article.get("url") for article in event.get("articles", [])
                    if article.get("url")
                ],
                "editorial_review_required": True,
            }
        else:
            selection[scope] = {
                "status": "no_eligible_candidate",
                "event_id": None,
                "editorial_review_required": True,
            }
    return selection


def build_pipeline_result(collection, time_window_hours=72,
                          similarity_threshold=0.58, shortlist_limit=10,
                          now=None):
    now = now or datetime.now(timezone.utc)
    clustered = cluster_candidates(
        collection.get("candidates", []),
        time_window_hours=time_window_hours,
        similarity_threshold=similarity_threshold,
    )
    shortlists = rank_events(clustered["groups"], now=now,
                             shortlist_limit=shortlist_limit)
    return {
        "pipeline": PIPELINE_VERSION,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "collection": {
            "candidate_count": collection.get("candidate_count", len(collection.get("candidates", []))),
            "source_count": collection.get("source_count", 0),
            "failed_sources": collection.get("failed_sources", []),
        },
        "clustering": {
            "group_count": clustered["group_count"],
            "article_count": clustered["article_count"],
            "time_window_hours": time_window_hours,
            "similarity_threshold": similarity_threshold,
        },
        "ranking_policy": {
            "weights": SCORE_WEIGHTS,
            "freshness_window_hours": FRESHNESS_HOURS,
            "minimum_proposal_score": MINIMUM_PROPOSAL_SCORE,
            "political_orientation_used": False,
            "editorial_importance_automated": False,
        },
        "shortlists": shortlists,
        "daily_selection": build_daily_selection(shortlists),
        "groups": clustered["groups"],
        "publishing": {
            "performed": False,
            "status": "candidate_generation_only",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="Existing collector JSON; otherwise fetch RSS feeds")
    parser.add_argument("--output", help="Write JSON result to this path instead of stdout")
    parser.add_argument("--time-window-hours", type=int, default=72)
    parser.add_argument("--threshold", type=float, default=0.58)
    parser.add_argument("--shortlist-limit", type=int, default=10)
    parser.add_argument("--pause-seconds", type=float, default=0.5)
    args = parser.parse_args()

    if args.time_window_hours < 1:
        parser.error("--time-window-hours must be positive")
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    if args.shortlist_limit < 1:
        parser.error("--shortlist-limit must be positive")

    if args.input:
        collection = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        collection = collect_all(pause_seconds=args.pause_seconds)

    result = build_pipeline_result(
        collection,
        time_window_hours=args.time_window_hours,
        similarity_threshold=args.threshold,
        shortlist_limit=args.shortlist_limit,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
