"""One-off generator for og.png, the social share card.

The card is committed as ``src/lastweekintech/static/og.png``; this script lives
here rather than beside the asset because ``generate_site`` publishes everything
in the static directory, and a build script is not a site asset. It exists so it
can be regenerated when the wordmark or tagline changes. It is deliberately NOT
part of the pipeline and Pillow is NOT a declared dependency — run it in an
environment that happens to have Pillow installed:

    uv run python src/lastweekintech/static/make_og_image.py

Fonts are looked up from a list of common system paths (macOS first, then a few
Linux locations). If none is found the script exits rather than emitting a card
in a fallback bitmap font.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1200, 630
OUTPUT = Path(__file__).resolve().parents[1] / "src" / "lastweekintech" / "static" / "og.png"

TOP = (16, 20, 26)
BOTTOM = (26, 36, 52)
GHOST = (32, 46, 66)
INK = (238, 242, 246)
MUTED = (154, 168, 184)
ACCENT = (125, 179, 240)

BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
REGULAR_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit(f"No usable font found; tried: {', '.join(candidates)}")


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), TOP)
    draw = ImageDraw.Draw(image)

    # Vertical gradient background.
    for y in range(HEIGHT):
        ratio = y / (HEIGHT - 1)
        draw.line(
            [(0, y), (WIDTH, y)],
            fill=tuple(round(a + (b - a) * ratio) for a, b in zip(TOP, BOTTOM, strict=True)),
        )

    # Ghost numeral: the "Top 7" promise, as a watermark.
    draw.text((980, 300), "7", font=load_font(BOLD_CANDIDATES, 520), fill=GHOST, anchor="mm")

    wordmark_font = load_font(BOLD_CANDIDATES, 92)
    tagline_font = load_font(REGULAR_CANDIDATES, 40)

    draw.text((90, 200), "LastWeekIn.Tech", font=wordmark_font, fill=INK)
    baseline = draw.textbbox((90, 200), "LastWeekIn.Tech", font=wordmark_font)[3]

    draw.rectangle([90, baseline + 26, 190, baseline + 34], fill=ACCENT)
    draw.text(
        (90, baseline + 70),
        "The 7 tech stories that mattered.",
        font=tagline_font,
        fill=MUTED,
    )
    draw.text(
        (90, baseline + 124),
        "Every Monday. No trackers, no ads.",
        font=tagline_font,
        fill=MUTED,
    )
    draw.text((90, 520), "lastweekin.tech", font=load_font(BOLD_CANDIDATES, 28), fill=ACCENT)

    image.save(OUTPUT, optimize=True)
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
