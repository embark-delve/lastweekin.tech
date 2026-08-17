"""Tests for static site generation."""

from pathlib import Path

from conftest import NOW, make_article, make_story
from jinja2 import Environment, FileSystemLoader

from lastweekintech import pipeline

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "src" / "lastweekintech" / "templates"
STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "lastweekintech" / "static"


def edition(
    week="2026-08-10",
    title="Anthropic ships something",
    summary="A real summary here.",
    category="AI",
    articles=None,
):
    story = make_story(
        title=title,
        category=category,
        articles=articles or [make_article(source="WIRED")],
    )
    story.summary = summary
    return pipeline.build_edition([story], week=week, now=NOW)


def generate(tmp_path, editions):
    return pipeline.generate_site(
        editions,
        output_dir=tmp_path,
        template_dir=TEMPLATE_DIR,
        static_dir=STATIC_DIR,
    )


def render(**context):
    """Render the template directly, to exercise variables the pipeline does not pass yet."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    defaults = {
        "edition": edition(),
        "past_editions": [],
        "root": "",
        "is_latest": True,
        "page_title": "LastWeekIn.Tech",
        "description": "The week in tech.",
    }
    return env.get_template("edition.html.jinja").render({**defaults, **context})


class TestGenerateSite:
    def test_writes_the_latest_edition_to_the_index(self, tmp_path):
        generate(tmp_path, [edition()])
        assert "Anthropic ships something" in (tmp_path / "index.html").read_text()

    def test_writes_a_page_per_archived_edition(self, tmp_path):
        generate(tmp_path, [edition(week="2026-08-10"), edition(week="2026-08-03")])
        assert (tmp_path / "archive" / "2026-08-03.html").exists()
        assert (tmp_path / "archive" / "2026-08-10.html").exists()

    def test_index_links_to_past_editions(self, tmp_path):
        generate(tmp_path, [edition(week="2026-08-10"), edition(week="2026-08-03")])
        assert "archive/2026-08-03.html" in (tmp_path / "index.html").read_text()

    def test_archive_pages_link_back_to_the_stylesheet_and_home(self, tmp_path):
        generate(tmp_path, [edition(week="2026-08-10"), edition(week="2026-08-03")])
        page = (tmp_path / "archive" / "2026-08-03.html").read_text()
        assert "../style.css" in page
        assert 'href="../index.html"' in page

    def test_copies_the_stylesheet(self, tmp_path):
        generate(tmp_path, [edition()])
        assert (tmp_path / "style.css").read_text() == (STATIC_DIR / "style.css").read_text()

    def test_external_links_do_not_leak_the_opener(self, tmp_path):
        generate(tmp_path, [edition()])
        index = (tmp_path / "index.html").read_text()
        assert index.count('target="_blank"') == index.count('rel="noopener noreferrer"')

    def test_describes_the_page_for_search_engines_and_social_cards(self, tmp_path):
        generate(tmp_path, [edition()])
        index = (tmp_path / "index.html").read_text()
        assert '<meta name="description"' in index
        assert '<meta property="og:title"' in index

    def test_escapes_markup_in_story_titles(self, tmp_path):
        generate(tmp_path, [edition(title="<script>alert(1)</script>")])
        assert "<script>alert(1)</script>" not in (tmp_path / "index.html").read_text()

    def test_omits_the_summary_block_when_there_is_none(self, tmp_path):
        generate(tmp_path, [edition(summary="")])
        assert "story-summary" not in (tmp_path / "index.html").read_text()

    def test_returns_every_page_it_wrote(self, tmp_path):
        pages = generate(tmp_path, [edition(week="2026-08-10"), edition(week="2026-08-03")])
        assert {p for p in pages if p.suffix == ".html"} == {
            tmp_path / "index.html",
            tmp_path / "archive" / "2026-08-10.html",
            tmp_path / "archive" / "2026-08-03.html",
        }

    def test_does_nothing_without_editions(self, tmp_path):
        assert generate(tmp_path, []) == []
        assert not (tmp_path / "index.html").exists()


def multi_outlet_story(sources=("WIRED", "Ars Technica", "The Verge"), hn_points=None):
    return [
        make_article(source=source, url=f"https://example.com/{source}", hn_points=hn_points)
        for source in sources
    ]


class TestWhyItMadeTheCut:
    """Selection is the product; the evidence for it belongs on the page."""

    def test_reports_hacker_news_traction(self, tmp_path):
        generate(tmp_path, [edition(articles=[make_article(source="WIRED", hn_points=512)])])
        assert "512 points on Hacker News" in (tmp_path / "index.html").read_text()

    def test_reports_breadth_of_coverage(self, tmp_path):
        generate(tmp_path, [edition(articles=multi_outlet_story())])
        assert "covered by 3 outlets" in (tmp_path / "index.html").read_text().lower()

    def test_reports_both_signals_together(self, tmp_path):
        generate(tmp_path, [edition(articles=multi_outlet_story(hn_points=512))])
        index = (tmp_path / "index.html").read_text()
        assert "512 points on Hacker News" in index
        assert "covered by 3 outlets" in index.lower()

    def test_says_nothing_rather_than_none_when_there_is_no_evidence(self, tmp_path):
        archived = {
            "week": "2026-01-05",
            "generated_at": "2026-01-05T09:00:00Z",
            "stories": [
                {
                    "rank": 1,
                    "title": "A lone report",
                    "source": "Ars Technica",
                    "sources": ["Ars Technica"],
                    "source_count": 1,
                    "url": "https://example.com/a",
                    "category": "General Tech",
                    "hn_points": None,
                    "score": None,
                    "summary": "",
                }
            ],
        }
        generate(tmp_path, [archived])
        index = (tmp_path / "index.html").read_text()
        assert "None" not in index
        assert "points on Hacker News" not in index
        assert "outlets" not in index

    def test_never_prints_the_raw_score(self, tmp_path):
        story = make_story(title="Scored story", articles=[make_article(source="WIRED")])
        story.summary = "A summary."
        story.score = 4.321
        generate(tmp_path, [pipeline.build_edition([story], week="2026-08-10", now=NOW)])
        assert "4.321" not in (tmp_path / "index.html").read_text()


class TestCategoryChips:
    def test_gives_a_known_category_its_own_class(self, tmp_path):
        generate(tmp_path, [edition(category="Security")])
        assert "category-security" in (tmp_path / "index.html").read_text()

    def test_falls_back_to_a_neutral_chip_for_an_unknown_category(self, tmp_path):
        generate(tmp_path, [edition(category="Quantum")])
        index = (tmp_path / "index.html").read_text()
        assert "Quantum" in index
        assert "category-ai" not in index

    def test_handles_a_multiword_category(self, tmp_path):
        generate(tmp_path, [edition(category="Open Source")])
        index = (tmp_path / "index.html").read_text()
        assert "category-open-source" in index
        assert "Open Source" in index

    def test_escapes_markup_in_a_category(self, tmp_path):
        generate(tmp_path, [edition(category="<script>alert(1)</script>")])
        assert "<script>alert(1)</script>" not in (tmp_path / "index.html").read_text()


class TestDiscoveryMetadata:
    def test_advertises_the_feed_for_autodiscovery(self, tmp_path):
        generate(tmp_path, [edition()])
        index = (tmp_path / "index.html").read_text()
        assert 'rel="alternate"' in index
        assert 'type="application/atom+xml"' in index
        assert "feed.xml" in index

    def test_archive_pages_point_at_the_feed_at_the_site_root(self, tmp_path):
        generate(tmp_path, [edition(week="2026-08-10"), edition(week="2026-08-03")])
        page = (tmp_path / "archive" / "2026-08-03.html").read_text()
        assert "../feed.xml" in page

    def test_asks_for_a_large_social_card(self, tmp_path):
        generate(tmp_path, [edition()])
        assert 'content="summary_large_image"' in (tmp_path / "index.html").read_text()

    def test_omits_absolute_metadata_when_no_site_url_is_configured(self):
        """The pipeline passes site_url today, but the template must not depend on it."""
        page = render()
        assert 'rel="canonical"' not in page
        assert 'property="og:image"' not in page
        assert "feed.xml" in page

    def test_pipeline_pages_carry_the_configured_site_url(self, tmp_path):
        generate(tmp_path, [edition()])
        index = (tmp_path / "index.html").read_text()
        assert 'rel="canonical"' in index
        assert "og.png" in index

    def test_uses_the_site_url_for_the_card_image_and_canonical(self):
        page = render(site_url="https://lastweekin.tech")
        assert '<meta property="og:image" content="https://lastweekin.tech/og.png"' in page
        assert '<link rel="canonical" href="https://lastweekin.tech/"' in page

    def test_tolerates_a_trailing_slash_on_the_site_url(self):
        page = render(site_url="https://lastweekin.tech/")
        assert "https://lastweekin.tech//" not in page

    def test_canonicalises_an_archive_page_to_its_own_url(self):
        page = render(
            site_url="https://lastweekin.tech",
            edition=edition(week="2026-08-03"),
            root="../",
            is_latest=False,
        )
        assert (
            '<link rel="canonical" href="https://lastweekin.tech/archive/2026-08-03.html"' in page
        )


class TestReaderPolish:
    def test_has_exactly_one_top_level_heading(self, tmp_path):
        generate(tmp_path, [edition()])
        assert (tmp_path / "index.html").read_text().count("<h1") == 1

    def test_announces_the_rank_to_screen_readers(self, tmp_path):
        generate(tmp_path, [edition()])
        index = (tmp_path / "index.html").read_text()
        assert 'class="story-rank" aria-hidden="true"' not in index

    def test_does_not_call_out_to_a_third_party_font_host(self, tmp_path):
        generate(tmp_path, [edition()])
        index = (tmp_path / "index.html").read_text()
        assert "fonts.googleapis.com" not in index
        assert "fonts.gstatic.com" not in index

    def test_writes_dates_the_way_a_reader_says_them(self, tmp_path):
        generate(tmp_path, [edition(week="2026-08-10")])
        index = (tmp_path / "index.html").read_text()
        assert '<time datetime="2026-08-10">Aug 10, 2026</time>' in index

    def test_falls_back_to_the_raw_week_for_an_unexpected_date(self):
        assert "whenever" in render(edition=edition(week="whenever"))

    def test_groups_a_long_archive_by_year(self, tmp_path):
        weeks = [f"2026-0{month}-0{day}" for month in (1, 2, 3) for day in (1, 5, 8)]
        weeks += [f"2025-1{month}-0{day}" for month in (0, 1, 2) for day in (1, 5, 8)]
        generate(tmp_path, [edition(week=week) for week in weeks])
        index = (tmp_path / "index.html").read_text()
        assert "<details" in index
        assert ">2025<" in index
