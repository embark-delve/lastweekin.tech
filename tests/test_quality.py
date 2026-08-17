"""Tests for the deterministic summary-quality checks and the golden eval set."""

from pathlib import Path

import pytest
import yaml
from conftest import make_article, make_story

from lastweekintech.quality import (
    CHECK_NAMES,
    LENGTH,
    NUMBER_GROUNDING,
    SUBSTANCE,
    TRUNCATION,
    JudgeError,
    assess_story,
    assess_summary,
    build_judge_messages,
    check_contract,
    check_entity_grounding,
    check_length,
    check_number_grounding,
    check_subject_coverage,
    check_substance,
    check_truncation,
    distinctive_entities,
    judge_available,
    judge_summary,
    parse_judge_response,
    split_sentences,
    trailing_fragment,
)
from lastweekintech.summarizer import Completion

# A stand-in for a downloaded article body: several paragraphs of plain prose,
# with the figures and names a summary is expected to reuse.
ARTICLE = """
Cloudflare's chief financial officer, Thomas Seifert, told investors on Thursday
that machine-generated traffic will outpace human traffic by up to a thousand-fold
within five years, driven largely by AI agents crawling the web on behalf of the
people who deploy them.

The company reported $696.5 million in revenue for the second quarter, up 36% year
over year, alongside a net loss of $205 million. Both figures beat the consensus
estimate that analysts had published ahead of the call.

Seifert said the shift forces a rethink of how a site tells a browser from a bot.
Cloudflare has spent the past year pushing pay-per-crawl controls that let
publishers charge AI companies for access to their pages.
"""

TITLE = "'Humans will be a rounding error on the internet' says Cloudflare exec"

GOOD_SUMMARY = (
    "Cloudflare's finance chief Thomas Seifert told investors that machine-generated "
    "traffic could outpace human traffic by up to a thousand-fold within five years. "
    "The company reported $696.5 million in quarterly revenue, up 36% year over year, "
    "alongside a net loss of $205 million."
)


class TestSplitSentences:
    def test_returns_each_complete_sentence(self):
        assert split_sentences("One thing happened. Then another did.") == [
            "One thing happened.",
            "Then another did.",
        ]

    def test_does_not_split_on_decimal_points(self):
        assert len(split_sentences("Revenue hit $696.5 million. Losses grew too.")) == 2

    def test_does_not_split_on_initials(self):
        assert len(split_sentences("A U.S. court sentenced him. He appealed.")) == 2

    def test_does_not_split_on_common_abbreviations(self):
        assert len(split_sentences("Acme Inc. filed suit. The case failed.")) == 2

    def test_drops_a_trailing_partial_sentence(self):
        assert split_sentences("Complete thought. Then it was cut") == ["Complete thought."]

    def test_returns_nothing_for_a_fragment_with_no_boundary(self):
        assert split_sentences("Bethesda marked Quake's 30") == []

    def test_handles_question_and_exclamation_endings(self):
        assert len(split_sentences("Was it? It was! Truly.")) == 3

    def test_handles_empty_text(self):
        assert split_sentences("") == []
        assert split_sentences(None) == []


class TestTrailingFragment:
    def test_returns_the_text_after_the_last_sentence_end(self):
        assert trailing_fragment("Complete thought. Then it was cut") == "Then it was cut"

    def test_is_empty_for_a_finished_summary(self):
        assert trailing_fragment("All done here.") == ""

    def test_returns_the_whole_text_when_no_sentence_ends(self):
        assert trailing_fragment("Bethesda marked Quake's 30") == "Bethesda marked Quake's 30"


class TestCheckTruncation:
    def test_passes_a_summary_that_ends_on_a_sentence(self):
        result = check_truncation(GOOD_SUMMARY)
        assert result.passed
        assert result.reason == ""

    def test_flags_a_summary_cut_off_mid_word(self):
        result = check_truncation("Bethesda marked Quake's 30")
        assert not result.passed
        assert "Bethesda marked Quake's 30" in result.reason

    def test_flags_a_summary_that_ends_on_a_comma(self):
        result = check_truncation(
            "Cloudflare beat expectations. Revenue rose while losses widened,"
        )
        assert not result.passed

    def test_flags_a_trailing_ellipsis(self):
        assert not check_truncation("Cloudflare beat expectations. Revenue rose...").passed

    def test_tolerates_a_closing_quote_after_the_terminator(self):
        assert check_truncation('Seifert called humans "a rounding error." He meant it.').passed

    def test_names_the_check(self):
        assert check_truncation(GOOD_SUMMARY).name == TRUNCATION


class TestCheckLength:
    def test_passes_two_sentences(self):
        assert check_length(GOOD_SUMMARY).passed

    def test_passes_three_sentences(self):
        assert check_length("One happened. Two happened. Three happened.").passed

    def test_passes_four_sentences(self):
        assert check_length("One did. Two did. Three did. Four did.").passed

    def test_flags_a_single_sentence_stub(self):
        result = check_length("Cloudflare reported revenue of $696.5 million this quarter.")
        assert not result.passed
        assert "1" in result.reason

    def test_flags_a_five_sentence_essay(self):
        result = check_length("A did. B did. C did. D did. E did.")
        assert not result.passed
        assert "5" in result.reason

    def test_counts_only_complete_sentences(self):
        """A trailing fragment is truncation, not a sentence, so it must not count."""
        result = check_length("A did. B was cut off mid")
        assert not result.passed
        assert "1" in result.reason


class TestDistinctiveEntities:
    def test_finds_capitalised_names(self):
        assert "Cloudflare" in distinctive_entities(TITLE)

    def test_ignores_common_words_even_when_capitalised(self):
        found = distinctive_entities("New AI Model Says The Internet Is Now Mostly Bots")
        assert "New" not in found
        assert "The" not in found
        assert "Says" not in found

    def test_keeps_product_names_with_digits(self):
        assert "GPT-5" in distinctive_entities("GPT-5 lands with a longer context window")

    def test_keeps_internally_capitalised_names(self):
        assert "iPhone" in distinctive_entities("The new iPhone ships in October")

    def test_strips_possessives(self):
        assert "Cloudflare" in distinctive_entities("Cloudflare's quarter beat estimates")

    def test_ignores_ordinals_and_bare_numbers(self):
        found = distinctive_entities("Quake marks its 30th anniversary with 4 new maps")
        assert found == ["Quake"]

    def test_ignores_month_and_weekday_names(self):
        assert distinctive_entities("It ships on Monday in October") == []

    def test_handles_empty_text(self):
        assert distinctive_entities("") == []
        assert distinctive_entities(None) == []


class TestCheckSubjectCoverage:
    def test_passes_when_the_summary_names_the_subject(self):
        assert check_subject_coverage(TITLE, GOOD_SUMMARY).passed

    def test_flags_a_summary_that_never_names_the_company(self):
        result = check_subject_coverage(
            TITLE,
            "The finance chief told investors that automated traffic will soon dwarf the "
            "organic kind. Revenue and losses both grew over the quarter.",
        )
        assert not result.passed
        assert "Cloudflare" in result.reason

    def test_tolerates_possessives_in_the_summary(self):
        assert check_subject_coverage("Cloudflare beats estimates", "Cloudflare's quarter.").passed

    def test_is_case_insensitive(self):
        assert check_subject_coverage("Cloudflare beats estimates", "CLOUDFLARE grew.").passed

    def test_is_skipped_when_the_title_has_no_distinctive_entity(self):
        result = check_subject_coverage("The best new laptops of the year", "Some laptops.")
        assert result.skipped
        assert result.passed


class TestCheckNumberGrounding:
    def test_passes_when_every_figure_appears_in_the_source(self):
        assert check_number_grounding(ARTICLE, GOOD_SUMMARY).passed

    def test_flags_a_hallucinated_figure(self):
        result = check_number_grounding(
            ARTICLE,
            "Cloudflare reported $896.4 million in revenue for the quarter. "
            "Losses reached $205 million.",
        )
        assert not result.passed
        assert "896.4" in result.reason

    def test_tolerates_currency_percent_and_thousands_separators(self):
        source = "The fine was $1,200,000 and the share fell 36%."
        assert check_number_grounding(source, "It paid 1200000 dollars. Shares fell 36 %.").passed

    def test_tolerates_narrow_and_non_breaking_spaces(self):
        """The archived editions are full of U+202F between a figure and its unit."""
        source = "Revenue was $696.5\u202fmillion, up 36% year over year, on a wide base."
        summary = "Revenue was $696.5\u00a0million. It rose 36\u202f% over the year."
        assert check_number_grounding(source, summary).passed

    def test_tolerates_a_rounded_figure(self):
        assert check_number_grounding(ARTICLE, "Revenue was $696 million. It grew.").passed

    def test_does_not_round_years(self):
        source = "The scheme ran from 2021 until police shut it down."
        result = check_number_grounding(source, "The scheme ran from 2022. Police shut it down.")
        assert not result.passed
        assert "2022" in result.reason

    def test_matches_a_figure_the_source_spells_out(self):
        source = "He was sentenced to sixteen years in federal prison for the scheme."
        assert check_number_grounding(source, "He got 16 years. The scheme is over.").passed

    def test_passes_a_summary_with_no_figures(self):
        assert check_number_grounding(
            ARTICLE, "Cloudflare warned investors. It expects more."
        ).passed

    def test_is_skipped_without_a_source(self):
        result = check_number_grounding("", "Revenue was $999 million. It grew.")
        assert result.skipped
        assert result.passed


class TestCheckEntityGrounding:
    def test_passes_when_names_come_from_the_source(self):
        assert check_entity_grounding(ARTICLE, GOOD_SUMMARY).passed

    def test_flags_an_invented_name(self):
        result = check_entity_grounding(
            ARTICLE,
            "Cloudflare's Thomas Seifert warned investors about bot traffic. "
            "Akamai disputed the figures.",
        )
        assert not result.passed
        assert "Akamai" in result.reason

    def test_tolerates_possessives_and_plurals(self):
        source = "Cloudflare said the publisher controls are live."
        assert check_entity_grounding(
            source, "Cloudflare's controls shipped. Publishers agreed."
        ).passed

    def test_ignores_common_words_at_the_start_of_a_sentence(self):
        source = "Cloudflare said the controls are live."
        summary = "Cloudflare shipped the controls. However, adoption is slow. Meanwhile it grows."
        assert check_entity_grounding(source, summary).passed

    def test_is_skipped_without_a_source(self):
        result = check_entity_grounding("", "Akamai disputed the figures. Nobody agreed.")
        assert result.skipped
        assert result.passed


class TestCheckContract:
    def test_passes_plain_reported_prose(self):
        assert check_contract(GOOD_SUMMARY).passed

    def test_flags_first_person(self):
        result = check_contract("I think Cloudflare is right. We should all worry about bots.")
        assert not result.passed
        assert "first person" in result.reason.lower()

    def test_allows_first_person_inside_a_quotation(self):
        assert check_contract(
            'Seifert said "we expect machine traffic to win." Cloudflare beat estimates.'
        ).passed

    def test_flags_meta_phrasing_about_the_article(self):
        result = check_contract(
            "This article discusses Cloudflare's quarter. It also covers bot traffic."
        )
        assert not result.passed
        assert "this article" in result.reason.lower()

    def test_flags_a_summary_preamble(self):
        assert not check_contract("In summary, Cloudflare grew. Losses grew too.").passed

    def test_flags_assistant_voice(self):
        assert not check_contract(
            "As an AI language model, here is the gist. Cloudflare grew."
        ).passed


class TestCheckSubstance:
    def test_passes_a_real_summary(self):
        assert check_substance(GOOD_SUMMARY).passed

    def test_flags_the_literal_stub(self):
        result = check_substance("Summary not available.")
        assert not result.passed
        assert "placeholder" in result.reason.lower()

    def test_flags_an_empty_summary(self):
        assert not check_substance("").passed
        assert not check_substance("   ").passed
        assert not check_substance(None).passed

    def test_flags_a_summary_too_short_to_be_useful(self):
        assert not check_substance("Cloudflare grew.").passed


class TestAssessSummary:
    def test_runs_every_check(self):
        report = assess_summary(TITLE, ARTICLE, GOOD_SUMMARY)
        assert tuple(check.name for check in report.checks) == CHECK_NAMES

    def test_a_good_summary_scores_full_marks(self):
        report = assess_summary(TITLE, ARTICLE, GOOD_SUMMARY)
        assert report.passed
        assert report.score == 1.0
        assert report.failed_checks == ()

    def test_the_production_truncation_failure_is_caught(self):
        """The literal summary shipped for the Quake story on 2026-08-10."""
        report = assess_summary(
            "New official 30th anniversary Quake mission pack adds new maps",
            "Bethesda marked Quake's 30th anniversary with a new mission pack.",
            "Bethesda marked Quake's 30",
        )
        assert not report.passed
        assert TRUNCATION in report.failed_checks
        assert LENGTH in report.failed_checks
        assert any("cut off" in reason for reason in report.reasons)

    def test_the_literal_stub_fails_on_substance(self):
        report = assess_summary(TITLE, ARTICLE, "Summary not available.")
        assert SUBSTANCE in report.failed_checks
        assert report.score == 0.0

    def test_a_failed_substance_check_zeroes_the_score(self):
        """A placeholder banks vacuous passes on grounding and voice; it must
        not be allowed to score above a summary that merely runs long."""
        stub = assess_summary(TITLE, ARTICLE, "N/A")
        long_but_real = assess_summary(TITLE, ARTICLE, GOOD_SUMMARY + " And more. And more. Yes.")
        assert stub.score == 0.0
        assert long_but_real.score > stub.score

    def test_an_empty_summary_scores_zero_on_everything_measurable(self):
        report = assess_summary(TITLE, ARTICLE, "")
        assert report.score == 0.0

    def test_skipped_checks_stay_out_of_the_score(self):
        """Without a source there is nothing to ground against, so it must not count."""
        report = assess_summary(TITLE, "", GOOD_SUMMARY)
        assert report.check(NUMBER_GROUNDING).skipped
        assert report.score == 1.0

    def test_looks_up_a_check_by_name(self):
        report = assess_summary(TITLE, ARTICLE, GOOD_SUMMARY)
        assert report.check(TRUNCATION).name == TRUNCATION
        with pytest.raises(KeyError):
            report.check("no_such_check")


class TestAssessStory:
    def test_scores_against_the_richest_article_body(self):
        story = make_story(
            title="Cloudflare warns about bot traffic",
            articles=[
                make_article(url="https://a.example/1", content="A paywall stub."),
                make_article(url="https://b.example/2", content=ARTICLE),
            ],
        )
        story.summary = "Cloudflare reported $696.5 million in revenue. Losses hit $205 million."
        assert assess_story(story).check(NUMBER_GROUNDING).passed

    def test_handles_a_story_with_no_bodies(self):
        story = make_story(title="Cloudflare warns about bot traffic")
        story.summary = None
        assert not assess_story(story).passed


class TestParseJudgeResponse:
    def test_parses_a_plain_verdict(self):
        verdict = parse_judge_response('{"faithful": true, "reason": "all supported"}')
        assert verdict.faithful
        assert verdict.reason == "all supported"

    def test_parses_a_fenced_verdict(self):
        reply = '```json\n{"faithful": false, "unsupported": ["the $896 million figure"]}\n```'
        verdict = parse_judge_response(reply)
        assert not verdict.faithful
        assert verdict.unsupported == ("the $896 million figure",)

    def test_keeps_the_raw_reply_for_inspection(self):
        assert parse_judge_response('{"faithful": true}').raw == '{"faithful": true}'

    def test_rejects_a_reply_with_no_json(self):
        with pytest.raises(JudgeError):
            parse_judge_response("Looks fine to me.")

    def test_rejects_a_reply_with_no_verdict(self):
        with pytest.raises(JudgeError):
            parse_judge_response('{"reason": "I forgot the verdict"}')


class TestJudgeSummary:
    def test_uses_the_injected_completion_function(self):
        calls = []

        def complete(model, messages, max_tokens):
            calls.append((model, messages, max_tokens))
            return Completion('{"faithful": true, "reason": "supported"}', "stop")

        verdict = judge_summary(TITLE, ARTICLE, GOOD_SUMMARY, complete=complete)
        assert verdict.faithful
        assert len(calls) == 1

    def test_sends_the_headline_source_and_summary(self):
        messages = build_judge_messages(TITLE, ARTICLE, GOOD_SUMMARY)
        prompt = messages[-1]["content"]
        assert TITLE in prompt
        assert "Thomas Seifert" in prompt
        assert GOOD_SUMMARY in prompt

    def test_truncates_an_over_long_source(self):
        messages = build_judge_messages(TITLE, "x" * 50000, GOOD_SUMMARY)
        assert len(messages[-1]["content"]) < 20000

    def test_refuses_to_run_live_without_a_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(JudgeError, match="OPENROUTER_API_KEY"):
            judge_summary(TITLE, ARTICLE, GOOD_SUMMARY)

    def test_is_available_only_when_a_key_is_present(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert not judge_available()
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        assert judge_available()


# --------------------------------------------------------------------------- #
# The golden set
# --------------------------------------------------------------------------- #

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "evals" / "golden.yaml"


def load_golden_set():
    """Return the eval fixtures as (id, title, source, summary, expected failures)."""
    data = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    sources = data["sources"]
    return [
        (
            fixture["id"],
            fixture["title"],
            sources[fixture["source"]],
            fixture.get("summary") or "",
            frozenset(fixture["expect_failures"]),
        )
        for fixture in data["fixtures"]
    ]


GOLDEN_SET = load_golden_set()
CLEAN = [case for case in GOLDEN_SET if not case[4]]
FLAWED = [case for case in GOLDEN_SET if case[4]]


class TestGoldenSet:
    def test_is_large_enough_to_mean_something(self):
        assert len(GOLDEN_SET) >= 20

    def test_holds_both_clean_and_flawed_fixtures(self):
        """Fixtures expected to pass are the false-positive guard; without them
        a check that fires on everything would look perfect."""
        assert len(CLEAN) >= 8
        assert len(FLAWED) >= 8

    def test_every_check_is_exercised_by_some_fixture(self):
        exercised = {name for case in GOLDEN_SET for name in case[4]}
        assert exercised == set(CHECK_NAMES)

    def test_fixture_ids_are_unique(self):
        ids = [case[0] for case in GOLDEN_SET]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize(
        ("title", "source", "summary", "expected"),
        [case[1:] for case in GOLDEN_SET],
        ids=[case[0] for case in GOLDEN_SET],
    )
    def test_verdict_matches_the_fixture(self, title, source, summary, expected):
        report = assess_summary(title, source, summary)
        assert set(report.failed_checks) == set(expected), "; ".join(report.reasons)

    def test_clean_fixtures_score_full_marks(self):
        for case_id, title, source, summary, _ in CLEAN:
            assert assess_summary(title, source, summary).score == 1.0, case_id

    def test_flawed_fixtures_score_below_full_marks(self):
        for case_id, title, source, summary, _ in FLAWED:
            assert assess_summary(title, source, summary).score < 1.0, case_id

    def test_the_oracle_agrees_on_the_whole_set(self):
        """The aggregate the runner prints: agreement must be total."""
        agreed = sum(
            set(assess_summary(title, source, summary).failed_checks) == set(expected)
            for _, title, source, summary, expected in GOLDEN_SET
        )
        assert agreed == len(GOLDEN_SET)
