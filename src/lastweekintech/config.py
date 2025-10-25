"""
Configuration loading for the LastWeekIn.Tech pipeline.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List

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
class Config:
    """Represents the main configuration."""

    feeds: List[Feed]
    hn: HNSettings
    weights: Weights
    window_days: int

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        """Loads the configuration from a YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)

        return cls(
            feeds=[Feed(**feed) for feed in data["feeds"]],
            hn=HNSettings(**data["hn"]),
            weights=Weights(**data["weights"]),
            window_days=data["window_days"],
        )


def get_config() -> Config:
    """Returns the application configuration."""
    config_path = Path(__file__).parent / "config.yaml"
    return Config.from_yaml(config_path)
