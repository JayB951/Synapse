"""AGORA M5: deterministic editorial quality gates and human-review checklist."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from agora_pipeline import parse_datetime

QA_VERSION = "AGORA_EDITORIAL_QA_M5.2"
REQUIRED_SCOPES = ("hungary", "international")
REQUIRED_DIMENSIONS = ("interpretation", "consequences", "response")
REVIEW_FLAGS = (
    "news_facts_verified",
    "source_independence_verified",
    "historical_sources_verified",
    "anachronism_reviewed",
    "commentary_written_and_fact_checked",
    "quotation_checks_completed",
    "attribution_and_rights_checked",
)


def _check(checks, code, passed, message, severity="error", scope=None):
    checks.append({
        "code": code,
        "passed": bool(passed),
        "severity": severity,
        "scope": scope,
        "message": message,
    })


def build_review_template(editorial):
    scopes = {}
    for scope in REQUIRED_SCOPES:
        item = editorial.get("daily_editorial", {}).get(scope, {})
        selection = item.get("historical_selection") or {}
        scopes[scope] = {
            "event_id": selection.get("event_id"),
            "editorial_notes": "",
            "figure_reviews": [
                {
                    "figure_id": figure.get("figure_id"),
                    "sections": {
                        dimension: {
                            "text_completed": False,
                            "historical_claims_cited": False,
                            "present_day_claims_cited": False,
                            "reviewer_notes": "",
                        }
                        for dimension in REQUIRED_DIMENSIONS
                    },
                }
                for figure in selection.get("figures", [])
            ],
        }
    return {
        "review_schema": "AGORA_HUMAN_REVIEW_M5.2",
        "approved": False,
        "editor_name": "",
        "reviewed_at": None,
        "checks": {flag: False for flag in REVIEW_FLAGS},
        "scope_reviews": scopes,
        "review_note": "A sablon kitöltése önmagában nem jelent jóváhagyást. Csak ténylegesen ellenőrzött állításokat jelölj igaznak.",
    }


def evaluate_quality(pipeline, editorial, review=None, now=None):
    now = now or datetime.now(timezone.utc)
    review = review or {}
    groups = {item.get("event_id"): item for item in pipeline.get("groups", [])}
    checks = []
    per_scope = {}
    for scope in REQUIRED_SCOPES:
        item = editorial.get("daily_editorial", {}).get(scope, {})
        selection = item.get("historical_selection") or {}
        package = item.get("commentary_package") or {}
        event_id = selection.get("event_id")
        event = groups.get(event_id)
        scope_checks = []

        if not event_id or not event:
            news_selection = item.get("news_selection") or {}
            legitimate_empty_international = (
                scope == "international"
                and item.get("status") == "no_qualifying_international_news"
                and news_selection.get("status") in {"no_qualifying_news", "no_candidates"}
                and bool(str(news_selection.get("internal_rationale") or "").strip())
            )
            if legitimate_empty_international:
                _check(
                    scope_checks, "international_newsworthiness_gate", True,
                    "A Gemini szerkesztőségi szűrés nem talált megfelelő nemzetközi hírt; a rovat üresen maradhat.",
                    scope=scope,
                )
                per_scope[scope] = scope_checks
                checks.extend(scope_checks)
                continue
            _check(scope_checks, "event_selected", False, "Nincs azonosítható napi esemény vagy igazolt szerkesztőségi kizárás.", scope=scope)
            per_scope[scope] = scope_checks
            checks.extend(scope_checks)
            continue

        _check(scope_checks, "scope_matches", event.get("scope") == scope,
               "Az esemény földrajzi besorolása megfelel a rovatnak.", scope=scope)
        _check(scope_checks, "event_not_reused", True,
               "Az eseményazonosító egyedisége a globális ellenőrzésben vizsgálandó.", "warning", scope)

        if scope == "international":
            news_selection = item.get("news_selection") or {}
            _check(
                scope_checks, "international_newsworthiness_gate",
                news_selection.get("status") == "selected",
                "A nemzetközi esemény átment a WORLD SHARDS tartalmi relevanciaszűrésén.",
                scope=scope,
            )

        latest = parse_datetime(event.get("latest_published_at"))
        age_hours = (now - latest).total_seconds() / 3600 if latest else None
        _check(scope_checks, "freshness_72h", age_hours is not None and -1 <= age_hours <= 72,
               "A legfrissebb publikáció legfeljebb 72 órás és dátuma értelmezhető.", scope=scope)

        articles = event.get("articles") or []
        source_codes = sorted({str(a.get("source_code")) for a in articles if a.get("source_code")})
        valid_urls = [a for a in articles if str(a.get("url") or "").startswith(("https://", "http://"))]
        dated = [a for a in articles if parse_datetime(a.get("published_at"))]
        summaries = [a for a in articles if str(a.get("summary") or "").strip()]
        independent_count = len(source_codes)
        _check(scope_checks, "independent_sources_min_2", independent_count >= 2,
               f"Legalább két külön forráskód szükséges; jelenleg {independent_count} található.", scope=scope)
        _check(scope_checks, "source_urls_min_2", len({a.get("source_code") for a in valid_urls}) >= 2,
               "Legalább két külön kiadótól kell használható eredeti cikk-URL.", scope=scope)
        _check(scope_checks, "publication_dates", len(dated) >= 2,
               "Legalább két forráscikk publikálási dátuma ellenőrizhető.", "warning", scope)
        _check(scope_checks, "article_summaries", len(summaries) >= 2,
               "Legalább két cikkhez elérhető összefoglaló.", "warning", scope)

        figures = selection.get("figures") or []
        _check(scope_checks, "exactly_3_figures", len(figures) == 3,
               f"Három történelmi személyiség szükséges; jelenleg {len(figures)} van.", scope=scope)
        _check(scope_checks, "no_duplicate_figures", len({f.get("figure_id") for f in figures}) == len(figures),
               "Egy eseményhez nem rendelhető ugyanaz a személy többször.", scope=scope)
        briefs = package.get("briefs") or []
        _check(scope_checks, "brief_count_matches", len(briefs) == len(figures),
               "Minden kiválasztott személyhez külön kommentár-csomag tartozik.", scope=scope)
        for brief in briefs:
            sections = {section.get("id"): section for section in brief.get("sections", [])}
            for dimension in REQUIRED_DIMENSIONS:
                section = sections.get(dimension, {})
                text_ready = bool(str(section.get("draft_text") or "").strip())
                evidence_ready = (
                    bool(section.get("evidence_notes"))
                    and bool(section.get("source_urls"))
                    and bool(section.get("news_source_urls"))
                )
                _check(scope_checks, f"{brief.get('figure_id')}_{dimension}_text",
                       text_ready, f"{brief.get('figure_name')}: elkészült a(z) {dimension} szöveg.", scope=scope)
                _check(scope_checks, f"{brief.get('figure_id')}_{dimension}_evidence",
                       evidence_ready, f"{brief.get('figure_name')}: a(z) {dimension} részhez történeti bizonyíték, hírforrás és hivatkozás tartozik.", scope=scope)

        human_scope = review.get("scope_reviews", {}).get(scope, {})
        human_figure_reviews = {f.get("figure_id"): f for f in human_scope.get("figure_reviews", [])}
        for figure in figures:
            human_figure = human_figure_reviews.get(figure.get("figure_id"), {})
            for dimension in REQUIRED_DIMENSIONS:
                flags = human_figure.get("sections", {}).get(dimension, {})
                _check(scope_checks, f"human_{figure.get('figure_id')}_{dimension}",
                       all(flags.get(flag) is True for flag in (
                           "text_completed", "historical_claims_cited", "present_day_claims_cited"
                       )),
                       f"Szerkesztői ellenőrzés szükséges: {figure.get('name')} / {dimension}.", scope=scope)
        per_scope[scope] = scope_checks
        checks.extend(scope_checks)

    hu_id = editorial.get("daily_editorial", {}).get("hungary", {}).get("historical_selection", {}).get("event_id")
    int_item = editorial.get("daily_editorial", {}).get("international", {})
    int_id = (int_item.get("historical_selection") or {}).get("event_id")
    int_decision = int_item.get("news_selection") or {}
    international_decision_recorded = (
        bool(int_id) and int_decision.get("status") == "selected"
    ) or (
        not int_id
        and int_item.get("status") == "no_qualifying_international_news"
        and int_decision.get("status") in {"no_qualifying_news", "no_candidates"}
    )
    distinct_when_both_exist = not int_id or (hu_id and hu_id != int_id)
    _check(
        checks, "hungary_event_and_international_editorial_decision",
        bool(hu_id) and international_decision_recorded and distinct_when_both_exist,
        "A magyar rovat eseménye és a nemzetközi rovat dokumentált szerkesztőségi döntése rendelkezésre áll; a nemzetközi rovat indokoltan maradhat üres.",
    )
    for flag in REVIEW_FLAGS:
        _check(checks, "human_" + flag, review.get("checks", {}).get(flag) is True,
               f"Szerkesztői jóváhagyás szükséges: {flag}.")
    _check(checks, "editor_identity", bool(str(review.get("editor_name") or "").strip()),
           "A felelős szerkesztő nevét rögzíteni kell.")
    reviewed_at = parse_datetime(review.get("reviewed_at"))
    _check(checks, "review_timestamp", reviewed_at is not None,
           "A szerkesztői ellenőrzés időpontját rögzíteni kell.")

    errors = [item for item in checks if not item["passed"] and item["severity"] == "error"]
    warnings = [item for item in checks if not item["passed"] and item["severity"] == "warning"]
    approved = not errors and review.get("approved") is True
    return {
        "qa_engine": QA_VERSION,
        "status": "approved" if approved else ("blocked" if errors else "awaiting_human_approval"),
        "approved": approved,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["passed"] for item in checks),
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "scopes": per_scope,
        "checks": checks,
        "human_review": review,
        "publishing_performed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="AGORA pipeline JSON")
    parser.add_argument("--editorial", required=True, help="AGORA daily editorial JSON")
    parser.add_argument("--review", help="Completed human-review JSON")
    parser.add_argument("--review-template", help="Write a blank human-review template")
    parser.add_argument("--output", help="Write QA report JSON")
    parser.add_argument("--allow-pending", action="store_true", help="Return success for a blocked preview; never approves it")
    args = parser.parse_args()
    pipeline = json.loads(Path(args.input).read_text(encoding="utf-8"))
    editorial = json.loads(Path(args.editorial).read_text(encoding="utf-8"))
    review = json.loads(Path(args.review).read_text(encoding="utf-8")) if args.review else {}
    if args.review_template:
        Path(args.review_template).write_text(
            json.dumps(build_review_template(editorial), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    result = evaluate_quality(pipeline, editorial, review)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    if not result["approved"] and not args.allow_pending:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
