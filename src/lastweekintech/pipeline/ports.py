from typing import Protocol
from .domain import Article

class SourceFetcher(Protocol):
    def fetch(self, since_ts: int, until_ts: int) -> list[Article]:
        ...

class ContentExtractor(Protocol):
    def extract(self, url: str) -> str:  # Returns full text or an empty string
        ...
