"""Editorial selection for the LastWeekIn.Tech pipeline.

The mechanical ranking is ballot access, not the verdict. Scoring by traction,
breadth and recency narrows the week to a candidate pool, but a number cannot
tell a durable industry shift from a viral curiosity — that is editorial
judgment, and it is what human curators are for. Once a week, one model call
plays that role: it reads the pool with a rubric and picks the edition, saying
*why* each story matters and what kind of week it was.

The editor proposes; the pipeline disposes. Its picks pass through the same
mechanical guards as the fallback path (the AI floor, the per-source cap, the
preference for stories with extractable bodies), and any failure — a model
outage, an unparseable answer, an invalid pick — falls back to the mechanical
selection. The editor can only ever improve an edition, never cost one.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field

from openai import OpenAI

from lastweekintech.config import EditorSettings
from lastweekintech.domain import Story
from lastweekintech.summarizer import OPENROUTER_BASE_URL, CompleteFn, Completion

SYSTEM_PROMPT = (
    "You are the editor-in-chief of LastWeekIn.Tech, a weekly digest of the "
    "{count} technology stories that mattered. From the numbered candidates, "
    "choose exactly {count}, in the order you would print them.\n"
    "\n"
    "Judge by:\n"
    "- Durable impact: will this still matter in a year, or is it churn?\n"
    "- Novelty: something genuinely new, not an increment or a rumor.\n"
    "- Breadth: how many people does this actually affect?\n"
    "- Trust: multi-outlet coverage and press-consensus stories over "
    "single-community popularity.\n"
    "- Mix: avoid gadget reviews, deals and listicles; prefer a spread of "
    "topics and outlets (at most {max_per_source} per outlet where possible, "
    "and at least {min_ai} AI stories when the pool has that many worth "
    "running).\n"
    "- Never pick a candidate marked as having no article text: it cannot be "
    "summarized.\n"
    "\n"
    "Reply with JSON only, no prose around it:\n"
    '{{"intro": "2-3 sentences on what kind of week this was in tech", '
    '"picks": [{{"n": <candidate number>, "why": "<one sharp sentence on why '
    'this story matters>"}}]}}'
)


@dataclass
class Pick:
    """One editorial choice: a candidate number and the case for it."""

    n: int
    why: str = ""


@dataclass
class EditorVerdict:
    """The editor's edition: picks in print order, plus the week in brief."""

    picks: list[Pick] = field(default_factory=list)
    intro: str = ""


class Editor:
    """Selects the edition from the candidate pool, falling back across models."""

    def __init__(self, settings: EditorSettings, complete: CompleteFn | None = None):
        self.settings = settings
        self.models = [settings.model_name, *settings.fallback_models]
        # Which model actually answered, for the run metrics.
        self.last_model: str | None = None
        self._complete = complete or self._complete_via_api

        if complete is None:
            if not os.getenv("OPENROUTER_API_KEY"):
                raise ValueError("OPENROUTER_API_KEY environment variable not set.")
            self._client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=os.getenv("OPENROUTER_API_KEY"),
            )

    def select(
        self,
        candidates: list[Story],
        count: int,
        min_ai: int,
        max_per_source: int,
    ) -> EditorVerdict | None:
        """Pick the edition from ``candidates``; ``None`` means "use the fallback".

        A verdict is only returned when a model produced exactly the right
        number of distinct, in-range picks — anything less trustworthy than
        that is not worth overriding the mechanical selection for.
        """
        if not candidates:
            return None
        wanted = min(count, len(candidates))
        self.last_model = None

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    count=wanted, min_ai=min_ai, max_per_source=max_per_source
                ),
            },
            {"role": "user", "content": _render_candidates(candidates, self.settings)},
        ]

        for model in self.models:
            try:
                logging.info(f"Asking {model} to pick the edition...")
                completion = self._complete(model, messages, self.settings.max_tokens)
            except Exception as e:  # noqa: BLE001 - try the next model instead
                logging.warning(f"Editor model {model} failed: {e}")
                continue

            verdict = _parse_verdict(completion.text, pool=len(candidates), wanted=wanted)
            if verdict:
                self.last_model = model
                return verdict
            logging.warning(
                f"Editor model {model} returned an unusable verdict "
                f"(finish_reason={completion.finish_reason!r}): {completion.text[:200]!r}"
            )

        logging.warning("No editor model produced a usable verdict; using the fallback ranking.")
        return None

    def _complete_via_api(
        self, model: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion:
        response = self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=self.settings.temperature,
        )
        choice = response.choices[0]
        return Completion(text=choice.message.content or "", finish_reason=choice.finish_reason)


def _render_candidates(candidates: list[Story], settings: EditorSettings) -> str:
    lines = []
    for n, story in enumerate(candidates, start=1):
        outlets = sorted({a.source for a in story.articles})
        points = max((a.hn_points or 0) for a in story.articles)
        signals = [f"outlets: {', '.join(outlets)}"]
        if points:
            signals.append(f"{points} HN points")
        if story.consensus:
            signals.append("press consensus")

        body = max((a.content or "" for a in story.articles), key=len)
        excerpt = (
            " ".join(body.split())[: settings.excerpt_chars]
            if body
            else "NO ARTICLE TEXT AVAILABLE — cannot be summarized"
        )
        lines.append(
            f"{n}. [{story.category}] {story.title}\n   ({'; '.join(signals)})\n   {excerpt}"
        )
    return "Candidates:\n\n" + "\n\n".join(lines)


def _parse_verdict(answer: str, pool: int, wanted: int) -> EditorVerdict | None:
    """Read the model's JSON, accepting nothing less than a complete edition."""
    match = re.search(r"\{.*\}", answer or "", re.DOTALL)
    if not match:
        return None
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("picks"), list):
        return None

    picks = []
    seen = set()
    for entry in raw["picks"]:
        if not isinstance(entry, dict):
            return None
        n = entry.get("n")
        if not isinstance(n, int) or not 1 <= n <= pool or n in seen:
            return None
        seen.add(n)
        picks.append(Pick(n=n, why=str(entry.get("why") or "").strip()))

    # Trust an over-long list down to the print order, never an under-long one.
    if len(picks) < wanted:
        return None
    return EditorVerdict(picks=picks[:wanted], intro=str(raw.get("intro") or "").strip())
