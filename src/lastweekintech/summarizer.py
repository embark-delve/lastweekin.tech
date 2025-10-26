"""
Summarization module for the LastWeekIn.Tech pipeline using LiteLLM.
"""

import logging
import os

from litellm import completion

from lastweekintech.config import SummarizerSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class Summarizer:
    """A wrapper around the LiteLLM library for summarization."""

    def __init__(self, settings: SummarizerSettings):
        self.model_name = settings.model_name
        self.fallback_model = settings.fallback_model
        if "openrouter" in self.model_name and not os.getenv("OPENROUTER_API_KEY"):
            raise ValueError("OPENROUTER_API_KEY environment variable not set.")
        logging.info(f"Using summarization model: {self.model_name}")

    def summarize(self, text: str) -> str:
        """Generates a summary for the given text."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that summarizes "
                    "technical articles into a single, concise paragraph."
                ),
            },
            {
                "role": "user",
                "content": f"Please summarize the following article:\n\n{text}",
            },
        ]

        try:
            logging.info(f"Generating summary with {self.model_name}...")
            response = completion(
                model=self.model_name,
                messages=messages,
                max_tokens=150,
                temperature=0.7,
            )
            summary = response.choices[0].message.content.strip()
            if summary:
                return summary
            raise ValueError("Empty summary returned from primary model")
        except Exception as e:
            logging.warning(
                f"Primary model {self.model_name} failed: {e}. "
                f"Falling back to {self.fallback_model}."
            )
            try:
                response = completion(
                    model=self.fallback_model,
                    messages=messages,
                    max_tokens=120,
                )
                summary = response.choices[0].message.content.strip()
                return summary
            except Exception as e_fallback:
                logging.error(f"Fallback model failed: {e_fallback}")
                return ""
