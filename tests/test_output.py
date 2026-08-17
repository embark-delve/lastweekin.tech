"""Tests for edition building, archiving and the publish gate."""

import json

import pytest
from conftest import NOW, make_article, make_story

from lastweekintech import pipeline
from lastweekintech.validation import DigestValidationError, assert_publishable, validate_digest


def digest(count=7, missing=0, category="AI"):
    stories = []
    for i in range(count):
        story = make_story(
            title=f"Story {i}",
            category=category if i < 4 else "General Tech",
            score=100 - i,
            articles=[make_article(url=f"https://example.com/{i}")],
        )
        story.summary = None if i < missing else "A perfectly serviceable summary of the news."
        stories.append(story)
    return stories


class TestValidateDigest:
    def test_accepts_a_complete_digest(self, config):
        assert validate_digest(digest(), config) == []

    def test_rejects_a_short_digest(self, config):
        assert validate_digest(digest(count=5), config)

    def test_rejects_too_many_missing_summaries(self, config):
        config.digest.max_missing_summaries = 1
        assert validate_digest(digest(missing=2), config)

    def test_tolerates_the_configured_number_of_missing_summaries(self, config):
        config.digest.max_missing_summaries = 1
        assert validate_digest(digest(missing=1), config) == []

    def test_counts_a_stub_summary_as_missing(self, config):
        config.digest.max_missing_summaries = 0
        stories = digest()
        stories[0].summary = "Summary not available."
        assert validate_digest(stories, config)

    def test_counts_a_one_line_fragment_as_missing(self, config):
        config.digest.max_missing_summaries = 0
        stories = digest()
        stories[0].summary = "Bethesda marked Quake's 30"
        assert validate_digest(stories, config)

    def test_rejects_duplicate_stories(self, config):
        stories = digest()
        stories[1].articles = list(stories[0].articles)
        assert validate_digest(stories, config)

    def test_rejects_a_story_without_a_link(self, config):
        stories = digest()
        stories[0].articles = []
        assert validate_digest(stories, config)

    def test_assert_publishable_raises_with_every_problem_listed(self, config):
        with pytest.raises(DigestValidationError) as excinfo:
            assert_publishable(digest(count=3, missing=3), config)
        assert "3" in str(excinfo.value)

    def test_assert_publishable_is_quiet_for_a_good_digest(self, config):
        assert assert_publishable(digest(), config) is None


class TestQualityGate:
    """A summary that is present but bad must not reach readers either.

    The hard checks above only ask whether a summary exists. 44 weeks of archive
    show the other failure mode: text that is present, non-stub, long enough,
    and cut off mid-word.
    """

    def truncated(self, config, count=7):
        stories = digest(count=count)
        for story in stories:
            story.summary = (
                "Bethesda marked the anniversary with a mission pack that adds new maps and"
            )
        return stories

    def test_rejects_a_digest_of_truncated_summaries(self, config):
        assert validate_digest(self.truncated(config), config)

    def test_names_the_failing_check(self, config):
        problems = " ".join(validate_digest(self.truncated(config), config))
        assert "truncation" in problems

    def test_accepts_well_formed_summaries(self, config):
        assert validate_digest(digest(), config) == []

    def test_tolerance_is_configurable(self, config):
        stories = self.truncated(config)
        config.digest.max_low_quality_summaries = len(stories)
        assert validate_digest(stories, config) == []

    def test_naming_an_entity_absent_from_the_source_does_not_block_publication(self, config):
        """A live run rejected an edition for naming Mozilla, Alibaba and Zhipu AI.

        All three were correct; none appeared in the fetched page, because
        extraction often returns a partial body (an ad block, a model card).
        The check cannot tell true outside context from invention, so it advises
        rather than blocks. Invented *figures* are still blocking.
        """
        stories = digest()
        for story in stories:
            story.articles[0].content = "The browser will keep supporting the extension."
            story.summary = (
                "Mozilla confirmed Firefox will keep supporting uBlock Origin. "
                "Chromium browsers have completed their migration away from it."
            )
        assert validate_digest(stories, config) == []

    def test_a_single_weak_summary_does_not_block_an_otherwise_good_edition(self, config):
        stories = digest()
        stories[0].summary = "Bethesda marked the anniversary with a mission pack that adds new"
        assert validate_digest(stories, config) == []


class TestBuildEdition:
    def test_ranks_stories_in_order(self):
        edition = pipeline.build_edition(digest(), week="2026-08-10", now=NOW)
        assert [s["rank"] for s in edition["stories"]] == list(range(1, 8))

    def test_records_the_week_and_generation_time(self):
        edition = pipeline.build_edition(digest(), week="2026-08-10", now=NOW)
        assert edition["week"] == "2026-08-10"
        assert edition["generated_at"].startswith("2026-08-10")

    def test_lists_every_outlet_that_covered_the_story(self):
        story = make_story(
            articles=[
                make_article(source="WIRED", url="https://w.example/1"),
                make_article(source="Ars Technica", url="https://a.example/1"),
            ]
        )
        [entry] = pipeline.build_edition([story], week="2026-08-10", now=NOW)["stories"]
        assert sorted(entry["sources"]) == ["Ars Technica", "WIRED"]
        assert entry["source_count"] == 2

    def test_links_to_the_article_with_the_most_traction(self):
        story = make_story(
            articles=[
                make_article(source="Blog", url="https://blog.example/1", hn_points=None),
                make_article(source="WIRED", url="https://wired.example/1", hn_points=400),
            ]
        )
        [entry] = pipeline.build_edition([story], week="2026-08-10", now=NOW)["stories"]
        assert entry["url"] == "https://wired.example/1"
        assert entry["hn_points"] == 400

    def test_renders_a_missing_summary_as_an_explicit_placeholder(self):
        [story] = digest(count=1, missing=1)
        [entry] = pipeline.build_edition([story], week="2026-08-10", now=NOW)["stories"]
        assert entry["summary"] == ""


class TestSaveEdition:
    def test_writes_latest_and_an_archive_copy(self, tmp_path):
        edition = pipeline.build_edition(digest(), week="2026-08-10", now=NOW)
        latest, archived = pipeline.save_edition(edition, tmp_path)
        assert latest == tmp_path / "latest.json"
        assert archived == tmp_path / "archive" / "2026-08-10.json"
        assert json.loads(archived.read_text())["week"] == "2026-08-10"

    def test_latest_and_archive_hold_the_same_edition(self, tmp_path):
        edition = pipeline.build_edition(digest(), week="2026-08-10", now=NOW)
        latest, archived = pipeline.save_edition(edition, tmp_path)
        assert json.loads(latest.read_text()) == json.loads(archived.read_text())


class TestListEditions:
    def test_lists_archived_editions_newest_first(self, tmp_path):
        for week in ("2026-07-27", "2026-08-10", "2026-08-03"):
            pipeline.save_edition(
                pipeline.build_edition(digest(), week=week, now=NOW),
                tmp_path,
            )
        assert [e["week"] for e in pipeline.list_editions(tmp_path)] == [
            "2026-08-10",
            "2026-08-03",
            "2026-07-27",
        ]

    def test_returns_nothing_when_no_archive_exists(self, tmp_path):
        assert pipeline.list_editions(tmp_path) == []

    def test_ignores_files_that_are_not_editions(self, tmp_path):
        archive = tmp_path / "archive"
        archive.mkdir(parents=True)
        (archive / "notes.txt").write_text("ignore me")
        (archive / "broken.json").write_text("{not json")
        assert pipeline.list_editions(tmp_path) == []
