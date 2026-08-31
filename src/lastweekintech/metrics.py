"""A machine-readable record of what one run actually did.

The pipeline degrades gracefully at every stage, which is the right behaviour
for an unattended batch job but leaves a successful run and a barely-successful
run looking identical from the outside. This module is how a run says what it
saw: how many articles arrived, how much of the week the candidate pool
covered, how many bodies failed to download, whether the AI floor was met
naturally or by promotion, and where the wall clock went.

Nothing here may cost an edition. The record is filled in as a side effect of a
run that would have happened anyway, and :func:`write_run_metrics` swallows
every error it can raise — a full disk must not turn a good digest into a
failed job.
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

RUNS_DIRNAME = "runs"


@dataclass
class RunMetrics:
    """What one pipeline run observed.

    Passed into ``build_digest`` by the caller and filled in as the stages run,
    rather than accumulated in a module-level singleton: two runs in one process
    (the test suite does exactly this) must not see each other's numbers.
    """

    week: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Intake.
    articles_from_feeds: int = 0
    articles_from_hn: int = 0
    articles_before_dedupe: int = 0
    articles_after_dedupe: int = 0

    # Clustering. ``multi_source_stories`` is the one to watch: breadth of
    # coverage is weighted heavily in the ranking but fires rarely, so a run
    # where it is zero ranked entirely on Hacker News traction and recency.
    stories: int = 0
    multi_source_stories: int = 0
    max_sources: int = 0

    # Cross-week deduplication.
    repeats_dropped: int = 0
    repeats_restored: int = 0

    # The Perplexity consensus check. ``consensus_missed`` lists headlines the
    # wider press led with that the funnel never saw at all — a headline that
    # recurs here is how a missing feed announces itself.
    consensus_stories: int = 0
    consensus_matched: int = 0
    consensus_missed: list[str] = field(default_factory=list)

    # Candidate pool: only these stories have their bodies downloaded.
    candidate_stories: int = 0
    candidate_articles: int = 0
    extraction_succeeded: int = 0
    extraction_failed: int = 0

    categories: dict[str, int] = field(default_factory=dict)

    # The AI floor. ``ai_before_promotion`` is what the ranking produced on its
    # own; anything in ``ai_promoted`` is the floor overriding the ranking, and
    # a week where that number is large is a week the ranking disagreed with.
    ai_before_promotion: int = 0
    ai_promoted: int = 0
    ai_published: int = 0

    summaries: int = 0
    summaries_failed: int = 0
    summary_models: dict[str, str] = field(default_factory=dict)

    stage_seconds: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        """Time a stage, recording it even when the stage raises."""
        started = perf_counter()
        try:
            yield
        finally:
            self.stage_seconds[name] = round(perf_counter() - started, 3)

    def record_extraction(self, articles: list[Any]) -> None:
        """Count how many candidate bodies actually came back."""
        self.candidate_articles = len(articles)
        self.extraction_succeeded = sum(1 for a in articles if a.content)
        self.extraction_failed = len(articles) - self.extraction_succeeded

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarizer_model(summarizer: Any) -> str:
    """Best available answer to "which model wrote this summary?".

    ``Summarizer`` falls back down a list of models per call and does not report
    which one answered, so ``last_model`` is read first for any implementation
    that does, and the configured primary is the honest fallback: on a clean run
    it is correct, and on a run where the primary was rate-limited it names the
    model we *tried* rather than inventing one.
    """
    for attribute in ("last_model", "primary_model", "model_name"):
        value = getattr(summarizer, attribute, None)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def write_run_metrics(metrics: RunMetrics, data_dir: Path) -> Path | None:
    """Write the run record to ``data/runs/<week>.json``.

    Returns the path written, or ``None`` if anything went wrong. Measurement
    is never allowed to fail a run, so every error is logged and swallowed.
    """
    try:
        runs_dir = data_dir / RUNS_DIRNAME
        runs_dir.mkdir(parents=True, exist_ok=True)
        path = runs_dir / f"{metrics.week or 'unknown'}.json"
        payload = json.dumps(metrics.to_dict(), indent=2, ensure_ascii=False) + "\n"
        path.write_text(payload, encoding="utf-8")
        logging.info(f"Wrote run metrics to {path}")
        return path
    except Exception as e:  # noqa: BLE001 - metrics must never cost an edition
        logging.warning(f"Could not write run metrics: {e}")
        return None
