
import os
import sys
import calendar
from datetime import date
from collections import Counter

import requests


OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"

FETCH_LIMIT = 50
DISPLAY_LIMIT = 10
TIMEOUT_SECONDS = 30


# Egyértelműen elfogadható publikációtípusok
ACCEPTED_OPENALEX_TYPES = {
    "article",
    "book",
    "book-chapter",
    "dissertation",
    "preprint",
    "proceedings-article",
    "report",
}

ACCEPTED_CROSSREF_TYPES = {
    "journal-article",
    "proceedings-article",
    "book",
    "book-chapter",
    "posted-content",
    "dissertation",
    "report",
    "monograph",
    "edited-book",
    "reference-entry",
}

# Egyértelműen kizárandó típusok
EXCLUDED_TYPES = {
    "dataset",
    "software",
    "component",
    "paratext",
    "editorial",
    "journal-editorial",
    "book-review",
    "peer-review",
    "journal-issue",
    "journal-volume",
    "proceedings",
    "journal",
    "book-series",
}

# A nem egyértelmű típusok kézi ellenőrzést kapnak.


def get_start_date():
    """A mai naphoz képest 12 hónappal korábbi dátum."""
    today = date.today()
    year = today.year - 1
    day = min(
        today.day,
        calendar.monthrange(year, today.month)[1]
    )
    return date(year, today.month, day)


def print_header(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def request_openalex(start_date, end_date):
    api_key = os.getenv("OPENALEX_API_KEY")

    if not api_key:
        raise RuntimeError(
            "Hiányzik az OPENALEX_API_KEY GitHub Secret."
        )

    params = {
        "api_key": api_key,
        "filter": (
            f"from_publication_date:{start_date},"
            f"to_publication_date:{end_date},"
            "language:en"
        ),
        "per_page": FETCH_LIMIT,
        "sort": "publication_date:desc",
    }

    response = requests.get(
        OPENALEX_URL,
        params=params,
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json().get("results", [])


def request_crossref(start_date, end_date):
    mailto = os.getenv("CROSSREF_MAILTO")

    if not mailto:
        raise RuntimeError(
            "Hiányzik a CROSSREF_MAILTO GitHub Secret."
        )

    params = {
        "filter": (
            f"from-pub-date:{start_date},"
            f"until-pub-date:{end_date}"
        ),
        "rows": FETCH_LIMIT,
        "sort": "published",
        "order": "desc",
        "mailto": mailto,
    }

    headers = {
        "User-Agent": f"SYNAPSE/0.1 (mailto:{mailto})"
    }

    response = requests.get(
        CROSSREF_URL,
        params=params,
        headers=headers,
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json().get("message", {}).get("items", [])


def classify_type(publication_type, accepted_types):
    """Publikációtípus besorolása."""

    if not publication_type:
        return "ELLENŐRZENDŐ"

    normalized = publication_type.lower().strip()

    if normalized in EXCLUDED_TYPES:
        return "KIZÁRVA"

    if normalized in accepted_types:
        return "ELFOGADHATÓ"

    return "ELLENŐRZENDŐ"


def check_language(language):
    """Nyelvi metaadat előzetes ellenőrzése."""

    if not language:
        return "HIÁNYZIK – NYELVFELISMERÉS SZÜKSÉGES"

    normalized = str(language).lower().strip()

    if normalized in {"en", "eng", "english"}:
        return "ANGOL – METAADAT ALAPJÁN"

    return f"NEM ANGOL VAGY NEM FELISMERT: {language}"


def check_topics(topics):
    """Témaköri adatok meglétének ellenőrzése."""

    if not topics:
        return "HIÁNYZIK – KÉSŐBBI TÉMAAZONOSÍTÁS SZÜKSÉGES"

    return "VAN TÉMAKÖRI ADAT"


def print_record(
    index,
    title,
    publication_date,
    publication_type,
    language,
    topics,
    authors,
    has_abstract,
    classification,
):
    print(f"\n{index}. {title}")
    print("Dátum:", publication_date or "Nincs adat")
    print("Típus:", publication_type or "Nincs adat")
    print("Besorolás:", classification)
    print("Nyelv:", check_language(language))
    print("Témák:", check_topics(topics))
    print("Témakörök:", ", ".join(topics[:3]) if topics else "Nincs adat")
    print("Szerzők:", ", ".join(authors[:3]) if authors else "Nincs adat")
    print("Absztrakt:", "Van" if has_abstract else "Nincs")


def process_openalex(records):
    print_header("OPENALEX – ADATMINŐSÉGI ELLENŐRZÉS")

    classified = []

    for item in records:
        publication_type = item.get("type") or ""

        classification = classify_type(
            publication_type,
            ACCEPTED_OPENALEX_TYPES,
        )

        topics = [
            topic.get("display_name", "")
            for topic in (item.get("topics") or [])
            if topic.get("display_name")
        ]

        authors = [
            authorship.get("author", {}).get("display_name", "")
            for authorship in (item.get("authorships") or [])
            if authorship.get("author", {}).get("display_name")
        ]

        classified.append({
            "title": item.get("title") or "",
            "date": item.get("publication_date"),
            "type": publication_type,
            "language": item.get("language"),
            "topics": topics,
            "authors": authors,
            "abstract": bool(item.get("abstract_inverted_index")),
            "classification": classification,
        })

    print_summary(classified, "OPENALEX")
    return classified


def process_crossref(records):
    print_header("CROSSREF – ADATMINŐSÉGI ELLENŐRZÉS")

    classified = []

    for item in records:
        titles = item.get("title") or []
        title = titles[0] if titles else ""

        publication_type = item.get("type") or ""

        classification = classify_type(
            publication_type,
            ACCEPTED_CROSSREF_TYPES,
        )

        subjects = item.get("subject") or []

        authors = []
        for author in item.get("author") or []:
            name = " ".join(
                part for part in [
                    author.get("given", ""),
                    author.get("family", ""),
                ]
                if part
            )
            if name:
                authors.append(name)

        date_fields = [
            "published-online",
            "published-print",
            "published",
            "posted",
            "created",
        ]

        available_dates = []
        for field in date_fields:
            date_parts = (
                item.get(field, {}).get("date-parts") or []
            )
            if date_parts and date_parts[0]:
                parts = date_parts[0]
                year = parts[0]
                month = parts[1] if len(parts) > 1 else 1
                day = parts[2] if len(parts) > 2 else 1

                try:
                    available_dates.append(
                        date(year, month, day)
                    )
                except (ValueError, TypeError):
                    pass

        earliest_date = (
            min(available_dates).isoformat()
            if available_dates
            else None
        )

        classified.append({
            "title": title,
            "date": earliest_date,
            "type": publication_type,
            "language": item.get("language"),
            "topics": subjects,
            "authors": authors,
            "abstract": bool(item.get("abstract")),
            "classification": classification,
        })

    print_summary(classified, "CROSSREF")
    return classified


def print_summary(records, source_name):
    counts = Counter(
        record["classification"]
        for record in records
    )

    print("Lekért rekordok:", len(records))
    print("Elfogadható típus:", counts["ELFOGADHATÓ"])
    print("Kizárt típus:", counts["KIZÁRVA"])
    print("Kézi ellenőrzést igényel:", counts["ELLENŐRZENDŐ"])

    print_header(
        f"{source_name} – ELFOGADHATÓ PUBLIKÁCIÓK MINTÁJA"
    )

    accepted = [
        record for record in records
        if record["classification"] == "ELFOGADHATÓ"
    ]

    if not accepted:
        print("Nem találtunk elfogadható típusú rekordot.")
    else:
        for index, record in enumerate(
            accepted[:DISPLAY_LIMIT],
            start=1
        ):
            print_record(
                index=index,
                title=record["title"] or "[HIÁNYZÓ CÍM]",
                publication_date=record["date"],
                publication_type=record["type"],
                language=record["language"],
                topics=record["topics"],
                authors=record["authors"],
                has_abstract=record["abstract"],
                classification=record["classification"],
            )

    print_header(
        f"{source_name} – ELLENŐRZENDŐ TÍPUSOK"
    )

    review_records = [
        record for record in records
        if record["classification"] == "ELLENŐRZENDŐ"
    ]

    if not review_records:
        print("Nincs kézi ellenőrzést igénylő rekord.")
    else:
        for index, record in enumerate(
            review_records[:5],
            start=1
        ):
            print(
                f"{index}. "
                f"{record['title'] or '[HIÁNYZÓ CÍM]'} "
                f"| Típus: {record['type'] or 'Nincs adat'}"
            )


def main():
    print_header("SYNAPSE – ADATMINŐSÉGI TESZT")

    start_date = get_start_date()
    end_date = date.today()

    print("Gyűjtési időszak:", start_date, "-", end_date)
    print("Forrásonkénti lekérési limit:", FETCH_LIMIT)
    print("Megjelenített elfogadható rekordok:", DISPLAY_LIMIT)
    print("Adatbázisba mentés: NINCS")

    try:
        openalex_records = request_openalex(
            start_date,
            end_date,
        )

        crossref_records = request_crossref(
            start_date,
            end_date,
        )

        openalex_classified = process_openalex(
            openalex_records
        )

        crossref_classified = process_crossref(
            crossref_records
        )

        print_header("SYNAPSE – ÖSSZESÍTÉS")

        print("OpenAlex rekordok:", len(openalex_classified))
        print("Crossref rekordok:", len(crossref_classified))
        print(
            "Összes lekért rekord:",
            len(openalex_classified) + len(crossref_classified),
        )

        print(
            "A Supabase adatbázis nem módosult."
        )

        print(
            "A hiányzó nyelvi és témaköri adatok "
            "egyelőre csak jelölést kaptak."
        )

    except requests.exceptions.HTTPError as error:
        print("API HTTP HIBA:", error.response.status_code)
        print("Az API nem fogadta el a lekérdezést.")
        sys.exit(1)

    except requests.exceptions.RequestException as error:
        print("HÁLÓZATI HIBA:", str(error))
        sys.exit(1)

    except (RuntimeError, ValueError) as error:
        print("BEÁLLÍTÁSI HIBA:", str(error))
        sys.exit(1)


if __name__ == "__main__":
    main()
