"""Tests for editorial selection: the Editor and the guards around its verdict."""

import json

import pytest
from conftest import make_article, make_story

from lastweekintech import pipeline
from lastweekintech.config import EditorSettings
from lastweekintech.editor import Editor, EditorVerdict, Pick
from lastweekintech.summarizer import Completion


def canned(payload, finish_reason=None):
    """A complete() that always answers with ``payload`` (dict → JSON)."""
    text = json.dumps(payload) if isinstance(payload, dict) else payload

    def complete(model, messages, max_tokens):
        return Completion(text=text, finish_reason=finish_reason)

    return complete


def make_editor(payload, **settings):
    return Editor(EditorSettings(**settings), complete=canned(payload))


def verdict_for(*ns):
    return {"intro": "A big week.", "picks": [{"n": n, "why": f"why {n}"} for n in ns]}


def pool(count=6):
    return [make_story(title=f"story {i}", score=100 - i) for i in range(count)]


class TestEditorApiUsage:
    """The mapping from an OpenAI-shaped response onto Completion.

    Every other test injects ``complete`` and so never exercises this, but it
    is where the usage numbers actually come from: ``reasoning_tokens`` is
    nested a level down, and providers may omit ``usage`` altogether.
    """

    class FakeCompletions:
        def __init__(self, response):
            self.response = response

        def create(self, **kwargs):
            return self.response

    class FakeClient:
        def __init__(self, response):
            self.chat = type(
                "Chat", (), {"completions": TestEditorApiUsage.FakeCompletions(response)}
            )()

    @staticmethod
    def response(usage):
        message = type("Message", (), {"content": '{"intro": "i", "picks": []}'})()
        choice = type("Choice", (), {"message": message, "finish_reason": "stop"})()
        return type("Response", (), {"choices": [choice], "usage": usage})()

    def editor_with(self, usage):
        editor = Editor(EditorSettings(), complete=lambda m, msg, mt: Completion(text=""))
        editor._client = self.FakeClient(self.response(usage))
        return editor

    def test_maps_completion_and_reasoning_tokens_from_the_response(self):
        details = type("Details", (), {"reasoning_tokens": 6800})()
        usage = type(
            "Usage", (), {"completion_tokens": 7100, "completion_tokens_details": details}
        )()
        completion = self.editor_with(usage)._complete_via_api("m", [], 8000)
        assert completion.completion_tokens == 7100
        assert completion.reasoning_tokens == 6800

    def test_tolerates_a_response_that_reports_no_usage(self):
        completion = self.editor_with(None)._complete_via_api("m", [], 8000)
        assert completion.completion_tokens is None
        assert completion.reasoning_tokens is None

    def test_tolerates_usage_without_reasoning_details(self):
        usage = type("Usage", (), {"completion_tokens": 120, "completion_tokens_details": None})()
        completion = self.editor_with(usage)._complete_via_api("m", [], 8000)
        assert completion.completion_tokens == 120
        assert completion.reasoning_tokens is None


class TestEditorSelect:
    def test_returns_the_picks_and_intro(self):
        editor = make_editor(verdict_for(2, 1, 3))
        verdict = editor.select(pool(), count=3, min_ai=0, max_per_source=2)
        assert verdict is not None
        assert [p.n for p in verdict.picks] == [2, 1, 3]
        assert verdict.picks[0].why == "why 2"
        assert verdict.intro == "A big week."

    def test_records_which_model_answered(self):
        editor = make_editor(verdict_for(1, 2), model_name="test/editor")
        editor.select(pool(), count=2, min_ai=0, max_per_source=0)
        assert editor.last_model == "test/editor"

    def test_records_the_token_usage_of_the_answering_model(self):
        # The budget must cover the model's reasoning as well as its JSON, so
        # the headroom is only knowable if the usage is carried out of the call.
        def complete(model, messages, max_tokens):
            return Completion(
                text=json.dumps(verdict_for(1, 2)),
                completion_tokens=7100,
                reasoning_tokens=6800,
            )

        editor = Editor(EditorSettings(), complete=complete)
        editor.select(pool(), count=2, min_ai=0, max_per_source=0)
        assert editor.last_completion_tokens == 7100
        assert editor.last_reasoning_tokens == 6800

    def test_logs_the_token_spend_against_the_budget(self, caplog):
        # Run metrics are not written on a dry run (main.py), so a log line is
        # the only way the headroom is visible in the cheapest place to look.
        def complete(model, messages, max_tokens):
            return Completion(
                text=json.dumps(verdict_for(1, 2)),
                completion_tokens=7100,
                reasoning_tokens=6800,
            )

        editor = Editor(EditorSettings(max_tokens=8000), complete=complete)
        with caplog.at_level("INFO"):
            editor.select(pool(), count=2, min_ai=0, max_per_source=0)
        spend = [r.message for r in caplog.records if "7100" in r.message]
        assert spend, f"no line reporting the spend in {[r.message for r in caplog.records]}"
        assert "6800" in spend[0] and "8000" in spend[0]

    def test_token_usage_is_none_when_the_model_reports_none(self):
        editor = make_editor(verdict_for(1, 2))
        editor.select(pool(), count=2, min_ai=0, max_per_source=0)
        assert editor.last_completion_tokens is None
        assert editor.last_reasoning_tokens is None

    def test_tolerates_prose_around_the_json(self):
        answer = f"Here is my edition:\n```json\n{json.dumps(verdict_for(1, 2))}\n```"
        editor = make_editor(answer)
        assert editor.select(pool(), count=2, min_ai=0, max_per_source=0) is not None

    def test_truncates_an_overlong_list_to_print_order(self):
        editor = make_editor(verdict_for(1, 2, 3, 4, 5))
        verdict = editor.select(pool(), count=3, min_ai=0, max_per_source=0)
        assert [p.n for p in verdict.picks] == [1, 2, 3]

    @pytest.mark.parametrize(
        "payload",
        [
            "not json at all",
            {"intro": "x", "picks": "not a list"},
            verdict_for(1),  # too few picks
            verdict_for(1, 1, 2),  # duplicate pick
            verdict_for(1, 2, 99),  # out of range
            {"picks": [{"n": "one", "why": "strings are not indices"}, {"n": 2}, {"n": 3}]},
        ],
    )
    def test_an_unusable_verdict_yields_none(self, payload):
        editor = make_editor(payload)
        assert editor.select(pool(), count=3, min_ai=0, max_per_source=0) is None

    def test_falls_back_across_models(self):
        answers = iter([RuntimeError("down"), json.dumps(verdict_for(1, 2))])

        def complete(model, messages, max_tokens):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return Completion(text=answer)

        editor = Editor(
            EditorSettings(model_name="a/primary", fallback_models=["b/backup"]),
            complete=complete,
        )
        assert editor.select(pool(), count=2, min_ai=0, max_per_source=0) is not None
        assert editor.last_model == "b/backup"

    def test_an_empty_pool_yields_none_without_a_model_call(self):
        def complete(model, messages, max_tokens):
            raise AssertionError("should not be called")

        editor = Editor(EditorSettings(), complete=complete)
        assert editor.select([], count=3, min_ai=0, max_per_source=0) is None

    def test_the_prompt_shows_signals_and_marks_missing_bodies(self):
        seen = {}

        def complete(model, messages, max_tokens):
            seen["prompt"] = messages[1]["content"]
            return Completion(text=json.dumps(verdict_for(1, 2)))

        rich = make_story(
            title="Covered everywhere",
            score=5,
            articles=[make_article(title="Covered everywhere", hn_points=400)],
        )
        rich.consensus = True
        bare = make_story(
            title="Paywalled thing",
            score=4,
            articles=[make_article(title="Paywalled thing", content=None)],
        )
        Editor(EditorSettings(), complete=complete).select(
            [rich, bare], count=2, min_ai=0, max_per_source=0
        )
        assert "400 HN points" in seen["prompt"]
        assert "press consensus" in seen["prompt"]
        assert "NO ARTICLE TEXT AVAILABLE" in seen["prompt"]


class TestSelectEdition:
    def test_keeps_the_editors_print_order(self):
        candidates = pool(5)
        verdict = EditorVerdict(picks=[Pick(n=4, why="w4"), Pick(n=1), Pick(n=2)])
        selected = pipeline.select_edition(candidates, verdict, count=3, min_ai=0)
        assert [s.title for s in selected] == ["story 3", "story 0", "story 1"]

    def test_attaches_the_case_for_each_story(self):
        candidates = pool(3)
        verdict = EditorVerdict(picks=[Pick(n=1, why="the case"), Pick(n=2, why="")])
        selected = pipeline.select_edition(candidates, verdict, count=2, min_ai=0)
        assert selected[0].why == "the case"
        assert selected[1].why is None

    def test_the_source_cap_still_binds_the_editor(self):
        candidates = [
            make_story(
                title=f"a{i}",
                score=10 - i,
                articles=[make_article(title=f"a{i}", url=f"https://a/{i}", source="A")],
            )
            for i in range(3)
        ]
        candidates.append(
            make_story(
                title="b0",
                score=1,
                articles=[make_article(title="b0", url="https://b/0", source="B")],
            )
        )
        verdict = EditorVerdict(picks=[Pick(n=1), Pick(n=2), Pick(n=3)])
        selected = pipeline.select_edition(candidates, verdict, count=3, min_ai=0, max_per_source=2)
        assert [s.title for s in selected] == ["a0", "a1", "b0"]

    def test_the_ai_floor_still_binds_the_editor(self):
        candidates = [*pool(3), make_story(title="ai story", category="AI", score=1)]
        verdict = EditorVerdict(picks=[Pick(n=1), Pick(n=2), Pick(n=3)])
        selected = pipeline.select_edition(candidates, verdict, count=3, min_ai=1)
        assert sum(s.category == "AI" for s in selected) == 1

    def test_a_bodyless_pick_yields_to_a_summarizable_story(self):
        bodyless = make_story(
            title="paywalled", score=9, articles=[make_article(title="paywalled", content=None)]
        )
        candidates = [bodyless, *pool(3)]
        verdict = EditorVerdict(picks=[Pick(n=1), Pick(n=2), Pick(n=3)])
        selected = pipeline.select_edition(candidates, verdict, count=3, min_ai=0)
        assert "paywalled" not in {s.title for s in selected}


class TestBuildDigestWithEditor:
    class FakeEditor:
        def __init__(self, verdict):
            self.verdict = verdict
            self.last_model = "fake/editor"
            self.last_completion_tokens = None
            self.last_reasoning_tokens = None
            self.max_tokens = 0

        def select(self, candidates, count, min_ai, max_per_source):
            return self.verdict

    def run(self, config, editor, parse):
        from test_build_digest import FakeSummarizer, small_config

        from lastweekintech.metrics import RunMetrics

        record = RunMetrics()
        digest = pipeline.build_digest(
            small_config(config),
            FakeSummarizer(),
            now=__import__("conftest").NOW,
            parse=parse,
            download=lambda url: f"body for {url}",
            hn_fetch=lambda url, params: {"hits": []},
            editor=editor,
            delay=0,
            metrics=record,
        )
        return digest, record

    def test_the_verdict_shapes_the_edition_and_the_intro(self, config):
        from test_build_digest import feeds_for, unique_entries

        parse = feeds_for({"ars": unique_entries(5), "wired": []})
        editor = self.FakeEditor(
            EditorVerdict(picks=[Pick(n=3, why="w"), Pick(n=1), Pick(n=2)], intro="Some week.")
        )
        digest, record = self.run(config, editor, parse)
        assert digest.intro == "Some week."
        assert len(digest.stories) == 3
        assert record.editor_used and record.editor_model == "fake/editor"

    def test_records_the_editor_token_budget_and_usage(self, config):
        # Without the budget alongside the usage, a number like 7100 says
        # nothing about how close the run came to being truncated.
        from test_build_digest import feeds_for, unique_entries

        parse = feeds_for({"ars": unique_entries(5), "wired": []})
        editor = self.FakeEditor(EditorVerdict(picks=[Pick(n=1), Pick(n=2), Pick(n=3)]))
        editor.last_completion_tokens = 7100
        editor.last_reasoning_tokens = 6800
        editor.max_tokens = 8000
        _, record = self.run(config, editor, parse)
        assert record.editor_completion_tokens == 7100
        assert record.editor_reasoning_tokens == 6800
        assert record.editor_max_tokens == 8000

    def test_a_failed_editor_falls_back_to_the_ranking(self, config):
        from test_build_digest import feeds_for, unique_entries

        parse = feeds_for({"ars": unique_entries(5), "wired": []})
        digest, record = self.run(config, self.FakeEditor(None), parse)
        assert digest.intro is None
        assert len(digest.stories) == 3
        assert not record.editor_used
