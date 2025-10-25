import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .domain import Article, Cluster

def select_representative_article(cluster: Cluster, article_map: Dict[int, Article]) -> Article:
    """
    Selects the best representative article for a cluster.
    Rule: Highest hn_points, then oldest published timestamp.
    """
    cluster_articles = [article_map[aid] for aid in cluster.article_ids if aid in article_map]
    if not cluster_articles:
        # This should ideally not happen if data is consistent
        raise ValueError(f"No articles found for cluster {cluster.id}")

    # Sort by hn_points (desc, None treated as -1) and then by published timestamp (asc)
    cluster_articles.sort(key=lambda a: (a.hn_points or -1, -a.published), reverse=True)

    return cluster_articles[0]

def export_json(clusters: List[Cluster], articles: List[Article], week_date: str, path: str, now_ts: int) -> None:
    """
    Exports the ranked clusters to a JSON file in the specified v1 format.
    """
    # Sort clusters by score (desc), then published time (asc), then id (asc) for determinism
    clusters.sort(key=lambda c: (-c.score, c.published_min, c.id))

    article_map = {article.id: article for article in articles}

    candidates_list = []
    for cluster in clusters:
        try:
            rep_article = select_representative_article(cluster, article_map)
        except ValueError as e:
            print(f"Skipping cluster due to error: {e}")
            continue

        recency_days = round((now_ts - cluster.published_min) / (24 * 3600), 1)

        candidate = {
            "title": rep_article.title,
            "url": rep_article.url,
            "source": rep_article.source,
            "published": datetime.fromtimestamp(rep_article.published).isoformat(),
            "cluster_id": cluster.id,
            "signals": {
                "hn_points": cluster.hn_points_max,
                "source_hits": cluster.source_hits,
                "recency_days": recency_days
            },
            "score": cluster.score
        }
        candidates_list.append(candidate)

    # Prepare final JSON output
    output_data = {
        "week": week_date,
        "candidates": candidates_list,
        "top7_placeholder": [c.id for c in clusters[:7]]
    }

    # Write to file
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    # Test data
    now_timestamp = int(time.time())
    week_string = datetime.fromtimestamp(now_timestamp).strftime('%Y-%m-%d')

    test_articles = [
        Article(id=1, source='TechCrunch', title='AI Startup News', url='http://tc.com/ai', published=now_timestamp - 86400, hn_points=200),
        Article(id=2, source='The Verge', title='AI News', url='http://verge.com/ai', published=now_timestamp - 87000, hn_points=300),
        Article(id=3, source='Wired', title='Google Pixel Story', url='http://wired.com/pixel', published=now_timestamp - 172800, hn_points=100),
    ]

    test_clusters = [
        Cluster(id='c1', article_ids=[1, 2], source_hits=2, hn_points_max=300, published_min=now_timestamp - 87000, score=45.1),
        Cluster(id='c2', article_ids=[3], source_hits=1, hn_points_max=100, published_min=now_timestamp - 172800, score=22.5),
    ]

    output_file = Path(__file__).parent.parent / "data" / "test_latest.json"

    print("--- Testing JSON Export ---")
    export_json(test_clusters, test_articles, week_string, str(output_file), now_timestamp)
    print(f"Exported test JSON to: {output_file}")

    # Verify output
    with open(output_file, 'r') as f:
        data = json.load(f)

    assert data['week'] == week_string
    assert len(data['candidates']) == 2
    assert data['candidates'][0]['cluster_id'] == 'c1'
    assert data['candidates'][0]['score'] == 45.1
    assert data['candidates'][0]['title'] == 'AI News' # From article 2 (higher HN points)
    assert data['top7_placeholder'] == ['c1', 'c2']

    output_file.unlink() # Clean up test file
    print("\nJSON export tests passed!")
