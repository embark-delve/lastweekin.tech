import re
import string
from collections import defaultdict
from difflib import SequenceMatcher
from typing import List
from urllib.parse import urlparse
import nltk
from nltk.corpus import stopwords

from .domain import Article, Cluster

# Download stopwords if not already present
try:
    stopwords.words('english')
except LookupError:
    nltk.download('stopwords')

STOPWORDS = set(stopwords.words('english'))
PUNCTUATION = set(string.punctuation)

def normalize_title(title: str) -> str:
    """
    Normalizes a title by lowercasing, expanding numbers, removing punctuation,
    stopwords, and common site suffixes.
    """
    title = title.lower()
    # Remove site suffixes, which are often separated by | or –
    title = re.split(r'\s[|–—]\s', title)[0].strip()
    # Replace hyphens with spaces before punctuation removal
    title = title.replace('-', ' ')
    # Expand numbers like "50m" to "50 million"
    title = re.sub(r'(\d+)\s*m\b', r'\1 million', title)
    title = re.sub(r'(\d+)\s*b\b', r'\1 billion', title)
    title = "".join(char for char in title if char not in PUNCTUATION)
    tokens = [token for token in title.split() if token not in STOPWORDS]
    return " ".join(tokens)

def get_url_key(url: str) -> str:
    """
    Creates a simplified key from a URL by combining the hostname and the
    first two path components.
    """
    try:
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        key = f"{parsed.hostname}/{'/'.join(path_parts[:2])}"
        return key
    except Exception:
        return ""

def are_titles_similar(title1: str, title2: str, threshold: float = 0.55) -> bool:
    """
    Checks if two normalized titles are similar based on Jaccard similarity.
    """
    tokens1 = set(title1.split())
    tokens2 = set(title2.split())
    if not tokens1 or not tokens2:
        return False

    intersection = len(tokens1.intersection(tokens2))
    union = len(tokens1.union(tokens2))

    return (intersection / union) >= threshold

def cluster_articles(articles: List[Article]) -> List[Cluster]:
    """
    Clusters articles based on title similarity and URL heuristics.
    """
    # First pass: group by URL key for obvious duplicates
    url_based_groups = defaultdict(list)
    for article in articles:
        url_key = get_url_key(article.url)
        if url_key:
            url_based_groups[url_key].append(article)

    # Put articles with unique URL keys into a list for title-based clustering
    single_articles = []
    initial_clusters = []
    for key, group in url_based_groups.items():
        if len(group) > 1:
            initial_clusters.append(group)
        else:
            single_articles.append(group[0])

    # Second pass: cluster remaining articles by title similarity using a graph approach
    title_clusters: List[List[Article]] = []
    normalized_titles = {
        article.id: normalize_title(article.title) for article in single_articles
    }

    # Build adjacency list for the graph of similar articles
    adj = defaultdict(list)
    for i in range(len(single_articles)):
        for j in range(i + 1, len(single_articles)):
            article_i = single_articles[i]
            article_j = single_articles[j]

            title_i_norm = normalized_titles[article_i.id]
            title_j_norm = normalized_titles[article_j.id]

            if are_titles_similar(title_i_norm, title_j_norm):
                adj[article_i.id].append(article_j.id)
                adj[article_j.id].append(article_i.id)

    # Find connected components (which are our clusters) using DFS
    visited = set()
    article_map = {a.id: a for a in single_articles}
    for article in single_articles:
        if article.id not in visited:
            component_articles = []
            stack = [article.id]
            visited.add(article.id)
            while stack:
                node_id = stack.pop()
                component_articles.append(article_map[node_id])
                for neighbor_id in adj.get(node_id, []):
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        stack.append(neighbor_id)
            title_clusters.append(component_articles)

    # Combine URL-based clusters and title-based clusters
    all_article_groups = initial_clusters + title_clusters

    # Convert article groups into Cluster objects
    final_clusters = []
    for i, article_group in enumerate(all_article_groups):
        cluster_id = f"cluster_{i+1}"
        article_ids = [a.id for a in article_group]
        source_hits = len(set(a.source for a in article_group))
        hn_points_max = max((a.hn_points for a in article_group if a.hn_points is not None), default=0)
        published_min = min(a.published for a in article_group)

        cluster = Cluster(
            id=cluster_id,
            article_ids=article_ids,
            source_hits=source_hits,
            hn_points_max=hn_points_max,
            published_min=published_min
        )
        final_clusters.append(cluster)

    return final_clusters


if __name__ == '__main__':
    # Test data
    articles_to_test = [
        Article(id=1, source='TechCrunch', title='AI Startup Raises $50M', url='https://techcrunch.com/ai-startup-50m', published=100, hn_points=150),
        Article(id=2, source='The Verge', title='AI Startup Gets $50 Million in Funding', url='https://verge.com/ai-funding-spree', published=110, hn_points=100),
        Article(id=3, source='Wired', title='The Big AI Funding News', url='https://wired.com/story/ai-startup-gets-50-million', published=120, hn_points=None),
        Article(id=4, source='HackerNews', title='Google Launches New Pixel Phone', url='https://blog.google/pixel-10', published=130, hn_points=300),
        Article(id=5, source='Ars Technica', title='A Look at the New Google Pixel', url='https://arstechnica.com/gadgets/2023/10/google-pixel-review', published=140, hn_points=None),
        Article(id=6, source='TechCrunch', title='Self-Driving Car Company Hits Milestone', url='https://techcrunch.com/self-driving-milestone', published=150, hn_points=200),
        # Obvious duplicate by URL
        Article(id=7, source='The Verge', title='Self-Driving Cars Reach New Milestone | The Verge', url='https://techcrunch.com/self-driving-milestone?utm_source=rss', published=160, hn_points=None),
    ]

    print("--- Testing Article Clustering ---")
    result_clusters = cluster_articles(articles_to_test)

    print(f"Clustering finished. Found {len(result_clusters)} clusters.")
    for c in result_clusters:
        print(f"  - Cluster {c.id}: {c.article_ids} (Sources: {c.source_hits}, HN Points: {c.hn_points_max})")

    # Verification
    assert len(result_clusters) == 3
    # Find cluster with articles 1,2,3
    ai_cluster = next(c for c in result_clusters if 1 in c.article_ids)
    assert set(ai_cluster.article_ids) == {1, 2, 3}
    assert ai_cluster.source_hits == 3
    assert ai_cluster.hn_points_max == 150

    # Find cluster with articles 4,5
    pixel_cluster = next(c for c in result_clusters if 4 in c.article_ids)
    assert set(pixel_cluster.article_ids) == {4, 5}
    assert pixel_cluster.hn_points_max == 300

    # Find cluster with articles 6,7
    car_cluster = next(c for c in result_clusters if 6 in c.article_ids)
    assert set(car_cluster.article_ids) == {6, 7}
    assert car_cluster.source_hits == 2 # Merged by URL first

    print("\nClustering tests passed!")
