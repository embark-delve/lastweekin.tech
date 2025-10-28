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
        self.clients = {}

        for provider in self.settings.providers:
            api_key = os.getenv(provider.api_key_env)
            if not api_key:
                raise ValueError(
                    f"{provider.api_key_env} environment variable not set.",
                )
            self.clients[provider.name] = OpenAI(
                base_url=provider.base_url,
                api_key=api_key,
            )

        logging.info(f"Using summarization model: {self.primary_model}")

    def _get_client(self, model_name: str) -> OpenAI:
        provider_name, _ = model_name.split("/", 1)
        client = self.clients.get(provider_name)
        if not client:
            raise ValueError(f"Provider '{provider_name}' not configured.")
        return client

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
