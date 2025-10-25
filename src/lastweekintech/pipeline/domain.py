from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Article:
    id: int
    source: str
    title: str
    url: str
    published: int  # Unix timestamp
    hn_points: Optional[int] = None
    hn_comments: Optional[int] = None
    content: Optional[str] = None

@dataclass
class Cluster:
    id: str
    article_ids: list[int] = field(default_factory=list)
    source_hits: int = 0
    hn_points_max: int = 0
    published_min: int = 0
    score: float = 0.0
