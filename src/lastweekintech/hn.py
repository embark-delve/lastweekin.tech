"""Hacker News signal via the Algolia search API.

Community traction is the pipeline's only measure of importance that is not a
proxy (breadth of coverage) or a tiebreaker (recency), so it is worth getting
from the API rather than scraping points out of feed titles — hnrss headlines
never carried them, which left the signal dead.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import requests

from lastweekintech.config import Config
from lastweekintech.domain import Article
from lastweekintech.text import normalize_url

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={}"
HN_SOURCE = "Hacker News"
REQUEST_TIMEOUT = 20

JsonFetcher = Callable[[str, dict[str, Any]], dict[str, Any]]


def build_search_params(config: Config, now: datetime | None = None) -> dict[str, Any]:
    """Build the Algolia query for stories in the window above the point threshold."""
    now = now or datetime.now(UTC)
    cutoff = int(now.timestamp()) - config.window_days * 86400
    return {
        "tags": "story",
        "numericFilters": f"created_at_i>{cutoff},points>={config.hn.min_points}",
        "hitsPerPage": config.hn.limit,
    }


def parse_hits(hits: list[dict[str, Any]]) -> list[Article]:
    """Convert Algolia hits into Articles."""
    articles = []
    for item in hits:
        title = item.get("title")
        if not title:
            continue

        object_id = item.get("objectID", "")
        created = item.get("created_at_i")
        articles.append(
            Article(
                title=title,
                url=item.get("url") or HN_ITEM_URL.format(object_id),
                source=HN_SOURCE,
                published_at=datetime.fromtimestamp(created, tz=UTC) if created else None,
                hn_points=int(item.get("points") or 0),
            )
        )
    return articles


def fetch_hn_articles(
    config: Config,
    now: datetime | None = None,
    fetch: JsonFetcher | None = None,
) -> list[Article]:
    """Fetch the week's Hacker News stories above ``hn.min_points``."""
    if not config.hn.enabled:
        return []

    fetch = fetch or _get_json
    try:
        payload = fetch(HN_SEARCH_URL, build_search_params(config, now))
    except Exception as exc:  # noqa: BLE001 - a dead HN API must not kill the run
        logging.error(f"Hacker News lookup failed, continuing without it: {exc}")
        return []

    articles = [
        article
        for article in parse_hits(payload.get("hits", []))
        if (article.hn_points or 0) >= config.hn.min_points
    ]
    logging.info(
        f"Fetched {len(articles)} Hacker News stories above {config.hn.min_points} points."
    )
    return articles


def merge_hn_points(articles: list[Article], hn_articles: list[Article]) -> list[Article]:
    """Attach Hacker News points to the same story as covered by other outlets."""
    points_by_url: dict[str, int] = {}
    for article in hn_articles:
        key = normalize_url(article.url)
        if key:
            points_by_url[key] = max(points_by_url.get(key, 0), article.hn_points or 0)

    matched = 0
    for article in articles:
        points = points_by_url.get(normalize_url(article.url))
        if points is None:
            continue
        if article.hn_points is None or points > article.hn_points:
            article.hn_points = points
        matched += 1

    logging.info(f"Matched Hacker News traction to {matched} articles.")
    return articles


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()
