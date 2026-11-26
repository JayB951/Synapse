import unittest
from send_edition_email import build_email_bodies, validate_edition

class EditionEmailTests(unittest.TestCase):
    def setUp(self):
        self.edition = {
            "edition_date": "2026-11-26",
            "status": "published",
            "introduction": "Napi bevezető",
        }
        counts = {
            "research_frontier": 5,
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
                    "content_item_id": f"content-{position}",
                    "section_code": section,
                    "position": position,
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

    def test_rejects_missing_article(self):
        with self.assertRaises(RuntimeError):
            validate_edition(self.edition, self.items[:-1])

    def test_rejects_incomplete_article(self):
        broken = [dict(item) for item in self.items]
        broken[0]["display_body"] = ""
        with self.assertRaises(RuntimeError):
            validate_edition(self.edition, broken)

    def test_email_contains_all_fourteen_full_bodies(self):
        plain, rendered, date_label = build_email_bodies(self.edition, self.items, {})
        self.assertEqual(date_label, "2026. 11. 26.")
        for number in range(1, 15):
            self.assertIn(f"Teljes szöveg {number}", plain)
            self.assertIn(f"Teljes szöveg {number}", rendered)

if __name__ == "__main__":
    unittest.main()
