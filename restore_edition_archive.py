"""Restore today's durable edition artifact from an earlier daily workflow run.

The archive is the email outbox: no database access is required to retry delivery.
A delivery receipt prevents the same edition from being sent again after success.
"""
import io
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile

from zoneinfo import ZoneInfo

LOGGER = logging.getLogger("world-shards-archive-restore")
TIMEZONE = ZoneInfo("Europe/Budapest")
API_ROOT = "https://api.github.com"


def api_get(url, token):
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "world-shards-reliability",
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read()


def write_outputs(**values):
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def restore_today_archive():
    today = datetime.now(TIMEZONE).date().isoformat()
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    repository = os.getenv("GITHUB_REPOSITORY")
    branch = os.getenv("GITHUB_REF_NAME")
    current_run = os.getenv("GITHUB_RUN_ID")
    if not all((token, repository, branch, current_run)):
        LOGGER.warning("GitHub artifact-visszaállítás kihagyva: hiányzó Actions-környezet.")
        write_outputs(archive_found=False, delivery_sent=False, sqlite_found=False)
        return False

    # The current-day archive is needed for email retries, while the newest
    # SQLite artifact may be from an earlier day and must survive until DB recovery.
    query = urlencode({"branch": branch, "per_page": 100})
    runs_url = (
        f"{API_ROOT}/repos/{repository}/actions/workflows/"
        f"world-shards-daily.yml/runs?{query}"
    )
    sqlite_restored = False
    archive_restored = False
    delivery_sent = False

    try:
        runs = json.loads(api_get(runs_url, token))
        for run in runs.get("workflow_runs", []):
            if str(run.get("id")) == str(current_run):
                continue
            run_date = str(run.get("created_at") or "")[:10]
            artifacts_url = (
                f"{API_ROOT}/repos/{repository}/actions/runs/"
                f"{run['id']}/artifacts?per_page=100"
            )
            artifacts = json.loads(api_get(artifacts_url, token))
            candidates = [
                artifact for artifact in artifacts.get("artifacts", [])
                if artifact.get("name", "").startswith("world-shards-edition-")
                and not artifact.get("expired")
            ]

            for artifact in candidates:
                try:
                    archive_bytes = api_get(artifact["archive_download_url"], token)
                    with ZipFile(io.BytesIO(archive_bytes)) as bundle:
                        if not sqlite_restored:
                            sqlite_member = next(
                                (
                                    name for name in bundle.namelist()
                                    if Path(name).name == ".world_shards_fallback.sqlite3"
                                ),
                                None,
                            )
                            if sqlite_member:
                                sqlite_bytes = bundle.read(sqlite_member)
                                if sqlite_bytes.startswith(b"SQLite format 3\x00"):
                                    sqlite_path = Path(os.getenv(
                                        "WORLD_SHARDS_SQLITE_PATH",
                                        ".world_shards_fallback.sqlite3",
                                    ))
                                    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
                                    sqlite_path.write_bytes(sqlite_bytes)
                                    sqlite_restored = True
                                    LOGGER.info(
                                        "A korábbi SQLite tartalék-adattár visszaállítva a(z) %s futásból.",
                                        run["id"],
                                    )

                        if run_date == today and not archive_restored:
                            archive_member = next(
                                (
                                    name for name in bundle.namelist()
                                    if Path(name).name == f"edition-{today}.json"
                                ),
                                None,
                            )
                            if archive_member:
                                archive = json.loads(bundle.read(archive_member))
                                edition = archive.get("edition") or {}
                                if (
                                    archive.get("archive_type") == "world_shards_edition"
                                    and archive.get("schema_version") == 1
                                    and edition.get("edition_date") == today
                                ):
                                    archive_dir = Path(
                                        os.getenv("WORLD_SHARDS_ARCHIVE_DIR", "world-shards-archive")
                                    )
                                    archive_dir.mkdir(parents=True, exist_ok=True)
                                    archive_path = archive_dir / f"edition-{today}.json"
                                    archive_path.write_text(
                                        json.dumps(archive, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8",
                                    )
                                    archive_restored = True

                                    receipt_member = next(
                                        (
                                            name for name in bundle.namelist()
                                            if Path(name).name == "delivery-receipt.json"
                                        ),
                                        None,
                                    )
                                    if receipt_member:
                                        receipt = json.loads(bundle.read(receipt_member))
                                        if (
                                            receipt.get("edition_date") == today
                                            and receipt.get("status") == "sent"
                                        ):
                                            (archive_dir / "delivery-receipt.json").write_text(
                                                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8",
                                            )
                                            delivery_sent = True
                                    LOGGER.info(
                                        "Mai archívum visszaállítva a(z) %s futásból; kézbesítve=%s.",
                                        run["id"], delivery_sent,
                                    )
                except Exception:
                    LOGGER.exception(
                        "Korábbi archívum feldolgozása sikertelen (run=%s, artifact=%s).",
                        run.get("id"), artifact.get("name"),
                    )
                    continue

            if run_date < today and (sqlite_restored or archive_restored):
                break
            if sqlite_restored and archive_restored:
                break
    except Exception:
        LOGGER.exception("A korábbi WORLD SHARDS archívumok keresése sikertelen.")

    write_outputs(
        archive_found=archive_restored,
        delivery_sent=delivery_sent,
        sqlite_found=sqlite_restored,
    )
    return archive_restored

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    restore_today_archive()


if __name__ == "__main__":
    main()
