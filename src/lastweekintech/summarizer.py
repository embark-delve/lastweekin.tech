"""
Summarization for the LastWeekIn.Tech pipeline, via any OpenAI-compatible API.
"""

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from lastweekintech.config import SummarizerSettings
from lastweekintech.text import trim_to_sentence

# Leading markdown furniture some models wrap a summary in: heading lines
# ("# Summary") and bold-only label lines ("**Summary**"). Observed live on
# 2026-08-30 from models in the fallback chain; stripped rather than rejected
# because the prose underneath is usually fine.
_MARKDOWN_PREAMBLE = re.compile(r"^(?:\s*(?:#{1,6}\s+\S[^\n]*|\*\*[^\n*]+\*\*\s*)(?:\n+|$))+")

# A summary that opens by declining is a refusal, not a summary. Anchored to
# the start so reported prose about inability ("NASA said it cannot...") is
# never misread. Rejecting it returns "" to the caller, which is what lets the
# fallback chain try the next model or article.
_REFUSAL = re.compile(
    r"^(?:i\s+(?:cannot|can't|am\s+unable)|i'm\s+(?:unable|sorry)|unfortunately,?\s+i)",
    re.IGNORECASE,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
HUGGINGFACE_BASE_URL = "https://router.huggingface.co/v1"

SYSTEM_PROMPT = (
    "You summarize technical news for a weekly digest. Write 2-4 complete "
    "sentences in plain prose. Lead with what happened and who it affects. "
    "Use only facts present in the article, name the companies, people and "
    "products involved, and never add commentary or speculation."
)


@dataclass
class Completion:
    """A model response and why generation stopped."""

    text: str
    finish_reason: str | None = None


CompleteFn = Callable[[str, list[dict[str, str]], int], Completion]


class Summarizer:
    """Summarizes article text, falling back across models until one answers."""

    def __init__(self, settings: SummarizerSettings, complete: CompleteFn | None = None):
        self.settings = settings
        self.primary_model = settings.model_name
        self.fallback_models = list(settings.fallback_models)
        # Which model actually answered the last call. The run metrics report
        # this per story, and on a week where the primary is rate-limited the
        # configured name would be a lie.
        self.last_model: str | None = None
        self._complete = complete or self._complete_via_api

        if complete is None:
            # Credentials are checked before any client is built: the OpenAI
            # constructor raises its own error for a missing key, which reaches
            # the user as a traceback instead of a configuration message.
            self._drop_unusable_models()
            self._openrouter_client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=os.getenv("OPENROUTER_API_KEY"),
            )
            self._huggingface_client = (
                OpenAI(base_url=HUGGINGFACE_BASE_URL, api_key=settings.hf_token)
                if settings.hf_token
                else None
            )

        logging.info(f"Using summarization model: {self.primary_model}")

    def summarize(self, text: str) -> str:
        """Summarize ``text``, returning "" when no model produces a usable answer."""
        text = (text or "").strip()
        self.last_model = None
        if not text:
            return ""

        for model in [self.primary_model, *self.fallback_models]:
            summary = self._summarize_with_model(model, text)
            if summary:
                self.last_model = model
                return summary

        logging.error("All summarization models failed.")
        return ""

    def _summarize_with_model(self, model: str, text: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Summarize this article:\n\n{text[: self.settings.max_input_chars]}",
            },
        ]
        try:
            logging.info(f"Generating summary with {model}...")
            completion = self._complete(model, messages, self.settings.max_tokens)
        except Exception as e:  # noqa: BLE001 - try the next model instead
            logging.warning(f"Model {model} failed: {e}")
            return ""

        summary = _MARKDOWN_PREAMBLE.sub("", (completion.text or "").strip()).strip()
        if not summary:
            logging.warning(f"Model {model} returned an empty summary.")
            return ""

        if _REFUSAL.match(summary):
            logging.warning(f"Model {model} refused to summarize: {summary[:80]!r}")
            return ""

        if completion.finish_reason == "length":
            # The budget ran out mid-sentence; keep only whole sentences, and
            # treat a summary with none as a failure so a fallback model runs.
            trimmed = trim_to_sentence(summary)
            if trimmed == summary:
                logging.warning(f"Model {model} hit the token limit with no complete sentence.")
                return ""
            logging.info(f"Trimmed a truncated summary from {model} to its last full sentence.")
            return trimmed

        return summary

    def _complete_via_api(
        self, model: str, messages: list[dict[str, str]], max_tokens: int
    ) -> Completion:
        response = self._client_for(model).chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=self.settings.temperature,
        )
        choice: Any = response.choices[0]
        return Completion(text=choice.message.content or "", finish_reason=choice.finish_reason)

    def _client_for(self, model: str) -> OpenAI:
        if model in self.settings.huggingface_models:
            if not self._huggingface_client:
                raise RuntimeError("Hugging Face client not initialized: HF_TOKEN is missing.")
            return self._huggingface_client
        return self._openrouter_client

    def _drop_unusable_models(self) -> None:
        """Skip models whose credentials are absent rather than failing per story."""
        if not self.settings.hf_token:
            unusable = set(self.settings.huggingface_models)
            self.fallback_models = [m for m in self.fallback_models if m not in unusable]
            if self.primary_model in unusable:
                raise ValueError(f"HF_TOKEN is not set but {self.primary_model} requires it.")
            if unusable:
                logging.warning(f"HF_TOKEN not set; skipping {len(unusable)} Hugging Face models.")

        if not os.getenv("OPENROUTER_API_KEY") and self.primary_model not in set(
            self.settings.huggingface_models
        ):
            raise ValueError("OPENROUTER_API_KEY environment variable not set.")
