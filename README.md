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

- **AI-Powered Summarization**: Utilizes `litellm` to connect to various LLM
  providers like OpenRouter for high-quality, abstractive summaries. The models
  are fully configurable.
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

4. **Set up environment variables:**

   Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

   Then, edit the `.env` file to add your API keys.
   - `OPENROUTER_API_KEY`: Your API key for [OpenRouter](https://openrouter.ai/).
     This is required for the default summarization models.
   - `HF_TOKEN`: Your Hugging Face token, required if using Hugging Face models.

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

## Automation

This project uses GitHub Actions to automate the weekly generation of the tech
digest. The workflow is defined in `.github/workflows/main.yml` and is
configured to run every Monday at 8:00 AM UTC. It can also be triggered
manually from the Actions tab in the GitHub repository.

### Setting up API Keys for Automation

The workflow requires API keys to be set as secrets in your GitHub repository.
To add these secrets, follow these steps for each key:

1. Go to your repository on GitHub.
2. Click on the **Settings** tab.
3. In the left sidebar, click on **Secrets and variables**, then **Actions**.
4. Click on the **New repository secret** button.
5. Add the following secrets:
   - `OPENROUTER_API_KEY`: Your OpenRouter API key.
   - `HF_TOKEN`: Your Hugging Face token.

Once the secrets are added, the GitHub Actions workflow will be able to use them
to run the summarization pipeline.

## Configuration

The pipeline is configured through the `src/lastweekintech/config.yaml` file.
This file allows you to customize the pipeline's behavior:

- **`feeds`**: A list of RSS feeds to use as article sources.
- **`hn`**: Settings related to Hacker News.
- **`window_days`**: The number of days to look back when fetching articles.
- **`weights`**: The scoring weights for different factors.
- **`summarizer`**: Settings for the summarization models.
  - `model_name`: The primary model to use. The model name should be prefixed
    with the provider name (e.g., `openrouter/minimax/minimax-m2:free`).
  - `fallback_models`: A list of fallback models to use if the primary one fails.
  - `providers`: A list of API providers, each with a `name`, `base_url`, and
    the corresponding environment variable (`api_key_env`) for the API key.
