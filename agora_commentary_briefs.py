"""AGORA M4: evidence-linked commentary briefs, not fabricated finished commentary.

The output is a structured editorial brief for a human author or a later
approved language model. It deliberately contains no invented quotations.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRIEF_VERSION = "AGORA_COMMENTARY_BRIEF_M4.1"

DIMENSIONS = [
    {
        "id": "interpretation",
        "label": "Értelmezés",
        "instruction": "A mai esemény értelmezése a személy dokumentált gondolkodása alapján. Válaszd külön a történeti tényt és a mai hipotetikus alkalmazást.",
        "questions": ["Melyik dokumentált alapelv vagy fogalom kapcsolódik az eseményhez?", "Milyen fontos különbség van a történelmi helyzet és a mai esemény között?"],
    },
    {
        "id": "consequences",
        "label": "Következmények",
        "instruction": "A lehetséges következmények, kockázatok és történelmi mintázatok elemzése; bizonytalanság esetén több forgatókönyv megőrzése.",
        "questions": ["Milyen következményekre figyelmeztethet a történelmi tapasztalat?", "Mi az, amit a történelmi források nem támasztanak alá?"],
    },
    {
        "id": "response",
        "label": "Megoldás",
        "instruction": "A személy dokumentált elveiből levezethető, mai helyzetre alkalmazott lehetséges megoldási irány. Ne tulajdoníts neki szó szerinti mai javaslatot.",
        "questions": ["Milyen elv vagy intézményi megoldás következik a dokumentált műveiből?", "Milyen korlátai vagy nem kívánt következményei lehetnek ennek ma?"],
    },
]


def build_commentary_brief(event, match):
    return {
        "figure_id": match["figure_id"],
        "figure_name": match["name"],
        "event_id": event.get("event_id"),
        "event_title": event.get("representative_title") or event.get("title"),
        "historical_basis": {
            "core_ideas": match.get("core_ideas", []),
            "works": match.get("works", []),
            "profile_limitations": match.get("limits"),
            "matched_keywords": match.get("matched_keywords", []),
        },
        "sections": [
            {
                **dimension,
                "draft_text": None,
                "evidence_notes": [],
                "source_urls": [work["url"] for work in match.get("works", [])],
                "status": "awaiting_research_and_authoring",
            }
            for dimension in DIMENSIONS
        ],
        "mandatory_disclosures": {
            "hypothetical_reconstruction": True,
            "direct_quote_used": False,
            "direct_quote_requires_exact_source_and_location": True,
            "historical_claims_require_citations": True,
            "present_day_facts_require_news_sources": True,
            "historical_source_verification_required": True,
            "anachronism_review_required": True,
        },
        "publication_status": "not_ready",
    }


def build_commentary_package(event, selection):
    briefs = [
        build_commentary_brief(event, match)
        for match in selection.get("figures", [])
    ]
    return {
        "brief_engine": BRIEF_VERSION,
        "event_id": event.get("event_id"),
        "event_title": event.get("representative_title") or event.get("title"),
        "figure_count": len(briefs),
        "commentary_count": len(briefs) * 3,
        "briefs": briefs,
        "status": "editorial_research_required" if briefs else "no_briefs_created",
        "publishing": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Combined historical match JSON")
    parser.add_argument("--events", required=True, help="AGORA pipeline JSON")
    parser.add_argument("--output")
    args = parser.parse_args()
    matched = json.loads(Path(args.input).read_text(encoding="utf-8"))
    pipeline = json.loads(Path(args.events).read_text(encoding="utf-8"))
    packages = {}
    for scope, selection in matched.get("selections", {}).items():
        event_id = selection.get("event_id")
        event = next((g for g in pipeline.get("groups", []) if g.get("event_id") == event_id), {})
        packages[scope] = build_commentary_package(event, selection)
    rendered = json.dumps({"brief_engine": BRIEF_VERSION, "packages": packages}, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
