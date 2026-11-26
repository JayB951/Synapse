"""Send the complete, verified WORLD SHARDS edition by email.

This script is read-only with respect to Supabase. It sends only today's
Budapest-local edition after confirming its published status and all 16
processed content records, including both AGORA sections.
"""
import base64
import hashlib
import hmac
import html
import logging
import os
import uuid
import smtplib
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

from supabase import create_client

TIMEZONE = ZoneInfo("Europe/Budapest")
EXPECTED_COUNTS = {
    "research_frontier": 7,
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


def build_rating_links(items, supabase_url, signing_secret, voter_token, now=None):
    """Create signed, expiring links; opening a link never writes a rating."""
    if not supabase_url or not signing_secret or len(signing_secret) < 32:
        raise ValueError("Érvénytelen értékelési URL vagy túl rövid aláírókulcs.")
    voter_token = str(uuid.UUID(voter_token))
    now = now or datetime.now(timezone.utc)
    expires = int((now + timedelta(days=30)).timestamp())
    endpoint = supabase_url.rstrip("/") + "/functions/v1/email-rating"
    links = {}
    for item in items:
        item_id = str(uuid.UUID(item["id"]))
        item_links = {}
        for rating in range(1, 6):
            message = f"{item_id}|{rating}|{voter_token}|{expires}".encode("utf-8")
            signature = base64.urlsafe_b64encode(
                hmac.new(signing_secret.encode("utf-8"), message, hashlib.sha256).digest()
            ).decode("ascii").rstrip("=")
            query = urlencode({
                "item_id": item_id,
                "rating": rating,
                "voter_token": voter_token,
                "exp": expires,
                "sig": signature,
            })
            item_links[rating] = f"{endpoint}?{query}"
        links[item_id] = item_links
    return links


def build_email_bodies(edition, items, source_by_id, rating_links_by_item=None):
    date_label = datetime.strptime(edition["edition_date"], "%Y-%m-%d").strftime("%Y. %m. %d.")
    plain = [
        f"WORLD SHARDS – {date_label}",
        edition.get("introduction") or "A napi WORLD SHARDS teljes kiadása.",
        "",
        f"A kiadás mind a {EXPECTED_TOTAL} tartalma, rovatonként rendezve:",
        "",
    ]
    html_sections = []
    current_section = None

    for item in sorted(items, key=lambda row: row["position"]):
        section_code = item["section_code"]
        section_title = SECTION_NAMES.get(section_code, section_code)
        if section_code == "research_frontier":
            editor_note = item.get("editor_note")
            if editor_note == "MAGYAR AGORA":
                section_title = "Magyar AGORA"
            elif editor_note == "WORLD AGORA":
                section_title = "WORLD AGORA"
        if section_title != current_section:
            current_section = section_title
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

        rating_html = ""
        rating_links = (rating_links_by_item or {}).get(item.get("id"), {})
        if rating_links:
            stars = " ".join(
                f'<a href="{html.escape(rating_links[score], quote=True)}" '
                f'style="color:#b18a42;text-decoration:none;font-size:23px;letter-spacing:2px;" '
                f'aria-label="{score} csillag">★</a>'
                for score in range(1, 6)
            )
            rating_html = (
                '<div style="margin-top:18px;padding:12px 14px;background:#f7f5f0;'
                'border-left:3px solid #c8a96a;">'
                '<div style="font-size:12px;color:#555;margin-bottom:5px;">Értékeld ezt a cikket:</div>'
                f'<div>{stars}</div>'
                '<div style="font-size:10px;color:#777;margin-top:4px;">'
                'A választás a megnyíló oldalon külön megerősítést igényel.</div></div>'
            )
            plain.extend(["Értékeld a cikket (a link megnyitása után erősítsd meg):"])
            plain.extend([f"{score} csillag: {rating_links[score]}" for score in range(1, 6)])
            plain.append("")

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
            f'{image_html}{body_paragraphs}{source_html}{rating_html}</article>'
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
<p style="color:#666;font-size:13px;">{EXPECTED_TOTAL} szerkesztett tartalom, köztük a Magyar és a nemzetközi AGORA</p>
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
            "id,content_item_id,section_code,position,editor_note,processing_status,"
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
        raise RuntimeError(
            "E-mail nem küldhető: hiányzik a MAIL_USERNAME, MAIL_PASSWORD vagy WORLD_SHARDS_NOTIFY_EMAIL secret."
        )

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
    rating_links = None
    rating_secret = os.getenv("EMAIL_RATING_SECRET")
    rating_voter_token = os.getenv("EMAIL_RATING_VOTER_TOKEN")
    if rating_secret and rating_voter_token:
        rating_links = build_rating_links(
            items,
            os.getenv("SUPABASE_URL", ""),
            rating_secret,
            rating_voter_token,
        )
        logger.info("Az e-mailhez 1–5 csillagos értékelési linkek készültek.")
    else:
        logger.warning("Az e-mail csillagos értékelés nélkül készül: hiányzik az EMAIL_RATING_SECRET vagy EMAIL_RATING_VOTER_TOKEN.")
    plain_body, html_body, date_label = build_email_bodies(
        edition, items, source_by_id, rating_links
    )
    logger.info("E-mail tartalma ellenőrizve: %s elem, benne mindkét AGORA-rovat.", len(items))
    if not send_email(plain_body, html_body, date_label):
        raise RuntimeError("Az SMTP-küldés nem igazolható; a napi workflow hibával álljon le.")


if __name__ == "__main__":
    main()
