"""
Summarization module for the LastWeekIn.Tech pipeline.
"""

import logging

from transformers import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class Summarizer:
    """A wrapper around a Hugging Face summarization pipeline."""

    def __init__(self, model_name: str = "facebook/bart-large-cnn"):
        logging.info(f"Loading summarization model: {model_name}...")
        self.pipeline = pipeline("summarization", model=model_name)
        logging.info("Summarization model loaded.")

    def summarize(self, text: str) -> str:
        """Generates a summary for the given text."""
        try:
            summary = self.pipeline(text, max_length=120, min_length=30, do_sample=False)
            return summary[0]["summary_text"]
        except Exception as e:
            logging.error(f"Failed to generate summary: {e}")
            return ""
