"""
WORLD SHARDS – Music of the Day Collector
Version: M1.5.1 / 0.1.0

A napi kiadvány kiválasztott témáihoz keres kapcsolódó zeneművet
az ingyenes, API-kulcs nélküli iTunes Search API segítségével.

Nem tölt le és nem tárol hangfájlt.
"""

import logging
import os
import re
from collections import Counter
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from supabase import create_client


VERSION = "M1.5.1 / 0.1.0"
TIMEZONE = ZoneInfo("Europe/Budapest")
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
REQUEST_TIMEOUT = 25
ITUNES_COUNTRY = "US"
SEARCH_LIMIT = 25
MAX_SEARCH_TOPICS = 3

SECTION_LIMITS = {
    "research_frontier": 5,
    "art_of_the_day": 1,
    "the_thinker": 1,
    "battlefield": 1,
    "fundamentals": 1,
    "world_explorer": 1,
    "unsolved": 1,
}

STOP_WORDS = set("""
a an and are as at be been by can could did do does for from had has have
he her hers him his how i if in into is it its may might more most of on
or our she should so than that the their them then there these they this
those through to was we were what when where which who will with would you
your about after all also among any because before between both but during
each few first following further here however including its many much not
one other over same such some still than them these those under until very
while within without
""".split())

HEADERS = {
    "User-Agent": (
        "WORLD-SHARDS-MusicCollector/0.1 "
        "(daily editorial music selection)"
    )
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("world-shards-music-collector")


def get_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise RuntimeError("Hiányzó SUPABASE_URL vagy SUPABASE_SECRET_KEY.")
    return create_client(url, key)


def tokenize(value):
    words = re.findall(r"[a-z][a-z0-9'-]{2,}", str(value or "").lower())
    return [word for word in words if word not in STOP_WORDS]


def get_daily_topics(supabase):
    """Ugyanazokat a napi témakör-jelölteket olvassa, mint a Builder."""
    topics = []

    for section_code, limit in SECTION_LIMITS.items():
        response = (
            supabase.table("shard_content_items")
            .select(
                "id,section_code,title,summary,body,source_name,"
                "source_url,relevance_score,collected_at,metadata"
            )
            .eq("section_code", section_code)
            .eq("status", "candidate")
            .order("relevance_score", desc=True)
            .order("collected_at", desc=True)
            .limit(limit)
            .execute()
        )
        topics.extend(response.data or [])

    # A napi zene ne a záró rovat viccéhez vagy képregényéhez kapcsolódjon.
    return topics


def build_topic_query(topic):
    title = str(topic.get("title") or "")
    summary = str(topic.get("summary") or "")
    title_tokens = tokenize(title)
    summary_counts = Counter(tokenize(summary))

    selected = []
    for token in title_tokens:
        if token not in selected:
            selected.append(token)
        if len(selected) >= 3:
            break

    if len(selected) < 3:
        for token, _ in summary_counts.most_common():
            if token not in selected:
                selected.append(token)
            if len(selected) >= 3:
                break

    return " ".join(selected)


def choose_search_topics(topics, max_topics=MAX_SEARCH_TOPICS):
    """Legfeljebb három eltérő, értelmezhető napi témát választ."""
    chosen = []
    seen_queries = set()

    ordered = sorted(
        topics,
        key=lambda item: (
            float(item.get("relevance_score") or 0),
            str(item.get("title") or ""),
        ),
        reverse=True,
    )

    for topic in ordered:
        query = build_topic_query(topic)
        normalized = query.casefold()
        if len(tokenize(query)) < 2 or normalized in seen_queries:
            continue
        seen_queries.add(normalized)
        chosen.append((query, topic))
        if len(chosen) >= max_topics:
            break

    return chosen


def fetch_itunes_tracks(query, http_get=requests.get):
    params = {
        "term": query,
        "entity": "song",
        "media": "music",
        "country": ITUNES_COUNTRY,
        "limit": SEARCH_LIMIT,
    }
    response = http_get(
        ITUNES_SEARCH_URL,
        params=params,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    if not isinstance(payload, dict):
        raise RuntimeError("Érvénytelen iTunes API-válasz.")
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise RuntimeError("Az iTunes API results mezője nem lista.")
    return results


def deduplicate_tracks(tracks):
    """Track ID, ennek hiányában hallgatási URL alapján deduplikál."""
    unique = []
    seen = set()

    for track in tracks:
        track_id = track.get("trackId")
        track_url = track.get("trackViewUrl")
        key = ("id", str(track_id)) if track_id is not None else (
            "url", str(track_url or "")
        )
        if not key[1] or key in seen:
            continue
        seen.add(key)
        unique.append(track)

    return unique


def score_track(track, topic):
    """A track címét és albumát súlyozza; puszta előadónév nem elég."""
    track_name = str(track.get("trackName") or "")
    artist_name = str(track.get("artistName") or "")
    album_name = str(track.get("collectionName") or "")

    topic_title = str(topic.get("title") or "")
    topic_text = " ".join([
        topic_title,
        str(topic.get("summary") or ""),
        str(topic.get("body") or "")[:2500],
    ])

    topic_tokens = set(tokenize(topic_text))
    if not topic_tokens:
        return 0

    track_tokens = set(tokenize(track_name))
    album_tokens = set(tokenize(album_name))
    artist_tokens = set(tokenize(artist_name))

    title_matches = topic_tokens.intersection(track_tokens)
    album_matches = topic_tokens.intersection(album_tokens)
    artist_matches = topic_tokens.intersection(artist_tokens)

    score = (
        len(title_matches) * 4
        + len(album_matches) * 2
        + len(artist_matches)
    )

    # A keresési találatnak legalább a dal címében vagy albumában
    # kell érdemi egyezést mutatnia.
    if not title_matches and not album_matches:
        return 0

    return score


def choose_best_track(tracks, topics):
    """A legerősebb tartalmi egyezést választja determinisztikus döntetlennel."""
    candidates = []

    for track in deduplicate_tracks(tracks):
        if not track.get("trackName") or not track.get("artistName"):
            continue
        if not track.get("trackViewUrl"):
            continue

        for topic in topics:
            score = score_track(track, topic)
            if score < 2:
                continue

            candidates.append({
                "track": track,
                "topic": topic,
                "score": score,
            })

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item["score"],
            str(item["track"].get("trackName") or "").casefold(),
            str(item["track"].get("trackId") or ""),
        ),
        reverse=True,
    )
    return candidates[0]


def build_music_record(selection, edition_date):
    track = selection["track"]
    topic = selection["topic"]

    track_name = str(track["trackName"]).strip()
    artist_name = str(track["artistName"]).strip()
    album_name = str(track.get("collectionName") or "").strip()
    release_date = track.get("releaseDate")
    source_url = str(track.get("trackViewUrl") or "").strip()

    if not track_name or not artist_name or not source_url:
        raise ValueError("A zenei rekordhoz hiányzik a cím, előadó vagy link.")

    title = f"{artist_name} – {track_name}"
    summary_parts = [f"Előadó: {artist_name}"]
    if album_name:
        summary_parts.append(f"Album: {album_name}")
    if release_date:
        summary_parts.append(f"Megjelenés: {str(release_date)[:10]}")
    summary_parts.append(
        f"Napi kapcsolódó téma: {topic.get('title') or 'World Shards'}"
    )

    body = (
        f"Zeneszám: {track_name}\n"
        f"Előadó: {artist_name}\n"
        f"Album: {album_name or 'Nincs megadva'}\n"
        f"Megjelenés: {release_date or 'Nincs megadva'}\n\n"
        "A zenemű a napi kiadvány egyik témájához kapcsolódó szerkesztőségi "
        "zenei ajánlás. A kapcsolatot a dal címe vagy albuma és a napi "
        "tartalom kulcsszavai alapján választottuk ki.\n\n"
        f"Kapcsolódó napi tartalom: {topic.get('title') or ''}\n"
        f"Meghallgatási oldal: {source_url}\n"
        "A link az Apple/iTunes adatlapjára vezet; a teljes dal elérhetősége "
        "az adott szolgáltatástól és régiótól függ."
    )

    return {
        "section_code": "music_of_the_day",
        "title": title,
        "summary": " | ".join(summary_parts),
        "body": body,
        "source_name": "iTunes Search API",
        "source_url": source_url,
        "source_language": "en",
        "status": "candidate",
        "metadata": {
            "collector": "WORLD_SHARDS_M1.5.1",
            "collector_version": VERSION,
            "source_provider": "Apple iTunes Search API",
            "edition_date": edition_date,
            "track_id": track.get("trackId"),
            "track_name": track_name,
            "artist_name": artist_name,
            "album_name": album_name or None,
            "release_date": release_date,
            "preview_url": track.get("previewUrl"),
            "artwork_url": track.get("artworkUrl100"),
            "genre": track.get("primaryGenreName"),
            "country": ITUNES_COUNTRY,
            "related_content_item_id": topic.get("id"),
            "related_section_code": topic.get("section_code"),
            "related_content_title": topic.get("title"),
            "relation_score": selection["score"],
            "full_track_downloaded": False,
        },
    }


def music_record_exists_for_date(supabase, edition_date):
    response = (
        supabase.table("shard_content_items")
        .select("id,title,status")
        .eq("section_code", "music_of_the_day")
        .contains("metadata", {"edition_date": edition_date})
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def save_music_record(supabase, record, edition_date):
    existing = music_record_exists_for_date(supabase, edition_date)
    if existing:
        logger.info(
            "A mai zenei rekord már létezik (%s, %s); nincs duplikált beszúrás.",
            existing.get("id"),
            existing.get("status"),
        )
        return "already_exists"

    response = (
        supabase.table("shard_content_items")
        .insert(record)
        .execute()
    )
    if not response.data:
        raise RuntimeError("A zenei rekord mentése nem sikerült.")
    return "inserted"


def collect_music(supabase, http_get=requests.get, edition_date=None):
    edition_date = edition_date or datetime.now(TIMEZONE).date().isoformat()

    existing = music_record_exists_for_date(supabase, edition_date)
    if existing:
        logger.info(
            "A mai Music of the Day már megvan: %s",
            existing.get("title"),
        )
        return {"status": "already_exists", "title": existing.get("title")}

    topics = get_daily_topics(supabase)
    if not topics:
        raise RuntimeError(
            "Nincs kiválasztható napi tartalmi téma; a zenei keresés kimarad."
        )

    search_topics = choose_search_topics(topics)
    if not search_topics:
        raise RuntimeError("Nem állítható elő használható zenei keresőkifejezés.")

    all_tracks = []
    topic_by_query = {}

    for query, topic in search_topics:
        logger.info(
            "iTunes keresés: '%s' (rovat: %s)",
            query,
            topic.get("section_code"),
        )
        try:
            tracks = fetch_itunes_tracks(query, http_get=http_get)
        except Exception:
            logger.exception("iTunes keresési hiba: %s", query)
            continue

        for track in tracks:
            if isinstance(track, dict):
                all_tracks.append(track)
                topic_by_query[query] = topic

    # A kiválasztott témákkal egyező trackek újrapontozása.
    selection = choose_best_track(
        all_tracks,
        [topic for _, topic in search_topics],
    )

    if not selection:
        raise RuntimeError(
            "Az iTunes találatok között nem volt kellően kapcsolódó, "
            "érvényes meghallgatási linkkel rendelkező zeneszám."
        )

    record = build_music_record(selection, edition_date)
    result = save_music_record(supabase, record, edition_date)

    logger.info(
        "Music of the Day: %s – %s (%s)",
        record["metadata"]["artist_name"],
        record["metadata"]["track_name"],
        result,
    )
    return {"status": result, "title": record["title"]}


def main():
    logger.info("WORLD SHARDS Music Collector %s indul.", VERSION)
    supabase = get_supabase_client()
    result = collect_music(supabase)
    logger.info("Music of the Day eredmény: %s", result["status"])


if __name__ == "__main__":
    main()
