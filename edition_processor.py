
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
# Version: 0.4.1
# ============================================================

VERSION = "0.4.1"

MODEL_NAME = "gemini-3.5-flash-lite"

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL_NAME}:generateContent"
)

REQUEST_TIMEOUT = 60

MAX_PROCESSING_MINUTES = 60
ROUND_WAIT_SECONDS = 60

JSON_RETRY_LIMIT = 2

RETRY_DELAYS = {
    429: 180,
    500: 60,
    502: 60,
    503: 90,
    504: 60
}

MAX_OUTPUT_TOKENS = 4096
MAX_SOURCE_LENGTH = 12000

EXPECTED_ITEMS = 13

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
        raise RuntimeError("Hiányzó SUPABASE_URL.")

    if not SUPABASE_SECRET_KEY:
        raise RuntimeError("Hiányzó SUPABASE_SECRET_KEY.")

    return create_client(
        SUPABASE_URL,
        SUPABASE_SECRET_KEY
    )


# ============================================================
# TIME MANAGEMENT
# ============================================================

def remaining_time(deadline):

    return max(
        0,
        deadline - time.monotonic()
    )


def wait_with_deadline(seconds, deadline):

    available = remaining_time(deadline)

    if available <= 0:
        return False

    wait_time = min(
        seconds,
        available
    )

    logger.info(
        f"Várakozás: {int(wait_time)} másodperc."
    )

    time.sleep(wait_time)

    return remaining_time(deadline) > 0


# ============================================================
# GEMINI API
# ============================================================

def call_gemini(prompt):

    if not GEMINI_API_KEY:
        raise RuntimeError("Hiányzó GEMINI_API_KEY.")

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY
    }

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "title": {
                        "type": "STRING"
                    },
                    "summary": {
                        "type": "STRING"
                    },
                    "body": {
                        "type": "STRING"
                    }
                },
                "required": [
                    "title",
                    "summary",
                    "body"
                ],
                "propertyOrdering": [
                    "title",
                    "summary",
                    "body"
                ]
            }
        }
    }

    try:

        response = requests.post(
            GEMINI_URL,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

    except requests.RequestException as error:

        raise RuntimeError(
            f"Gemini hálózati hiba: {error}"
        )

    if response.status_code == 404:

        raise RuntimeError(
            f"A Gemini modell nem található: {MODEL_NAME}. "
            f"Válasz: {response.text[:1000]}"
        )

    if response.status_code == 429:

        raise RuntimeError(
            "Gemini API 429: kvótakorlát vagy túl sok kérés."
        )

    if response.status_code in RETRY_DELAYS:

        raise RuntimeError(
            f"Gemini API {response.status_code}: "
            f"{response.text[:1000]}"
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

        candidates = result.get(
            "candidates",
            []
        )

        if not candidates:

            raise RuntimeError(
                "A Gemini API nem adott vissza feldolgozható választ."
            )

        candidate = candidates[0]

        finish_reason = candidate.get("finishReason")

        if finish_reason == "MAX_TOKENS":

            raise RuntimeError(
                "A Gemini válasza elérte a kimeneti tokenkorlátot."
            )

        parts = (
            candidate
            .get("content", {})
            .get("parts", [])
        )

        generated_text = "\n".join(
            part.get("text", "")
            for part in parts
            if part.get("text")
        ).strip()

        if not generated_text:

            raise RuntimeError(
                "A Gemini API üres választ adott."
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

    text = html.unescape(str(value))

    text = re.sub(
        r"<[^>]+>",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def clean_display_text(value):

    if value is None:
        return ""

    text = html.unescape(str(value))

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
            "Legyen érdekes és közérthető."
        )
    },

    "the_thinker": {
        "name": "The Thinker",
        "description": (
            "Filozófiai vagy gondolkodástörténeti téma. "
            "Mutasd be az alapgondolatot, annak hátterét, "
            "és azt, hogy miért érdekes ma is. "
            "A szöveg legyen gondolatébresztő."
        )
    },

    "battlefield": {
        "name": "Battlefield",
        "description": (
            "Hadtörténelmi vagy katonai téma. "
            "Mutasd be a történelmi hátteret, a szereplőket, "
            "a stratégiai helyzetet, a történéseket "
            "és azok következményeit. "
            "A történelmi pontosság fontos."
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

def get_source_content(
    supabase,
    content_item_id
):

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

            parts.append(
                f"{label}: {cleaned}"
            )

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

                parts.append(
                    f"{key}: {cleaned}"
                )

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

def build_prompt(
    section_code,
    source
):

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

    return f"""
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

Kizárólag a kért JSON-struktúrát add vissza:

{{
  "title": "Magyar cím",
  "summary": "Rövid, 2-3 mondatos magyar összefoglaló.",
  "body": "A teljes magyar magazinszöveg."
}}

A body mezőben 3-5 értelmes bekezdést írj.
A szöveg hossza igazodjon a forrás tartalmához.
Ne használj Markdown kódblokkot a JSON körül.
"""


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

    except json.JSONDecodeError as error:

        raise RuntimeError(
            "A Gemini JSON válasza hibás: "
            f"{error}. Válasz eleje: {text[:500]}"
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
# GENERATION WITH JSON RETRIES
# ============================================================

def generate_content_with_retries(
    section_code,
    source
):

    prompt = build_prompt(
        section_code,
        source
    )

    last_error = None

    for attempt in range(1, JSON_RETRY_LIMIT + 2):

        logger.info(
            f"Gemini generálás: {attempt}. próbálkozás."
        )

        generated_text = call_gemini(
            prompt
        )

        try:

            return parse_generated_content(
                generated_text
            )

        except RuntimeError as error:

            last_error = error

            logger.warning(
                f"Hibás Gemini-kimenet: {error}"
            )

            if attempt <= JSON_RETRY_LIMIT:

                prompt += """

FONTOS JAVÍTÁS:
Az előző válaszod nem volt érvényes JSON.
Most kizárólag érvényes JSON objektumot adj vissza,
a title, summary és body mezőkkel.
Ne írj semmilyen szöveget a JSON elé vagy mögé.
"""

    raise RuntimeError(
        f"A Gemini többszöri próbálkozás után sem adott "
        f"érvényes JSON-t: {last_error}"
    )


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

    (
        supabase
        .table("shard_edition_items")
        .update(update_data)
        .eq("id", item_id)
        .execute()
    )

    # Visszaellenőrzés: csak a ténylegesen mentett
    # rekord tekinthető completed állapotúnak.

    response = (
        supabase
        .table("shard_edition_items")
        .select(
            "processing_status,display_title,"
            "display_summary,display_body"
        )
        .eq("id", item_id)
        .limit(1)
        .execute()
    )

    if not response.data:

        raise RuntimeError(
            f"A mentett rekord nem található: {item_id}"
        )

    saved = response.data[0]

    if saved.get("processing_status") != "completed":

        raise RuntimeError(
            f"A rekord státusza nem completed: {item_id}"
        )

    for field in [
        "display_title",
        "display_summary",
        "display_body"
    ]:

        if not saved.get(field):

            raise RuntimeError(
                f"A mentett rekord mezője üres: {field}"
            )


def mark_processing_failed(
    supabase,
    item_id
):

    (
        supabase
        .table("shard_edition_items")
        .update({
            "processing_status": "failed",
            "processed_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "model_name": MODEL_NAME
        })
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


def get_all_edition_items(
    supabase,
    edition_id
):

    response = (
        supabase
        .table("shard_edition_items")
        .select(
            "id,edition_id,content_item_id,"
            "section_code,position,processing_status,"
            "display_title,display_summary,display_body"
        )
        .eq("edition_id", edition_id)
        .order(
            "position",
            desc=False
        )
        .execute()
    )

    return response.data or []


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
# COMPLETION VALIDATION
# ============================================================

def is_item_completed(item):

    return (
        item.get("processing_status") == "completed"
        and bool(item.get("display_title"))
        and bool(item.get("display_summary"))
        and bool(item.get("display_body"))
    )


def verify_edition_completion(
    supabase,
    edition_id
):

    items = get_all_edition_items(
        supabase,
        edition_id
    )

    total = len(items)

    completed = sum(
        1
        for item in items
        if is_item_completed(item)
    )

    logger.info(
        f"Kiadvány állapota: {completed}/{total} kész."
    )

    if total != EXPECTED_ITEMS:

        logger.warning(
            f"A kiadvány elemszáma {total}, "
            f"nem {EXPECTED_ITEMS}."
        )

        return False

    return completed == EXPECTED_ITEMS


# ============================================================
# ITEM PROCESSING
# ============================================================

def process_item(
    supabase,
    item
):

    item_id = item["id"]

    source = get_source_content(
        supabase,
        item["content_item_id"]
    )

    generated_content = generate_content_with_retries(
        item["section_code"],
        source
    )

    save_processed_content(
        supabase,
        item_id,
        generated_content
    )


# ============================================================
# PROCESSING LOOP
# ============================================================

def process_edition(
    supabase,
    edition
):

    edition_id = edition["id"]

    deadline = (
        time.monotonic()
        + MAX_PROCESSING_MINUTES * 60
    )

    round_number = 0

    logger.info(
        f"Feldolgozási időkeret: {MAX_PROCESSING_MINUTES} perc."
    )

    while remaining_time(deadline) > 0:

        round_number += 1

        logger.info(
            "========================================"
        )

        logger.info(
            f"FELDOLGOZÁSI KÖR: {round_number}"
        )

        all_items = get_all_edition_items(
            supabase,
            edition_id
        )

        total = len(all_items)

        completed = sum(
            1
            for item in all_items
            if is_item_completed(item)
        )

        logger.info(
            f"Jelenlegi állapot: {completed}/{total} kész."
        )

        if total != EXPECTED_ITEMS:

            raise RuntimeError(
                f"A kiadványban {total} elem található, "
                f"de {EXPECTED_ITEMS} szükséges. "
                "A feldolgozás nem indul el."
            )

        if completed == EXPECTED_ITEMS:

            logger.info(
                "Mind a 13 tartalom elkészült."
            )

            logger.info(
                "A kiadvány teljes. A státusz változatlanul draft marad."
            )

            return True

        pending_items = get_pending_items(
            supabase,
            edition_id
        )

        if not pending_items:

            logger.warning(
                "Nincs pending vagy failed rekord, "
                "de a kiadvány még nem teljes."
            )

        for item in pending_items:

            if remaining_time(deadline) <= 0:
                break

            item_id = item["id"]

            section_code = item["section_code"]

            position = item["position"]

            logger.info(
                f"Feldolgozás: {section_code} / "
                f"pozíció: {position}"
            )

            try:

                process_item(
                    supabase,
                    item
                )

                logger.info(
                    f"Sikeres feldolgozás: {section_code} "
                    f"/ pozíció: {position}"
                )

            except Exception as error:

                logger.exception(
                    f"Feldolgozási hiba a(z) "
                    f"{position}. elemnél: {error}"
                )

                try:

                    mark_processing_failed(
                        supabase,
                        item_id
                    )

                except Exception:

                    logger.exception(
                        "A failed státusz mentése sem sikerült."
                    )

                error_text = str(error)

                if "Gemini API 429" in error_text:

                    logger.warning(
                        "Gemini kvótakorlát. "
                        "Hosszabb várakozás következik."
                    )

                    if not wait_with_deadline(
                        RETRY_DELAYS[429],
                        deadline
                    ):
                        break

                    break

                if any(
                    f"Gemini API {status}" in error_text
                    for status in RETRY_DELAYS
                ):

                    logger.warning(
                        "Átmeneti Gemini API-hiba. "
                        "A következő körben újrapróbáljuk."
                    )

            if remaining_time(deadline) > 0:
                time.sleep(2)

        if verify_edition_completion(
            supabase,
            edition_id
        ):

            logger.info(
                "Mind a 13 tartalom elkészült."
            )

            logger.info(
                "A kiadvány teljes. A státusz változatlanul draft marad."
            )

            return True

        if remaining_time(deadline) <= 0:
            break

        logger.info(
            "A kiadvány még nem teljes. "
            "A következő körben csak a hiányzó elemeket próbáljuk."
        )

        if not wait_with_deadline(
            ROUND_WAIT_SECONDS,
            deadline
        ):
            break

    # ========================================================
    # TIME LIMIT REACHED
    # ========================================================

    final_items = get_all_edition_items(
        supabase,
        edition_id
    )

    final_completed = sum(
        1
        for item in final_items
        if is_item_completed(item)
    )

    logger.warning(
        "A 60 perces feldolgozási időkeret lejárt."
    )

    logger.warning(
        f"Végső állapot: {final_completed}/{len(final_items)} kész."
    )

    logger.warning(
        "A sikeresen feldolgozott rekordok mentve maradtak. "
        "A következő futtatás csak a hiányzó elemeket dolgozza fel."
    )

    return False


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

    logger.info(
        f"Maximális feldolgozási idő: "
        f"{MAX_PROCESSING_MINUTES} perc."
    )

    supabase = get_supabase_client()

    edition = get_latest_draft_edition(
        supabase
    )

    logger.info(
        "Feldolgozandó kiadvány: "
        f"{edition.get('title')} / "
        f"{edition.get('edition_date')}"
    )

    result = process_edition(
        supabase,
        edition
    )

    logger.info(
        "========================================"
    )

    if result:

        logger.info(
            "WORLD SHARDS KIADVÁNY TELJES."
        )

        logger.info(
            "Státusz: draft (változatlan)."
        )

        logger.info(
            "Mind a 13 tartalom sikeresen feldolgozva."
        )

        logger.info(
            "A kiadvány készen áll a következő feldolgozási lépésre."
        )

    else:

        logger.error(
            "A kiadvány nem készült el a megadott időkereten belül."
        )

        raise RuntimeError(
            "A 60 perces feldolgozási időkeret lejárt. "
            "A sikeres rekordok megmaradtak; "
            "a workflow újrafuttatásával folytatható."
        )

    logger.info(
        "========================================"
    )


if __name__ == "__main__":

    try:

        main()

    except Exception:

        logger.exception(
            "A WORLD SHARDS tartalomfeldolgozás sikertelen."
        )

        raise
