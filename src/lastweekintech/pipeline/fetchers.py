import requests
import feedparser
import time
from datetime import datetime, timedelta
from typing import List
from .ports import SourceFetcher
from .domain import Article
from .config import config

class HNFetcher(SourceFetcher):
    """Fetches articles from Hacker News using the Algolia API."""

    API_URL = "http://hn.algolia.com/api/v1/search_by_date"

    def fetch(self, since_ts: int, until_ts: int) -> List[Article]:
        """
        Fetches stories from HN that were created within the given timestamp range.
        """
        min_points = config.get('hn', {}).get('min_points', 0)
        query = f"points>={min_points}"

        numeric_filters = f"created_at_i>={since_ts},created_at_i<{until_ts}"

        params = {
            "query": query,
            "tags": "story",
            "numericFilters": numeric_filters,
            "hitsPerPage": 1000  # Max allowed
        }

        try:
            response = requests.get(self.API_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            print(f"Error fetching from HN: {e}")
            return []

        articles = []
        for hit in data.get("hits", []):
            if not hit.get("url") or not hit.get("title"):
                continue

            article = Article(
                id=0, # Will be set by the database layer
                source="HackerNews",
                title=hit["title"],
                url=hit["url"],
                published=hit["created_at_i"],
                hn_points=hit.get("points"),
                hn_comments=hit.get("num_comments"),
                content=None
            )
            articles.append(article)

        return articles

class RSSFetcher(SourceFetcher):
    """Fetches articles from a list of RSS feeds."""

    def fetch(self, since_ts: int, until_ts: int) -> List[Article]:
        """
        Fetches posts from the configured RSS feeds if they were published
        within the given timestamp range.
        """
        articles = []
        feeds = config.get("feeds", [])

        for feed_info in feeds:
            feed_name = feed_info.get("name", "Unknown")
            feed_url = feed_info.get("url")
            if not feed_url:
                continue

            try:
                parsed_feed = feedparser.parse(feed_url)
            except Exception as e:
                print(f"Error parsing feed {feed_name}: {e}")
                continue

            for entry in parsed_feed.entries:
                published_ts = 0
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_ts = int(time.mktime(entry.published_parsed))

                if since_ts <= published_ts < until_ts:
                    article = Article(
                        id=0,
                        source=feed_name,
                        title=entry.title,
                        url=entry.link,
                        published=published_ts,
                        content=entry.get("summary") # As a fallback
                    )
                    articles.append(article)

        return articles

if __name__ == '__main__':
    # Test the fetchers
    now = datetime.now()
    until_timestamp = int(now.timestamp())
    since_timestamp = int((now - timedelta(days=config.get('window_days', 7))).timestamp())

    print("--- Testing HNFetcher ---")
    hn_fetcher = HNFetcher()
    hn_articles = hn_fetcher.fetch(since_timestamp, until_timestamp)
    print(f"Fetched {len(hn_articles)} articles from Hacker News.")
    if hn_articles:
        print("Sample:", hn_articles[0])

    print("\n--- Testing RSSFetcher ---")
    rss_fetcher = RSSFetcher()
    rss_articles = rss_fetcher.fetch(since_timestamp, until_timestamp)
    print(f"Fetched {len(rss_articles)} articles from RSS feeds.")
    if rss_articles:
        print("Sample:", rss_articles[0])
