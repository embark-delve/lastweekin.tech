"""Deterministic quality checks for generated summaries.

The publish gate in :mod:`lastweekintech.validation` answers one question: is
this digest fit to ship at all? It deliberately knows nothing about whether a
summary is *good*, which left every prompt or model change unmeasurable.

This module is the measurement. Every check here is pure, network-free and
independently callable, so the same code serves as a test oracle, as an offline
report over ``data/archive/*.json`` and as a regression suite for prompt
changes. Each check returns a reason rather than a bare boolean: a score that
cannot say what is wrong is not actionable.

Checks deliberately *not* implemented, because a noisy check is worse than no
check: n-gram overlap with the source (punishes good abstractive prose),
readability scores (say nothing about faithfulness), and any attempt to judge
"leads with what happened" or tone without a model. Those live behind the
optional LLM judge at the bottom of this file.
"""

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field

from lastweekintech.domain import Story
from lastweekintech.summarizer import OPENROUTER_BASE_URL, CompleteFn, Completion

# Placeholder text emitted by earlier versions of the pipeline, and the length
# below which a "summary" is a fragment. These live here rather than in the
# publish gate because they define what a usable summary *is*; the gate decides
# only how many bad ones an edition may carry.
STUB_SUMMARIES = {"summary not available.", "summary not available", "n/a", ""}
MIN_SUMMARY_CHARS = 40

# --------------------------------------------------------------------------- #
# Check names and weights
# --------------------------------------------------------------------------- #

SUBSTANCE = "substance"
TRUNCATION = "truncation"
LENGTH = "length"
SUBJECT_COVERAGE = "subject_coverage"
NUMBER_GROUNDING = "number_grounding"
ENTITY_GROUNDING = "entity_grounding"
CONTRACT = "contract"

# Not every failure is equally bad. A summary that is cut off mid-word, invents
# a figure or never names its subject is unusable; one that runs to five
# sentences is merely off-spec. The weights encode that, so a single number
# still ranks two prompts sensibly.
CHECK_WEIGHTS = {
    SUBSTANCE: 3.0,
    TRUNCATION: 2.0,
    SUBJECT_COVERAGE: 2.0,
    NUMBER_GROUNDING: 2.0,
    CONTRACT: 1.5,
    ENTITY_GROUNDING: 1.0,
    LENGTH: 1.0,
}

CHECK_NAMES = (
    SUBSTANCE,
    TRUNCATION,
    LENGTH,
    SUBJECT_COVERAGE,
    NUMBER_GROUNDING,
    ENTITY_GROUNDING,
    CONTRACT,
)

# The summarizer prompt asks for 2-4 complete sentences.
MIN_SENTENCES = 2
MAX_SENTENCES = 4

# How far a figure may drift from the source before it counts as ungrounded.
# Rounding "$696.5 million" to "$696 million" is good summarization; "$896.4
# million" is not.
NUMBER_TOLERANCE = 0.01


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one check, with the reason it failed."""

    name: str
    passed: bool
    reason: str = ""
    details: tuple[str, ...] = ()
    # A check that cannot be run (no source text, no entity in the title)
    # reports ``skipped`` and stays out of the score rather than inventing a
    # verdict from nothing.
    skipped: bool = False

    @property
    def weight(self) -> float:
        return CHECK_WEIGHTS.get(self.name, 1.0)


@dataclass(frozen=True)
class QualityReport:
    """Every check for one summary, plus the score they add up to."""

    title: str
    summary: str
    checks: tuple[CheckResult, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """True when no check failed."""
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if not check.passed)

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.failures)

    @property
    def reasons(self) -> tuple[str, ...]:
        return tuple(check.reason for check in self.failures)

    @property
    def score(self) -> float:
        """The weighted fraction of applicable checks that passed, 0.0-1.0.

        A failed substance check zeroes the score outright. A placeholder still
        quotes no invented figures and still uses no first person, and letting
        it bank those vacuous passes put "Summary not available." above half
        marks — a ranking nobody should act on.
        """
        for check in self.checks:
            if check.name == SUBSTANCE and not check.passed:
                return 0.0

        applicable = [check for check in self.checks if not check.skipped]
        total = sum(check.weight for check in applicable)
        if not total:
            return 0.0
        earned = sum(check.weight for check in applicable if check.passed)
        return round(earned / total, 3)

    def check(self, name: str) -> CheckResult:
        """Return the result named ``name``."""
        for check in self.checks:
            if check.name == name:
                return check
        raise KeyError(name)


# --------------------------------------------------------------------------- #
# Text primitives
# --------------------------------------------------------------------------- #

# Sentence terminator, optionally followed by a closing quote or bracket, that
# is followed by whitespace or the end of the text. Same shape as
# ``text._SENTENCE_END``; kept here because this module also needs the match
# positions to look either side of the boundary.
_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]?(?=\s|$)")  # noqa: RUF001 - curly quotes intended

# The word immediately before a candidate boundary.
_WORD_BEFORE = re.compile(r"([A-Za-z][A-Za-z0-9]*)$")

# A trailing ellipsis is an explicit truncation marker even though it ends in a
# period the sentence splitter would happily accept.
_TRAILING_ELLIPSIS = re.compile(r"(?:\.\s*\.\s*\.|…)[\"'”’)\]]?\s*$")  # noqa: RUF001

# Abbreviations whose trailing period is not a sentence end. Single letters
# ("U.S.", "A.I.", initials) are handled separately.
_ABBREVIATIONS = {
    "al", "approx", "apr", "aug", "capt", "co", "corp", "dec", "dept", "dr", "eng", "est", "etc",
    "feb", "fig", "gen", "gov", "inc", "jan", "jr", "jul", "jun", "lt", "ltd", "mar", "mr", "mrs",
    "ms", "no", "nov", "oct", "prof", "rep", "rev", "sen", "sept", "sep", "sr", "st", "univ", "vs",
}  # fmt: skip

# Words that are capitalised without being names: sentence openers, headline
# verbs and calendar terms. Everything here is excluded from entity extraction,
# which is what keeps title-case headlines from reading as a wall of entities.
_COMMON_WORDS = {
    "a", "about", "above", "according", "across", "add", "adds", "after", "again", "against",
    "all", "almost", "along", "already", "also", "although", "always", "among", "an", "and",
    "announce", "announced", "announces", "another", "any", "are", "around", "as", "at", "back",
    "bad", "be", "because", "become", "becomes", "been", "before", "behind", "being", "below",
    "best", "better", "between", "big", "biggest", "both", "bring", "brings", "build", "builds",
    "built", "but", "buy", "buys", "by", "call", "called", "calls", "can", "cannot", "come",
    "comes", "coming", "could", "cut", "cuts", "day", "days", "despite", "did", "do", "does",
    "doing", "done", "down", "during", "each", "early", "either", "end", "enough", "even",
    "ever", "every", "few", "find", "finds", "first", "for", "found", "from", "full", "further",
    "get", "gets", "getting", "give", "gives", "go", "goes", "going", "gone", "good", "got",
    "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how", "however",
    "i", "if", "in", "including", "inside", "instead", "into", "is", "it", "its", "just", "keep",
    "keeps", "kill", "kills", "know", "known", "knows", "large", "largest", "last", "late",
    "later", "latest", "launch", "launched", "launches", "less", "let", "lets", "like", "little",
    "long", "look", "looks", "made", "make", "makes", "making", "many", "may", "me", "meanwhile",
    "might", "mine", "monday", "month", "months", "more", "most", "much", "must", "my", "near",
    "nearly", "need", "needs", "neither", "never", "new", "newest", "next", "no", "not", "nothing",
    "now", "of", "off", "old", "on", "once", "one", "only", "onto", "open", "opens", "or",
    "other", "others", "our", "ours", "out", "outside", "over", "overall", "own", "part", "past",
    "per", "plan", "plans", "put", "puts", "release", "released", "releases", "report",
    "reported", "reports", "review", "reviews", "run", "runs", "said", "same", "saturday", "say",
    "says", "second", "see", "seen", "sees", "sell", "sells", "set", "sets", "several", "she",
    "ship", "ships", "should", "show", "shows", "since", "small", "so", "some", "soon", "start",
    "started", "starts", "still", "stop", "stops", "such", "sunday", "take", "takes", "taking",
    "team", "tell", "tells", "than", "that", "the", "their", "theirs", "them", "then", "there",
    "these", "they", "third", "this", "those", "though", "three", "through", "thursday", "time",
    "times", "to", "today", "together", "too", "took", "top", "toward", "try", "tries", "tuesday",
    "turn", "turns", "two", "under", "until", "up", "update", "updated", "updates", "upon", "us",
    "use", "used", "uses", "using", "very", "want", "wants", "was", "way", "we", "wednesday",
    "week", "weeks", "well", "went", "were", "what", "when", "where", "whether", "which", "while",
    "who", "whose", "why", "will", "with", "within", "without", "work", "works", "would", "year",
    "years", "yet", "you", "your", "april", "august", "december", "february", "friday", "january",
    "july", "june", "march", "november", "october", "september",
    # Generic nouns that open sentences in business and tech prose. Without
    # these, "Losses widened" and "Summary not available." read as names and
    # the grounding check reports them as hallucinated.
    "analyst", "analysts", "app", "apps", "available", "battery", "code", "company", "companies",
    "content", "customer", "customers", "data", "device", "devices", "feature", "features",
    "growth", "hardware", "loss", "losses", "market", "markets", "model", "models", "news",
    "people", "price", "prices", "privacy", "product", "products", "research", "revenue",
    "sales", "security", "service", "services", "software", "story", "stories", "summary",
    "support", "tool", "tools", "user", "users", "version", "versions",
}  # fmt: skip

# A token that could be a name: letters or digits, allowing internal periods,
# hyphens and apostrophes ("U.S.", "GPT-5", "O'Reilly").
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.'\-]*")

# A figure: grouped thousands or a plain run of digits, with an optional
# decimal part. Deliberately strict — a looser pattern swallowed the gap in
# "in 2021, 18 companies" and read it as the single number 202118.
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

# Number words the source may spell out where the summary uses digits.
_SPELLED_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "thousand": 1000, "million": 1000000, "billion": 1000000000,
}  # fmt: skip

_SPELLED_NUMBER_PATTERN = re.compile(
    r"(?<![a-z])(?:" + "|".join(_SPELLED_NUMBERS) + r")(?![a-z])", re.IGNORECASE
)

# Text inside double quotes: a quoted source may legitimately speak in the first
# person, so pronoun matching ignores these spans.
_QUOTED = re.compile(r"[\"\u201c][^\"\u201d]*[\"\u201d]")

_FIRST_PERSON = re.compile(
    r"(?<![A-Za-z0-9])(?:i|i'm|i've|i'll|we|we're|we've|we'll|our|ours|my|mine|me)"
    r"(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# "us" only in lower case, so "US" and "U.S." are not read as a pronoun.
_FIRST_PERSON_US = re.compile(r"(?<![A-Za-z0-9])us(?![A-Za-z0-9])")

_META_PHRASES = (
    "this article",
    "the article",
    "this piece",
    "this post",
    "this story describes",
    "the author",
    "the passage",
    "the text above",
    "in summary",
    "to summarize",
    "to sum up",
    "in conclusion",
    "here is a summary",
    "here's a summary",
    "here is the gist",
    "as an ai",
    "as a language model",
    "i cannot",
    "i'm sorry",
)

# Typographic characters that must compare equal to their ASCII forms. Named by
# codepoint: the literals are invisible or indistinguishable in a diff.
_SPACE_VARIANTS = ("\u00a0", "\u202f", "\u2009", "\u2007")  # nbsp, narrow nbsp, thin, figure
_APOSTROPHE_VARIANTS = ("\u2018", "\u2019", "\u02bc")
_QUOTE_VARIANTS = ("\u201c", "\u201d")

_META_PATTERN = re.compile(
    r"(?<![a-z])(?:" + "|".join(re.escape(p) for p in _META_PHRASES) + r")(?![a-z])",
    re.IGNORECASE,
)


def normalize_text(text: str | None) -> str:
    """Return ``text`` with typographic spaces and quotes flattened to ASCII.

    Model output and scraped article bodies are full of narrow no-break spaces
    and curly quotes: the archived editions write revenue as "$696\u202fmillion"
    and possessives as "Cloudflare\u2019s". Every check below compares strings,
    so they all start here.
    """
    if not text:
        return ""
    flattened = unicodedata.normalize("NFKC", text)
    for char in _SPACE_VARIANTS:
        flattened = flattened.replace(char, " ")
    for char in _APOSTROPHE_VARIANTS:
        flattened = flattened.replace(char, "'")
    for char in _QUOTE_VARIANTS:
        flattened = flattened.replace(char, '"')
    return flattened


def _sentence_ends(text: str) -> list[int]:
    """Return the offsets just past each real sentence boundary in ``text``."""
    ends = []
    for match in _SENTENCE_END.finditer(text):
        before = _WORD_BEFORE.search(text[: match.start()])
        if before:
            word = before.group(1)
            # "Inc." and single letters ("U.S.", initials) keep their period.
            if word.lower() in _ABBREVIATIONS or len(word) == 1:
                continue
        rest = text[match.end() :].lstrip()
        # Prose does not start a sentence in lower case; an abbreviation the
        # list above misses usually does.
        if rest and rest[0].islower():
            continue
        ends.append(match.end())
    return ends


def split_sentences(text: str | None) -> list[str]:
    """Split ``text`` into its *complete* sentences.

    Anything after the last sentence boundary is dropped: a trailing fragment
    is what truncation looks like, and counting it as a sentence would hide the
    very failure this module exists to catch.
    """
    stripped = normalize_text(text).strip()
    if not stripped:
        return []

    sentences = []
    start = 0
    for end in _sentence_ends(stripped):
        sentence = stripped[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
    return sentences


def trailing_fragment(text: str | None) -> str:
    """Return the incomplete sentence left at the end of ``text``, if any."""
    stripped = normalize_text(text).strip()
    if not stripped:
        return ""
    ends = _sentence_ends(stripped)
    return stripped[ends[-1] :].strip() if ends else stripped


def distinctive_entities(text: str | None) -> list[str]:
    """Return the capitalised, non-generic tokens of ``text``, in order.

    Capitalisation is the only name signal available without an NER model, so
    the generic-word list does the real work: without it a title-case headline
    reads as a wall of entities and every check downstream becomes noise.
    """
    stripped = normalize_text(text)
    if not stripped:
        return []

    entities = []
    for match in _TOKEN.finditer(stripped):
        token = match.group(0).strip(".-'")
        if not token or len(token) < 2:
            continue
        # A name is capitalised, or capitalised internally ("iPhone", "eBay").
        if not (token[0].isupper() or any(char.isupper() for char in token[1:])):
            continue
        if not any(char.isalpha() for char in token):
            continue
        bare = token.removesuffix("'s").removesuffix("'S")
        if bare.lower() in _COMMON_WORDS or len(bare) < 2:
            continue
        if bare not in entities:
            entities.append(bare)
    return entities


def _mentions(text: str, term: str) -> bool:
    """True when ``term`` appears in ``text`` as a whole word, case-insensitively.

    Tolerant of possessives and of a plural on either side, so "Publishers" in a
    summary is not reported as absent from a source that says "publisher", and
    "Losses" is not reported as absent from one that says "loss".
    """
    for stem in _stems(term):
        pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(stem) + r"(?:'s|s|es)?(?![A-Za-z0-9])", re.IGNORECASE
        )
        if pattern.search(text):
            return True
    return False


def _stems(term: str) -> list[str]:
    """Return ``term`` and the singular forms it might have been inflected from."""
    stems = [term]
    lowered = term.lower()
    if len(term) > 4 and lowered.endswith("ies"):
        stems.append(term[:-3] + "y")
    if len(term) > 4 and lowered.endswith("es"):
        stems.append(term[:-2])
    if len(term) > 3 and lowered.endswith("s") and not lowered.endswith("ss"):
        stems.append(term[:-1])
    return stems


def _numbers(text: str) -> list[float]:
    """Return every figure in ``text`` as a float, separators removed."""
    values = []
    for match in _NUMBER.finditer(normalize_text(text)):
        raw = match.group(0).replace(",", "").replace(" ", "")
        try:
            values.append(float(raw))
        except ValueError:  # pragma: no cover - the pattern cannot produce this
            continue
    return values


def _source_numbers(source_text: str) -> list[float]:
    """Every figure in the source, including the ones it spells out in words."""
    values = _numbers(source_text)
    for match in _SPELLED_NUMBER_PATTERN.finditer(normalize_text(source_text)):
        values.append(float(_SPELLED_NUMBERS[match.group(0).lower()]))
    return values


def _is_year(value: float) -> bool:
    return value.is_integer() and 1900 <= value <= 2100


def _decimals(value: float) -> int:
    if value.is_integer():
        return 0
    text = repr(value)
    return len(text.split(".")[1]) if "." in text else 0


def _grounded_number(value: float, source_values: list[float]) -> bool:
    """True when ``value`` is supported by some figure in the source.

    Rounding is legitimate summarization, so a small relative drift counts as
    grounded — except for years, where "2021" and "2022" are a rounding error
    apart numerically and a factual error apart in practice.
    """
    for source in source_values:
        if source == value:
            return True
        if _is_year(value) or _is_year(source):
            continue
        if round(source, _decimals(value)) == value:
            return True
        if abs(source - value) <= NUMBER_TOLERANCE * max(abs(source), 1.0):
            return True
    return False


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


def check_substance(summary: str | None) -> CheckResult:
    """The summary is real text and not one of the placeholders we used to ship."""
    text = normalize_text(summary).strip()
    if not text:
        return CheckResult(SUBSTANCE, False, "the summary is empty")
    if text.lower() in STUB_SUMMARIES:
        return CheckResult(SUBSTANCE, False, f"the summary is the placeholder {text!r}")
    if len(text) < MIN_SUMMARY_CHARS:
        return CheckResult(
            SUBSTANCE,
            False,
            f"the summary is {len(text)} characters, below the {MIN_SUMMARY_CHARS} minimum",
        )
    return CheckResult(SUBSTANCE, True)


def check_truncation(summary: str | None) -> CheckResult:
    """The summary ends on a finished sentence rather than mid-thought."""
    text = normalize_text(summary).strip()
    if not text:
        return CheckResult(TRUNCATION, False, "the summary is empty")

    if _TRAILING_ELLIPSIS.search(text):
        return CheckResult(TRUNCATION, False, "the summary trails off in an ellipsis")

    fragment = trailing_fragment(text)
    if fragment:
        return CheckResult(
            TRUNCATION,
            False,
            f"the summary is cut off mid-sentence: ...{fragment[-80:]!r}"
            if len(fragment) > 80
            else f"the summary is cut off mid-sentence: {fragment!r}",
            details=(fragment,),
        )
    return CheckResult(TRUNCATION, True)


def check_length(summary: str | None) -> CheckResult:
    """The summary is the 2-4 complete sentences the prompt asks for."""
    count = len(split_sentences(summary))
    if count < MIN_SENTENCES:
        return CheckResult(
            LENGTH,
            False,
            f"{count} complete sentence(s); the contract asks for {MIN_SENTENCES}-{MAX_SENTENCES}",
        )
    if count > MAX_SENTENCES:
        return CheckResult(
            LENGTH,
            False,
            f"{count} sentences; the contract asks for {MIN_SENTENCES}-{MAX_SENTENCES}",
        )
    return CheckResult(LENGTH, True)


def check_subject_coverage(title: str | None, summary: str | None) -> CheckResult:
    """The summary names at least one subject of the headline.

    Requiring *every* headline entity would fail good summaries that drop a
    secondary name, so this asks the weaker question that actually matters in a
    digest: does the reader learn what the item is about?
    """
    entities = distinctive_entities(title)
    if not entities:
        return CheckResult(
            SUBJECT_COVERAGE, True, "no distinctive entity in the title to look for", skipped=True
        )

    text = normalize_text(summary)
    covered = [entity for entity in entities if _mentions(text, entity)]
    if covered:
        return CheckResult(SUBJECT_COVERAGE, True, details=tuple(covered))
    return CheckResult(
        SUBJECT_COVERAGE,
        False,
        f"the summary never names the subject of the headline: {', '.join(entities)}",
        details=tuple(entities),
    )


def check_number_grounding(source_text: str | None, summary: str | None) -> CheckResult:
    """Every figure in the summary appears in the source article.

    The cheapest hallucination signal there is, and the one production actually
    needs: a wrong revenue number in a digest is worse than no digest.
    """
    source = normalize_text(source_text).strip()
    if not source:
        return CheckResult(
            NUMBER_GROUNDING, True, "no source text to check figures against", skipped=True
        )

    if not normalize_text(summary).strip():
        # An empty summary must not earn credit for inventing nothing; the
        # substance check owns that failure.
        return CheckResult(NUMBER_GROUNDING, True, "the summary is empty", skipped=True)

    values = _numbers(summary or "")
    if not values:
        return CheckResult(NUMBER_GROUNDING, True, "the summary quotes no figures")

    source_values = _source_numbers(source)
    ungrounded = [value for value in values if not _grounded_number(value, source_values)]
    if not ungrounded:
        return CheckResult(NUMBER_GROUNDING, True)

    shown = [f"{value:g}" for value in dict.fromkeys(ungrounded)]
    return CheckResult(
        NUMBER_GROUNDING,
        False,
        f"{len(shown)} figure(s) absent from the source: {', '.join(shown)}",
        details=tuple(shown),
    )


def check_entity_grounding(source_text: str | None, summary: str | None) -> CheckResult:
    """Every name in the summary appears in the source article.

    Weaker than the figure check — a summary may legitimately compress "United
    States" to "US" — so it carries a lower weight and matches generously.
    """
    source = normalize_text(source_text).strip()
    if not source:
        return CheckResult(
            ENTITY_GROUNDING, True, "no source text to check names against", skipped=True
        )

    if not normalize_text(summary).strip():
        return CheckResult(ENTITY_GROUNDING, True, "the summary is empty", skipped=True)

    entities = distinctive_entities(summary)
    if not entities:
        return CheckResult(ENTITY_GROUNDING, True, "the summary names no entities")

    ungrounded = []
    for entity in entities:
        parts = [part for part in re.split(r"[.\-']", entity) if len(part) > 1] or [entity]
        if not any(_mentions(source, part) for part in parts):
            ungrounded.append(entity)

    if not ungrounded:
        return CheckResult(ENTITY_GROUNDING, True)
    return CheckResult(
        ENTITY_GROUNDING,
        False,
        f"{len(ungrounded)} name(s) absent from the source: {', '.join(ungrounded)}",
        details=tuple(ungrounded),
    )


def check_contract(summary: str | None) -> CheckResult:
    """The summary is reported prose, not commentary or a note about itself."""
    text = normalize_text(summary)
    if not text.strip():
        return CheckResult(CONTRACT, False, "the summary is empty")

    problems = []

    meta = sorted({match.group(0).lower() for match in _META_PATTERN.finditer(text)})
    if meta:
        problems.append(f"meta-phrasing: {', '.join(repr(phrase) for phrase in meta)}")

    # A quoted speaker is allowed to say "we"; the summarizer is not.
    unquoted = _QUOTED.sub(" ", text)
    pronouns = sorted({match.group(0).lower() for match in _FIRST_PERSON.finditer(unquoted)})
    pronouns += sorted({match.group(0) for match in _FIRST_PERSON_US.finditer(unquoted)})
    if pronouns:
        problems.append(f"first person: {', '.join(repr(word) for word in pronouns)}")

    if problems:
        return CheckResult(CONTRACT, False, "; ".join(problems), details=tuple(problems))
    return CheckResult(CONTRACT, True)


def assess_summary(title: str, source_text: str | None, summary: str | None) -> QualityReport:
    """Run every check over one summary and return the combined report."""
    return QualityReport(
        title=title,
        summary=normalize_text(summary).strip(),
        checks=(
            check_substance(summary),
            check_truncation(summary),
            check_length(summary),
            check_subject_coverage(title, summary),
            check_number_grounding(source_text, summary),
            check_entity_grounding(source_text, summary),
            check_contract(summary),
        ),
    )


def assess_story(story: Story) -> QualityReport:
    """Assess a story's summary against the richest article body in its cluster.

    Mirrors :func:`lastweekintech.pipeline.summarize_stories`, which summarizes
    the longest body available, so the check sees the text the model saw.
    """
    bodies = sorted((a.content or "" for a in story.articles), key=len, reverse=True)
    return assess_summary(story.title, bodies[0] if bodies else "", story.summary)


# --------------------------------------------------------------------------- #
# Optional LLM judge
# --------------------------------------------------------------------------- #
#
# Everything above is deterministic and runs in the test suite. Everything below
# calls a model, so it is opt-in: `judge_available()` gates it on a key, the
# `complete` callable is injectable exactly as in the summarizer, and no code
# path here runs unless a caller asks for it by name.

JUDGE_MODEL = "openai/gpt-4o-mini"

JUDGE_SYSTEM_PROMPT = (
    "You audit summaries of technical news for faithfulness. Given an article "
    "and a summary of it, decide whether every claim in the summary is "
    "supported by the article. Judge only faithfulness, never style or "
    "interest. Reply with a single JSON object and nothing else: "
    '{"faithful": true or false, "unsupported": ["claim", ...], '
    '"reason": "one sentence"}.'
)

JUDGE_MAX_TOKENS = 400
JUDGE_MAX_SOURCE_CHARS = 12000

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class JudgeError(RuntimeError):
    """Raised when the judge model returns something unusable."""


@dataclass(frozen=True)
class JudgeVerdict:
    """A model's faithfulness verdict on one summary."""

    faithful: bool
    reason: str = ""
    unsupported: tuple[str, ...] = ()
    raw: str = ""


def judge_available() -> bool:
    """True when a live judge could run: only an API key stands in the way."""
    return bool(os.getenv("OPENROUTER_API_KEY"))


def build_judge_messages(title: str, source_text: str, summary: str) -> list[dict[str, str]]:
    """Return the chat messages for a faithfulness audit."""
    return [
        {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"HEADLINE:\n{title}\n\n"
                f"ARTICLE:\n{(source_text or '')[:JUDGE_MAX_SOURCE_CHARS]}\n\n"
                f"SUMMARY:\n{summary}"
            ),
        },
    ]


def parse_judge_response(text: str) -> JudgeVerdict:
    """Parse a judge reply, tolerating the code fences models like to add."""
    match = _JSON_OBJECT.search(text or "")
    if not match:
        raise JudgeError(f"no JSON object in the judge reply: {text!r}")
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeError(f"unparsable judge reply: {text!r}") from exc
    if not isinstance(payload, dict) or "faithful" not in payload:
        raise JudgeError(f"judge reply has no verdict: {text!r}")

    unsupported = payload.get("unsupported") or []
    if isinstance(unsupported, str):
        unsupported = [unsupported]
    return JudgeVerdict(
        faithful=bool(payload["faithful"]),
        reason=str(payload.get("reason", "")),
        unsupported=tuple(str(item) for item in unsupported),
        raw=text,
    )


def judge_summary(
    title: str,
    source_text: str,
    summary: str,
    complete: CompleteFn | None = None,
    model: str = JUDGE_MODEL,
) -> JudgeVerdict:
    """Ask a model whether ``summary`` is faithful to ``source_text``.

    ``complete`` is injectable for the same reason it is in the summarizer: the
    tests stub it and never touch the network. With no ``complete`` and no API
    key this raises rather than silently reporting a verdict nobody produced.
    """
    responder = complete or _complete_via_api
    if complete is None and not judge_available():
        raise JudgeError("OPENROUTER_API_KEY is not set; the LLM judge cannot run.")

    completion = responder(
        model, build_judge_messages(title, source_text, summary), JUDGE_MAX_TOKENS
    )
    logging.info(f"Judged a summary with {model}.")
    return parse_judge_response(completion.text)


def _complete_via_api(model: str, messages: list[dict[str, str]], max_tokens: int) -> Completion:
    """Default judge transport. Imported lazily so no client is built unused."""
    from openai import OpenAI

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=os.getenv("OPENROUTER_API_KEY"))
    response = client.chat.completions.create(
        model=model,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=max_tokens,
        temperature=0.0,
    )
    choice = response.choices[0]
    return Completion(text=choice.message.content or "", finish_reason=choice.finish_reason)
