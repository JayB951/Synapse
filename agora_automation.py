"""Fully automated AGORA generation and Supabase integration.

Runs both Hungarian and international editorial tracks, validates their structure,
and stores two edition-scoped content records for the existing WORLD SHARDS builder.
"""
import argparse
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


from agora_daily_editorial import build_editorial_output
from agora_gemini_engine import GeminiClient, translate_event_to_hungarian
from agora_pipeline import build_pipeline_result, parse_datetime
from agora_rss_collector import collect_all
from agora_world_shards_adapter import build_content_items

TIMEZONE = ZoneInfo("Europe/Budapest")
REQUIRED_SCOPES = ("hungary", "international")
REQUIRED_DIMENSIONS = ("interpretation", "consequences", "response")
LOGGER = logging.getLogger("agora-automation")


def _long_form_ok(text):
    sentences = [
        item.strip() for item in re.split(r"(?<=[.!?])\s+", str(text or "").strip())
        if len(item.strip().split()) >= 5
    ]
    connector = re.compile(
        r"\b(és|de|mert|miközben|ezért|ugyanakkor|noha|bár|hiszen|amely|amelyek|"
        r"amelynek|amelyben|így|azonban|viszont|tehát|ha|hogy|valamint|illetve|"
        r"mivel|ugyanis|amikor|amíg|miután|hanem|sőt|holott|amennyiben|továbbá|"
        r"mindemellett|nemcsak|akár|hacsak|mialatt|minthogy|ennek ellenére|annak ellenére)\b",
        re.IGNORECASE,
    )
    compound = sum(bool(connector.search(sentence)) for sentence in sentences)
    words = len(re.findall(r"\b[\wÁÉÍÓÖŐÚÜŰáéíóöőúüű-]+\b", str(text or "")))
    return len(sentences) >= 4 and compound >= 4 and words >= 60


def automated_quality_gate(pipeline, editorial, now=None):
    """Deterministic publication gate; no manual review template or approval step."""
    now = now or datetime.now(timezone.utc)
    groups = {item.get("event_id"): item for item in pipeline.get("groups", [])}
    errors = []
    summary = {}

    for scope in REQUIRED_SCOPES:
        item = editorial.get("daily_editorial", {}).get(scope) or {}
        decision = item.get("news_selection") or {}
        selection = item.get("historical_selection") or {}
        package = item.get("commentary_package") or {}
        event_id = selection.get("event_id")
        event = groups.get(event_id)

        if not event or event.get("scope") != scope:
            errors.append(
                f"{scope}: nincs megfelelően kiválasztott esemény "
                f"(státusz: {decision.get('status')}, jelöltek: {decision.get('candidate_count')}, "
                f"indok: {decision.get('internal_rationale') or 'nincs megadva'})."
            )
            continue
        if scope == "international":
            translation = event.get("hungarian_translation") or {}
            translated_articles = translation.get("articles") or []
            if translation.get("language") != "hu" or not translation.get("event_title") or len(translated_articles) != len(articles):
                errors.append("international: hiányzik a teljes magyar nyelvű hírfordítás.")

        if decision.get("status") != "selected" or decision.get("selected_event_id") != event_id:
            errors.append(f"{scope}: a Gemini hírválasztása nem egyezik a kiválasztott eseménnyel.")

        latest = parse_datetime(event.get("latest_published_at"))
        age = (now - latest).total_seconds() / 3600 if latest else None
        if age is None or age < -1 or age > 72:
            errors.append(f"{scope}: a hír nem rendelkezik érvényes, 72 órán belüli dátummal.")

        articles = event.get("articles") or []
        sources = {str(article.get("source_code")) for article in articles if article.get("source_code")}
        valid_urls = {
            article.get("url") for article in articles
            if str(article.get("url") or "").startswith(("http://", "https://"))
        }
        if len(sources) < 1 or len(valid_urls) < 1:
            errors.append(
                f"{scope}: legalább egy kiadó és legalább egy ellenőrizhető cikk-URL szükséges "
                f"(kiadók: {len(sources)}, URL-ek: {len(valid_urls)})."
            )

        figures = selection.get("figures") or []
        briefs = package.get("briefs") or []
        if len(figures) != 3 or len({figure.get("figure_id") for figure in figures}) != 3:
            errors.append(f"{scope}: pontosan három különböző történelmi személy szükséges.")
        if len(briefs) != 3:
            errors.append(f"{scope}: pontosan három személyes kommentárcsomag szükséges.")

        for brief in briefs:
            sections = {section.get("id"): section for section in brief.get("sections", [])}
            if set(sections) != set(REQUIRED_DIMENSIONS):
                errors.append(f"{scope}/{brief.get('figure_name')}: hiányzik valamelyik kommentárrész.")
                continue
            for dimension in REQUIRED_DIMENSIONS:
                section = sections[dimension]
                if not _long_form_ok(section.get("draft_text")):
                    errors.append(
                        f"{scope}/{brief.get('figure_name')}/{dimension}: "
                        "a szöveg nem éri el a négy összetett mondat / 60 szó minimumot."
                    )
                if not section.get("evidence_notes") or not section.get("source_urls") or not section.get("news_source_urls"):
                    errors.append(f"{scope}/{brief.get('figure_name')}/{dimension}: hiányzó forrásalap.")

        summary[scope] = {
            "event_id": event_id,
            "title": event.get("representative_title"),
            "source_count": len(sources),
            "historical_figure_count": len(figures),
            "commentary_count": sum(len(brief.get("sections", [])) for brief in briefs),
        }

    if len({
        (editorial.get("daily_editorial", {}).get(scope, {}).get("historical_selection") or {}).get("event_id")
        for scope in REQUIRED_SCOPES
    }) != 2:
        errors.append("A magyar és a nemzetközi rovat nem használhatja ugyanazt az eseményt.")

    report = {
        "qa_engine": "AGORA_AUTOMATED_PUBLICATION_GATE_M1",
        "status": "approved" if not errors else "blocked",
        "approved": not errors,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "summary": summary,
        "errors": errors,
        "human_review_required": False,
        "publishing_performed": False,
    }
    if errors:
        raise RuntimeError("AGORA automatikus minőségkapu blokkolta a mentést:\n- " + "\n- ".join(errors))
    return report


def get_supabase_client():
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise RuntimeError("Hiányzó SUPABASE_URL vagy SUPABASE_SECRET_KEY.")
    return create_client(url, key)


def save_content_item(supabase, record):
    section_code = record["section_code"]
    content_type = record["metadata"]["content_type"]
    edition_date = record["metadata"]["edition_date"]
    existing = (
        supabase.table("shard_content_items")
        .select("id,status")
        .eq("section_code", section_code)
        .contains("metadata", {"edition_date": edition_date, "content_type": content_type})
        .limit(1)
        .execute()
    )
    if existing.data:
        current = existing.data[0]
        if current.get("status") == "candidate":
            response = (
                supabase.table("shard_content_items")
                .update(record)
                .eq("id", current["id"])
                .execute()
            )
            if not response.data:
                raise RuntimeError(f"{content_type}: a meglévő jelölt frissítése nem igazolható.")
            LOGGER.info("%s: meglévő napi jelölt frissítve.", content_type)
            return current["id"]
        LOGGER.info("%s: már kiválasztott tartalom, változatlanul hagyva.", content_type)
        return current["id"]

    response = supabase.table("shard_content_items").insert(record).execute()
    if not response.data:
        raise RuntimeError(f"{content_type}: a Supabase-beszúrás nem adott vissza rekordot.")
    LOGGER.info("%s: új napi tartalom mentve.", content_type)
    return response.data[0]["id"]


def run(edition_date=None):
    edition_date = edition_date or datetime.now(TIMEZONE).date().isoformat()
    LOGGER.info("AGORA teljes automatizálás indul: %s", edition_date)

    collection = collect_all()
    if not collection.get("candidates"):
        raise RuntimeError("Az AGORA RSS-gyűjtés egyetlen jelöltet sem adott.")
    pipeline = build_pipeline_result(collection, shortlist_limit=30)
    client = GeminiClient()
    editorial = build_editorial_output(pipeline, json.loads(
        Path("agora_historical_figures.json").read_text(encoding="utf-8")
    ), gemini_client=client)
    for scope in REQUIRED_SCOPES:
        decision = (editorial.get("daily_editorial", {}).get(scope) or {}).get("news_selection") or {}
        LOGGER.info(
            "%s hírválasztás: státusz=%s, jelöltek=%s, kiválasztott=%s",
            scope, decision.get("status"), decision.get("candidate_count"),
            decision.get("selected_event_id") or "nincs",
        )
    international_item = editorial.get("daily_editorial", {}).get("international") or {}
    international_id = (international_item.get("historical_selection") or {}).get("event_id")
    international_event = next(
        (item for item in pipeline.get("groups", []) if item.get("event_id") == international_id),
        None,
    )
    if international_event is None:
        raise RuntimeError("A nemzetközi hír magyar fordítása nem készíthető el: nincs kiválasztott esemény.")
    international_event["hungarian_translation"] = translate_event_to_hungarian(
        international_event, client
    )
    LOGGER.info("A nemzetközi AGORA-hír magyar fordítása elkészült.")

    qa_report = automated_quality_gate(pipeline, editorial)
    records = build_content_items(pipeline, editorial, qa_report, edition_date)

    supabase = get_supabase_client()
    saved = [save_content_item(supabase, record) for record in records]
    LOGGER.info("AGORA sikeresen integrálva: %s", ", ".join(record["metadata"]["content_type"] for record in records))
    return {
        "edition_date": edition_date,
        "content_item_ids": saved,
        "sections": [record["metadata"]["content_type"] for record in records],
        "qa": qa_report,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition-date", help="Target WORLD SHARDS date (YYYY-MM-DD); defaults to Budapest today.")
    parser.add_argument("--output", help="Optional JSON result path.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = run(args.edition_date)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
