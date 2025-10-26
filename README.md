# LastWeekIn.Tech

## Overview

This project is a Python-based data pipeline designed to generate a weekly
tech digest. The primary goal is to create a 'Top-7' list of tech news with a
significant focus on AI-related developments. The pipeline fetches articles from
various RSS feeds, scores them based on relevance and popularity, clusters them
to identify the most significant stories of the week, and outputs the result as
a structured JSON file.

## Features

- **RSS Feed Aggregation**: Fetches articles from a configurable list of tech
  news sources within a defined time window.
- **Content Extraction**: Uses the `newspaper3k` library to extract the main
  body content from each article's URL.
- **Story Clustering**: Groups similar articles into unique "stories" using
  fuzzy title matching to avoid duplicates.
- **Configurable Scoring**: Ranks stories based on a weighted algorithm that
  considers the number of sources covering the story, Hacker News points, and
  recency. All weights are configurable.
- **AI Story Quota**: Ensures that the final 'Top-7' list includes a minimum
  number of AI-related stories, as defined in the project's goals.
- **AI-Powered Summarization**: Utilizes the `facebook/bart-large-cnn` model
  from the Hugging Face `transformers` library to generate high-quality,
  abstractive summaries for each story.
- **JSON Output**: Saves the final curated list of stories to a clean,
  well-structured JSON file.
- **CLI Application**: Provides a command-line interface built with Typer for
  easy execution and configuration of the pipeline.

## Setup and Installation

This project uses `uv` for dependency and environment management.

1. **Create a virtual environment:**

   ```bash
   uv venv
   ```

2. **Activate the virtual environment:**

   ```bash
   source .venv/bin/activate
   ```

3. **Install dependencies:**

   ```bash
   uv sync
   ```

## Usage

The pipeline is executed as a CLI application. To run the full pipeline and
generate the `latest.json` file in the `data/` directory, use the following
command:

```bash
uv run python -m lastweekintech.main
```

### Options

- `--output-path`, `-o`: Specify a custom output path for the JSON file.

  ```bash
  uv run python -m lastweekintech.main --output-path /path/to/your/output.json
  ```

## Configuration

The pipeline is configured through the `src/lastweekintech/config.yaml` file.
This file allows you to customize the pipeline's behavior:

- **`feeds`**: A list of RSS feeds to use as article sources. Each feed has a
  `name` and a `url`.
- **`hn`**: Settings related to Hacker News, such as the `min_points`
  required for an article to be considered.
- **`window_days`**: The number of days to look back when fetching articles.
- **`weights`**: The scoring weights for different factors (`hn` for Hacker
  News points, `src` for source count, `rec` for recency).
