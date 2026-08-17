"""Score the golden summary set and print a readable report.

    uv run python -m evals.run             # the report, plus aggregates
    uv run python -m evals.run --verbose   # with the reason for every failure
    uv run python -m evals.run --judge     # add an LLM faithfulness pass (needs a key)

Exits non-zero when the checks disagree with the golden set, so the same
command works in CI. ``uv run pytest tests/test_quality.py -k golden`` asserts
the same thing without the report.

The aggregate worth watching is the per-check table at the bottom: a check that
misses what it is for is weak, and a check with false positives is worse than
not having it at all.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from lastweekintech.quality import (
    CHECK_NAMES,
    JudgeError,
    QualityReport,
    assess_summary,
    judge_available,
    judge_summary,
)

GOLDEN_PATH = Path(__file__).resolve().parent / "golden.yaml"


@dataclass(frozen=True)
class Fixture:
    """One golden case: a story, a candidate summary and the expected verdict."""

    id: str
    title: str
    source_text: str
    summary: str
    expected: frozenset[str]
    note: str = ""


@dataclass(frozen=True)
class Outcome:
    """What the checks said about a fixture, next to what they should have said."""

    fixture: Fixture
    report: QualityReport

    @property
    def actual(self) -> frozenset[str]:
        return frozenset(self.report.failed_checks)

    @property
    def missed(self) -> frozenset[str]:
        """Failures the golden set expects and the checks did not find."""
        return self.fixture.expected - self.actual

    @property
    def spurious(self) -> frozenset[str]:
        """Failures the checks invented. The expensive kind of wrong."""
        return self.actual - self.fixture.expected

    @property
    def agreed(self) -> bool:
        return not self.missed and not self.spurious


def load_fixtures(path: Path = GOLDEN_PATH) -> list[Fixture]:
    """Read the golden set, resolving each fixture's shared source text."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    sources = data["sources"]
    return [
        Fixture(
            id=fixture["id"],
            title=fixture["title"],
            source_text=sources[fixture["source"]],
            summary=fixture.get("summary") or "",
            expected=frozenset(fixture["expect_failures"]),
            note=fixture.get("note", ""),
        )
        for fixture in data["fixtures"]
    ]


def evaluate(fixtures: list[Fixture]) -> list[Outcome]:
    """Score every fixture. Deterministic and network-free."""
    return [
        Outcome(fixture, assess_summary(fixture.title, fixture.source_text, fixture.summary))
        for fixture in fixtures
    ]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def format_report(outcomes: list[Outcome], verbose: bool = False) -> str:
    """Render the per-fixture results and the aggregates beneath them."""
    lines = ["", "GOLDEN SET", "=" * 96, ""]
    width = max((len(o.fixture.id) for o in outcomes), default=20)

    for outcome in sorted(outcomes, key=lambda o: (o.agreed, o.fixture.id)):
        marker = "ok  " if outcome.agreed else "WRONG"
        found = ", ".join(sorted(outcome.actual)) or "-"
        lines.append(
            f"  {marker} {outcome.fixture.id:<{width}}  {outcome.report.score:>5.2f}  {found}"
        )
        if not outcome.agreed:
            if outcome.missed:
                lines.append(
                    f"       {'':<{width}}         missed: {', '.join(sorted(outcome.missed))}"
                )
            if outcome.spurious:
                spurious = ", ".join(sorted(outcome.spurious))
                lines.append(f"       {'':<{width}}         false positive: {spurious}")
        if verbose:
            for reason in outcome.report.reasons:
                lines.append(f"       {'':<{width}}         - {reason}")

    clean = [o for o in outcomes if not o.fixture.expected]
    flawed = [o for o in outcomes if o.fixture.expected]
    agreed = [o for o in outcomes if o.agreed]

    lines += [
        "",
        "AGGREGATE",
        "-" * 96,
        f"  fixtures                 {len(outcomes)}",
        f"  oracle agreement         {len(agreed)}/{len(outcomes)}"
        f" ({100 * len(agreed) / len(outcomes):.1f}%)",
        f"  clean fixtures           {len(clean)},"
        f" mean score {_mean([o.report.score for o in clean]):.2f}",
        f"  flawed fixtures          {len(flawed)},"
        f" mean score {_mean([o.report.score for o in flawed]):.2f}",
        "",
        "PER CHECK",
        "-" * 96,
        f"  {'check':<20} {'expected':>9} {'detected':>9} {'missed':>7} {'false pos':>10}",
    ]

    for name in CHECK_NAMES:
        expected = [o for o in outcomes if name in o.fixture.expected]
        detected = [o for o in expected if name in o.actual]
        false_positive = [
            o for o in outcomes if name in o.actual and name not in o.fixture.expected
        ]
        lines.append(
            f"  {name:<20} {len(expected):>9} {len(detected):>9}"
            f" {len(expected) - len(detected):>7} {len(false_positive):>10}"
        )

    lines.append("")
    return "\n".join(lines)


def run_judge(fixtures: list[Fixture]) -> str:
    """Optional: ask a model whether each summary is faithful to its source.

    Never runs unless ``--judge`` is passed and a key is present, and never
    runs from the test suite at all.
    """
    if not judge_available():
        return "\nLLM JUDGE\n" + "-" * 96 + "\n  skipped: OPENROUTER_API_KEY is not set\n"

    lines = ["", "LLM JUDGE", "-" * 96]
    for fixture in fixtures:
        if not fixture.summary.strip():
            lines.append(f"  skip      {fixture.id}: empty summary")
            continue
        try:
            verdict = judge_summary(fixture.title, fixture.source_text, fixture.summary)
        except (JudgeError, OSError, ValueError) as exc:
            lines.append(f"  error     {fixture.id}: {exc}")
            continue
        label = "faithful" if verdict.faithful else "UNFAITHFUL"
        lines.append(f"  {label:<9} {fixture.id}: {verdict.reason}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true", help="Print every failure reason.")
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Also run the optional LLM faithfulness judge (requires OPENROUTER_API_KEY).",
    )
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH, help="Path to golden.yaml.")
    args = parser.parse_args(argv)

    fixtures = load_fixtures(args.golden)
    outcomes = evaluate(fixtures)
    print(format_report(outcomes, verbose=args.verbose))

    if args.judge:
        print(run_judge(fixtures))

    disagreements = [outcome for outcome in outcomes if not outcome.agreed]
    if disagreements:
        print(f"FAILED: {len(disagreements)} fixture(s) disagree with the golden set.")
        return 1
    print("PASSED: the checks agree with the golden set on every fixture.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
