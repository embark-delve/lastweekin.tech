"""
Core data pipeline for LastWeekIn.Tech.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
from newspaper import Article as NewsArticle
from newspaper import Config as NewspaperConfig
from thefuzz import fuzz

from lastweekintech.config import Config
from lastweekintech.domain import Article, Story

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# Set up newspaper3k configuration
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
newspaper_config = NewspaperConfig()
newspaper_config.browser_user_agent = USER_AGENT
newspaper_config.request_timeout = 10
newspaper_config.fetch_images = False


def fetch_articles(config: Config) -> list[Article]:
    """Fetch articles from all configured RSS feeds."""
    articles = []
    time_window = timedelta(days=config.window_days)
    start_date = datetime.now(timezone.utc) - time_window

    for feed in config.feeds:
        logging.info(f"Fetching articles from {feed.name}...")
        try:
            parsed_feed = feedparser.parse(feed.url)
            for entry in parsed_feed.entries:
                published_at = (
                    datetime.fromtimestamp(time.mktime(entry.published_parsed))
                    .replace(tzinfo=timezone.utc)
                    if hasattr(entry, "published_parsed")
                    and entry.published_parsed
                    else datetime.now(timezone.utc)
                )

                if published_at >= start_date:
                    article = Article(
                        title=entry.title,
                        url=entry.link,
                        source=feed.name,
                        published_at=published_at,
                    )
                    articles.append(article)
        except Exception as e:
            logging.error(f"Failed to fetch or parse feed {feed.name}: {e}")
    logging.info(f"Fetched a total of {len(articles)} articles.")
    return articles


def extract_content(articles: list[Article]) -> list[Article]:
    """Extract full content for each article."""
    enriched_articles = []
    for i, article_meta in enumerate(articles):
        logging.info(
            f"Extracting content for article {i + 1}/{len(articles)}: {article_meta.title}"
        )
        try:
            article = NewsArticle(article_meta.url, config=newspaper_config)
            article.download()
            article.parse()
            article_meta.content = article.text
            enriched_articles.append(article_meta)
            # Be polite to servers
            time.sleep(0.5)
        except Exception as e:
            logging.warning(
                f"Failed to extract content from {article_meta.url}: {e}"
            )
    logging.info(f"Successfully extracted content for {len(enriched_articles)} articles.")
    return enriched_articles


def cluster_articles(articles: list[Article]) -> list[Story]:
    """Cluster articles into stories based on title similarity."""
    stories = []
    for article in articles:
        found_cluster = False
        for story in stories:
            # Using token_set_ratio for better matching of titles
            if fuzz.token_set_ratio(article.title, story.title) > 80:
                story.articles.append(article)
                found_cluster = True
                break
        if not found_cluster:
            stories.append(Story(title=article.title, articles=[article]))
    logging.info(f"Clustered {len(articles)} articles into {len(stories)} stories.")
    return stories


def score_stories(stories: list[Story], config: Config) -> list[Story]:
    """Score stories based on various factors."""
    for story in stories:
        # Simple scoring: number of sources
        score = len(story.articles) * config.weights.src
        story.score = score
    return sorted(stories, key=lambda s: s.score, reverse=True)


def select_top_stories(stories: list[Story], count: int = 7) -> list[Story]:
    """Select the top N stories."""
    # Placeholder for AI story enforcement
    return stories[:count]


def summarize_stories(stories: list[Story]) -> list[Story]:
    """Generate a summary for each story."""
    for story in stories:
        # Placeholder summarization: take the first 3 sentences of the first article
        if story.articles and story.articles[0].content:
            content = story.articles[0].content
            sentences = content.split('.')
            summary = ". ".join(sentences[:3]) + "."
            story.summary = summary
        else:
            story.summary = "Summary not available."
    logging.info("Generated summaries for all stories.")
    return stories


def save_stories_to_json(stories: list[Story], output_path: Path):
    """Save the final stories to a JSON file."""
    output_data = {
        "week": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "stories": [],
    }

    for i, story in enumerate(stories):
        # Use the first article for source and url
        main_article = story.articles[0] if story.articles else None
        output_data["stories"].append(
            {
                "rank": i + 1,
                "title": story.title,
                "source": main_article.source if main_article else "N/A",
                "url": main_article.url if main_article else "N/A",
                "category": "General Tech",  # Placeholder for category
                "summary": story.summary or "Summary not available.",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    logging.info(f"Saved stories to {output_path}")
