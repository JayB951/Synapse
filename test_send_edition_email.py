import unittest
from urllib.parse import urlparse, parse_qs
import uuid
import os
import json
import tempfile
from unittest.mock import patch
from datetime import datetime, timezone
from send_edition_email import build_email_bodies, build_rating_links, validate_edition, send_email, load_local_archive, save_delivery_receipt

class EditionEmailTests(unittest.TestCase):
    def setUp(self):
        self.edition = {
            "edition_date": "2026-11-26",
            "status": "published",
            "introduction": "Napi bevezető",
        }
        counts = {
            "research_frontier": 7,
            "art_of_the_day": 1,
            "the_thinker": 1,
            "battlefield": 1,
            "fundamentals": 1,
            "world_explorer": 1,
            "unsolved": 1,
            "music_of_the_day": 1,
            "closing": 2,
        }
        self.items = []
        position = 1
        for section, count in counts.items():
            for index in range(count):
                self.items.append({
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"world-shards-item-{position}")),
                    "content_item_id": f"content-{position}",
                    "section_code": section,
                    "position": position,
                    "editor_note": (
                        "MAGYAR AGORA" if position == 6 else
                        "WORLD AGORA" if position == 7 else None
                    ),
                    "processing_status": "completed",
                    "display_title": f"Cím {position}",
                    "display_summary": f"Összefoglaló {position}",
                    "display_body": f"Teljes szöveg {position}",
                })
                position += 1

    def test_accepts_complete_published_edition(self):
        validate_edition(self.edition, self.items)

    def test_rejects_draft_edition(self):
        draft = dict(self.edition, status="draft")
        with self.assertRaises(RuntimeError):
            validate_edition(draft, self.items)

    def test_accepts_complete_draft_for_local_archive_delivery(self):
        draft = dict(self.edition, status="draft")
        validate_edition(draft, self.items, require_published=False)

    def test_loads_complete_local_archive_without_supabase(self):
        from send_edition_email import TIMEZONE
        today = datetime.now(TIMEZONE).date().isoformat()
        archive = {
            "schema_version": 1,
            "archive_type": "world_shards_edition",
            "edition": dict(self.edition, edition_date=today, status="draft"),
            "items": self.items,
            "source_by_id": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            archive_path = os.path.join(directory, f"edition-{today}.json")
            with open(archive_path, "w", encoding="utf-8") as handle:
                json.dump(archive, handle)
            with patch.dict(os.environ, {"WORLD_SHARDS_ARCHIVE_DIR": directory}):
                edition, items, sources = load_local_archive()
        self.assertEqual(edition["edition_date"], today)
        self.assertEqual(len(items), 16)
        self.assertEqual(sources, {})

    def test_delivery_receipt_is_written_after_success(self):
        from send_edition_email import TIMEZONE
        today = datetime.now(TIMEZONE).date().isoformat()
        edition = dict(self.edition, edition_date=today)
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"WORLD_SHARDS_ARCHIVE_DIR": directory}
        ):
            save_delivery_receipt(edition)
            with open(os.path.join(directory, "delivery-receipt.json"), encoding="utf-8") as handle:
                receipt = json.load(handle)
        self.assertEqual(receipt["edition_date"], today)
        self.assertEqual(receipt["status"], "sent")

    def test_retries_transient_smtp_connection_failure(self):
        class FakeSMTP:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False
            def login(self, sender, password):
                return None
            def send_message(self, message):
                return None

        with patch.dict(os.environ, {
            "MAIL_USERNAME": "sender@example.org",
            "MAIL_PASSWORD": "test-password",
            "NOTIFY_EMAIL": "reader@example.org",
        }), patch("send_edition_email.smtplib.SMTP_SSL",
                 side_effect=[OSError("temporary network issue"), FakeSMTP()]) as smtp, \
             patch("send_edition_email.time.sleep"):
            self.assertTrue(send_email("plain", "<p>html</p>", "2026. 11. 28."))
            self.assertEqual(smtp.call_count, 2)

    def test_rejects_missing_article(self):
        with self.assertRaises(RuntimeError):
            validate_edition(self.edition, self.items[:-1])

    def test_rejects_incomplete_article(self):
        broken = [dict(item) for item in self.items]
        broken[0]["display_body"] = ""
        with self.assertRaises(RuntimeError):
            validate_edition(self.edition, broken)

    def test_email_contains_all_sixteen_full_bodies(self):
        plain, rendered, date_label = build_email_bodies(self.edition, self.items, {})
        self.assertEqual(date_label, "2026. 11. 26.")
        for number in range(1, 17):
            self.assertIn(f"Teljes szöveg {number}", plain)
            self.assertIn(f"Teljes szöveg {number}", rendered)

    def test_email_opens_with_hungarian_then_world_agora(self):
        plain, rendered, _ = build_email_bodies(self.edition, self.items, {})
        self.assertLess(plain.index("MAGYAR AGORA"), plain.index("WORLD AGORA"))
        self.assertLess(plain.index("WORLD AGORA"), plain.index("Cím 1"))
        self.assertLess(rendered.index("Magyar AGORA"), rendered.index("WORLD AGORA"))
        self.assertLess(rendered.index("WORLD AGORA"), rendered.index("Cím 1"))

    def test_email_separates_both_agora_sections(self):
        plain, rendered, _ = build_email_bodies(self.edition, self.items, {})
        self.assertIn("MAGYAR AGORA", plain)
        self.assertIn("WORLD AGORA", plain)
        self.assertIn("Magyar AGORA", rendered)
        self.assertIn("WORLD AGORA", rendered)

    def test_image_is_rendered_in_html_and_linked_in_plain_text(self):
        sources = {
            "content-1": {
                "source_name": "Art Institute",
                "source_url": "https://example.org/art",
                "image_url": "https://images.example.org/artwork.jpg",
                "metadata": {"alt_text": "Festmény részlete"},
            }
        }
        plain, rendered, _ = build_email_bodies(self.edition, self.items, sources)
        self.assertIn("Kép: https://images.example.org/artwork.jpg", plain)
        self.assertIn('src="https://images.example.org/artwork.jpg"', rendered)
        self.assertIn('alt="Festmény részlete"', rendered)

    def test_rejects_non_http_image_urls(self):
        from send_edition_email import get_image_details
        image, _ = get_image_details({"image_url": "javascript:alert(1)"})
        self.assertIsNone(image)

    def test_signed_rating_links_cover_all_five_scores(self):
        secret = "test-signing-secret-that-is-long-enough-123456"
        voter = str(uuid.uuid4())
        now = datetime(2026, 11, 26, tzinfo=timezone.utc)
        links = build_rating_links(
            self.items[:1],
            "https://example.supabase.co",
            secret,
            voter,
            now=now,
        )
        item_id = self.items[0]["id"]
        self.assertEqual(set(links[item_id]), {1, 2, 3, 4, 5})
        query = parse_qs(urlparse(links[item_id][4]).query)
        self.assertEqual(query["rating"], ["4"])
        self.assertEqual(query["item_id"], [item_id])
        self.assertEqual(query["voter_token"], [voter])
        self.assertTrue(query["sig"][0])

    def test_email_renders_five_rating_links(self):
        secret = "test-signing-secret-that-is-long-enough-123456"
        links = build_rating_links(
            self.items[:1],
            "https://example.supabase.co",
            secret,
            str(uuid.uuid4()),
            now=datetime(2026, 11, 26, tzinfo=timezone.utc),
        )
        _, rendered, _ = build_email_bodies(
            self.edition, self.items[:1], {}, links
        )
        self.assertEqual(rendered.count('aria-label="1 csillag"'), 1)
        self.assertIn("A választás a megnyíló oldalon külön megerősítést igényel.", rendered)

if __name__ == "__main__":
    unittest.main()
