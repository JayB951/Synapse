
import os
import re
import json
import time
import html
import logging
import requests

from datetime import datetime, timezone
from supabase import create_client


# ============================================================
# WORLD SHARDS - EDITION PROCESSOR
# Version: 0.3.0
# ============================================================

VERSION = "0.3.0"

MODEL_NAME = "gemini-3.5-flash-lite"

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL_NAME}:generateContent"
)

REQUEST_TIMEOUT = 60
REQUEST_DELAY = 2

MAX_OUTPUT_TOKENS = 1600
MAX_SOURCE_LENGTH = 12000

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger("world_shards_processor")


# ============================================================
# SUPABASE
# ============================================================

def get_supabase_client():
    if not SUPABASE_URL:
        raise RuntimeError("Hiányzó SUPABASE_URL környezeti változó.")

    if not SUPABASE_SECRET_KEY:
        raise RuntimeError(
            "Hiányzó SUPABASE_SECRET_KEY környezeti változó."
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_SECRET_KEY
    )


# ============================================================
# GEMINI API
# ============================================================

def call_gemini(prompt):
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Hiányzó GEMINI_API_KEY környezeti változó."
        )

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json"
        }
    }

    response = requests.post(
        GEMINI_URL,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code == 404:
        raise RuntimeError(
            f"A Gemini modell nem található vagy nem érhető el: "
            f"{MODEL_NAME}. API válasz: {response.text[:1000]}"
        )

    if response.status_code == 429:
        raise RuntimeError(
            "Gemini API kvótakorlát vagy túl sok kérés. "
            f"API válasz: {response.text[:1000]}"
        )

    if response.status_code in (401, 403):
        raise RuntimeError(
            "Gemini API hitelesítési hiba. "
            "Ellenőrizd a GEMINI_API_KEY GitHub Secret értékét."
        )

    if response.status_code >= 400:
        raise RuntimeError(
            f"Gemini API hiba ({response.status_code}): "
            f"{response.text[:1500]}"
        )

    try:
        result = response.json()

        candidates = result.get("candidates", [])

        if not candidates:
            raise RuntimeError(
                "A Gemini API nem adott vissza feldolgozható választ."
            )

        parts = candidates[0].get("content", {}).get("parts", [])

        generated_text = "\n".join(
            part.get("text", "")
            for part in parts
            if part.get("text")
        ).strip()

        if not generated_text:
            raise RuntimeError(
                "A Gemini API üres szöveges választ adott."
            )

        return generated_text

    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError(
            f"A Gemini API válaszának feldolgozása sikertelen: {error}"
        )


# ============================================================
# TEXT CLEANING
# ============================================================

def clean_source_text(value):
    if value is None:
        return ""

    text = str(value)
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def clean_display_text(value):
    if value is None:
        return ""

    text = str(value)
    text = html.unescape(text)

    text = re.sub(
        r"<br\s*/?>",
        "\n",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"</p\s*>",
        "\n\n",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"<[^>]+>",
        "",
        text
    )

    text = re.sub(
        r"[ \t]+\n",
        "\n",
        text
    )

    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


# ============================================================
# SECTION STYLES
# ============================================================

SECTION_STYLES = {

    "research_frontier": {
        "name": "Research Frontier",
        "description": (
            "Tudományos publikáció bemutatása. "
            "Magyarázd el a kutatási kérdést, a módszert, "
            "az eredményeket és azok jelentőségét. "
            "A tudományos pontosság elsődleges."
        )
    },

    "art_of_the_day": {
        "name": "Art of the Day",
        "description": (
            "Művészeti alkotás bemutatása. "
            "Mutasd be az alkotót, a mű keletkezését, "
            "a technikát és az alkotás művészeti jelentőségét. "
            "Legyen érdekes, közérthető és vizuálisan elképzelhető."
        )
    },

    "the_thinker": {
        "name": "The Thinker",
        "description": (
            "Filozófiai vagy gondolkodástörténeti téma. "
            "Mutasd be az alapgondolatot, annak hátterét, "
            "és azt, hogy miért érdekes ma is. "
            "A szöveg gondolatébresztő legyen."
        )
    },

    "battlefield": {
        "name": "Battlefield",
        "description": (
            "Hadtörténelmi vagy katonai téma. "
            "Mutasd be a történelmi hátteret, a szereplőket, "
            "a stratégiai helyzetet, a történéseket "
            "és azok következményeit. "
            "A katonai és történelmi pontosság fontos."
        )
    },

    "fundamentals": {
        "name": "Fundamentals",
        "description": (
            "Egy fontos alapfogalom vagy jelenség magyarázata. "
            "Indulj az egyszerű definícióból, majd fokozatosan "
            "mutasd be a működését és a jelentőségét. "
            "Legyen közérthető, de ne felszínes."
        )
    },

    "world_explorer": {
        "name": "World Explorer",
        "description": (
            "Különleges földrajzi hely, természeti csoda "
            "vagy érdekes helyszín bemutatása. "
            "Mutasd be az elhelyezkedést, a természeti "
            "vagy földrajzi sajátosságokat és a különlegességét."
        )
    },

    "unsolved": {
        "name": "Unsolved",
        "description": (
            "Megoldatlan rejtély vagy nyitott kérdés bemutatása. "
            "Válaszd külön a bizonyított tényeket, "
            "az elméleteket és a spekulációkat. "
            "Ne állítsd bizonyított tényként azt, ami nem az."
        )
    },

    "closing": {
        "name": "Closing",
        "description": (
            "A kiadvány könnyed, humoros záró rovata. "
            "Őrizd meg az eredeti vicc vagy képregény lényegét, "
            "és készíts hozzá természetes magyar szöveget. "
            "Ne találj ki új poént, ha az eredeti tartalom "
            "fordítása a feladat."
        )
    }
}


# ============================================================
# SOURCE DATA
# ============================================================

def get_source_content(supabase, content_item_id):

    response = (
        supabase
        .table("shard_content_items")
        .select(
            "id,section_code,title,summary,body,"
            "source_name,source_url,source_language,metadata"
        )
        .eq("id", content_item_id)
        .limit(1)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            f"A forrástartalom nem található: {content_item_id}"
        )

    return response.data[0]


def build_source_text(source):

    parts = []

    fields = [
        ("Eredeti cím", source.get("title")),
        ("Eredeti összefoglaló", source.get("summary")),
        ("Eredeti tartalom", source.get("body")),
        ("Forrás neve", source.get("source_name")),
        ("Forrás nyelve", source.get("source_language"))
    ]

    for label, value in fields:
        cleaned = clean_source_text(value)

        if cleaned:
            parts.append(f"{label}: {cleaned}")

    metadata = source.get("metadata") or {}

    metadata_fields = [
        "artist",
        "date",
        "medium",
        "description",
        "alt",
        "transcript",
        "category",
        "type",
        "setup",
        "delivery"
    ]

    for key in metadata_fields:
        value = metadata.get(key)

        if value:
            cleaned = clean_source_text(value)

            if cleaned:
                parts.append(f"{key}: {cleaned}")

    source_text = "\n\n".join(parts)

    if len(source_text) > MAX_SOURCE_LENGTH:
        source_text = source_text[:MAX_SOURCE_LENGTH]

    if not source_text.strip():
        raise RuntimeError(
            "A forrástartalom üres, nincs feldolgozható szöveg."
        )

    return source_text


# ============================================================
# PROMPT GENERATION
# ============================================================

def build_prompt(section_code, source):

    section = SECTION_STYLES.get(
        section_code,
        {
            "name": section_code,
            "description": (
                "Készíts informatív, közérthető magazincikket."
            )
        }
    )

    source_text = build_source_text(source)

    original_title = clean_source_text(
        source.get("title")
    )

    source_url = source.get("source_url") or ""

    prompt = f"""
Te a WORLD SHARDS nevű magyar nyelvű digitális magazin
szerkesztője vagy.

FELADAT:

A megadott angol nyelvű forrástartalomból készíts
igényes, természetes magyar nyelvű magazintartalmat.

ROVAT:
{section["name"]}

ROVAT SZERKESZTÉSI IRÁNYELVE:
{section["description"]}

EREDETI CÍM:
{original_title}

FORRÁSLINK:
{source_url}

FORRÁSTARTALOM:
{source_text}

KÖTELEZŐ SZABÁLYOK:

1. A teljes szöveg magyar nyelvű legyen.
2. Ne készíts szó szerinti, gépies fordítást.
3. Természetes, gördülékeny, igényes magyar prózát használj.
4. A tényeket, neveket, számokat és összefüggéseket őrizd meg.
5. Ne találj ki olyan adatot, amely nem szerepel a forrásban.
6. Ha a forrás valamiben bizonytalan, ezt a magyar szövegben
   is jelezd.
7. Ne hivatkozz olyan kutatásra, személyre vagy eseményre,
   amely nem szerepel a forrásban.
8. Kerüld a felesleges bevezető mondatokat és az üres
   általánosságokat.
9. Ne említsd, hogy mesterséges intelligencia készítette
   a szöveget.
10. Ne használj angol alcímeket.
11. A forrás tartalmát ne bővítsd kitalált információkkal.

KIMENET:

Kizárólag érvényes JSON objektumot adj vissza,
az alábbi három mezővel:

{{
  "title": "Magyar cím",
  "summary": "Rövid, 2-3 mondatos magyar összefoglaló.",
  "body": "A teljes magyar magazinszöveg."
}}

A body mezőben 3-5 értelmes bekezdést írj.
A szöveg hossza igazodjon a forrás tartalmához.
Ne használj Markdown kódblokkot a JSON körül.
"""

    return prompt


# ============================================================
# RESPONSE PARSING
# ============================================================

def parse_generated_content(generated_text):

    text = generated_text.strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```$",
        "",
        text
    )

    try:
        data = json.loads(text)

    except json.JSONDecodeError:

        start = text.find("{")
        end = text.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise RuntimeError(
                "A Gemini válasza nem tartalmaz érvényes JSON objektumot."
            )

        try:
            data = json.loads(
                text[start:end + 1]
            )

        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"A Gemini JSON válasza hibás: {error}"
            )

    if not isinstance(data, dict):
        raise RuntimeError(
            "A Gemini válasza nem JSON objektum."
        )

    required_fields = [
        "title",
        "summary",
        "body"
    ]

    for field in required_fields:

        if field not in data:
            raise RuntimeError(
                f"Hiányzó mező a Gemini válaszában: {field}"
            )

        if not isinstance(data[field], str):
            raise RuntimeError(
                f"Hibás adattípus a Gemini válaszában: {field}"
            )

        data[field] = clean_display_text(
            data[field]
        )

        if not data[field]:
            raise RuntimeError(
                f"Üres mező a Gemini válaszában: {field}"
            )

    return data


# ============================================================
# DATABASE UPDATE
# ============================================================

def save_processed_content(
    supabase,
    item_id,
    generated_content
):

    update_data = {
        "display_title": generated_content["title"],
        "display_summary": generated_content["summary"],
        "display_body": generated_content["body"],
        "processing_status": "completed",
        "processed_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "model_name": MODEL_NAME
    }

    response = (
        supabase
        .table("shard_edition_items")
        .update(update_data)
        .eq("id", item_id)
        .execute()
    )

    if response.data is not None and len(response.data) == 0:
        raise RuntimeError(
            f"A feldolgozott tartalom mentése nem sikerült: {item_id}"
        )


def mark_processing_failed(
    supabase,
    item_id
):

    update_data = {
        "processing_status": "failed",
        "processed_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "model_name": MODEL_NAME
    }

    (
        supabase
        .table("shard_edition_items")
        .update(update_data)
        .eq("id", item_id)
        .execute()
    )


# ============================================================
# EDITION RETRIEVAL
# ============================================================

def get_latest_draft_edition(supabase):

    response = (
        supabase
        .table("shard_editions")
        .select(
            "id,edition_date,title,status"
        )
        .eq("status", "draft")
        .order(
            "edition_date",
            desc=True
        )
        .limit(1)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "Nem található feldolgozható draft kiadvány."
        )

    return response.data[0]


def get_pending_items(
    supabase,
    edition_id
):

    response = (
        supabase
        .table("shard_edition_items")
        .select(
            "id,edition_id,content_item_id,"
            "section_code,position,processing_status"
        )
        .eq("edition_id", edition_id)
        .in_(
            "processing_status",
            ["pending", "failed"]
        )
        .order(
            "position",
            desc=False
        )
        .execute()
    )

    return response.data or []


# ============================================================
# ITEM PROCESSING
# ============================================================

def process_item(
    supabase,
    item
):

    item_id = item["id"]
    content_item_id = item["content_item_id"]
    section_code = item["section_code"]

    source = get_source_content(
        supabase,
        content_item_id
    )

    prompt = build_prompt(
        section_code,
        source
    )

    generated_text = call_gemini(
        prompt
    )

    generated_content = parse_generated_content(
        generated_text
    )

    save_processed_content(
        supabase,
        item_id,
        generated_content
    )


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        f"WORLD SHARDS Edition Processor v{VERSION} indul."
    )

    logger.info(
        f"Használt modell: {MODEL_NAME}"
    )

    supabase = get_supabase_client()

    edition = get_latest_draft_edition(
        supabase
    )

    edition_id = edition["id"]

    logger.info(
        "Feldolgozandó kiadvány: "
        f"{edition.get('title')} / "
        f"{edition.get('edition_date')}"
    )

    items = get_pending_items(
        supabase,
        edition_id
    )

    logger.info(
        f"{len(items)} tartalom vár feldolgozásra."
    )

    if not items:
        logger.info(
            "Nincs feldolgozásra váró tartalom."
        )
        return

    successful = 0
    failed = 0
    quota_limited = False

    for item in items:

        section_code = item["section_code"]
        position = item["position"]
        item_id = item["id"]

        logger.info(
            f"Feldolgozás: {section_code} / "
            f"pozíció: {position}"
        )

        try:

            process_item(
                supabase,
                item
            )

            successful += 1

            logger.info(
                f"Sikeres feldolgozás: {section_code} "
                f"/ pozíció: {position}"
            )

        except Exception as error:

            failed += 1

            logger.exception(
                f"Feldolgozási hiba a(z) "
                f"{position}. elemnél."
            )

            try:

                mark_processing_failed(
                    supabase,
                    item_id
                )

            except Exception:

                logger.exception(
                    "A hibás feldolgozás státuszának "
                    "mentése sem sikerült."
                )

            if "kvótakorlát" in str(error).lower():
                quota_limited = True

                logger.warning(
                    "Gemini kvótakorlát miatt a további "
                    "feldolgozást leállítjuk."
                )

                break

        if successful + failed < len(items):
            time.sleep(REQUEST_DELAY)

    logger.info(
        "========================================"
    )

    logger.info(
        "FELDOLGOZÁS BEFEJEZVE"
    )

    logger.info(
        f"Sikeres: {successful}"
    )

    logger.info(
        f"Hibás: {failed}"
    )

    logger.info(
        f"Kvótakorlát: {quota_limited}"
    )

    logger.info(
        f"Modell: {MODEL_NAME}"
    )

    logger.info(
        "========================================"
    )

    if failed > 0:

        raise RuntimeError(
            "A feldolgozás részleges vagy hibás. "
            "A sikeres elemek mentve maradtak."
        )


if __name__ == "__main__":

    try:
        main()

    except Exception:

        logger.exception(
            "A WORLD SHARDS tartalomfeldolgozás sikertelen."
        )

        raise
