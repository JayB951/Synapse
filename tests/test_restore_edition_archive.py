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
                f"edition-{today}.json",
                json.dumps(archive),
            )
            if include_receipt:
                bundle.writestr(
                    "delivery-receipt.json",
                    json.dumps({
                        "edition_date": today,
                        "status": "sent",
                        "sent_at": "2026-11-28T07:00:00+00:00",
                    }),
                )
        return today, buffer.getvalue()

    def _run_restore(self, include_receipt):
        today, zip_bytes = self._artifact_zip(include_receipt)
        runs_response = json.dumps({
            "workflow_runs": [{"id": 100}, {"id": 101}]
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
                "GITHUB_REPOSITORY": "JayB951/Synapse",
                "GITHUB_REF_NAME": "main",
                "GITHUB_RUN_ID": "101",
                "WORLD_SHARDS_ARCHIVE_DIR": directory,
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

        self.assertEqual(restored["edition"]["edition_date"], today)
        return result, outputs

    def test_restores_archive_and_sent_receipt(self):
        result, outputs = self._run_restore(include_receipt=True)
        self.assertTrue(result)
        self.assertIn("archive_found=true", outputs)
        self.assertIn("delivery_sent=true", outputs)

    def test_restores_archive_without_claiming_delivery(self):
        result, outputs = self._run_restore(include_receipt=False)
        self.assertTrue(result)
        self.assertIn("archive_found=true", outputs)
        self.assertIn("delivery_sent=false", outputs)


if __name__ == "__main__":
    unittest.main()
