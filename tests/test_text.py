"""Tests for the pure text helpers."""

import pytest

from lastweekintech.text import (
    CATEGORIES,
    CATEGORY_PRECEDENCE,
    GENERAL_CATEGORY,
    classify_text,
    contains_ai_terms,
    count_ai_terms,
    count_category_terms,
    normalize_url,
    trim_to_sentence,
)


class TestNormalizeUrl:
    def test_strips_tracking_parameters(self):
        assert (
            normalize_url("https://example.com/story?utm_source=rss&utm_medium=feed")
            == "https://example.com/story"
        )

    def test_keeps_meaningful_query_parameters(self):
        assert normalize_url("https://example.com/p?id=42") == "https://example.com/p?id=42"

    def test_lowercases_scheme_and_host_only(self):
        assert normalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"

    def test_strips_fragment_and_trailing_slash(self):
        assert normalize_url("https://example.com/story/#comments") == "https://example.com/story"

    def test_treats_www_as_the_same_host(self):
        assert normalize_url("https://www.example.com/a") == normalize_url("https://example.com/a")

    def test_leaves_bare_root_url_usable(self):
        assert normalize_url("https://example.com/") == "https://example.com"


class TestContainsAiTerms:
    def test_matches_standalone_ai(self):
        assert contains_ai_terms("OpenAI ships a new AI model")

    def test_does_not_match_ai_inside_another_word(self):
        assert not contains_ai_terms("London still dominates Britain's datacenter map")

    def test_does_not_match_train_or_aids_or_email(self):
        assert not contains_ai_terms("Smart glasses are only smart if we train them to be good")
        assert not contains_ai_terms("Yeasound RIC800 Hearing Aids Review: Good Audio")
        assert not contains_ai_terms("Microsoft accidentally kills epic Outlook email threads")

    def test_matches_multiword_phrases(self):
        assert contains_ai_terms("A new large language model tops the charts")

    def test_matches_vendor_and_product_names(self):
        assert contains_ai_terms("Anthropic releases Claude update")
        assert contains_ai_terms("Google DeepMind publishes results")

    def test_is_case_insensitive(self):
        assert contains_ai_terms("MACHINE LEARNING breakthrough")

    def test_matches_punctuated_ai(self):
        assert contains_ai_terms("The A.I. boom continues")

    def test_matches_model_family_names(self):
        """Model releases are the most common AI story and rarely say "AI"."""
        for title in (
            "Qwen 3.8 27B",
            "GLM-5.3: frontier coding",
            "Llama 4 released",
            "Mixtral 8x7B",
        ):
            assert contains_ai_terms(title), title

    def test_does_not_match_a_model_name_inside_another_word(self):
        assert not contains_ai_terms("The glmnet package for R gets an update")


class TestAnthropicModelNames:
    """A live run filed "Why does Opus 5 feel worse to work with?" as General Tech."""

    def test_matches_anthropic_model_names_with_a_version(self):
        for title in (
            "Why does Opus 5 feel worse to work with?",
            "Sonnet 4.5 tops the coding leaderboard",
            "Haiku-4.5 is cheap enough to run on every request",
        ):
            assert classify_text(title) == "AI", title

    def test_does_not_match_the_bare_words_opus_sonnet_or_haiku(self):
        """Opus is an audio codec, Sonnet makes Thunderbolt docks, a haiku is a poem."""
        for title in (
            "The Opus audio codec gets a bitrate overhaul",
            "Sonnet ships a new Thunderbolt dock",
            "A haiku generator written in 40 lines",
        ):
            assert classify_text(title) != "AI", title


class TestClassifyText:
    def test_every_category_is_one_of_the_agreed_strings(self):
        assert CATEGORIES == (
            "AI",
            "Security",
            "Policy",
            "Hardware",
            "Open Source",
            "Business",
            "General Tech",
        )

    def test_precedence_is_explicit_and_excludes_the_residual(self):
        assert CATEGORY_PRECEDENCE == (
            "AI",
            "Security",
            "Policy",
            "Open Source",
            "Hardware",
            "Business",
        )
        assert GENERAL_CATEGORY not in CATEGORY_PRECEDENCE

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("OpenAI ships a new reasoning model", "AI"),
            ("Ransomware crew leaks 1.6M customer records", "Security"),
            ("EU regulators open an antitrust probe into app stores", "Policy"),
            ("Debian votes to replace systemd in the next release", "Open Source"),
            ("TSMC starts risk production on its 2nm node", "Hardware"),
            ("Adobe's CEO steps down after a quarter of falling revenue", "Business"),
            ("Whale migrations are being disrupted by climate change", "General Tech"),
        ],
    )
    def test_classifies_each_category(self, title, expected):
        assert classify_text(title) == expected

    def test_ai_wins_over_security_for_an_ai_security_story(self):
        """Precedence must be deterministic, and AI is what the digest floor counts."""
        assert classify_text("Researchers exploit a zero-day in Claude's agent sandbox") == "AI"

    def test_security_wins_over_policy(self):
        assert (
            classify_text("Senate probes the ransomware breach at a federal agency") == "Security"
        )

    def test_policy_wins_over_hardware(self):
        assert (
            classify_text("EU antitrust regulators fine a chipmaker over GPU bundling") == "Policy"
        )

    def test_open_source_wins_over_hardware(self):
        assert (
            classify_text("The Linux kernel drops support for an old CPU family") == "Open Source"
        )

    def test_hardware_wins_over_business(self):
        assert classify_text("Nvidia's revenue climbs as GPU demand holds") == "Hardware"

    def test_falls_back_to_the_residual_category(self):
        assert classify_text("A quiet afternoon in the park") == GENERAL_CATEGORY
        assert classify_text("") == GENERAL_CATEGORY
        assert classify_text(None) == GENERAL_CATEGORY

    def test_category_matching_stays_word_bounded(self):
        """The substring bug that labelled "Britain", "train" and "email" as AI."""
        for title in (
            "London still dominates Britain's datacenter map",
            "Smart glasses are only smart if we train them to be good",
            "Yeasound RIC800 Hearing Aids Review: Good Audio",
        ):
            assert classify_text(title) != "AI", title


class TestCountCategoryTerms:
    def test_counts_mentions_for_a_named_category(self):
        assert count_category_terms("The malware dropped ransomware on the host", "Security") == 2

    def test_is_zero_for_an_unrelated_category(self):
        assert count_category_terms("The malware dropped ransomware", "Business") == 0

    def test_handles_empty_text(self):
        assert count_category_terms("", "AI") == 0
        assert count_category_terms(None, "AI") == 0

    def test_rejects_an_unknown_category(self):
        with pytest.raises(KeyError):
            count_category_terms("anything", "Sports")


class TestCountAiTerms:
    def test_counts_each_occurrence(self):
        assert count_ai_terms("AI is AI and machine learning too") == 3

    def test_returns_zero_for_unrelated_text(self):
        assert count_ai_terms("A story about trains in Britain") == 0

    def test_handles_empty_text(self):
        assert count_ai_terms("") == 0
        assert count_ai_terms(None) == 0


class TestTrimToSentence:
    def test_drops_trailing_partial_sentence(self):
        assert trim_to_sentence("First sentence. Second one was cut off mid") == "First sentence."

    def test_leaves_complete_text_untouched(self):
        assert trim_to_sentence("All done here.") == "All done here."

    def test_handles_question_and_exclamation_endings(self):
        assert trim_to_sentence("Really? Yes! And then some") == "Really? Yes!"

    def test_returns_original_when_no_sentence_boundary_exists(self):
        assert trim_to_sentence("no boundary at all") == "no boundary at all"

    def test_does_not_split_on_decimal_points(self):
        assert trim_to_sentence("Revenue hit $696.5 million this quarter.") == (
            "Revenue hit $696.5 million this quarter."
        )

    def test_ignores_closing_quote_after_terminator(self):
        assert trim_to_sentence('He said "it works." Then he left the') == 'He said "it works."'
