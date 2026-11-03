"""Draw the app icon files from the mark on the landing page.

The mark is a page with two lines of text and one highlighter stroke, on a
20 by 20 grid. Needs Pillow, which the app itself does not:

    python assets/make_icons.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

PAGE = "#EEF0F5"
STROKE = "#F5DC4A"
LINE = "#1A1F2B"
GRID = 20
MASTER = 1024
SUPERSAMPLE = 4
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw_master() -> Image.Image:
    unit = MASTER * SUPERSAMPLE / GRID

    def box(x: float, y: float, width: float, height: float) -> list[float]:
        return [x * unit, y * unit, (x + width) * unit - 1, (y + height) * unit - 1]

    image = Image.new("RGBA", (MASTER * SUPERSAMPLE, MASTER * SUPERSAMPLE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(box(0, 0, 20, 20), radius=4 * unit, fill=PAGE)
    draw.rectangle(box(0, 7.5, 20, 5), fill=STROKE)
    draw.rectangle(box(4, 4, 12, 1.5), fill=LINE)
    draw.rectangle(box(4, 14.5, 8, 1.5), fill=LINE)
    return image.resize((MASTER, MASTER), Image.Resampling.LANCZOS)


def main() -> None:
    folder = Path(__file__).resolve().parent
    master = draw_master()
    master.resize((512, 512), Image.Resampling.LANCZOS).save(folder / "icon.png", optimize=True)
    master.save(folder / "icon.ico", sizes=[(size, size) for size in ICO_SIZES])
    master.save(folder / "icon.icns")


if __name__ == "__main__":
    main()
