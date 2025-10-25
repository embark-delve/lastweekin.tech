# LastWeekIn.Tech

## Overview

This project is a Python-based data pipeline designed to generate a weekly tech digest. The primary goal is to create a 'Top-7' list of tech news with a significant focus on AI-related developments. The pipeline fetches articles from various RSS feeds, scores them based on relevance and popularity, and clusters them to identify the most significant stories of the week.

## Features

- **RSS Feed Aggregation**: Fetches articles from a configurable list of tech news sources.
- **Content Extraction**: Uses the `newspaper3k` library to extract article content.
- **Scoring and Clustering**: Scores articles based on Hacker News points, source, and recency, then clusters them to find top stories.
- **CLI Application**: Built with Typer for easy pipeline execution.
- **SQLite Persistence**: Uses SQLite to store data between pipeline steps.

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

The pipeline is executed as a CLI application. To run the pipeline, use the following command:

```bash
uv run python src/lastweekintech/main.py
```

## Configuration

The pipeline is configured through the `src/lastweekintech/config.yaml` file. This file contains the list of RSS feeds, Hacker News settings, and scoring weights.
