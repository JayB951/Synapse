
import os
import re
import json
import time
import logging
import requests

from datetime import datetime, timezone
from supabase import create_client


VERSION = "0.1.0"
MODEL_NAME = "gemini-3.5-flash-lite"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + MODEL_NAME
    + ":generateContent"
)

REQUEST_TIMEOUT = 60
MAX_SOURCE_LENGTH = 12000
REQUEST_DELAY = 2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("world-shards-processor")


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")

    if not url or not key:
        raise RuntimeError(
            "Hiányzó SUPABASE_URL vagy SUPABASE_SECRET_KEY."
        )

    return create_client(url, key)


def get_gemini_key():
    key = os.getenv("GEMINI_API_KEY")

    if not key:
        raise RuntimeError("Hiányzó GEMINI_API_KEY.")

    return key


def get_latest_draft(supabase):
    response = (
        supabase.table("shard_editions")
        .select("id,edition_date,title,status")
        .eq("status", "draft")
        .order("edition_date", desc=True)
        .limit(1)
        .execute()
    )

    if not response.data:
        raise RuntimeError("Nem található feldolgozható draft kiadvány.")

    return response.data[0]


def get_pending_items(supabase, edition_id):
    response = (
        supabase.table("shard_edition_items")
        .select(
            "id,edition_id,content_item_id,section_code,position,"
            "processing_status"
        )
        .eq("edition_id", edition_id)
        .eq("processing_status", "pending")
        .order("position")
        .execute()
    )

    return response.data or []


def get_source_content(supabase, content_item_id):
    response = (
        supabase.table("shard_content_items")
        .select(
            "id,section_code,title,summary,body,source_name,"
            "source_url,source_language,metadata"
        )
        .eq("id", content_item_id)
        .limit(1)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            f"Nem található forrástartalom: {content_item_id}"
        )

    return response.data[0]


def clean_source_text(value):
    if not value:
        return ""

    if not isinstance(value, str):
        value = str(value)

    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def build_source_text(item):
    parts = []

    fields = [
        ("Eredeti cím", item.get("title")),
        ("Eredeti összefoglaló", item.get("summary")),
        ("Eredeti szöveg", item.get("body")),
    ]

    metadata = item.get("metadata") or {}

    if isinstance(metadata, dict):
        for key in (
            "artist",
            "date",
            "medium",
            "description",
            "alt",
            "transcript",
            "category",
            "type",
            "setup",
            "delivery",
        ):
            value = metadata.get(key)

            if value:
                fields.append((key, value))

    for label, value in fields:
        cleaned = clean_source_text(value)

        if cleaned:
            parts.append(f"{label}: {cleaned}")

    source_text = "\n".join(parts)

    return source_text[:MAX_SOURCE_LENGTH]


def get_section_style(section_code):
    styles = {
        "research_frontier": (
            "Tudományos-ismeretterjesztő stílus. "
            "Magyarázd el a kutatás kérdését, módszerét és jelentőségét. "
            "Ne állíts többet annál, amit a forrás alátámaszt."
        ),
        "art_of_the_day": (
            "Művészeti magazinstílus. Mutasd be az alkotást, "
            "az alkotót, a technikát és a művészeti érdekességeket. "
            "Ne találj ki művészettörténeti tényeket."
        ),
        "the_thinker": (
            "Gondolatébresztő, filozófiai-ismeretterjesztő stílus. "
            "Mutasd be a gondolat lényegét és jelentőségét."
        ),
        "battlefield": (
            "Hadtörténeti magazinstílus. Ismertesd a történelmi "
            "környezetet, a szereplőket és az esemény jelentőségét."
        ),
        "fundamentals": (
            "Közérthető tudományos magyarázat. A fogalmat lépésről "
            "lépésre, pontosan és példákkal mutasd be."
        ),
        "world_explorer": (
            "Felfedező magazinstílus. Mutasd be a helyszínt, "
            "természeti vagy földrajzi sajátosságait és érdekességeit."
        ),
        "unsolved": (
            "Rejtélyeket bemutató dokumentarista stílus. "
            "Világosan különítsd el a bizonyított tényeket, "
            "a feltételezéseket és a megválaszolatlan kérdéseket."
        ),
        "closing": (
            "Könnyed, szellemes magazinstílus. Vicc esetén őrizd meg "
            "a poén eredeti jelentését. Képregénynél magyarázd el "
            "röviden a helyzetet, ha ez szükséges."
        ),
    }

    return styles.get(
        section_code,
        "Közérthető, érdekes magazinstílus."
    )


def build_prompt(item):
    section_code = item.get("section_code", "")
    source_text = build_source_text(item)

    style = get_section_style(section_code)

    return f"""
Te egy igényes magyar nyelvű digitális magazin szerkesztője vagy.

Feladatod az alábbi angol nyelvű forrásanyag magyar nyelvű
feldolgozása.

ROVAT: {section_code}

SZERKESZTÉSI STÍLUS:
{style}

KÖTELEZŐ SZABÁLYOK:
- Kizárólag magyarul írj.
- Ne találj ki tényeket, adatokat, neveket vagy idézeteket.
- Ne egészítsd ki a forrást ellenőrizetlen információkkal.
- Ha a forrás hiányos, maradj annál, ami biztosan tudható.
- A bizonytalanságot egyértelműen jelezd.
- Ne hivatkozz nem létező kutatásokra vagy forrásokra.
- Ne írj a feladatodról, csak a kész magazintartalmat add vissza.
- A részletes szöveg legyen informatív, de ne legyen szóismétlő.
- Az eredeti forrás állításait ne változtasd meg.

KIMENET:
Kizárólag érvényes JSON objektumot adj vissza, az alábbi mezőkkel:

{{
  "title": "Magyar cím",
  "summary": "2-3 mondatos magyar összefoglaló",
  "body": "Magyar nyelvű, részletes magazincikk"
}}

A részletes szöveg általában 3-5 rövid bekezdés legyen.
A viccek esetében ne magyarázd túl a poént.
A műalkotások esetében ne találj ki értelmezést tényként.

FORRÁSANYAG:
{source_text}
"""


def call_gemini(api_key, prompt):
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.35,
            "maxOutputTokens": 1400,
            "responseMimeType": "application/json",
        },
    }

    response = requests.post(
        GEMINI_URL,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code == 429:
        raise RuntimeError(
            "Gemini API kvótakorlát vagy túl sok kérés (429)."
        )

    if response.status_code in (401, 403):
        raise RuntimeError(
            "Gemini API hitelesítési vagy jogosultsági hiba."
        )

    response.raise_for_status()

    data = response.json()

    candidates = data.get("candidates") or []

    if not candidates:
        raise RuntimeError("A Gemini nem adott vissza szöveges választ.")

    parts = (
        candidates[0]
        .get("content", {})
        .get("parts", [])
    )

    generated_text = "".join(
        part.get("text", "")
        for part in parts
    ).strip()

    if not generated_text:
        raise RuntimeError("A Gemini válasza üres.")

    return generated_text


def parse_generated_content(generated_text):
    text = generated_text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"A Gemini válasza nem érvényes JSON: {error}"
        )

    title = clean_source_text(result.get("title"))
    summary = clean_source_text(result.get("summary"))
    body = clean_source_text(result.get("body"))

    if not title or not summary or not body:
        raise RuntimeError(
            "A Gemini válaszából hiányzik a cím, összefoglaló vagy szöveg."
        )

    return {
        "title": title,
        "summary": summary,
        "body": body,
    }


def update_processing_result(
    supabase,
    edition_item_id,
    result,
):
    (
        supabase.table("shard_edition_items")
        .update({
            "display_title": result["title"],
            "display_summary": result["summary"],
            "display_body": result["body"],
            "processing_status": "completed",
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "model_name": MODEL_NAME,
        })
        .eq("id", edition_item_id)
        .execute()
    )


def mark_processing_failed(supabase, edition_item_id):
    (
        supabase.table("shard_edition_items")
        .update({
            "processing_status": "failed",
        })
        .eq("id", edition_item_id)
        .execute()
    )


def process_item(supabase, api_key, edition_item):
    edition_item_id = edition_item["id"]
    content_item_id = edition_item["content_item_id"]
    section_code = edition_item["section_code"]

    logger.info(
        "Feldolgozás: %s / pozíció: %s",
        section_code,
        edition_item["position"],
    )

    source_item = get_source_content(
        supabase,
        content_item_id,
    )

    prompt = build_prompt(source_item)

    generated_text = call_gemini(
        api_key,
        prompt,
    )

    result = parse_generated_content(generated_text)

    update_processing_result(
        supabase,
        edition_item_id,
        result,
    )

    logger.info(
        "Sikeres feldolgozás: %s",
        result["title"],
    )


def main():
    logger.info(
        "WORLD SHARDS Edition Processor v%s indul.",
        VERSION,
    )

    supabase = get_supabase_client()
    api_key = get_gemini_key()

    edition = get_latest_draft(supabase)

    logger.info(
        "Feldolgozandó kiadvány: %s / %s",
        edition["title"],
        edition["edition_date"],
    )

    pending_items = get_pending_items(
        supabase,
        edition["id"],
    )

    if not pending_items:
        logger.info("Nincs feldolgozásra váró tartalom.")
        return

    logger.info(
        "%s tartalom vár feldolgozásra.",
        len(pending_items),
    )

    completed = 0
    failed = 0

    for index, edition_item in enumerate(pending_items):
        try:
            process_item(
                supabase,
                api_key,
                edition_item,
            )
            completed += 1

        except Exception as error:
            failed += 1

            logger.exception(
                "Feldolgozási hiba a(z) %s. elemnél: %s",
                edition_item.get("position"),
                error,
            )

            try:
                mark_processing_failed(
                    supabase,
                    edition_item["id"],
                )
            except Exception:
                logger.exception(
                    "A feldolgozási hiba státuszának mentése sikertelen."
                )

            if "kvótakorlát" in str(error).lower():
                logger.warning(
                    "A kvótakorlát miatt a további feldolgozás leáll."
                )
                break

        if index < len(pending_items) - 1:
            time.sleep(REQUEST_DELAY)

    logger.info("----------------------------------------")
    logger.info("FELDOLGOZÁS BEFEJEZVE")
    logger.info("Sikeres: %s", completed)
    logger.info("Hibás: %s", failed)
    logger.info("Modell: %s", MODEL_NAME)
    logger.info("----------------------------------------")

    if failed:
        raise RuntimeError(
            "A feldolgozás részleges vagy hibás. "
            "A sikeres elemek mentve maradtak."
        )


if __name__ == "__main__":
    main()
