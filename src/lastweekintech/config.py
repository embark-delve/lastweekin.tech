"""
Configuration loading for the LastWeekIn.Tech pipeline.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Feed:
    """Represents an RSS feed source."""

    name: str
    url: str


@dataclass
class HNSettings:
    """Represents Hacker News settings."""

    min_points: int


@dataclass
class Weights:
    """Represents scoring weights."""

    hn: int
    src: int
    rec: int


@dataclass
class Provider:
    """Represents an API provider."""

    name: str
    base_url: str
    api_key_env: str


@dataclass
class SummarizerSettings:
    """Represents summarizer settings."""

    model_name: str
    fallback_models: list[str]
    providers: list[Provider] = field(default_factory=list)


@dataclass
class Config:
    """Represents the main configuration."""

    feeds: list[Feed]
    hn: HNSettings
    weights: Weights
    window_days: int
    summarizer: SummarizerSettings

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        """Loads the configuration from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        return cls(
            feeds=[Feed(**feed) for feed in data["feeds"]],
            hn=HNSettings(**data["hn"]),
            weights=Weights(**data["weights"]),
            window_days=data["window_days"],
            summarizer=SummarizerSettings(**data["summarizer"]),
        )


def get_config() -> Config:
    """Returns the application configuration."""
    config_path = Path(__file__).parent / "config.yaml"
    return Config.from_yaml(config_path)
