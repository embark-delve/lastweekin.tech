# LastWeekIn.Tech

This project is a Python-based pipeline to generate a weekly digest of the top 7 tech articles, with a focus on AI. This is Phase 1 of the project, which focuses on the data collection and processing pipeline.

## Project Structure

- `src/lastweekintech/pipeline/`: Contains the core logic for fetching, extracting, clustering, scoring, and exporting articles.
- `src/lastweekintech/tests/`: Contains unit and integration tests.
- `src/lastweekintech/data/`: The default directory for the SQLite database and JSON output.
- `src/lastweekintech/config.yaml`: Configuration file for RSS feeds, API settings, and scoring weights.
- `pyproject.toml`: Project metadata and dependencies, managed by Poetry.

## Setup and Installation

This project uses [Poetry](https://python-poetry.org/) for dependency management.

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd lastweekintech
    ```

2.  **Install dependencies using Poetry:**
    ```bash
    poetry install
    ```
    This will create a virtual environment and install all the necessary packages from `pyproject.toml`.

3.  **Initialize the database:**
    The first time you run the pipeline, you need to create the SQLite database and its schema.
    ```bash
    poetry run python -m src.lastweekintech.pipeline.database
    ```

## Running the Pipeline

The pipeline is controlled via a command-line interface (CLI) built with Typer. You can run individual steps or the entire pipeline at once. All commands should be run from the root of the project.

### Running the Full Pipeline

To run all stages in sequence (fetch, extract, cluster, score, and export), use the `run` command:

```bash
poetry run python -m src.lastweekintech.pipeline.cli run
```

This will generate the `latest.json` file in the `data` directory.

### Running Individual Steps

You can also run each step of the pipeline individually:

1.  **Fetch articles:**
    ```bash
    poetry run python -m src.lastweekintech.pipeline.cli fetch
    ```

2.  **Extract content:**
    ```bash
    poetry run python -m src.lastweekintech.pipeline.cli extract
    ```

3.  **Cluster articles:**
    ```bash
    poetry run python -m src.lastweekintech.pipeline.cli cluster
    ```

4.  **Score clusters:**
    ```bash
    poetry run python -m src.lastweekintech.pipeline.cli score
    ```

5.  **Export to JSON:**
    ```bash
    poetry run python -m src.lastweekintech.pipeline.cli export --out data/latest.json
    ```

## Running Tests

To run the test suite, use `pytest`:

```bash
poetry run pytest
```
