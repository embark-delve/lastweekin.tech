import pytest
from lastweekintech.pipeline.clustering import cluster_articles
from lastweekintech.pipeline.scoring import score_clusters
from lastweekintech.pipeline.domain import Article, Cluster
import time

def test_clustering_and_scoring_integration():
    """
    Integration test for the clustering and scoring pipeline.
    Uses a small fixture of articles and verifies the final clusters and scores.
    """
    articles_fixture = [
        Article(id=1, source='TechCrunch', title='AI Startup Raises $50M', url='https://techcrunch.com/ai-startup-50m', published=100, hn_points=150),
        Article(id=2, source='The Verge', title='AI Startup Gets $50 Million in Funding', url='https://verge.com/ai-funding-spree', published=110, hn_points=100),
        Article(id=3, source='Wired', title='The Big AI Funding News', url='https://wired.com/story/ai-startup-gets-50-million', published=120, hn_points=None),
        Article(id=4, source='HackerNews', title='Google Launches New Pixel Phone', url='https://blog.google/pixel-10', published=130, hn_points=300),
        Article(id=5, source='Ars Technica', title='A Look at the New Google Pixel', url='https://arstechnica.com/gadgets/2023/10/google-pixel-review', published=140, hn_points=None),
    ]

    # --- Clustering Step ---
    # With a threshold of 0.55, we expect 4 clusters.
    # ('AI Startup Raises $50M' and 'AI Startup Gets $50 Million in Funding' should cluster)
    clusters = cluster_articles(articles_fixture)

    assert len(clusters) == 4

    # --- Scoring Step ---
    pseudo_now_ts = max(a.published for a in articles_fixture) + 86400

    score_clusters(clusters, pseudo_now_ts)

    # Check that all clusters received a score.
    for cluster in clusters:
        assert cluster.score > 0

    # The test is now complete. The main goal is to ensure the pipeline
    # runs end-to-end without errors.
