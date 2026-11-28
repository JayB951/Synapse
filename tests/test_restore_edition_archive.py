import io
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import restore_edition_archive
from artifact_crypto import encrypt_bytes
from urllib.request import Request


class RestoreEditionArchiveTests(unittest.TestCase):
    def _artifact_zip(self, include_receipt):
        today = datetime.now(ZoneInfo("Europe/Budapest")).date().isoformat()
        archive = {
            "schema_version": 1,
            "archive_type": "world_shards_edition",
            "edition": {"edition_date": today, "status": "draft"},
            "items": [],
            "source_by_id": {},
        }
        buffer = io.BytesIO()
        with ZipFile(buffer, "w") as bundle:
            bundle.writestr(
                f"edition-{today}.json.gpg",
                encrypt_bytes(json.dumps(archive).encode("utf-8"), "test-secret"),
            )
            bundle.writestr(
                "world-shards-fallback.sqlite3.gpg",
                encrypt_bytes(b"SQLite format 3\x00test-database", "test-secret"),
            )
            if include_receipt:
                bundle.writestr(
                    "delivery-receipt.json.gpg",
                    encrypt_bytes(json.dumps({
                        "edition_date": today,
                        "status": "sent",
                        "sent_at": "2026-11-28T07:00:00+00:00",
                    }).encode("utf-8"), "test-secret"),
                )
        return today, buffer.getvalue()

    def _run_restore(self, include_receipt):
        today, zip_bytes = self._artifact_zip(include_receipt)
        runs_response = json.dumps({
            "workflow_runs": [
                {"id": 100, "created_at": f"{today}T07:00:00Z"},
                {"id": 101, "created_at": f"{today}T07:01:00Z"},
            ]
        }).encode("utf-8")
        artifacts_response = json.dumps({
            "artifacts": [{
                "name": "world-shards-edition-100",
                "expired": False,
                "archive_download_url": "https://example.test/artifact.zip",
            }]
        }).encode("utf-8")

        with tempfile.TemporaryDirectory() as directory:
            output_path = os.path.join(directory, "github-output.txt")
            with patch.dict(os.environ, {
                "GH_TOKEN": "test-token",
                "SUPABASE_SECRET_KEY": "test-secret",
                "GITHUB_REPOSITORY": "JayB951/Synapse",
                "GITHUB_REF_NAME": "main",
                "GITHUB_RUN_ID": "101",
                "WORLD_SHARDS_ARCHIVE_DIR": directory,
                "WORLD_SHARDS_SQLITE_PATH": os.path.join(directory, "world-shards-fallback.sqlite3"),
                "GITHUB_OUTPUT": output_path,
            }), patch.object(
                restore_edition_archive,
                "api_get",
                side_effect=[runs_response, artifacts_response, zip_bytes],
            ):
                result = restore_edition_archive.restore_today_archive()
            archive_path = os.path.join(directory, f"edition-{today}.json")
            self.assertTrue(os.path.isfile(archive_path))
            with open(archive_path, encoding="utf-8") as handle:
                restored = json.load(handle)
            with open(output_path, encoding="utf-8") as handle:
                outputs = handle.read()
            sqlite_path = os.path.join(directory, "world-shards-fallback.sqlite3")
            self.assertTrue(os.path.isfile(sqlite_path))
            with open(sqlite_path, "rb") as handle:
                self.assertTrue(handle.read().startswith(b"SQLite format 3\x00"))

        self.assertEqual(restored["edition"]["edition_date"], today)
        return result, outputs

    def test_artifact_redirect_does_not_forward_github_bearer_token(self):
        handler = restore_edition_archive.SafeGitHubRedirectHandler()
        request = Request(
            "https://api.github.com/repos/JayB951/Synapse/actions/artifacts/1/zip",
            headers={"Authorization": "Bearer test-secret"},
        )
        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://signed-artifact-storage.example/blob.zip",
        )
        self.assertNotIn("Authorization", redirected.headers)
        self.assertNotIn("authorization", redirected.headers)

    def test_restores_archive_and_sent_receipt(self):
        result, outputs = self._run_restore(include_receipt=True)
        self.assertTrue(result)
        self.assertIn("archive_found=true", outputs)
        self.assertIn("delivery_sent=true", outputs)
        self.assertIn("sqlite_found=true", outputs)

    def test_restores_archive_without_claiming_delivery(self):
        result, outputs = self._run_restore(include_receipt=False)
        self.assertTrue(result)
        self.assertIn("archive_found=true", outputs)
        self.assertIn("delivery_sent=false", outputs)
        self.assertIn("sqlite_found=true", outputs)

    def test_restores_sqlite_state_from_previous_day_without_an_edition_archive(self):
        today = datetime.now(ZoneInfo("Europe/Budapest")).date().isoformat()
        sqlite_bytes = encrypt_bytes(
            b"SQLite format 3\x00previous-day-cache", "test-secret"
        )
        buffer = io.BytesIO()
        with ZipFile(buffer, "w") as bundle:
            bundle.writestr("world-shards-fallback.sqlite3.gpg", sqlite_bytes)

        runs_response = json.dumps({
            "workflow_runs": [{"id": 100, "created_at": "2026-11-27T07:00:00Z"}]
        }).encode("utf-8")
        artifacts_response = json.dumps({
            "artifacts": [{
                "name": "world-shards-edition-100",
                "expired": False,
                "archive_download_url": "https://example.test/previous.zip",
            }]
        }).encode("utf-8")

        with tempfile.TemporaryDirectory() as directory:
            output_path = os.path.join(directory, "github-output.txt")
            with patch.dict(os.environ, {
                "GH_TOKEN": "test-token",
                "SUPABASE_SECRET_KEY": "test-secret",
                "GITHUB_REPOSITORY": "JayB951/Synapse",
                "GITHUB_REF_NAME": "main",
                "GITHUB_RUN_ID": "101",
                "WORLD_SHARDS_ARCHIVE_DIR": directory,
                "WORLD_SHARDS_SQLITE_PATH": os.path.join(directory, "world-shards-fallback.sqlite3"),
                "GITHUB_OUTPUT": output_path,
            }), patch.object(
                restore_edition_archive,
                "api_get",
                side_effect=[
                    runs_response,
                    artifacts_response,
                    buffer.getvalue(),
                ],
            ):
                result = restore_edition_archive.restore_today_archive()
            with open(output_path, encoding="utf-8") as handle:
                outputs = handle.read()
            with open(os.path.join(directory, "world-shards-fallback.sqlite3"), "rb") as handle:
                restored_sqlite = handle.read()

        self.assertFalse(result)
        self.assertTrue(restored_sqlite.startswith(b"SQLite format 3\x00"))
        self.assertIn("archive_found=false", outputs)
        self.assertIn("sqlite_found=true", outputs)


if __name__ == "__main__":
    unittest.main()
