from app.integrations.intelligence import clean_text, safe_external_url
from app.integrations.news import parse_feed, validate_feed_url_syntax


def test_parse_rss_feed():
    xml = b"""<?xml version='1.0'?>
    <rss version='2.0'><channel><item>
      <title>USD rises after data</title>
      <description><![CDATA[Markets <b>react</b> to data]]></description>
      <link>https://example.com/story/1</link>
      <guid>story-1</guid>
      <pubDate>Tue, 17 Nov 2026 10:00:00 GMT</pubDate>
    </item></channel></rss>"""
    items = parse_feed(xml)
    assert len(items) == 1
    assert items[0]["title"] == "USD rises after data"
    assert items[0]["external_id"] == "story-1"
    assert items[0]["url"] == "https://example.com/story/1"
    assert items[0]["summary"]


def test_parse_atom_feed():
    xml = b"""<?xml version='1.0'?>
    <feed xmlns='http://www.w3.org/2005/Atom'><entry>
      <title>Gold market update</title>
      <id>tag:example.com,2026:2</id>
      <link href='https://example.com/gold'/>
      <updated>2026-11-17T10:00:00Z</updated>
      <summary>Gold prices move</summary>
    </entry></feed>"""
    items = parse_feed(xml)
    assert len(items) == 1
    assert items[0]["title"] == "Gold market update"
    assert items[0]["url"] == "https://example.com/gold"


def test_feed_requires_https_and_rejects_credentials():
    assert validate_feed_url_syntax("https://example.com/feed.xml")
    for url in ("http://example.com/feed", "https://user:pass@example.com/feed",
                "https://localhost/feed", "https://example.local/feed"):
        try:
            validate_feed_url_syntax(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"URL should have been rejected: {url}")


def test_external_links_require_https():
    assert safe_external_url("https://example.com/a") == "https://example.com/a"
    assert safe_external_url("http://example.com/a") is None
    assert safe_external_url("https://user:pass@example.com/a") is None


def test_html_is_removed_from_news_text():
    assert clean_text("<p>Market <b>moves</b></p>") == "Market moves"
