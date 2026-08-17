"""Tests for feed ingestion and content extraction."""

import time
from datetime import timedelta

import pytest
from conftest import NOW, make_article

from lastweekintech import pipeline
from lastweekintech.config import Feed


class FakeEntry(dict):
    """feedparser entries expose keys as attributes."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def entry(title="A story", link="https://example.com/a", age_hours=1.0):
    published = NOW - timedelta(hours=age_hours)
    return FakeEntry(title=title, link=link, published_parsed=published.utctimetuple())


def feed_with(*entries):
    return lambda url: FakeEntry(entries=list(entries), bozo=0)


class TestFetchArticles:
    def test_keeps_entries_inside_the_window(self, config):
        articles = pipeline.fetch_articles(config, now=NOW, parse=feed_with(entry()))
        assert len(articles) == 1

    def test_drops_entries_older_than_the_window(self, config):
        parse = feed_with(entry(age_hours=24 * 30))
        assert pipeline.fetch_articles(config, now=NOW, parse=parse) == []

    def test_uses_the_configured_feed_name_as_the_source(self, config):
        [article] = pipeline.fetch_articles(config, now=NOW, parse=feed_with(entry()))
        assert article.source == "Example"

    def test_does_not_invent_hacker_news_points_from_the_title(self, config):
        """Points come from the Algolia API; titles never reliably carried them."""
        parse = feed_with(entry(title="A story (250 points)"))
        [article] = pipeline.fetch_articles(config, now=NOW, parse=parse)
        assert article.hn_points is None

    def test_keeps_entries_that_have_no_publication_date(self, config):
        parse = feed_with(FakeEntry(title="Undated", link="https://example.com/u"))
        assert len(pipeline.fetch_articles(config, now=NOW, parse=parse)) == 1

    def test_skips_entries_without_a_link(self, config):
        parse = feed_with(FakeEntry(title="No link", published_parsed=NOW.utctimetuple()))
        assert pipeline.fetch_articles(config, now=NOW, parse=parse) == []

    def test_one_broken_feed_does_not_stop_the_others(self, config):
        config.feeds = [Feed(name="Broken", url="b"), Feed(name="Working", url="w")]

        def parse(url):
            if url == "b":
                raise OSError("feed is down")
            return FakeEntry(entries=[entry()], bozo=0)

        [article] = pipeline.fetch_articles(config, now=NOW, parse=parse)
        assert article.source == "Working"


class TestExtractArticleText:
    """The HTML-to-text step, exercised without the network."""

    def page(self, body, extra=""):
        paragraphs = "".join(f"<p>{p}</p>" for p in body)
        return (
            "<html><head><title>A story</title></head><body>"
            f"<article>{paragraphs}</article>{extra}</body></html>"
        )

    def test_extracts_the_article_body(self):
        html = self.page(["The council voted on the measure at length. " * 8])
        assert "council voted" in pipeline.extract_article_text(html, "https://example.com/a")

    def test_returns_empty_string_when_there_is_no_article(self):
        assert pipeline.extract_article_text("<html><body></body></html>", "https://x.test/") == ""

    def test_survives_input_that_is_not_html(self):
        assert pipeline.extract_article_text("not html at all", "https://x.test/") == ""

    def test_accepts_bytes_so_the_encoding_is_detected_from_the_document(self):
        html = self.page(["Le conseil a voté très longuement à ce sujet. " * 8])
        text = pipeline.extract_article_text(html.encode("utf-8"), "https://example.fr/a")
        assert "voté" in text

    def story_paragraphs(self, n=20):
        return [
            f"The council voted on measure {i} after a long and detailed public debate."
            for i in range(n)
        ]

    def test_drops_a_recirculation_block_that_outranks_the_body(self):
        """Some outlets wrap "more stories" lists in a container the extractor
        ranks above the article; The Register served its sidebar as the body."""
        recirc = (
            "<div class='related'>"
            + "".join(
                f"<p>Unrelated headline number {i} about something else entirely.</p>"
                for i in range(200)
            )
            + "</div>"
        )
        html = self.page(self.story_paragraphs(), extra=recirc)
        text = pipeline.extract_article_text(html, "https://example.com/a")
        assert "council voted" in text
        assert "Unrelated headline" not in text

    def test_prefers_the_article_even_when_the_junk_block_is_far_longer(self):
        """The guard is an absolute floor, not a ratio: a recirculation block
        many times the length of the story must still lose to the story."""
        recirc = (
            "<div class='sidebar'>"
            + "".join(
                f"<p>Filler headline {i} about another topic entirely.</p>" for i in range(600)
            )
            + "</div>"
        )
        html = self.page(self.story_paragraphs(), extra=recirc)
        assert "council voted" in pipeline.extract_article_text(html, "https://example.com/a")

    def test_keeps_the_unpruned_body_when_pruning_would_eat_the_article(self):
        """A page whose article itself sits in a "related" container must not be
        emptied by the pruning step."""
        body = "".join(f"<p>{p}</p>" for p in self.story_paragraphs(40))
        html = f"<html><body><div class='related-content'>{body}</div></body></html>"
        assert "council voted" in pipeline.extract_article_text(html, "https://example.com/a")


class TestDownloadArticleText:
    """The default downloader, with the HTTP call stubbed out."""

    class FakeResponse:
        def __init__(self, content=b"", status=200):
            self.content = content
            self.status = status

        def raise_for_status(self):
            if self.status >= 400:
                raise OSError(f"HTTP {self.status}")

    def capture(self, monkeypatch, response):
        calls = {}

        def fake_get(url, **kwargs):
            calls["url"] = url
            calls.update(kwargs)
            return response

        monkeypatch.setattr(pipeline.requests, "get", fake_get)
        return calls

    def test_sends_a_browser_user_agent_and_a_timeout(self, monkeypatch):
        """A default agent gets the weekly batch 403'd, and no timeout hangs it."""
        calls = self.capture(monkeypatch, self.FakeResponse())
        pipeline._download_article_text("https://example.com/a")
        assert "Mozilla/5.0" in calls["headers"]["User-Agent"]
        assert calls["timeout"] == pipeline.REQUEST_TIMEOUT

    def test_raises_on_an_error_response_so_the_caller_records_a_failure(self, monkeypatch):
        self.capture(monkeypatch, self.FakeResponse(status=403))
        with pytest.raises(OSError):
            pipeline._download_article_text("https://example.com/a")

    def test_returns_the_extracted_body(self, monkeypatch):
        paragraphs = "".join(
            f"<p>The council voted on measure {i} after a long and detailed debate.</p>"
            for i in range(20)
        )
        html = f"<html><body><article>{paragraphs}</article></body></html>".encode()
        self.capture(monkeypatch, self.FakeResponse(content=html))
        assert "council voted" in pipeline._download_article_text("https://example.com/a")


class TestExtractContent:
    def test_fills_in_the_extracted_body(self):
        articles = [make_article(content=None)]
        result = pipeline.extract_content(articles, download=lambda url: "the body", delay=0)
        assert result[0].content == "the body"

    def test_keeps_articles_whose_extraction_returned_nothing(self):
        """An empty body is not a reason to drop a story; another article may cover it."""
        articles = [make_article(url="https://example.com/paywalled", content=None)]
        result = pipeline.extract_content(articles, download=lambda url: "", delay=0)
        assert len(result) == 1
        assert not result[0].content

    def test_keeps_articles_whose_extraction_failed(self):
        def download(url):
            raise OSError("403")

        result = pipeline.extract_content([make_article()], download=download, delay=0)
        assert len(result) == 1

    def test_extracts_every_article(self):
        articles = [make_article(url=f"https://example.com/{i}") for i in range(12)]
        result = pipeline.extract_content(articles, download=lambda url: url, delay=0)
        assert {a.content for a in result} == {a.url for a in articles}

    def test_runs_downloads_concurrently(self):
        articles = [make_article(url=f"https://host{i}.example/a") for i in range(8)]

        def download(url):
            time.sleep(0.05)
            return "body"

        started = time.monotonic()
        pipeline.extract_content(articles, download=download, delay=0, max_workers=8)
        assert time.monotonic() - started < 0.3

    def test_spaces_out_requests_to_the_same_host(self):
        articles = [make_article(url=f"https://same.example/{i}") for i in range(3)]
        calls = []

        def download(url):
            calls.append(time.monotonic())
            return "body"

        pipeline.extract_content(articles, download=download, delay=0.05, max_workers=4)
        assert calls[-1] - calls[0] >= 0.1
