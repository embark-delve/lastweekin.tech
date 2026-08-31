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

    hn_points: int | None = None
    # True for feeds that report on coverage rather than produce it (Techmeme).
    # Their presence in a cluster is corroboration, but the digest should link
    # to the original reporting, never to the aggregator's rewrite.
    aggregator: bool = False


@dataclass
class Story:
    """Represents a deduplicated news story."""

    title: str
    articles: list[Article] = field(default_factory=list)
    summary: str | None = None
    score: float = 0.0
    category: str = "General Tech"
