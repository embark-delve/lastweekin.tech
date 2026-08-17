"""The publish gate.

The pipeline degrades gracefully at every stage — a dead feed, a paywalled
article and a rate-limited model all shrug and continue. That is the right
behaviour for a batch job, but it means a run can succeed while producing a
digest nobody should read. This module is the one place that says no.
"""

import logging

from lastweekintech.config import Config
from lastweekintech.domain import Story
from lastweekintech.quality import (
    CONTRACT,
    ENTITY_GROUNDING,
    LENGTH,
    MIN_SUMMARY_CHARS,
    NUMBER_GROUNDING,
    STUB_SUMMARIES,
    SUBJECT_COVERAGE,
    SUBSTANCE,
    TRUNCATION,
    assess_story,
)
from lastweekintech.text import normalize_url

# Checks that mean a summary is broken, as opposed to merely off-style or
# unprovable. Two are deliberately advisory:
#
#   LENGTH — a one-sentence summary is terse, not wrong, and an edition should
#   not be blocked over house style when the facts are sound.
#
#   ENTITY_GROUNDING — it fires on any proper noun absent from the extracted
#   source, and cannot tell invention from correct outside context. A live run
#   was rejected for naming Mozilla, Alibaba and Zhipu AI, all correct, none
#   present in the fetched pages, because extraction routinely returns a partial
#   body (an ad block, a model card). Invented *figures* still block: a number
#   absent from the source is far more likely to be wrong than a company name.
BLOCKING_CHECKS = frozenset({
    SUBSTANCE,
    TRUNCATION,
    SUBJECT_COVERAGE,
    NUMBER_GROUNDING,
    CONTRACT,
})

ADVISORY_CHECKS = frozenset({LENGTH, ENTITY_GROUNDING})


class DigestValidationError(Exception):
    """Raised when a digest is not fit to publish."""


def has_summary(story: Story) -> bool:
    """Return True when a story carries a real summary."""
    summary = (story.summary or "").strip()
    return summary.lower() not in STUB_SUMMARIES and len(summary) >= MIN_SUMMARY_CHARS


def validate_digest(stories: list[Story], config: Config) -> list[str]:
    """Return the reasons ``stories`` should not be published, if any."""
    problems = []
    expected = config.digest.story_count

    if len(stories) != expected:
        problems.append(f"expected {expected} stories, got {len(stories)}")

    missing = [s.title for s in stories if not has_summary(s)]
    if len(missing) > config.digest.max_missing_summaries:
        problems.append(
            f"{len(missing)} stories without a usable summary "
            f"(limit {config.digest.max_missing_summaries}): {'; '.join(missing[:3])}"
        )

    # Present-but-bad is the other half of the problem: of 308 summaries in the
    # archive, 48% were empty and a further 23% were cut off mid-word. The
    # checks in quality.py catch the second kind, which reads as real text.
    weak = [
        (story.title, blocking)
        for story, blocking in (
            (s, BLOCKING_CHECKS.intersection(assess_story(s).failed_checks))
            for s in stories
            if has_summary(s)
        )
        if blocking
    ]
    if len(weak) > config.digest.max_low_quality_summaries:
        failed_checks = sorted({check for _, checks in weak for check in checks})
        problems.append(
            f"{len(weak)} summaries failed quality checks "
            f"(limit {config.digest.max_low_quality_summaries}): {', '.join(failed_checks)}"
        )

    linkless = [s.title for s in stories if not any(a.url for a in s.articles)]
    if linkless:
        problems.append(f"{len(linkless)} stories without a link: {'; '.join(linkless[:3])}")

    urls = [normalize_url(s.articles[0].url) for s in stories if s.articles]
    duplicates = {url for url in urls if urls.count(url) > 1}
    if duplicates:
        problems.append(f"{len(duplicates)} duplicate stories in the digest")

    return problems


def assert_publishable(stories: list[Story], config: Config) -> None:
    """Raise :class:`DigestValidationError` unless ``stories`` is fit to publish."""
    problems = validate_digest(stories, config)
    if problems:
        raise DigestValidationError("Refusing to publish this digest: " + "; ".join(problems))
    logging.info(f"Publish gate passed: {len(stories)} stories, all with usable summaries.")
