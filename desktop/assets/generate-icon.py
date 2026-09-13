"""Regenerates desktop/build/icon.ico from the same mark used as the web
favicon (web/public/favicon.svg) - redrawn with Pillow at high resolution
rather than rasterizing the SVG (no SVG renderer available in this venv),
since it's just four rounded squares at fixed proportions."""

from pathlib import Path
from PIL import Image, ImageDraw

SCALE = 40  # 24-unit viewBox * 40 = 960px working canvas, downsampled for AA
SIZE = 24 * SCALE

COLORS = {
    "light_blue": (0x68, 0xC4, 0xFF, 255),
    "mid_blue": (0x0C, 0x79, 0xD8, 255),
    "bright_blue": (0x2E, 0x9E, 0xFF, 255),
}


def rect(x0, y0, x1, y1):
    return (x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE)


def rounded_square_sharp_corner(draw, x0, y0, x1, y1, radius, sharp_corner, fill):
    """A square rounded on 3 corners, sharp on the 4th (so two adjacent
    quadrants tile together with no gap/overlap at their shared corner)."""
    draw.rounded_rectangle(rect(x0, y0, x1, y1), radius=radius * SCALE, fill=fill)
    r = radius
    patches = {
        "top_left": (x0, y0, x0 + r, y0 + r),
        "top_right": (x1 - r, y0, x1, y0 + r),
        "bottom_left": (x0, y1 - r, x0 + r, y1),
        "bottom_right": (x1 - r, y1 - r, x1, y1),
    }
    px0, py0, px1, py1 = patches[sharp_corner]
    draw.rectangle(rect(px0, py0, px1, py1), fill=fill)


def main():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Big top-left square (2,2)-(12,12), sharp at its bottom-right (inner) corner.
    rounded_square_sharp_corner(draw, 2, 2, 12, 12, 2.72727, "bottom_right", COLORS["bright_blue"])
    # Big bottom-right square (12,12)-(22,22), sharp at its top-left (inner) corner.
    rounded_square_sharp_corner(draw, 12, 12, 22, 22, 2.72727, "top_left", COLORS["light_blue"])
    # Small fully-rounded accent squares in the two remaining notches.
    draw.rounded_rectangle(rect(15, 2, 22, 9), radius=2 * SCALE, fill=COLORS["mid_blue"])
    draw.rounded_rectangle(rect(2, 15, 9, 22), radius=2 * SCALE, fill=COLORS["mid_blue"])

    out_dir = Path(__file__).resolve().parent
    sizes = [256, 128, 64, 48, 32, 16]
    img.save(out_dir / "icon.ico", format="ICO", sizes=[(s, s) for s in sizes])
    img.resize((256, 256), Image.LANCZOS).save(out_dir / "icon-preview.png")
    print(f"Wrote {out_dir / 'icon.ico'} with sizes {sizes}")


if __name__ == "__main__":
    main()
