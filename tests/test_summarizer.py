"""Tests for summarization and its fallback behaviour."""

import pytest
from conftest import make_article, make_story

from lastweekintech import pipeline
from lastweekintech.config import SummarizerSettings
from lastweekintech.summarizer import Completion, Summarizer


def settings(**overrides) -> SummarizerSettings:
    base = {
        "model_name": "primary/model",
        "fallback_models": ["backup/model"],
        "max_tokens": 400,
        "max_input_chars": 100,
    }
    return SummarizerSettings(**(base | overrides))


def responder(**by_model):
    """Build a completion function that answers per model name."""
    calls = []

    def complete(model, messages, max_tokens):
        calls.append((model, messages, max_tokens))
        result = by_model[model]
        if isinstance(result, Exception):
            raise result
        return result

    complete.calls = calls
    return complete


class TestSummarize:
    def test_returns_the_primary_model_summary(self):
        complete = responder(**{"primary/model": Completion("A tidy summary.", "stop")})
        assert Summarizer(settings(), complete=complete).summarize("text") == "A tidy summary."

    def test_falls_back_when_the_primary_model_returns_nothing(self):
        complete = responder(**{
            "primary/model": Completion("", "stop"),
            "backup/model": Completion("Backup summary.", "stop"),
        })
        assert Summarizer(settings(), complete=complete).summarize("text") == "Backup summary."

    def test_falls_back_when_the_primary_model_raises(self):
        complete = responder(**{
            "primary/model": RuntimeError("rate limited"),
            "backup/model": Completion("Backup summary.", "stop"),
        })
        assert Summarizer(settings(), complete=complete).summarize("text") == "Backup summary."

    def test_returns_empty_when_every_model_fails(self):
        complete = responder(**{
            "primary/model": RuntimeError("down"),
            "backup/model": RuntimeError("down"),
        })
        assert Summarizer(settings(), complete=complete).summarize("text") == ""

    def test_trims_a_summary_the_model_cut_off_mid_sentence(self):
        complete = responder(**{
            "primary/model": Completion("Complete thought. Then it was cut", "length")
        })
        assert Summarizer(settings(), complete=complete).summarize("text") == "Complete thought."

    def test_falls_back_when_a_truncated_summary_has_no_usable_sentence(self):
        complete = responder(**{
            "primary/model": Completion("Bethesda marked Quake's 30", "length"),
            "backup/model": Completion("A whole summary.", "stop"),
        })
        assert Summarizer(settings(), complete=complete).summarize("text") == "A whole summary."

    def test_leaves_a_complete_summary_untouched(self):
        complete = responder(**{"primary/model": Completion("Two words. Here.", "stop")})
        assert Summarizer(settings(), complete=complete).summarize("text") == "Two words. Here."

    def test_sends_the_configured_token_budget(self):
        complete = responder(**{"primary/model": Completion("Done.", "stop")})
        Summarizer(settings(max_tokens=512), complete=complete).summarize("text")
        assert complete.calls[0][2] == 512

    def test_truncates_over_long_input(self):
        complete = responder(**{"primary/model": Completion("Done.", "stop")})
        Summarizer(settings(max_input_chars=100), complete=complete).summarize("x" * 5000)
        prompt = complete.calls[0][1][-1]["content"]
        assert len(prompt) < 500

    def test_refuses_empty_input_without_calling_a_model(self):
        def complete(model, messages, max_tokens):
            raise AssertionError("must not call a model for empty text")

        assert Summarizer(settings(), complete=complete).summarize("   ") == ""


class TestReportsWhichModelAnswered:
    """Run metrics record the model per story, so a fallback must be visible."""

    def test_records_the_model_that_produced_the_summary(self):
        complete = responder(**{
            "primary/model": Completion("", "stop"),
            "backup/model": Completion("Backup summary.", "stop"),
        })
        summarizer = Summarizer(settings(), complete=complete)
        summarizer.summarize("text")
        assert summarizer.last_model == "backup/model"

    def test_last_model_is_unset_before_any_call(self):
        assert Summarizer(settings(), complete=responder()).last_model is None

    def test_last_model_is_unset_when_every_model_fails(self):
        complete = responder(**{
            "primary/model": RuntimeError("down"),
            "backup/model": RuntimeError("down"),
        })
        summarizer = Summarizer(settings(), complete=complete)
        summarizer.summarize("text")
        assert summarizer.last_model is None


class TestCredentialChecks:
    def test_a_missing_openrouter_key_is_a_clear_configuration_error(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            Summarizer(settings())

    def test_hugging_face_fallbacks_are_dropped_when_the_token_is_absent(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        configured = settings(
            fallback_models=["backup/model", "hf/model"],
            huggingface_models=["hf/model"],
            hf_token=None,
        )
        assert Summarizer(configured).fallback_models == ["backup/model"]

    def test_a_hugging_face_primary_without_a_token_is_a_configuration_error(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        configured = settings(model_name="hf/model", huggingface_models=["hf/model"], hf_token=None)
        with pytest.raises(ValueError, match="HF_TOKEN"):
            Summarizer(configured)


class TestSummarizeStories:
    def test_summarizes_the_article_with_the_most_content(self):
        story = make_story(
            articles=[
                make_article(url="https://a.example/1", content="short"),
                make_article(url="https://b.example/2", content="a much longer body of text"),
            ]
        )
        seen = []

        class Fake:
            def summarize(self, text):
                seen.append(text)
                return "Summary."

        pipeline.summarize_stories([story], Fake())
        assert seen == ["a much longer body of text"]

    def test_falls_through_to_another_article_when_the_first_yields_nothing(self):
        story = make_story(
            articles=[
                make_article(url="https://a.example/1", content="a much longer body of text"),
                make_article(url="https://b.example/2", content="shorter"),
            ]
        )

        class Fake:
            def summarize(self, text):
                return "" if text.startswith("a much") else "Second summary."

        pipeline.summarize_stories([story], Fake())
        assert story.summary == "Second summary."

    def test_leaves_the_summary_unset_when_no_article_has_content(self):
        story = make_story(articles=[make_article(content=None)])

        class Fake:
            def summarize(self, text):
                raise AssertionError("nothing to summarize")

        pipeline.summarize_stories([story], Fake())
        assert story.summary is None

    def test_leaves_the_summary_unset_when_every_model_fails(self):
        story = make_story(articles=[make_article(content="body")])

        class Fake:
            def summarize(self, text):
                return ""

        pipeline.summarize_stories([story], Fake())
        assert story.summary is None
