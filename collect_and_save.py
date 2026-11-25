
"""
SYNAPSE – Adatgyűjtés és adatbázisba mentés
Verzió: M2.7.5 / 0.1.0

Folyamat:
1. OpenAlex lekérdezés
2. Crossref lekérdezés
3. Rekordok feldolgozása
4. DOI-alapú deduplikáció
5. Modellvalidáció
6. Supabase-mentés
"""

import sys

import test_sources as collector
import publication_model as model

from database_writer import (
    get_supabase_client,
    save_records,
)


def main():
    print("=" * 70)
    print("SYNAPSE – ADATGYŰJTÉS ÉS ADATBÁZISBA MENTÉS")
    print("Verzió: M2.7.5 / 0.1.0")
    print("=" * 70)

    print(
        f"Gyűjtési időszak: "
        f"{collector.START_DATE} – {collector.END_DATE}"
    )

    print(
        f"Forrásonkénti limit: {collector.RECORD_LIMIT}"
    )

    # 1. Adatgyűjtés
    openalex_raw = collector.fetch_openalex()
    crossref_raw = collector.fetch_crossref()

    if not openalex_raw and not crossref_raw:
        print("HIBA: Egyik adatforrásból sem érkezett rekord.")
        sys.exit(1)

    # 2. Feldolgozás
    openalex_records, _ = collector.process_openalex(
        openalex_raw
    )

    crossref_records, _ = collector.process_crossref(
        crossref_raw
    )

    all_records = openalex_records + crossref_records

    # 3. Deduplikáció
    unified_records, duplicate_count = (
        collector.deduplicate_records(all_records)
    )

    # 4. Modellvalidáció
    valid_records = [
        record
        for record in unified_records
        if model.validate_record(record)
    ]

    if len(valid_records) != len(unified_records):
        print(
            "FIGYELEM: Modellvalidáción kiesett rekordok:",
            len(unified_records) - len(valid_records),
        )

    if not valid_records:
        print("Nincs menthető publikáció.")
        sys.exit(1)

    print()
    print("Adatgyűjtési összesítés")
    print("-" * 50)
    print("OpenAlex elfogadott:", len(openalex_records))
    print("Crossref elfogadott:", len(crossref_records))
    print("Összesített rekord:", len(unified_records))
    print("Összevont duplikáció:", duplicate_count)
    print("Mentésre váró rekord:", len(valid_records))

    # 5. Supabase-kapcsolat
    print()
    print("Supabase-kapcsolat létrehozása...")

    client = get_supabase_client()

    print("Supabase-kapcsolat: SIKERES")

    # 6. Mentés
    print()
    print("Adatbázisba mentés indul...")

    result = save_records(
        client,
        valid_records,
    )

    # 7. Eredmény
    print()
    print("=" * 70)
    print("MENTÉSI EREDMÉNY")
    print("=" * 70)

    print("Állapot:", result["status"])
    print("Új publikáció:", result["inserted"])
    print("Frissített publikáció:", result["updated"])
    print("Kihagyott publikáció:", result["skipped"])

    if result["errors"]:
        print()
        print("Hibák:")

        for error in result["errors"][:20]:
            print("-", error)

    print("=" * 70)

    if result["status"] == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
