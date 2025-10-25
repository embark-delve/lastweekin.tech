"""""
Domain models for the LastWeekIn.Tech pipeline.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Article:
    """Represents a single news article."""

    title: str
    url: str
    source: str
    content: Optional[str] = None
    published_at: Optional[datetime] = None


@dataclass
class Story:
    """Represents a deduplicated news story."""

    title: str
    articles: List[Article] = field(default_factory=list)
    summary: Optional[str] = None
    score: float = 0.0
