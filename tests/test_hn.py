"""Tests for the Hacker News importance signal."""

from datetime import UTC

from conftest import NOW, make_article

from lastweekintech import hn


def hit(object_id="1", title="A story", url="https://example.com/a", points=120, created=None):
    return {
        "objectID": object_id,
        "title": title,
        "url": url,
        "points": points,
        "num_comments": 10,
        "created_at_i": int((created or NOW).timestamp()),
    }


class TestParseHits:
    def test_maps_a_hit_onto_an_article(self):
        [article] = hn.parse_hits([hit(title="Big news", url="https://example.com/x", points=340)])
        assert (article.title, article.url, article.hn_points) == (
            "Big news",
            "https://example.com/x",
            340,
        )

    def test_labels_the_source_as_hacker_news(self):
        [article] = hn.parse_hits([hit()])
        assert article.source == hn.HN_SOURCE

    def test_converts_the_unix_timestamp_to_an_aware_datetime(self):
        [article] = hn.parse_hits([hit()])
        assert article.published_at == NOW.astimezone(UTC)

    def test_falls_back_to_the_discussion_permalink_for_text_posts(self):
        [article] = hn.parse_hits([hit(object_id="42", url=None)])
        assert article.url == "https://news.ycombinator.com/item?id=42"

    def test_skips_hits_without_a_title(self):
        assert hn.parse_hits([hit(title=None)]) == []

    def test_treats_missing_points_as_zero(self):
        [article] = hn.parse_hits([{"objectID": "7", "title": "T", "url": "https://e.com/t"}])
        assert article.hn_points == 0


class TestBuildSearchParams:
    def test_restricts_to_stories_in_the_window_above_the_point_threshold(self, config):
        params = hn.build_search_params(config, now=NOW)
        assert params["tags"] == "story"
        assert f"points>={config.hn.min_points}" in params["numericFilters"]
        expected_cutoff = int(NOW.timestamp()) - config.window_days * 86400
        assert f"created_at_i>{expected_cutoff}" in params["numericFilters"]

    def test_requests_at_most_the_configured_limit(self, config):
        assert hn.build_search_params(config, now=NOW)["hitsPerPage"] == config.hn.limit


class TestFetchHnArticles:
    def test_returns_articles_from_the_api(self, config):
        fetch = lambda url, params: {"hits": [hit(), hit(object_id="2", url="https://e.com/2")]}
        assert len(hn.fetch_hn_articles(config, now=NOW, fetch=fetch)) == 2

    def test_drops_hits_below_the_point_threshold(self, config):
        fetch = lambda url, params: {"hits": [hit(points=5), hit(object_id="2", points=500)]}
        articles = hn.fetch_hn_articles(config, now=NOW, fetch=fetch)
        assert [a.hn_points for a in articles] == [500]

    def test_returns_nothing_when_disabled(self, config):
        config.hn.enabled = False

        def fetch(url, params):
            raise AssertionError("must not call the API when disabled")

        assert hn.fetch_hn_articles(config, now=NOW, fetch=fetch) == []

    def test_survives_an_api_failure(self, config):
        def fetch(url, params):
            raise OSError("network down")

        assert hn.fetch_hn_articles(config, now=NOW, fetch=fetch) == []


class TestMergeHnPoints:
    def test_attaches_points_to_the_same_story_from_another_outlet(self):
        articles = [make_article(url="https://example.com/story?utm_source=rss", source="WIRED")]
        hn_articles = [make_article(url="https://example.com/story", hn_points=250)]
        assert hn.merge_hn_points(articles, hn_articles)[0].hn_points == 250

    def test_leaves_unrelated_articles_alone(self):
        articles = [make_article(url="https://example.com/other")]
        hn_articles = [make_article(url="https://example.com/story", hn_points=250)]
        assert hn.merge_hn_points(articles, hn_articles)[0].hn_points is None

    def test_keeps_the_highest_point_total(self):
        articles = [make_article(url="https://example.com/s", hn_points=400)]
        hn_articles = [make_article(url="https://example.com/s", hn_points=100)]
        assert hn.merge_hn_points(articles, hn_articles)[0].hn_points == 400
