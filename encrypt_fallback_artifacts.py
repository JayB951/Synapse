"""Encrypt all private edition and SQLite state files before GitHub artifact upload."""
import logging
import os
from pathlib import Path

from artifact_crypto import encrypt_bytes

LOGGER = logging.getLogger("world-shards-artifact-encryption")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    secret = (
        os.getenv("WORLD_SHARDS_FALLBACK_ENCRYPTION_KEY")
        or os.getenv("SUPABASE_SECRET_KEY")
    )
    archive_dir = Path(os.getenv("WORLD_SHARDS_ARCHIVE_DIR", "world-shards-archive"))
    sqlite_path = Path(os.getenv(
        "WORLD_SHARDS_SQLITE_PATH", "world-shards-fallback.sqlite3"
    ))

    sources = list(archive_dir.glob("*.json")) if archive_dir.exists() else []
    if sqlite_path.is_file():
        sources.append(sqlite_path)

    if not sources:
        LOGGER.info("Nincs titkosítandó napi archívum vagy SQLite állomány.")
        return
    if not secret:
        raise RuntimeError(
            "A privát WORLD SHARDS artifactok nem tölthetők fel titkosítási kulcs nélkül. "
            "Állítsd be a WORLD_SHARDS_FALLBACK_ENCRYPTION_KEY secretet."
        )

    encrypted_count = 0
    for source in sources:
        encrypted_path = Path(str(source) + ".gpg")
        encrypted_path.write_bytes(encrypt_bytes(source.read_bytes(), secret))
        source.unlink()
        encrypted_count += 1
        LOGGER.info("Privát artifact titkosítva: %s", encrypted_path.name)

    LOGGER.info("%s privát állomány titkosítva, plaintext példányok eltávolítva.", encrypted_count)


if __name__ == "__main__":
    main()
