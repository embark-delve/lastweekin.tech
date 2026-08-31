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


class TestOutputHygiene:
    """Defects observed live on 2026-08-30: models in the fallback chain shipped
    summaries opening with markdown headers, and one shipped a refusal — and
    both sailed through to the page. The summarizer owns this: rejecting them
    here is what lets the fallback chain try again."""

    def test_strips_a_leading_markdown_heading(self):
        complete = responder(**{
            "primary/model": Completion("# Summary\n\nFlock contracts are being cut.", "stop")
        })
        summary = Summarizer(settings(), complete=complete).summarize("text")
        assert summary == "Flock contracts are being cut."

    def test_strips_a_leading_bold_label(self):
        complete = responder(**{
            "primary/model": Completion("**Summary**\nThe chip shipped early.", "stop")
        })
        summary = Summarizer(settings(), complete=complete).summarize("text")
        assert summary == "The chip shipped early."

    def test_a_heading_with_nothing_under_it_falls_back(self):
        complete = responder(**{
            "primary/model": Completion("# Summary", "stop"),
            "backup/model": Completion("A real summary of the story.", "stop"),
        })
        summary = Summarizer(settings(), complete=complete).summarize("text")
        assert summary == "A real summary of the story."

    @pytest.mark.parametrize(
        "refusal",
        [
            "I cannot provide a meaningful summary of this content.",
            "I can't summarize this article.",
            "I'm unable to summarize this text as it appears to be a listing.",
            "I am unable to produce a summary here.",
            "I'm sorry, but this text is not an article.",
        ],
    )
    def test_a_refusal_falls_back_instead_of_shipping(self, refusal):
        complete = responder(**{
            "primary/model": Completion(refusal, "stop"),
            "backup/model": Completion("A real summary of the story.", "stop"),
        })
        summary = Summarizer(settings(), complete=complete).summarize("text")
        assert summary == "A real summary of the story."

    def test_prose_mentioning_inability_is_not_a_refusal(self):
        text = "NASA said it cannot rescue the Swift observatory before its orbit decays."
        complete = responder(**{"primary/model": Completion(text, "stop")})
        assert Summarizer(settings(), complete=complete).summarize("text") == text


class TestAggregatorBodies:
    def test_summarizes_the_original_outlet_before_the_aggregator(self):
        aggregator = make_article(
            title="Big story", url="https://tm/1", source="Techmeme", content="x" * 5000
        )
        aggregator.aggregator = True
        outlet = make_article(
            title="Big story", url="https://ars/1", source="Ars Technica", content="y" * 500
        )
        story = make_story(title="Big story", articles=[aggregator, outlet])
        seen = []

        class Probe:
            def summarize(self, content):
                seen.append(content[:1])
                return "A summary."

        pipeline.summarize_stories([story], Probe())
        assert seen[0] == "y"  # the outlet's body, despite being far shorter
