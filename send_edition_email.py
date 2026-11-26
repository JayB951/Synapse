"""Send the complete, verified WORLD SHARDS edition by email.

This script is read-only with respect to Supabase. It sends only today's
Budapest-local edition after confirming its published status and all 14
processed article records.
"""
import html
import logging
import os
import smtplib
from collections import Counter
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from supabase import create_client

TIMEZONE = ZoneInfo("Europe/Budapest")
EXPECTED_COUNTS = {
    "research_frontier": 5,
    "art_of_the_day": 1,
    "the_thinker": 1,
    "battlefield": 1,
    "fundamentals": 1,
    "world_explorer": 1,
    "unsolved": 1,
    "music_of_the_day": 1,
    "closing": 2,
}
EXPECTED_TOTAL = sum(EXPECTED_COUNTS.values())
SECTION_NAMES = {
    "research_frontier": "Kutatási határvidék",
    "art_of_the_day": "A nap műalkotása",
    "the_thinker": "A gondolkodó",
    "battlefield": "Csatatér",
    "fundamentals": "Alapok",
    "world_explorer": "Világjáró",
    "unsolved": "Megoldatlan rejtély",
    "music_of_the_day": "A nap zenéje",
    "closing": "Lezárás",
}
MAGAZINE_URL = "https://jayb951.github.io/Synapse/"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("world-shards-email")


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise RuntimeError("Hiányzó SUPABASE_URL vagy SUPABASE_SECRET_KEY.")
    return create_client(url, key)


def validate_edition(edition, items):
    if not edition or edition.get("status") != "published":
        raise RuntimeError("Az e-mail nem küldhető: a napi kiadás nem published státuszú.")
    if len(items) != EXPECTED_TOTAL:
        raise RuntimeError(f"Az e-mail nem küldhető: {len(items)}/{EXPECTED_TOTAL} elem található.")
    counts = Counter(item.get("section_code") for item in items)
    if dict(counts) != EXPECTED_COUNTS:
        raise RuntimeError(f"Az e-mail nem küldhető: hibás rovateloszlás: {dict(counts)}.")
    positions = [item.get("position") for item in items]
    if sorted(positions) != list(range(1, EXPECTED_TOTAL + 1)):
        raise RuntimeError("Az e-mail nem küldhető: a pozíciók nem folytonosak 1–14 között.")
    for item in items:
        if (
            item.get("processing_status") != "completed"
            or not item.get("display_title")
            or not item.get("display_summary")
            or not item.get("display_body")
        ):
            raise RuntimeError(
                f"Az e-mail nem küldhető: hiányos feldolgozás a(z) {item.get('position')}. elemnél."
            )


def safe_source_url(value):
    if not value:
        return None
    parsed = urlparse(str(value))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return str(value)


def get_image_details(source):
    """Return a safe externally hosted image URL and a useful alt description."""
    metadata = source.get("metadata") or {}
    candidates = [
        source.get("image_url"),
        metadata.get("image_url"),
        metadata.get("artwork_url"),
    ]
    image_url = next(
        (safe_source_url(value) for value in candidates if safe_source_url(value)),
        None,
    )
    alt_text = (
        metadata.get("alt_text")
        or metadata.get("alt")
        or metadata.get("comic_title")
        or source.get("source_name")
        or "A cikkhez tartozó kép"
    )
    return image_url, str(alt_text)


def build_email_bodies(edition, items, source_by_id):
    date_label = datetime.strptime(edition["edition_date"], "%Y-%m-%d").strftime("%Y. %m. %d.")
    plain = [
        f"WORLD SHARDS – {date_label}",
        edition.get("introduction") or "A napi WORLD SHARDS teljes kiadása.",
        "",
        f"A kiadás mind a {EXPECTED_TOTAL} eleme, rovatonként rendezve:",
        "",
    ]
    html_sections = []
    current_section = None

    for item in sorted(items, key=lambda row: row["position"]):
        section_code = item["section_code"]
        if section_code != current_section:
            current_section = section_code
            section_title = SECTION_NAMES.get(section_code, section_code)
            plain.extend(["", "=" * 58, section_title.upper(), "=" * 58, ""])
            html_sections.append(
                f'<h2 style="margin:30px 0 14px;padding-bottom:8px;'
                f'border-bottom:2px solid #c8a96a;color:#243044;">{html.escape(section_title)}</h2>'
            )

        title = item["display_title"]
        summary = item["display_summary"]
        body = item["display_body"]
        source = source_by_id.get(item.get("content_item_id"), {})
        source_name = source.get("source_name") or ""
        source_url = safe_source_url(source.get("source_url"))
        image_url, image_alt = get_image_details(source)

        plain.extend([title, "-" * min(len(title), 50), summary, ""])
        if image_url:
            plain.extend([f"Kép: {image_url}", ""])
        plain.extend([body, ""])
        if source_name or source_url:
            source_line = "Forrás: " + source_name
            if source_url:
                source_line += (" – " if source_name else "") + source_url
            plain.extend([source_line, ""])

        body_paragraphs = "".join(
            f'<p style="margin:0 0 14px;line-height:1.65;white-space:pre-line;">{html.escape(part)}</p>'
            for part in body.split("\n\n") if part.strip()
        )
        source_html = ""
        if source_name or source_url:
            source_html = '<p style="font-size:12px;color:#666;margin-top:12px;">Forrás: '
            if source_url:
                source_html += f'<a href="{html.escape(source_url, quote=True)}">{html.escape(source_name or source_url)}</a>'
            else:
                source_html += html.escape(source_name)
            source_html += "</p>"

        image_html = ""
        if image_url:
            image_html = (
                '<div style="margin:14px 0 18px;text-align:center;">'
                f'<img src="{html.escape(image_url, quote=True)}" '
                f'alt="{html.escape(image_alt, quote=True)}" '
                'style="display:block;width:100%;max-width:680px;height:auto;'
                'margin:0 auto;border-radius:6px;" />'
                '</div>'
            )

        html_sections.append(
            '<article style="margin:0 0 26px;padding:0 0 18px;border-bottom:1px solid #e6e1d8;">'
            f'<h3 style="margin:0 0 8px;color:#182538;font-size:19px;">{html.escape(title)}</h3>'
            f'<p style="margin:0 0 14px;color:#555;font-style:italic;line-height:1.5;">{html.escape(summary)}</p>'
            f'{image_html}{body_paragraphs}{source_html}</article>'
        )

    plain.extend([
        "",
        "-" * 58,
        "A teljes online magazin:",
        MAGAZINE_URL,
        "",
        "Automatikus levél – a kiadás sikeres publikálása után küldve.",
    ])
    html_body = f"""<!doctype html>
<html lang="hu"><head><meta charset="utf-8"></head>
<body style="margin:0;background:#f4f2ed;font-family:Arial,Helvetica,sans-serif;color:#273142;">
<div style="max-width:760px;margin:0 auto;padding:28px 20px;background:#ffffff;">
<header style="padding:10px 0 24px;border-bottom:4px solid #c8a96a;">
<div style="font-size:12px;letter-spacing:3px;color:#8a744d;">NAPI DIGITÁLIS MAGAZIN</div>
<h1 style="margin:8px 0;color:#182538;font-family:Georgia,serif;">WORLD SHARDS</h1>
<p style="margin:0;color:#666;">{html.escape(date_label)} · A teljes napi kiadás</p>
</header>
<p style="line-height:1.6;">{html.escape(edition.get("introduction") or "A világ legérdekesebb felfedezései egyetlen kiadásban.")}</p>
<p style="color:#666;font-size:13px;">{EXPECTED_TOTAL} szerkesztett tartalom · 9 rovat</p>
{''.join(html_sections)}
<footer style="margin-top:30px;padding-top:18px;border-top:2px solid #c8a96a;">
<a href="{MAGAZINE_URL}" style="color:#6e572b;">WORLD SHARDS – online magazin</a>
<p style="font-size:11px;color:#777;">Automatikus levél, sikeres publikálás után küldve.</p>
</footer></div></body></html>"""
    return "\n".join(plain), html_body, date_label


def load_published_edition(supabase):
    edition_date = datetime.now(TIMEZONE).date().isoformat()
    edition_response = (
        supabase.table("shard_editions")
        .select("id,edition_date,title,introduction,status")
        .eq("edition_date", edition_date)
        .eq("status", "published")
        .limit(1)
        .execute()
    )
    if not edition_response.data:
        raise RuntimeError(f"Nincs ma ({edition_date}) published kiadás; e-mail nem küldhető.")
    edition = edition_response.data[0]

    items_response = (
        supabase.table("shard_edition_items")
        .select(
            "id,content_item_id,section_code,position,processing_status,"
            "display_title,display_summary,display_body"
        )
        .eq("edition_id", edition["id"])
        .order("position")
        .execute()
    )
    items = items_response.data or []
    validate_edition(edition, items)

    content_ids = list(dict.fromkeys(item["content_item_id"] for item in items if item.get("content_item_id")))
    source_by_id = {}
    if content_ids:
        source_response = (
            supabase.table("shard_content_items")
            .select("id,source_name,source_url,image_url,metadata")
            .in_("id", content_ids)
            .execute()
        )
        source_by_id = {row["id"]: row for row in (source_response.data or [])}

    return edition, items, source_by_id


def send_email(plain_body, html_body, date_label):
    sender = os.getenv("MAIL_USERNAME")
    password = os.getenv("MAIL_PASSWORD")
    recipient = os.getenv("NOTIFY_EMAIL")
    if not sender or not password or not recipient:
        logger.warning(
            "E-mail kihagyva: a MAIL_USERNAME, MAIL_PASSWORD vagy WORLD_SHARDS_NOTIFY_EMAIL secret hiányzik."
        )
        return False

    message = EmailMessage()
    message["Subject"] = f"WORLD SHARDS – teljes napi kiadás ({date_label})"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(plain_body)
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message)

    logger.info("A teljes napi kiadás e-mailben elküldve: %s", recipient)
    return True


def main():
    supabase = get_supabase_client()
    edition, items, source_by_id = load_published_edition(supabase)
    plain_body, html_body, date_label = build_email_bodies(edition, items, source_by_id)
    logger.info("E-mail tartalma ellenőrizve: %s elem, %s rovat.", len(items), len(EXPECTED_COUNTS))
    send_email(plain_body, html_body, date_label)


if __name__ == "__main__":
    main()
