"""
Summarization module for the LastWeekIn.Tech pipeline using OpenAI's API.
"""

import logging
import os

from openai import OpenAI

from lastweekintech.config import SummarizerSettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


class Summarizer:
    """A wrapper around the OpenAI library for summarization."""

    def __init__(self, settings: SummarizerSettings):
        self.settings = settings
        self.primary_model = self.settings.model_name
        self.fallback_models = self.settings.fallback_models

        self.openrouter_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )
        self.huggingface_client = None
        if self.settings.hf_token:
            self.huggingface_client = OpenAI(
                base_url="https://router.huggingface.co/v1",
                api_key=self.settings.hf_token,
            )

        if "openrouter" in self.primary_model and not os.getenv(
            "OPENROUTER_API_KEY",
        ):
            raise ValueError(
                "OPENROUTER_API_KEY environment variable not set.",
            )
        if self.primary_model in self.settings.huggingface_models and not self.settings.hf_token:
            raise ValueError("HF_TOKEN environment variable not set.")

        logging.info(f"Using summarization model: {self.primary_model}")

    def _get_client(self, model_name: str) -> OpenAI:
        if model_name in self.settings.huggingface_models:
            if not self.huggingface_client:
                raise ValueError(
                    "Hugging Face client not initialized. HF_TOKEN is missing.",
                )
            return self.huggingface_client
        return self.openrouter_client

    def _summarize_with_model(self, model_name: str, text: str) -> str:
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
            client = self._get_client(model_name)
            logging.info(f"Generating summary with {model_name}...")
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=150,
                temperature=0.7,
            )
            summary = response.choices[0].message.content.strip()
            if not summary:
                raise ValueError("Empty summary returned from model")
            return summary
        except Exception as e:
            logging.warning(f"Model {model_name} failed: {e}")
            return ""

    def summarize(self, text: str) -> str:
        """Generates a summary for the given text."""
        # Try the primary model first
        summary = self._summarize_with_model(self.primary_model, text)
        if summary:
            return summary

        # If the primary model fails, iterate through the fallback models
        for fallback_model in self.fallback_models:
            logging.info(f"Falling back to {fallback_model}...")
            summary = self._summarize_with_model(fallback_model, text)
            if summary:
                return summary

        logging.error("All summarization models failed.")
        return ""
