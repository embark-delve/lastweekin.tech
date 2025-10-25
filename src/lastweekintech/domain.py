"""
Domain models for the LastWeekIn.Tech pipeline.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Article:
    """Represents a single news article."""

    title: str
    url: str
    source: str
    content: str | None = None
    published_at: datetime | None = None


@dataclass
class Story:
    """Represents a deduplicated news story."""

    title: str
    articles: list[Article] = field(default_factory=list)
    summary: str | None = None
    score: float = 0.0
    category: str = "General Tech"
