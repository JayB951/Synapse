
import os
import sys
import calendar
from datetime import date

import requests


OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"

RESULT_LIMIT = 10
TIMEOUT_SECONDS = 30


def get_start_date():
    """A mai naphoz képest 12 hónappal korábbi dátum."""
    today = date.today()
    year = today.year - 1
    day = min(today.day, calendar.monthrange(year, today.month)[1])
    return date(year, today.month, day)


def print_header(title):
    print()
    print("=" * 65)
    print(title)
    print("=" * 65)


def request_openalex(start_date, end_date):
    api_key = os.getenv("OPENALEX_API_KEY")

    if not api_key:
        raise RuntimeError("Hiányzik az OPENALEX_API_KEY GitHub Secret.")

    params = {
        "api_key": api_key,
        "filter": (
            f"from_publication_date:{start_date},"
            f"to_publication_date:{end_date},"
            "language:en"
        ),
        "per_page": RESULT_LIMIT,
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
        raise RuntimeError("Hiányzik a CROSSREF_MAILTO GitHub Secret.")

    params = {
        "filter": (
            f"from-pub-date:{start_date},"
            f"until-pub-date:{end_date}"
        ),
        "rows": RESULT_LIMIT,
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


def print_openalex_records(records):
    print_header("OPENALEX – LEKÉRT PUBLIKÁCIÓK")

    print("Rekordok száma:", len(records))

    for index, item in enumerate(records, start=1):
        title = item.get("title") or "[HIÁNYZÓ CÍM]"
        topics = item.get("topics") or []
        authorships = item.get("authorships") or []

        topic_names = [
            topic.get("display_name", "")
            for topic in topics[:3]
        ]

        author_names = [
            authorship.get("author", {}).get("display_name", "")
            for authorship in authorships[:3]
        ]

        print(f"\n{index}. {title}")
        print("Dátum:", item.get("publication_date"))
        print("Nyelv:", item.get("language"))
        print("Típus:", item.get("type"))
        print("DOI:", item.get("doi"))
        print("Témák:", ", ".join(topic_names) or "Nincs adat")
        print("Szerzők:", ", ".join(author_names) or "Nincs adat")
        print("Absztrakt:", "Van" if item.get("abstract_inverted_index") else "Nincs")


def print_crossref_records(records):
    print_header("CROSSREF – LEKÉRT PUBLIKÁCIÓK")

    print("Rekordok száma:", len(records))

    for index, item in enumerate(records, start=1):
        titles = item.get("title") or []
        title = titles[0] if titles else "[HIÁNYZÓ CÍM]"

        subjects = item.get("subject") or []
        authors = item.get("author") or []

        author_names = [
            " ".join(
                part for part in [
                    author.get("given", ""),
                    author.get("family", "")
                ] if part
            )
            for author in authors[:3]
        ]

        publication_date = (
            item.get("published-online")
            or item.get("published-print")
            or item.get("published")
            or item.get("posted")
        )

        print(f"\n{index}. {title}")
        print("Dátum:", publication_date)
        print("Nyelv:", item.get("language") or "Nincs adat")
        print("Típus:", item.get("type"))
        print("DOI:", item.get("DOI"))
        print("Témák:", ", ".join(subjects[:3]) or "Nincs adat")
        print("Szerzők:", ", ".join(author_names) or "Nincs adat")
        print("Absztrakt:", "Van" if item.get("abstract") else "Nincs")


def main():
    print_header("SYNAPSE – ADATFORRÁS TESZT")

    start_date = get_start_date()
    end_date = date.today()

    print("Gyűjtési időszak:", start_date, "-", end_date)
    print("OpenAlex mintaméret:", RESULT_LIMIT)
    print("Crossref mintaméret:", RESULT_LIMIT)
    print("Adatbázisba mentés: NINCS")

    try:
        openalex_records = request_openalex(start_date, end_date)
        print_openalex_records(openalex_records)

        crossref_records = request_crossref(start_date, end_date)
        print_crossref_records(crossref_records)

        print_header("TESZT BEFEJEZVE")
        print("OpenAlex rekordok:", len(openalex_records))
        print("Crossref rekordok:", len(crossref_records))
        print("Összesen:", len(openalex_records) + len(crossref_records))
        print("A program nem módosította a Supabase adatbázist.")

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
