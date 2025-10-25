import math
import time
from typing import List

from .config import config
from .domain import Cluster

def score_clusters(clusters: List[Cluster], now_ts: int) -> None:
    """
    Calculates and assigns a score to each cluster in the list, based on a
    formula combining HN points, source diversity, and recency.
    The scores are assigned in-place.
    """
    weights = config.get("weights", {})
    w_hn = weights.get("hn", 3)
    w_src = weights.get("src", 5)
    w_rec = weights.get("rec", 2)

    window_days = config.get("window_days", 7)

    for cluster in clusters:
        # HN points component
        score_hn = w_hn * math.log2(1 + cluster.hn_points_max)

        # Source hits component
        score_src = w_src * cluster.source_hits

        # Recency component
        recency_days = (now_ts - cluster.published_min) / (24 * 3600)
        recency_factor = max(0, window_days - recency_days) / window_days
        score_rec = w_rec * recency_factor

        # Total score
        cluster.score = round(score_hn + score_src + score_rec, 3)

if __name__ == '__main__':
    # Test data
    now_timestamp = int(time.time())

    clusters_to_test = [
        # Cluster 1: High HN points, recent, multiple sources
        Cluster(id='c1', article_ids=[1,2,3], source_hits=3, hn_points_max=300, published_min=now_timestamp - (1 * 24 * 3600)),
        # Cluster 2: Low HN points, older, single source
        Cluster(id='c2', article_ids=[4], source_hits=1, hn_points_max=10, published_min=now_timestamp - (6 * 24 * 3600)),
        # Cluster 3: No HN points, medium recency, 2 sources
        Cluster(id='c3', article_ids=[5,6], source_hits=2, hn_points_max=0, published_min=now_timestamp - (3 * 24 * 3600)),
    ]

    print("--- Testing Cluster Scoring ---")
    score_clusters(clusters_to_test, now_timestamp)

    for c in clusters_to_test:
        print(f"  - Cluster {c.id}: Score = {c.score}")

    # Verification (based on default weights: hn=3, src=5, rec=2)
    # C1: 3*log2(301) + 5*3 + 2*(6/7) = 3*8.23 + 15 + 1.71 = 24.69 + 15 + 1.71 = 41.4
    expected_c1_score = round(3 * math.log2(301) + 5 * 3 + 2 * (6/7), 3)
    assert clusters_to_test[0].score == expected_c1_score
    print(f"Expected C1 score: {expected_c1_score}, Actual: {clusters_to_test[0].score}")

    # C2: 3*log2(11) + 5*1 + 2*(1/7) = 3*3.45 + 5 + 0.28 = 10.35 + 5 + 0.28 = 15.63
    expected_c2_score = round(3 * math.log2(11) + 5 * 1 + 2 * (1/7), 3)
    assert clusters_to_test[1].score == expected_c2_score
    print(f"Expected C2 score: {expected_c2_score}, Actual: {clusters_to_test[1].score}")

    # C3: 3*log2(1) + 5*2 + 2*(4/7) = 0 + 10 + 1.14 = 11.14
    expected_c3_score = round(3 * math.log2(1) + 5 * 2 + 2 * (4/7), 3)
    assert clusters_to_test[2].score == expected_c3_score
    print(f"Expected C3 score: {expected_c3_score}, Actual: {clusters_to_test[2].score}")

    print("\nScoring tests passed!")
