"""
Main CLI application for the LastWeekIn.Tech pipeline.
"""

from pathlib import Path
from typing import Optional

import typer

from lastweekintech import pipeline
from lastweekintech.config import get_config

app = typer.Typer()


@app.command()
def run(
    output_path: Optional[Path] = typer.Option(
        Path("data/latest.json"),
        "--output-path",
        "-o",
        help="Path to save the output JSON file.",
    )
):
    """
    Run the LastWeekIn.Tech data pipeline.
    """
    config = get_config()
    articles = pipeline.fetch_articles(config)
    enriched_articles = pipeline.extract_content(articles)
    stories = pipeline.cluster_articles(enriched_articles)
    scored_stories = pipeline.score_stories(stories, config)
    top_stories = pipeline.select_top_stories(scored_stories)
    summarized_stories = pipeline.summarize_stories(top_stories)
    pipeline.save_stories_to_json(summarized_stories, output_path)


if __name__ == "__main__":
    app()
