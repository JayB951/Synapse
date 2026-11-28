"""Best-effort replay of the SQLite fallback outbox into Supabase."""
import logging
import os

from resilient_storage import create_resilient_client

LOGGER = logging.getLogger("world-shards-fallback-sync")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    client = create_resilient_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SECRET_KEY"),
    )
    pending, deleted = client.store.pending_records()
    if not pending and not deleted:
        LOGGER.info("Nincs visszaszinkronizálandó helyi rekord.")
        return

    if client.remote is None:
        LOGGER.warning(
            "A Supabase jelenleg nem érhető el; helyi rekordok megőrizve: %s írás, %s törlés.",
            len(pending), len(deleted),
        )
        return

    # create_resilient_client already attempted one dependency-ordered replay.
    remaining, remaining_deleted = client.store.pending_records()
    if remaining or remaining_deleted:
        LOGGER.warning(
            "A visszaszinkronizálás részleges: %s írás és %s törlés maradt helyben.",
            len(remaining), len(remaining_deleted),
        )
    else:
        LOGGER.info("Minden korábbi helyi módosítás visszaszinkronizálva.")


if __name__ == "__main__":
    main()
