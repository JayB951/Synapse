"""AGORA M2.1: deterministic, dependency-free grouping of related news articles."""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse, urlunparse


DEFAULT_TIME_WINDOW_HOURS = 72
DEFAULT_SIMILARITY_THRESHOLD = 0.58

# Conservative stopword lists: remove common grammatical words, not topic terms.
STOPWORDS = {
    "hu": {"a", "az", "és", "hogy", "is", "meg", "már", "ma", "egy", "ezt", "azt", "aki", "ami", "mint", "mert", "de", "ha", "nem", "volt", "van", "lesz", "után", "előtt", "között", "szerint"},
    "en": {"the", "a", "an", "and", "or", "but", "that", "this", "these", "those", "is", "are", "was", "were", "be", "been", "to", "of", "in", "on", "at", "for", "from", "with", "by", "as", "after", "before", "over", "under"},
}


def normalize_title(title):
    """Normalize title for conservative lexical comparison."""
    value = unicodedata.normalize("NFKC", str(title or "")).casefold()
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def title_tokens(title, language):
    words = normalize_title(title).split()
    stopwords = STOPWORDS.get(language, set())
    return {word for word in words if len(word) > 1 and word not in stopwords}


def parse_date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def canonical_url(value):
    try:
        parsed = urlparse(str(value or "").strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return ""
        return urlunparse((
            parsed.scheme.lower(), parsed.netloc.lower(), parsed.path,
            parsed.params, parsed.query, "",
        ))
    except ValueError:
        return ""


def within_time_window(left, right, hours):
    left_date = parse_date(left.get("published_at"))
    right_date = parse_date(right.get("published_at"))
    # Missing/invalid dates must not create fuzzy matches.
    if left_date is None or right_date is None:
        return False
    return abs((left_date - right_date).total_seconds()) <= hours * 3600


def title_similarity(left, right):
    left_title = normalize_title(left.get("title"))
    right_title = normalize_title(right.get("title"))
    if not left_title or not right_title:
        return 0.0
    if left_title == right_title:
        return 1.0

    sequence_score = SequenceMatcher(None, left_title, right_title).ratio()
    left_tokens = title_tokens(left_title, left.get("language", ""))
    right_tokens = title_tokens(right_title, right.get("language", ""))
    if not left_tokens or not right_tokens:
        return sequence_score
    union = left_tokens | right_tokens
    jaccard_score = len(left_tokens & right_tokens) / len(union)
    # Both word overlap and phrase structure contribute; no embeddings/AI.
    return 0.55 * sequence_score + 0.45 * jaccard_score


def same_event_candidate(left, right, time_window_hours, threshold):
    # Never merge Hungarian and international candidate pools.
    if left.get("scope") != right.get("scope"):
        return False

    left_url = canonical_url(left.get("url"))
    right_url = canonical_url(right.get("url"))
    if left_url and left_url == right_url:
        return True

    if not within_time_window(left, right, time_window_hours):
        return False

    # Different languages are not compared by this lexical first version.
    if left.get("language") != right.get("language"):
        return False

    return title_similarity(left, right) >= threshold


class DisjointSet:
    def __init__(self, size):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, value):
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left, right):
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def cluster_candidates(candidates, time_window_hours=DEFAULT_TIME_WINDOW_HOURS,
                       similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD):
    """Return event groups; input records are retained without destructive merging."""
    records = [dict(item) for item in candidates]
    dsu = DisjointSet(len(records))

    for left_index in range(len(records)):
        for right_index in range(left_index + 1, len(records)):
            if same_event_candidate(
                records[left_index], records[right_index],
                time_window_hours, similarity_threshold,
            ):
                dsu.union(left_index, right_index)

    buckets = {}
    for index, record in enumerate(records):
        buckets.setdefault(dsu.find(index), []).append(record)

    groups = []
    for members in buckets.values():
        members.sort(key=lambda item: (
            str(item.get("published_at") or ""),
            str(item.get("source_code") or ""),
            str(item.get("url") or ""),
        ))
        scope = members[0].get("scope", "unknown")
        # Stable for an unchanged set of source URLs; no mutable database ID.
        identities = sorted(
            (str(item.get("source_code") or "") + "|" +
             (canonical_url(item.get("url")) or normalize_title(item.get("title"))))
            for item in members
        )
        digest = hashlib.sha256(
            (str(scope) + "|" + "|".join(identities)).encode("utf-8")
        ).hexdigest()[:20]
        source_codes = sorted({
            str(item.get("source_code"))
            for item in members if item.get("source_code")
        })
        groups.append({
            "event_id": "agora-event-" + digest,
            "scope": scope,
            "article_count": len(members),
            "independent_source_count": len(source_codes),
            "source_codes": source_codes,
            "representative_title": members[0].get("title", ""),
            "latest_published_at": max(
                (str(item.get("published_at") or "") for item in members),
                default="",
            ) or None,
            "articles": members,
        })

    groups.sort(key=lambda group: (
        group["scope"], -group["independent_source_count"],
        -group["article_count"], group["event_id"],
    ))
    return {
        "clusterer": "AGORA_EVENT_CLUSTERING_M2.1",
        "group_count": len(groups),
        "article_count": len(records),
        "groups": groups,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", help="JSON file from the RSS collector; defaults to stdin")
    parser.add_argument("--time-window-hours", type=int, default=DEFAULT_TIME_WINDOW_HOURS)
    parser.add_argument("--threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    args = parser.parse_args()

    if args.time_window_hours < 1:
        parser.error("--time-window-hours must be positive")
    if not 0.0 <= args.threshold <= 1.0:
        parser.error("--threshold must be between 0 and 1")

    raw = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    payload = json.loads(raw)
    candidates = payload.get("candidates", []) if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        parser.error("Input must be a list or an object containing a candidates list")

    result = cluster_candidates(
        candidates,
        time_window_hours=args.time_window_hours,
        similarity_threshold=args.threshold,
    )
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
