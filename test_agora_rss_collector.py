import unittest

import agora_rss_collector as collector


class AgoraRssCollectorTests(unittest.TestCase):

    def test_rss_item_normalization(self):
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item>
            <title>  Árvízvédelem &amp; felkészülés </title>
            <link>https://example.hu/hir/123?source=rss#top</link>
            <description><![CDATA[<p>Első <b>összefoglaló</b>.</p>]]></description>
            <pubDate>Thu, 26 Nov 2026 10:00:00 +0100</pubDate>
            <guid>story-123</guid>
          </item>
        </channel></rss>"""

        items = collector.extract_entries(xml)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Árvízvédelem & felkészülés")
        self.assertEqual(
            items[0]["url"],
            "https://example.hu/hir/123?source=rss",
        )
        self.assertEqual(items[0]["summary"], "Első összefoglaló.")
        self.assertEqual(items[0]["guid"], "story-123")
        self.assertEqual(
            items[0]["published_at"],
            "2026-11-26T09:00:00+00:00",
        )

    def test_atom_entry_link_and_date(self):
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>International event</title>
            <link href="https://example.com/world/story"/>
            <summary>Short summary</summary>
            <updated>2026-11-26T11:30:00Z</updated>
            <id>tag:example.com,2026:story</id>
          </entry>
        </feed>"""

        items = collector.extract_entries(xml)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.com/world/story")
        self.assertEqual(
            items[0]["published_at"],
            "2026-11-26T11:30:00+00:00",
        )

    def test_invalid_or_missing_article_url_is_rejected(self):
        xml = """<rss><channel>
          <item><title>No link</title><description>Text</description></item>
          <item><title>Bad link</title><link>javascript:alert(1)</link></item>
        </channel></rss>"""

        self.assertEqual(collector.extract_entries(xml), [])

    def test_url_fragment_removed_but_query_preserved(self):
        self.assertEqual(
            collector.normalize_url("HTTPS://Example.COM/a?x=1#part"),
            "https://example.com/a?x=1",
        )

    def test_missing_or_invalid_date_is_none(self):
        self.assertIsNone(collector.parse_timestamp(None))
        self.assertIsNone(collector.parse_timestamp("not a date"))


if __name__ == "__main__":
    unittest.main()
