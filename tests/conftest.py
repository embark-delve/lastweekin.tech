"""Shared fixtures and builders for the test suite."""

from datetime import UTC, datetime, timedelta

import pytest

from lastweekintech.config import Config, Feed, HNSettings, SummarizerSettings, Weights
from lastweekintech.domain import Article, Story

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def make_article(
    title: str = "A story",
    url: str = "https://example.com/a",
    source: str = "Example",
    content: str | None = "body text",
    age_hours: float = 0.0,
    hn_points: int | None = None,
) -> Article:
    return Article(
        title=title,
        url=url,
        source=source,
        content=content,
        published_at=NOW - timedelta(hours=age_hours),
        hn_points=hn_points,
    )


def make_story(
    title: str = "A story",
    category: str = "General Tech",
    score: float = 0.0,
    articles: list[Article] | None = None,
) -> Story:
    story = Story(title=title, articles=articles or [make_article(title=title)])
    story.category = category
    story.score = score
    return story


@pytest.fixture
def config() -> Config:
    return Config(
        feeds=[Feed(name="Example", url="https://example.com/rss")],
        hn=HNSettings(min_points=50, points_cap=500, limit=100),
        weights=Weights(hn=5.0, src=3.0, rec=1.0),
        window_days=7,
        summarizer=SummarizerSettings(
            model_name="test/model",
            fallback_models=[],
            max_tokens=400,
            max_input_chars=12000,
        ),
    )
