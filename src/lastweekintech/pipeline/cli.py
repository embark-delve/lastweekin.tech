import typer
from datetime import datetime, timedelta
import time
from typing import List
import sqlite3

from . import database as db
from .config import config
from .domain import Article, Cluster
from .fetchers import HNFetcher, RSSFetcher
from .extractor import NewspaperExtractor
from .clustering import cluster_articles
from .scoring import score_clusters
from .exporter import export_json

app = typer.Typer()

@app.command()
def fetch(since: str = typer.Option(None, help="Start date (YYYY-MM-DD)"),
          until: str = typer.Option(None, help="End date (YYYY-MM-DD)")):
    """Fetches articles from Hacker News and RSS feeds."""
    if until:
        until_dt = datetime.strptime(until, "%Y-%m-%d")
    else:
        until_dt = datetime.now()

    if since:
        since_dt = datetime.strptime(since, "%Y-%m-%d")
    else:
        since_dt = until_dt - timedelta(days=config.get('window_days', 7))

    since_ts = int(since_dt.timestamp())
    until_ts = int(until_dt.timestamp())

    print(f"Fetching articles from {since_dt.strftime('%Y-%m-%d')} to {until_dt.strftime('%Y-%m-%d')}...")

    hn_fetcher = HNFetcher()
    rss_fetcher = RSSFetcher()

    articles = hn_fetcher.fetch(since_ts, until_ts)
    articles.extend(rss_fetcher.fetch(since_ts, until_ts))

    conn = db.get_db_connection()
    cursor = conn.cursor()

    for article in articles:
        try:
            cursor.execute(
                """
                INSERT INTO articles (source, title, url, published_ts, hn_points, hn_comments, fetch_status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (article.source, article.title, article.url, article.published, article.hn_points, article.hn_comments, 'fetched')
            )
        except sqlite3.IntegrityError:
            print(f"Skipping duplicate URL: {article.url}")

    conn.commit()
    conn.close()
    print(f"Finished fetching. Stored {len(articles)} new articles in the database.")


@app.command()
def extract(parallel: int = typer.Option(4, help="Number of parallel workers.")):
    """Extracts full content for articles that are missing it."""
    # Note: True parallelism would require multiprocessing, this is a simplified version.
    print(f"Extracting content for fetched articles (using up to {parallel} 'threads')...")
    conn = db.get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, url FROM articles WHERE fetch_status = 'fetched'")
    articles_to_extract = cursor.fetchall()

    extractor = NewspaperExtractor()

    for row in articles_to_extract:
        article_id, url = row['id'], row['url']
        print(f"  - Extracting from: {url}")
        content = extractor.extract(url)

        status = 'extracted' if content else 'failed_extraction'

        cursor.execute(
            "UPDATE articles SET content = ?, fetch_status = ? WHERE id = ?",
            (content, status, article_id)
        )

    conn.commit()
    conn.close()
    print(f"Finished content extraction for {len(articles_to_extract)} articles.")

@app.command()
def cluster():
    """Clusters articles based on title similarity."""
    print("Clustering articles...")
    conn = db.get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM articles WHERE fetch_status IN ('extracted', 'fetched')")
    rows = cursor.fetchall()
    articles = [Article(**dict(row)) for row in rows]

    clusters = cluster_articles(articles)

    # Clear existing cluster data
    cursor.execute("DELETE FROM cluster_members")
    cursor.execute("DELETE FROM clusters")

    for c in clusters:
        cursor.execute(
            "INSERT INTO clusters (cluster_id, source_hits, hn_points_max, published_min_ts) VALUES (?, ?, ?, ?)",
            (c.id, c.source_hits, c.hn_points_max, c.published_min)
        )
        for article_id in c.article_ids:
            cursor.execute(
                "INSERT INTO cluster_members (cluster_id, article_id) VALUES (?, ?)",
                (c.id, article_id)
            )

    conn.commit()
    conn.close()
    print(f"Finished clustering. Found {len(clusters)} clusters.")

@app.command()
def score():
    """Scores each cluster based on various signals."""
    print("Scoring clusters...")
    conn = db.get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM clusters")
    rows = cursor.fetchall()
    # Recreate Cluster objects, need to fetch article_ids for each
    clusters = []
    for row in rows:
        cluster_id = row['cluster_id']
        cursor.execute("SELECT article_id FROM cluster_members WHERE cluster_id = ?", (cluster_id,))
        article_ids = [r['article_id'] for r in cursor.fetchall()]
        c = Cluster(**dict(row), article_ids=article_ids)
        clusters.append(c)

    now_ts = int(time.time())
    score_clusters(clusters, now_ts)

    for c in clusters:
        cursor.execute(
            "UPDATE clusters SET score = ? WHERE cluster_id = ?",
            (c.score, c.id)
        )

    conn.commit()
    conn.close()
    print(f"Finished scoring {len(clusters)} clusters.")

@app.command()
def export(out: str = typer.Option("data/latest.json", help="Output JSON file path.")):
    """Exports the final ranked list of articles to JSON."""
    print(f"Exporting results to {out}...")
    conn = db.get_db_connection()
    cursor = conn.cursor()

    # Fetch all articles and clusters
    cursor.execute("SELECT * FROM articles")
    articles = [Article(**dict(row)) for row in cursor.fetchall()]

    cursor.execute("SELECT * FROM clusters")
    clusters_rows = cursor.fetchall()
    clusters = []
    for row in clusters_rows:
        cluster_id = row['cluster_id']
        cursor.execute("SELECT article_id FROM cluster_members WHERE cluster_id = ?", (cluster_id,))
        article_ids = [r['article_id'] for r in cursor.fetchall()]
        c = Cluster(**dict(row), article_ids=article_ids)
        clusters.append(c)

    conn.close()

    now = datetime.now()
    week_date = now.strftime('%Y-%m-%d')
    now_ts = int(now.timestamp())

    export_json(clusters, articles, week_date, out, now_ts)
    print("Export complete.")


@app.command()
def run(weekly: bool = typer.Option(True, help="Run all stages of the pipeline.")):
    """Runs the entire pipeline: fetch -> extract -> cluster -> score -> export."""
    if weekly:
        print("--- Starting Weekly Pipeline Run ---")
        fetch.callback()
        extract.callback()
        cluster.callback()
        score.callback()
        export.callback()
        print("\n--- Weekly Pipeline Run Finished ---")

if __name__ == "__main__":
    app()
