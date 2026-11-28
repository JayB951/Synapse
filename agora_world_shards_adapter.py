"""M6: export an approved AGORA edition as a WORLD SHARDS content-item record.

This adapter never connects to Supabase. It only creates a JSON record matching
the shard_content_items fields consumed by edition_builder.py.
"""
import argparse
import json
import sys
from pathlib import Path

ADAPTER_VERSION = "AGORA_WORLD_SHARDS_ADAPTER_M6.2"
REQUIRED_SCOPES = ("hungary", "international")
DIMENSIONS = ("interpretation", "consequences", "response")


def build_content_item(pipeline, editorial, qa_report, edition_date):
    if not qa_report.get("approved") or qa_report.get("status") != "approved":
        raise ValueError("AGORA export blocked: a fully approved M5 QA report is required.")
    daily = editorial.get("daily_editorial", {})
    event_records = []
    all_sources = []
    all_figures = []
    body_parts = []
    scores = []

    for scope in REQUIRED_SCOPES:
        scope_data = daily.get(scope) or {}
        selection = scope_data.get("historical_selection") or {}
        package = scope_data.get("commentary_package") or {}
        event_id = selection.get("event_id")
        event = next((item for item in pipeline.get("groups", [])
                      if item.get("event_id") == event_id), None)
        if not event:
            raise ValueError(f"Missing event payload for {scope}: {event_id}")
        articles = event.get("articles") or []
        sources = []
        for article in articles:
            url = article.get("url")
            if url:
                sources.append({
                    "publisher": article.get("source_name") or article.get("source_code"),
                    "source_code": article.get("source_code"),
                    "title": article.get("title"),
                    "url": url,
                    "published_at": article.get("published_at"),
                })
        all_sources.extend(sources)
        scores.append(int(event.get("score") or 0))
        translation = event.get("hungarian_translation") if scope == "international" else None
        title = (
            (translation or {}).get("event_title")
            or event.get("representative_title")
            or selection.get("title")
            or "Cím nélküli esemény"
        )
        event_records.append({
            "scope": scope,
            "event_id": event_id,
            "title": title,
            "score": event.get("score"),
            "source_count": len({item.get("source_code") for item in sources if item.get("source_code")}),
            "sources": sources,
            "article_summaries": [
                {"title": article.get("title"), "summary": article.get("summary")}
                for article in articles if article.get("title") or article.get("summary")
            ],
        })
        body_parts.extend([f"## {'Magyarország' if scope == 'hungary' else 'Nemzetközi'} esemény",
                           title])
        for article_index, article in enumerate(articles):
            publisher = article.get("source_name") or article.get("source_code") or "Hírforrás"
            translated_article = (
                (translation or {}).get("articles", [])[article_index]
                if translation and article_index < len((translation or {}).get("articles", []))
                else {}
            )
            article_title = translated_article.get("title") or article.get("title") or title
            article_summary = translated_article.get("summary") or article.get("summary")
            if article_summary:
                body_parts.append(f"**{publisher}: {article_title}**")
                body_parts.append(article_summary)
        # Keep all verified links in metadata, but display one representative source per event.
        representative_source = next((item for item in sources if item.get("url")), None)
        if representative_source:
            body_parts.append(f"Forrás: {representative_source['url']}")
        for brief in package.get("briefs", []):
            all_figures.append({
                "scope": scope,
                "figure_id": brief.get("figure_id"),
                "name": brief.get("figure_name"),
                "role": brief.get("figure_role"),
            })
            role = str(brief.get("figure_role") or "").strip()
            body_parts.extend([
                f"### {brief.get('figure_name')}",
                f"**{role}**" if role else "",
                "Történelmi nézőpont",
                "#### Provokatív kérdés",
                str(brief.get("provocative_question") or "").strip(),
            ])
            if not str(brief.get("provocative_question") or "").strip().endswith("?"):
                raise ValueError(f"Missing persona-specific provocative question: {brief.get('figure_id')}")
            for dimension in DIMENSIONS:
                section = next((s for s in brief.get("sections", [])
                                if s.get("id") == dimension), None)
                if not section or not str(section.get("draft_text") or "").strip():
                    raise ValueError(f"Missing approved commentary text: {brief.get('figure_id')} / {dimension}")
                body_parts.extend([f"#### {section.get('label') or dimension}",
                                   section["draft_text"]])
            body_parts.append("A történelmi személyiség mai eseményre adott nézőpontja hipotetikus rekonstrukció, nem szó szerinti történelmi állásfoglalás.")

    if len(event_records) != 2 or len(all_figures) != 6:
        raise ValueError("AGORA export requires two news events and six historical figures.")
    source_urls = [item["url"] for item in all_sources]
    if not source_urls:
        raise ValueError("AGORA export requires original article URLs.")

    titles = [item["title"] for item in event_records]
    summary = "Magyar: " + titles[0] + " | Nemzetközi: " + titles[1]
    first_source = all_sources[0]
    latest_dates = [item.get("published_at") for item in all_sources if item.get("published_at")]
    latest_date = max(latest_dates) if latest_dates else None
    return {
        "section_code": "research_frontier",
        "title": f"AGORA – {edition_date}",
        "summary": summary[:1000],
        "body": "\n\n".join(body_parts),
        "source_name": "WORLD SHARDS AGORA",
        "source_url": first_source["url"],
        "source_published_at": latest_date,
        "collected_at": pipeline.get("generated_at"),
        "status": "candidate",
        "relevance_score": round(sum(scores) / len(scores)) if scores else 0,
        "metadata": {
            "adapter": ADAPTER_VERSION,
            "edition_date": edition_date,
            "content_type": "agora_daily_editorial",
            "news_items": event_records,
            "historical_figures": all_figures,
            "source_references": all_sources,
            "qa_status": "approved",
            "qa_engine": qa_report.get("qa_engine"),
            "reviewed_by": qa_report.get("human_review", {}).get("editor_name"),
            "reviewed_at": qa_report.get("human_review", {}).get("reviewed_at"),
            "publishing_performed": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="AGORA pipeline JSON")
    parser.add_argument("--editorial", required=True, help="AGORA editorial JSON")
    parser.add_argument("--qa", required=True, help="Approved M5 QA report JSON")
    parser.add_argument("--edition-date", required=True, help="WORLD SHARDS edition date, YYYY-MM-DD")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    pipeline = json.loads(Path(args.input).read_text(encoding="utf-8"))
    editorial = json.loads(Path(args.editorial).read_text(encoding="utf-8"))
    qa_report = json.loads(Path(args.qa).read_text(encoding="utf-8"))
    record = build_content_item(pipeline, editorial, qa_report, args.edition_date)
    Path(args.output).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()


def build_content_items(pipeline, editorial, qa_report, edition_date):
    """Return separate MAGYAR AGORA and WORLD AGORA content records."""
    combined = build_content_item(pipeline, editorial, qa_report, edition_date)
    metadata = combined["metadata"]
    body = combined["body"]
    markers = {
        "hungary": "## Magyarország",
        "international": "## Nemzetközi",
    }
    starts = {scope: body.find(marker) for scope, marker in markers.items()}
    if any(position < 0 for position in starts.values()):
        raise ValueError("AGORA export is missing one of its two section bodies.")

    ordered = sorted((position, scope) for scope, position in starts.items())
    bodies = {}
    for index, (start, scope) in enumerate(ordered):
        end = ordered[index + 1][0] if index + 1 < len(ordered) else len(body)
        bodies[scope] = body[start:end].strip()

    records = []
    for scope, section_code, title_prefix in (
        ("hungary", "agora_hungary", "MAGYAR AGORA"),
        ("international", "agora_world", "WORLD AGORA"),
    ):
        event = next(item for item in metadata["news_items"] if item["scope"] == scope)
        sources = [item for item in metadata["source_references"]
                   if item.get("source_code") in {
                       source.get("source_code") for source in event.get("sources", [])
                   }]
        figures = [item for item in metadata["historical_figures"]
                   if item.get("scope") == scope]
        latest_dates = [item.get("published_at") for item in sources if item.get("published_at")]
        records.append({
            "section_code": "research_frontier",
            "title": f"{title_prefix} – {edition_date}",
            "summary": event["title"][:1000],
            "body": bodies[scope],
            "source_name": title_prefix,
            "source_url": (sources[0].get("url") if sources else None),
            "source_published_at": max(latest_dates) if latest_dates else None,
            "collected_at": pipeline.get("generated_at"),
            "status": "candidate",
            "relevance_score": int(event.get("score") or 0),
            "metadata": {
                "adapter": ADAPTER_VERSION,
                "edition_date": edition_date,
                "content_type": section_code,
                "news_items": [event],
                "historical_figures": figures,
                "source_references": sources,
                "qa_status": "automatically_approved",
                "qa_engine": qa_report.get("qa_engine"),
                "publishing_performed": False,
            },
        })
    return records
