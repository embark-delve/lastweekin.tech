"""
Core data pipeline for LastWeekIn.Tech.
"""

import json
import logging
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import feedparser
from jinja2 import Environment, FileSystemLoader
from newspaper import Article as NewsArticle
from newspaper import Config as NewspaperConfig
from thefuzz import fuzz

from lastweekintech.config import Config
from lastweekintech.domain import Article, Story
from lastweekintech.summarizer import Summarizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Set up newspaper3k configuration
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
newspaper_config = NewspaperConfig()
newspaper_config.browser_user_agent = USER_AGENT
newspaper_config.request_timeout = 10
newspaper_config.fetch_images = False


def fetch_articles(config: Config) -> list[Article]:
    """Fetch articles from all configured RSS feeds."""
    articles = []
    time_window = timedelta(days=config.window_days)
    start_date = datetime.now(UTC) - time_window

    for feed in config.feeds:
        logging.info(f"Fetching articles from {feed.name}...")
        try:
            parsed_feed = feedparser.parse(feed.url)
            for entry in parsed_feed.entries:
                published_at = (
                    datetime.fromtimestamp(time.mktime(entry.published_parsed)).replace(tzinfo=UTC)
                    if hasattr(entry, "published_parsed") and entry.published_parsed
                    else datetime.now(UTC)
                )

                if published_at >= start_date:
                    hn_points = None
                    if "Hacker News" in feed.name:
                        # Extract points from title, e.g., "Title (123 points)"
                        import re

                        match = re.search(r"\((\d+) points\)", entry.title)
                        if match:
                            hn_points = int(match.group(1))

                    article = Article(
                        title=entry.title,
                        url=entry.link,
                        source=feed.name,
                        published_at=published_at,
                        hn_points=hn_points,
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
            logging.warning(f"Failed to extract content from {article_meta.url}: {e}")
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
    now = datetime.now(UTC)
    for story in stories:
        # HN score
        hn_articles = [a for a in story.articles if "Hacker News" in a.source]
        hn_score = (
            sum(a.hn_points for a in hn_articles if hasattr(a, "hn_points") and a.hn_points)
            * config.weights.hn
        )

        # Source count score
        src_score = len({a.source for a in story.articles}) * config.weights.src

        # Recency score
        latest_article = max(story.articles, key=lambda a: a.published_at or now)
        recency = 1 - (now - latest_article.published_at).days / config.window_days
        rec_score = recency * config.weights.rec

        story.score = hn_score + src_score + rec_score

    return sorted(stories, key=lambda s: s.score, reverse=True)


def categorize_stories(stories: list[Story]) -> list[Story]:
    """Categorize stories as AI-related or not."""
    ai_keywords = [
        "ai",
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "neural network",
        "llm",
        "large language model",
        "openai",
        "google deepmind",
        "meta ai",
    ]
    for story in stories:
        story.category = "AI"
        if not any(keyword in story.title.lower() for keyword in ai_keywords):
            story.category = "General Tech"
    return stories


def select_top_stories(stories: list[Story], count: int = 7) -> list[Story]:
    """Select the top N stories, ensuring at least 3 are AI-related."""
    ai_stories = [s for s in stories if s.category == "AI"]
    general_stories = [s for s in stories if s.category == "General Tech"]

    # Ensure at least 3 AI stories
    top_stories = ai_stories[:3]
    remaining_slots = count - len(top_stories)
    top_stories.extend(general_stories[:remaining_slots])

    return sorted(top_stories, key=lambda s: s.score, reverse=True)


def summarize_stories(stories: list[Story], summarizer: Summarizer) -> list[Story]:
    """Generate a summary for each story."""
    for story in stories:
        if story.articles and story.articles[0].content:
            content = story.articles[0].content
            summary = summarizer.summarize(content)

            story.summary = summary
        else:
            story.summary = "Summary not available."
    logging.info("Generated summaries for all stories.")
    return stories


def save_stories_to_json(stories: list[Story], output_path: Path):
    """Save the final stories to a JSON file."""
    output_data = {
        "week": datetime.now(UTC).strftime("%Y-%m-%d"),
        "stories": [],
    }

    for i, story in enumerate(stories):
        # Use the first article for source and url
        main_article = story.articles[0] if story.articles else None
        output_data["stories"].append({
            "rank": i + 1,
            "title": story.title,
            "source": main_article.source if main_article else "N/A",
            "url": main_article.url if main_article else "N/A",
            "category": story.category,
            "summary": story.summary or "Summary not available.",
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)
    logging.info(f"Saved stories to {output_path}")


def generate_html(data_path: Path, template_path: Path, output_path: Path):
    """Generate the static HTML file from the story data."""
    with open(data_path) as f:
        data = json.load(f)

    env = Environment(loader=FileSystemLoader(template_path.parent))
    template = env.get_template(template_path.name)

    html_content = template.render(week=data["week"], stories=data["stories"])

    with open(output_path, "w") as f:
        f.write(html_content)
    logging.info(f"Generated static HTML file at {output_path}")

    # Copy CSS file
    static_dir = Path("src/lastweekintech/static")
    shutil.copy(static_dir / "style.css", output_path.parent)
    logging.info("Copied static files.")
