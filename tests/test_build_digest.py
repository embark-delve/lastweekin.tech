"""End-to-end tests for the digest pipeline with the network stubbed out."""

import json
from datetime import timedelta

from conftest import NOW
from test_fetch import FakeEntry

from lastweekintech import pipeline
from lastweekintech.config import Feed
from lastweekintech.metrics import RunMetrics
from lastweekintech.text import CATEGORIES


class FakeSummarizer:
    def __init__(self, text="A complete summary of what happened this week."):
        self.text = text
        self.seen = []

    def summarize(self, content):
        self.seen.append(content)
        return self.text


def entry(title, link, age_hours=1.0):
    return FakeEntry(
        title=title,
        link=link,
        published_parsed=(NOW - timedelta(hours=age_hours)).utctimetuple(),
    )


def feeds_for(mapping):
    return lambda url: FakeEntry(entries=mapping.get(url, []), bozo=0)


# Distinct subjects, so the clusterer keeps them apart.
SUBJECTS = [
    "Rust compiler drops its bootstrap stage",
    "Postgres 19 lands with faster vacuum",
    "SpaceX slips its next Starship flight",
    "Nintendo patches a Switch exploit",
    "EU antitrust regulators open a probe",
    "Signal adds usernames for everyone",
    "Backblaze publishes drive failure stats",
    "Framework laptop gains a new mainboard",
    "Chrome ships a faster JavaScript parser",
    "Cloudflare outage takes down half the web",
    "Debian votes on a systemd successor",
    "Raspberry Pi raises the price of the Zero",
]


def unique_entries(count, prefix="https://ars.example"):
    return [
        entry(f"{SUBJECTS[i % len(SUBJECTS)]} ({i})", f"{prefix}/{i}", age_hours=1 + i)
        for i in range(count)
    ]


def small_config(config, story_count=3, min_ai=1):
    config.digest.story_count = story_count
    config.digest.min_ai_stories = min_ai
    config.feeds = [Feed(name="Ars Technica", url="ars"), Feed(name="WIRED", url="wired")]
    return config


def run(config, **overrides):
    summarizer = overrides.pop("summarizer", FakeSummarizer())
    kwargs = {
        "now": NOW,
        "parse": feeds_for({}),
        "download": lambda url: f"body for {url}",
        "hn_fetch": lambda url, params: {"hits": []},
        "delay": 0,
    }
    digest = pipeline.build_digest(config, summarizer, **(kwargs | overrides))
    return digest.stories, summarizer


class TestBuildDigest:
    def test_produces_the_requested_number_of_stories(self, config):
        parse = feeds_for({"ars": unique_entries(5), "wired": []})
        stories, _ = run(small_config(config), parse=parse)
        assert len(stories) == 3

    def test_ranks_a_story_covered_by_two_outlets_above_a_solo_story(self, config):
        parse = feeds_for({
            "ars": [
                entry("Google announces new AI chip for data centers", "https://ars.example/chip"),
                entry("A quiet gadget review of some headphones", "https://ars.example/quiet"),
            ],
            "wired": [
                entry(
                    "Google's new AI chip unveiled to boost data centers",
                    "https://wired.example/chip",
                ),
            ],
        })
        stories, _ = run(small_config(config, story_count=2), parse=parse)
        assert stories[0].articles.__len__() == 2

    def test_hacker_news_traction_lifts_a_story(self, config):
        parse = feeds_for({
            "ars": [
                entry("An obscure kernel change lands quietly", "https://ars.example/k", 100),
                entry("A routine gadget review of headphones", "https://ars.example/g", 1),
            ],
            "wired": [],
        })
        hn_fetch = lambda url, params: {
            "hits": [
                {
                    "objectID": "1",
                    "title": "An obscure kernel change lands quietly",
                    "url": "https://ars.example/kernel",
                    "points": 500,
                    "created_at_i": int(NOW.timestamp()),
                }
            ]
        }
        stories, _ = run(small_config(config, story_count=1), parse=parse, hn_fetch=hn_fetch)
        assert stories[0].title == "An obscure kernel change lands quietly"

    def test_includes_hacker_news_stories_no_feed_covered(self, config):
        hn_fetch = lambda url, params: {
            "hits": [
                {
                    "objectID": "1",
                    "title": "A show HN project nobody else covered",
                    "url": "https://hn.example/project",
                    "points": 300,
                    "created_at_i": int(NOW.timestamp()),
                }
            ]
        }
        stories, _ = run(small_config(config, story_count=1), hn_fetch=hn_fetch)
        assert stories[0].title == "A show HN project nobody else covered"

    def test_applies_the_ai_floor(self, config):
        parse = feeds_for({
            "ars": [
                *unique_entries(5),
                entry("Anthropic ships a new model", "https://ars.example/ai", age_hours=100),
            ],
            "wired": [],
        })
        stories, _ = run(small_config(config, story_count=3, min_ai=1), parse=parse)
        assert sum(s.category == "AI" for s in stories) == 1

    def test_only_extracts_content_for_candidate_stories(self, config):
        """Downloading every article of the week is the slowest part of the run."""
        parse = feeds_for({"ars": unique_entries(12), "wired": []})
        downloaded = []
        config = small_config(config, story_count=3)
        config.digest.candidate_pool = 10
        run(config, parse=parse, download=lambda url: downloaded.append(url) or "body")
        assert len(downloaded) == 10

    def test_summarizes_every_selected_story(self, config):
        parse = feeds_for({"ars": unique_entries(5), "wired": []})
        stories, summarizer = run(small_config(config), parse=parse)
        assert all(s.summary == summarizer.text for s in stories)

    def test_survives_every_feed_being_down(self, config):
        def parse(url):
            raise OSError("no network")

        stories, _ = run(small_config(config), parse=parse)
        assert stories == []

    def test_excludes_stories_published_in_a_recent_edition(self, config):
        parse = feeds_for({"ars": unique_entries(6), "wired": []})
        published = [
            {
                "week": (NOW - timedelta(days=7)).strftime("%Y-%m-%d"),
                "stories": [{"title": "already ran", "url": "https://ars.example/0"}],
            }
        ]
        stories, _ = run(small_config(config), parse=parse, editions=published)
        assert all(a.url != "https://ars.example/0" for s in stories for a in s.articles)

    def test_still_fills_the_edition_when_everything_is_a_repeat(self, config):
        parse = feeds_for({"ars": unique_entries(5), "wired": []})
        published = [
            {
                "week": (NOW - timedelta(days=7)).strftime("%Y-%m-%d"),
                "stories": [{"title": "ran", "url": f"https://ars.example/{i}"} for i in range(5)],
            }
        ]
        stories, _ = run(small_config(config, story_count=3), parse=parse, editions=published)
        assert len(stories) == 3


class TestRunMetrics:
    """Every run should leave behind a record of what actually happened."""

    def collect(self, config, **overrides):
        metrics = RunMetrics(week="2026-08-10")
        stories, summarizer = run(config, metrics=metrics, **overrides)
        return metrics, stories, summarizer

    def test_records_article_counts_before_and_after_dedupe(self, config):
        entries = unique_entries(4)
        parse = feeds_for({"ars": entries, "wired": entries})  # both feeds, same URLs
        metrics, _, _ = self.collect(small_config(config), parse=parse)
        assert metrics.articles_from_feeds == 8
        assert metrics.articles_before_dedupe == 8
        assert metrics.articles_after_dedupe == 4

    def test_records_hacker_news_article_count(self, config):
        hn_fetch = lambda url, params: {
            "hits": [
                {
                    "objectID": "1",
                    "title": "A show HN project",
                    "url": "https://hn.example/p",
                    "points": 300,
                    "created_at_i": int(NOW.timestamp()),
                }
            ]
        }
        metrics, _, _ = self.collect(small_config(config, story_count=1), hn_fetch=hn_fetch)
        assert metrics.articles_from_hn == 1

    def test_records_clustering_breadth(self, config):
        parse = feeds_for({
            "ars": [entry("Google announces new AI chip for data centers", "https://a/1")],
            "wired": [entry("Google's new AI chip unveiled to boost data centers", "https://b/1")],
        })
        metrics, _, _ = self.collect(small_config(config, story_count=1), parse=parse)
        assert metrics.stories == 1
        assert metrics.multi_source_stories == 1
        assert metrics.max_sources == 2

    def test_records_extraction_successes_and_failures(self, config):
        parse = feeds_for({"ars": unique_entries(4), "wired": []})

        def download(url):
            if url.endswith(("0", "1")):
                raise OSError("paywall")
            return "a body"

        metrics, _, _ = self.collect(small_config(config), parse=parse, download=download)
        assert metrics.extraction_failed == 2
        assert metrics.extraction_succeeded == 2

    def test_records_how_much_of_the_ranking_the_candidate_pool_covered(self, config):
        cfg = small_config(config, story_count=3)
        cfg.digest.candidate_pool = 5
        parse = feeds_for({"ars": unique_entries(12), "wired": []})
        metrics, _, _ = self.collect(cfg, parse=parse)
        assert metrics.stories == 12
        assert metrics.candidate_stories == 5

    def test_records_the_ai_count_before_and_after_promotion(self, config):
        """The natural count is the honest one; promotion is the floor doing work."""
        parse = feeds_for({
            "ars": [
                *unique_entries(5),
                entry("Anthropic ships a new model", "https://ars.example/ai", age_hours=100),
            ],
            "wired": [],
        })
        metrics, _, _ = self.collect(small_config(config, story_count=3, min_ai=1), parse=parse)
        assert metrics.ai_before_promotion == 0
        assert metrics.ai_promoted == 1
        assert metrics.ai_published == 1

    def test_records_no_promotion_when_the_ranking_already_meets_the_floor(self, config):
        parse = feeds_for({
            "ars": [entry("Anthropic ships a new model", "https://ars.example/ai")],
            "wired": [],
        })
        metrics, _, _ = self.collect(small_config(config, story_count=1, min_ai=1), parse=parse)
        assert metrics.ai_before_promotion == 1
        assert metrics.ai_promoted == 0

    def test_records_the_category_spread(self, config):
        parse = feeds_for({"ars": unique_entries(3), "wired": []})
        metrics, _, _ = self.collect(small_config(config), parse=parse)
        assert sum(metrics.categories.values()) == metrics.candidate_stories
        assert set(metrics.categories) <= set(CATEGORIES)

    def test_records_which_model_produced_each_summary(self, config):
        parse = feeds_for({"ars": unique_entries(2), "wired": []})
        summarizer = FakeSummarizer()
        summarizer.last_model = "test/model-a"
        metrics, stories, _ = self.collect(
            small_config(config, story_count=2), parse=parse, summarizer=summarizer
        )
        assert metrics.summaries == 2
        assert set(metrics.summary_models.values()) == {"test/model-a"}
        assert set(metrics.summary_models) == {s.title for s in stories}

    def test_records_failed_summaries(self, config):
        parse = feeds_for({"ars": unique_entries(2), "wired": []})
        metrics, _, _ = self.collect(
            small_config(config, story_count=2),
            parse=parse,
            summarizer=FakeSummarizer(text=""),
        )
        assert metrics.summaries == 0
        assert metrics.summaries_failed == 2

    def test_records_repeats_dropped_from_the_recent_archive(self, config):
        parse = feeds_for({"ars": unique_entries(6), "wired": []})
        published = [
            {
                "week": (NOW - timedelta(days=7)).strftime("%Y-%m-%d"),
                "stories": [{"title": "ran", "url": "https://ars.example/0"}],
            }
        ]
        metrics, _, _ = self.collect(small_config(config), parse=parse, editions=published)
        assert metrics.repeats_dropped == 1

    def test_times_every_stage(self, config):
        parse = feeds_for({"ars": unique_entries(3), "wired": []})
        metrics, _, _ = self.collect(small_config(config), parse=parse)
        assert {
            "fetch",
            "dedupe",
            "cluster",
            "score",
            "extract",
            "categorize",
            "select",
            "summarize",
        } <= set(metrics.stage_seconds)
        assert all(v >= 0 for v in metrics.stage_seconds.values())

    def test_the_record_is_json_serializable(self, config):
        parse = feeds_for({"ars": unique_entries(3), "wired": []})
        metrics, _, _ = self.collect(small_config(config), parse=parse)
        assert json.loads(json.dumps(metrics.to_dict()))["week"] == "2026-08-10"

    def test_the_run_works_without_a_metrics_record(self, config):
        parse = feeds_for({"ars": unique_entries(4), "wired": []})
        stories, _ = run(small_config(config), parse=parse, metrics=None)
        assert len(stories) == 3
