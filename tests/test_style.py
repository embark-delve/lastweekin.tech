"""Guards on the stylesheet's palette.

Every colour in the site lives in two ``:root`` blocks in ``style.css`` — the
light one and the ``prefers-color-scheme: dark`` one — and nothing else in the
stylesheet carries a colour. That makes the palette small enough to assert
things about, which is worth doing: a colour edit is exactly the kind of change
that looks fine in the one browser you happened to open and fails for someone
reading in bright sun or with a contrast filter on.
"""

import colorsys
import re

import pytest

from lastweekintech.pipeline import PACKAGE_DIR

DARK_MARKER = "@media (prefers-color-scheme: dark)"

# The warm-brown band the palette deliberately avoids. Hue alone is not enough:
# a near-grey with a faint warm cast reads as neutral, so the saturation floor
# is what separates "brown" from "not quite pure grey".
BROWN_HUES = (20, 50)
BROWN_MIN_SATURATION = 0.12

# Category kickers set small uppercase text in these colours, so the normal-text
# threshold applies to all of them rather than the large-text one.
MIN_CONTRAST = 4.5


def _tokens(css: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})\s*;", css))


def palettes() -> dict[str, dict[str, str]]:
    """The light and dark token sets, keyed by scheme."""
    css = (PACKAGE_DIR / "static" / "style.css").read_text()
    light, _, dark = css.partition(DARK_MARKER)
    return {"light": _tokens(light), "dark": _tokens(dark)}


def _rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4))


def relative_luminance(value: str) -> float:
    """WCAG relative luminance."""
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in _rgb(value)]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(one: str, two: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    a, b = relative_luminance(one), relative_luminance(two)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def is_warm_brown(value: str) -> bool:
    red, green, blue = _rgb(value)
    hue, _, saturation = colorsys.rgb_to_hls(red, green, blue)
    return BROWN_HUES[0] <= hue * 360 <= BROWN_HUES[1] and saturation > BROWN_MIN_SATURATION


@pytest.mark.parametrize("scheme", ["light", "dark"])
class TestPalette:
    def test_no_token_is_a_warm_brown(self, scheme):
        brown = {name: value for name, value in palettes()[scheme].items() if is_warm_brown(value)}
        assert not brown, f"warm-brown tokens in the {scheme} palette: {brown}"

    def test_every_ink_reads_against_its_paper(self, scheme):
        palette = palettes()[scheme]
        paper = palette["paper"]
        # Rules are hairlines, not text, so they are held to no contrast floor.
        inks = {n: v for n, v in palette.items() if n != "paper" and not n.startswith("rule")}
        failures = {
            name: round(contrast(value, paper), 2)
            for name, value in inks.items()
            if contrast(value, paper) < MIN_CONTRAST
        }
        assert not failures, f"below {MIN_CONTRAST}:1 on {paper} in {scheme}: {failures}"
