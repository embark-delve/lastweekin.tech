"""
Main CLI application for the LastWeekIn.Tech pipeline.
"""

from pathlib import Path
from typing import Annotated

import typer

from lastweekintech import pipeline
from lastweekintech.config import get_config
from lastweekintech.summarizer import Summarizer

app = typer.Typer()


@app.command()
def run(
    output_path: Annotated[
        Path | None,
        typer.Option(
            "--output-path",
            "-o",
            help="Path to save the output JSON file.",
        ),
    ] = None,
):
    """
    Run the LastWeekIn.Tech data pipeline.
    """
    if output_path is None:
        output_path = Path("data/latest.json")

    config = get_config()

    summarizer = Summarizer(config.summarizer)

    articles = pipeline.fetch_articles(config)
    enriched_articles = pipeline.extract_content(articles)
    stories = pipeline.cluster_articles(enriched_articles)
    categorized_stories = pipeline.categorize_stories(stories)
    scored_stories = pipeline.score_stories(categorized_stories, config)
    top_stories = pipeline.select_top_stories(scored_stories)

    summarized_stories = pipeline.summarize_stories(top_stories, summarizer)

    pipeline.save_stories_to_json(summarized_stories, output_path)


if __name__ == "__main__":
    app()
