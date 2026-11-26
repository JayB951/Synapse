"""AGORA Gemini engine: news-specific historical selection and persona-consistent simulation.

Uses one configurable Gemini model for two isolated roles:
1) select the three most relevant historical figures for an event;
2) simulate each selected figure in a separate call, producing three coherent sections.

The module never publishes. All generated historical claims remain subject to editorial source verification.
"""
import json
import os
import re
import time
from urllib.parse import urlparse

import requests

DEFAULT_MODEL = "gemini-3.8-flash"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SECONDS = 90
MAX_ATTEMPTS = 3
DIMENSIONS = ("interpretation", "consequences", "response")


class GeminiError(RuntimeError):
    """Gemini request or response validation failed."""


def _safe_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class GeminiClient:
    def __init__(self, api_key=None, model=None, session=None, sleep=time.sleep):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.session = session or requests.Session()
        self.sleep = sleep
        if not self.api_key:
            raise GeminiError("Hiányzó GEMINI_API_KEY környezeti változó.")

    def generate_json(self, system_instruction, payload, response_schema):
        url = f"{API_ROOT}/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": _safe_json(payload)}]}],
            "generationConfig": {
                "temperature": 0.25,
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
            },
        }
        last_error = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self.session.post(
                    url,
                    params={"key": self.api_key},
                    json=body,
                    timeout=TIMEOUT_SECONDS,
                )
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = f"Gemini átmeneti HTTP-hiba: {response.status_code}"
                    if attempt < MAX_ATTEMPTS - 1:
                        self.sleep(2 ** attempt)
                        continue
                response.raise_for_status()
                data = response.json()
                candidates = data.get("candidates") or []
                if not candidates:
                    raise GeminiError("A Gemini nem adott vissza használható jelöltet.")
                parts = candidates[0].get("content", {}).get("parts", [])
                raw = "".join(part.get("text", "") for part in parts if part.get("text"))
                if not raw:
                    raise GeminiError("A Gemini válasza üres.")
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise GeminiError(f"A Gemini nem érvényes JSON-t adott: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise GeminiError("A Gemini JSON-válaszának objektumnak kell lennie.")
                return parsed
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else "unknown"
                detail = (exc.response.text[:500] if exc.response is not None else str(exc))
                raise GeminiError(f"Gemini HTTP-hiba ({status}): {detail}") from exc
            except requests.RequestException as exc:
                last_error = f"Gemini hálózati/API-hiba: {exc}"
                if attempt < MAX_ATTEMPTS - 1:
                    self.sleep(2 ** attempt)
                    continue
                break
        raise GeminiError(last_error or "Ismeretlen Gemini-hiba.")


SELECTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "selected_figure_ids": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
        },
        "internal_rationale": {"type": "STRING"},
    },
    "required": ["selected_figure_ids", "internal_rationale"],
}

SIMULATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "sections": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "draft_text": {"type": "STRING"},
                    "evidence_notes": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "source_titles": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                },
                "required": ["id", "draft_text", "evidence_notes", "source_titles"],
            },
        },
        "historical_disclosure": {"type": "STRING"},
        "direct_quote_used": {"type": "BOOLEAN"},
    },
    "required": ["sections", "historical_disclosure", "direct_quote_used"],
}


def _event_payload(event):
    return {
        "event_id": event.get("event_id"),
        "title": event.get("representative_title") or event.get("title"),
        "scope": event.get("scope"),
        "latest_published_at": event.get("latest_published_at"),
        "articles": [
            {
                "publisher": item.get("source_name") or item.get("source_code"),
                "title": item.get("title"),
                "published_at": item.get("published_at"),
                "url": item.get("url"),
                "summary": item.get("summary"),
            }
            for item in event.get("articles", [])
        ],
    }


def select_historical_figures(event, catalog, client):
    """Select exactly three relevant profiles; never fill the list with weak matches."""
    figures = catalog.get("figures") or []
    compact_profiles = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "lifespan": item.get("lifespan"),
            "era": item.get("era"),
            "domains": item.get("domains", []),
            "topics": item.get("topics", []),
            "core_ideas": item.get("core_ideas", []),
            "works": item.get("works", []),
            "limits": item.get("limits"),
        }
        for item in figures
    ]
    system = (
        "Te vagy az AGORA történelmi szereplőválasztója. A megadott hírhez válaszd ki "
        "a katalógusból pontosan három, az eseményhez leginkább kapcsolódó történelmi személyt. "
        "A relevanciát a személy dokumentált gondolkodásmódja, művei, szakterülete és "
        "a konkrét esemény közötti kapcsolat határozza meg. A három kiválasztott személy "
        "különböző, egymást kiegészítő történelmi nézőpontot adjon. Ne közismertség, "
        "politikai szimpátia vagy mai pártpolitikai címke alapján válassz. Ne egyszerűsíts "
        "közhelyekre. Ne találj ki személyeket vagy profilokat; kizárólag a katalógusból "
        "válassz. A feladat minden esetben pontosan három személy kiválasztása; a "
        "katalógus leginkább releváns, egymást kiegészítő három profilját rangsorold. "
        "Az internal_rationale belső adat, nem publikációs szöveg. Csak JSON-t adj."
    )
    result = client.generate_json(
        system,
        {"news": _event_payload(event), "historical_catalogue": compact_profiles},
        SELECTION_SCHEMA,
    )
    ids = result.get("selected_figure_ids")
    if not isinstance(ids, list):
        raise GeminiError("A szereplőválasztó nem adott személyazonosító-listát.")
    if len(ids) != len(set(ids)):
        raise GeminiError("A szereplőválasztó duplikált történelmi személyt adott.")
    by_id = {item["id"]: item for item in figures}
    if any(item_id not in by_id for item_id in ids):
        raise GeminiError("A szereplőválasztó ismeretlen katalógusazonosítót adott.")
    selected = [by_id[item_id] for item_id in ids]
    return {
        "event_id": event.get("event_id"),
        "candidate_count": len(figures),
        "selected_count": len(selected),
        "figures": [
            {
                "figure_id": item["id"],
                "name": item["name"],
                "score": None,
                "matched_keywords": [],
                "relevant_topics": item.get("topics", []),
                "core_ideas": item.get("core_ideas", []),
                "works": item.get("works", []),
                "limits": item.get("limits"),
                "selection_rationale_internal": result.get("internal_rationale", ""),
                "source_verification_required": False,
                "historical_relevance_human_review_required": False,
            }
            for item in selected
        ],
        "selection_policy": {
            "method": "gemini_documented_profile_relevance",
            "political_affinity_used": False,
            "forced_fill": False,
            "human_review_required": False,
        },
        "status": "matched" if len(selected) == 3 else "insufficient_relevant_figures",
    }


def _validate_long_form_commentary(text, figure_name, dimension):
    import re
    sentences = [
        item.strip() for item in re.split(r"(?<=[.!?])\s+", text.strip())
        if len(item.strip().split()) >= 5
    ]
    connectors = re.compile(
        r"\b(és|de|mert|miközben|ezért|ugyanakkor|noha|bár|hiszen|amely|amelyek|amelynek|amelyben|így|azonban|viszont|tehát|ha|hogy|valamint|illetve|mivel|ugyanis|amikor|amíg|miután|hanem|sőt|holott|amennyiben|továbbá|mindemellett|nemcsak|akár|hacsak|mialatt|minthogy|ennek ellenére|annak ellenére)\b",
        re.IGNORECASE,
    )
    compound = sum(bool(connectors.search(sentence)) for sentence in sentences)
    words = len(re.findall(r"\b[\wÁÉÍÓÖŐÚÜŰáéíóöőúüű-]+\b", text))
    if len(sentences) < 4 or compound < 4 or words < 60:
        raise GeminiError(
            f"{figure_name}/{dimension}: legalább 4 összetett mondat és 60 szó szükséges "
            f"(mondat: {len(sentences)}, összetett: {compound}, szó: {words})."
        )


def simulate_historical_figure(event, profile, client):
    """One isolated model call per figure; all three dimensions share one reasoning context."""
    allowed_sources = profile.get("works", [])
    source_titles = [item.get("title") for item in allowed_sources if item.get("title")]
    system = (
        "Te vagy az AGORA történelmi személyiségszimulátora. A kiválasztott személy "
        "dokumentált gondolkodásmódját rekonstruáld, ne általános mai véleményt írj. "
        "Egyetlen koherens gondolatmenetben dolgozd ki mindhárom részt: értelmezés, "
        "következmények, megoldás. A három rész ugyanazt a személyiséget, értékrendet "
        "és fogalmi keretet tükrözze. Ne válaszolj egymástól független sablonokkal. "
        "Ne karikírozd a személyt és ne használj róla közismert leegyszerűsítő kliséket. "
        "A mai esemény tényeit kizárólag a megadott híranyagból vedd. Történelmi "
        "állításnál kizárólag a profilban megadott dokumentációra hivatkozhatsz; "
        "ne találj ki idézetet, oldalszámot, fejezetet, dátumot vagy művet. "
        "Szó szerinti idézetet ne használj. A forráscímek közül csak a megadottakat "
        "add meg. Ha egy történeti állítás a rendelkezésre álló profil alapján nem "
        "támasztható alá, ezt jelezd az evidence_notes mezőben, ne találgass. "
        "Magyarul írj, összefüggő, publikációra szánt prózát. MINDEN egyes kommentárrész legalább 4 különálló, teljes összetett mondatból és legalább 60 szóból álljon. Mind a négy mondat végén legyen pont, és mindegyikben legyen legalább egy kötőszó vagy alárendelő kapcsolat (például mert, miközben, ezért, ugyanakkor, noha, amely, így). Ne írj egyetlen hosszú mondatot, vázlatot vagy felsorolást. Mindhárom rész legyen "
        "érdemi, ne ismételje a másikat. A rekonstrukció hipotetikus, nem valódi "
        "történelmi idézet vagy állásfoglalás. Csak a kért JSON-t add vissza."
    )
    payload = {
        "news": _event_payload(event),
        "historical_person": {
            "name": profile.get("name"),
            "lifespan": profile.get("lifespan"),
            "era": profile.get("era"),
            "domains": profile.get("domains", []),
            "topics": profile.get("topics", []),
            "documented_core_ideas": profile.get("core_ideas", []),
            "documented_works": allowed_sources,
            "historical_limits_and_cautions": profile.get("limits"),
        },
        "required_sections": [
            {"id": "interpretation", "purpose": "A hír értelmezése a személy dokumentált gondolkodásmódja alapján."},
            {"id": "consequences", "purpose": "A lehetséges következmények, veszélyek és történelmi mintázatok."},
            {"id": "response", "purpose": "A dokumentált elvekből levezethető megoldási irány, mai alkalmazásként megjelölve."},
        ],
        "allowed_historical_source_titles": source_titles,
    }
    result = client.generate_json(system, payload, SIMULATION_SCHEMA)
    sections = result.get("sections")
    if not isinstance(sections, list):
        raise GeminiError(f"{profile.get('name')}: a szimulátor nem adott szakaszlistát.")
    by_id = {item.get("id"): item for item in sections if isinstance(item, dict)}
    if set(by_id) != set(DIMENSIONS):
        raise GeminiError(f"{profile.get('name')}: pontosan három előírt kommentárrész szükséges.")

    # Retry structurally short commentaries twice before blocking the edition.
    def validate_all_dimensions():
        for dimension in DIMENSIONS:
            _validate_long_form_commentary(
                str(by_id[dimension].get("draft_text") or ""),
                profile.get("name"),
                dimension,
            )

    try:
        validate_all_dimensions()
    except GeminiError as validation_error:
        for repair_attempt in range(3):
            repair_system = system + (
                " KÖTELEZŐ JAVÍTÁS: az előző válasz nem teljesítette a mondatszerkezeti "
                "követelményt. Írd újra mindhárom részt úgy, hogy mindegyik legalább négy "
                "különálló, teljes összetett mondatból és legalább 60 szóból álljon. "
                "Minden mondat külön, ponttal lezárt mondat legyen, és mindegyik tartalmazzon "
                "kötőszót vagy alárendelő kapcsolatot. Ne rövidíts, ne vond össze a mondatokat. "
                "Minden egyes mondatban használj legalább egy ilyen kapcsolatot: és, de, mert, "
                "miközben, ezért, ugyanakkor, noha, amely, így, azonban, valamint, illetve, mivel, ugyanis, amikor, amíg, miután, hanem, sőt, holott, amennyiben."
            )
            repair_payload = {
                **payload,
                "previous_generation": result,
                "validation_feedback": str(validation_error),
                "repair_attempt": repair_attempt + 1,
                "repair_instruction": (
                    "Javítsd újra a hibás kommentárrészeket; minden dimenzió legalább "
                    "négy különálló összetett mondatból és 60 szóból álljon."
                ),
            }
            result = client.generate_json(repair_system, repair_payload, SIMULATION_SCHEMA)
            sections = result.get("sections")
            if not isinstance(sections, list):
                raise GeminiError(f"{profile.get('name')}: a javító generálás nem adott szakaszlistát.")
            by_id = {item.get("id"): item for item in sections if isinstance(item, dict)}
            if set(by_id) != set(DIMENSIONS):
                raise GeminiError(f"{profile.get('name')}: a javító generálásból hiányzik egy kommentárrész.")
            try:
                validate_all_dimensions()
                break
            except GeminiError as next_error:
                validation_error = next_error
        else:
            raise validation_error

    news_source_urls = sorted({
        item.get("url") for item in event.get("articles", [])
        if str(item.get("url") or "").startswith("https://")
    })
    briefs = []
    for dimension in DIMENSIONS:
        section = by_id[dimension]
        draft = str(section.get("draft_text") or "").strip()
        notes = section.get("evidence_notes")
        cited_titles = section.get("source_titles")
        if not draft or not isinstance(notes, list) or not notes:
            raise GeminiError(f"{profile.get('name')}/{dimension}: hiányzó szöveg vagy bizonyítéki megjegyzés.")
        _validate_long_form_commentary(draft, profile.get("name"), dimension)
        if not isinstance(cited_titles, list) or not cited_titles:
            raise GeminiError(f"{profile.get('name')}/{dimension}: nincs megadott történelmi forrás.")
        if any(title not in source_titles for title in cited_titles):
            raise GeminiError(f"{profile.get('name')}/{dimension}: a modell nem engedélyezett forrást nevezett meg.")
        urls = [
            item["url"] for item in allowed_sources
            if item.get("title") in cited_titles and str(item.get("url", "")).startswith("https://")
        ]
        if not urls:
            raise GeminiError(f"{profile.get('name')}/{dimension}: a forráscímhez nincs érvényes URL.")
        briefs.append({
            "id": dimension,
            "label": {
                "interpretation": "Értelmezés",
                "consequences": "Következmények",
                "response": "Megoldás",
            }[dimension],
            "draft_text": draft,
            "evidence_notes": [str(note).strip() for note in notes if str(note).strip()],
            "source_urls": sorted(set(urls)),
            "news_source_urls": news_source_urls,
            "status": "automatically_validated",
        })
    if result.get("direct_quote_used") is True:
        raise GeminiError(f"{profile.get('name')}: tiltott szó szerinti idézet került a válaszba.")
    return {
        "figure_id": profile.get("id"),
        "figure_name": profile.get("name"),
        "event_id": event.get("event_id"),
        "event_title": event.get("representative_title") or event.get("title"),
        "historical_basis": {
            "core_ideas": profile.get("core_ideas", []),
            "works": allowed_sources,
            "profile_limitations": profile.get("limits"),
        },
        "sections": briefs,
        "mandatory_disclosures": {
            "hypothetical_reconstruction": True,
            "historical_disclosure": result.get("historical_disclosure") or (
                "A szöveg dokumentált történelmi nézetek alapján készült hipotetikus rekonstrukció."
            ),
            "direct_quote_used": False,
            "direct_quote_requires_exact_source_and_location": True,
            "historical_claims_require_citations": True,
            "present_day_facts_require_news_sources": True,
            "historical_source_verification_required": True,
            "anachronism_review_required": True,
        },
        "publication_status": "awaiting_automated_quality_gate",
    }


def build_gemini_commentary_package(event, selection, client):
    briefs = [
        simulate_historical_figure(event, figure, client)
        for figure in selection.get("figures", [])
    ]
    return {
        "engine": "AGORA_GEMINI_HISTORICAL_SIMULATOR_M1.0",
        "event_id": event.get("event_id"),
        "event_title": event.get("representative_title") or event.get("title"),
        "figure_count": len(briefs),
        "commentary_count": sum(len(item.get("sections", [])) for item in briefs),
        "briefs": briefs,
        "status": "awaiting_automated_quality_gate" if len(briefs) == 3 else "insufficient_relevant_figures",
        "publishing": False,
    }
