"""
gen_wordmark.py — generate Syne 800 wordmark C header files for TFT_eSPI.

Usage:
    python gen_wordmark.py [--font /path/to/Syne-ExtraBold.ttf]

Outputs wordmark_38.h and wordmark_22.h alongside this script.
Each header contains 1-bit MSB-first bitmap arrays for "digi" and "Slips"
at the named pixel size, suitable for TFT_eSPI drawBitmap().

Requirements: pip install Pillow requests
"""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


FONT_URL = (
    "https://fonts.gstatic.com/s/syne/v22/"
    "8vIS7w4qzmVxsWxjBZRjr0FKM_SKmlI.ttf"
)

SIZES = [38, 22]
HALVES = ["digi", "Slips"]


def fetch_font(local_path: str | None = None) -> Path:
    """Return a Path to Syne-ExtraBold.ttf, downloading if necessary."""
    if local_path:
        p = Path(local_path)
        if not p.exists():
            raise FileNotFoundError(f"Font not found: {local_path}")
        return p

    dest = Path(__file__).parent / "Syne-ExtraBold.ttf"
    if dest.exists():
        return dest

    import requests
    print("Downloading Syne-ExtraBold.ttf from Google Fonts...")
    r = requests.get(FONT_URL, timeout=15)
    r.raise_for_status()
    dest.write_bytes(r.content)
    print(f"  → saved to {dest}")
    return dest


def render_bitmap(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, size_px: int) -> tuple[int, int, bytes]:
    """
    Render text with the given PIL font (already sized by the caller).

    size_px is metadata only — it does not resize the font. The caller
    is responsible for loading the font at the correct size before calling.

    Returns (width, height, packed_bytes) where packed_bytes is a 1-bit
    MSB-first bitmap: ceil(width/8) bytes per row, rows top-to-bottom.
    Pixels are set (1) where the glyph is dark (< 128 grayscale).
    """
    sized = font

    # getbbox returns (left, top, right, bottom) relative to the draw origin.
    bbox = sized.getbbox(text)
    if bbox is None:
        return (0, 0, b"")
    l, t, r, b = bbox
    w = r - l
    h = b - t
    if w <= 0 or h <= 0:
        return (0, 0, b"")

    # Render onto a grayscale canvas exactly the size of the bounding box.
    img = Image.new("L", (w, h), 255)
    draw = ImageDraw.Draw(img)
    draw.text((-l, -t), text, font=sized, fill=0)

    # Pack to 1-bit MSB-first, one row at a time.
    stride = math.ceil(w / 8)
    rows = []
    pixels = img.load()
    for row in range(h):
        byte_row = bytearray(stride)
        for col in range(w):
            if pixels[col, row] < 128:
                byte_row[col // 8] |= 0x80 >> (col % 8)
        rows.append(bytes(byte_row))

    return (w, h, b"".join(rows))


def to_c_header(prefix: str, size: int, w: int, h: int, data: bytes) -> str:
    """
    Return a C header string exporting:
        #define {PREFIX}_{SIZE}_W  {w}
        #define {PREFIX}_{SIZE}_H  {h}
        const uint8_t PROGMEM {PREFIX}_{SIZE}_BITMAP[] = { ... };
    """
    hex_bytes = ", ".join(f"0x{b:02X}" for b in data)
    return (
        f"#define {prefix}_{size}_W  {w}\n"
        f"#define {prefix}_{size}_H  {h}\n"
        f"const uint8_t PROGMEM {prefix}_{size}_BITMAP[] = {{{hex_bytes}}};\n"
    )


def write_headers(font_path: Path, output_dir: Path) -> None:
    """Generate wordmark_38.h and wordmark_22.h in output_dir."""
    for size in SIZES:
        font = ImageFont.truetype(str(font_path), size)
        blocks = []
        for half in HALVES:
            prefix = half.upper()
            w, h, data = render_bitmap(half, font, size)
            blocks.append(to_c_header(prefix, size, w, h, data))
        header = "\n".join(blocks)
        out = output_dir / f"wordmark_{size}.h"
        out.write_text(header, encoding="utf-8")
        print(f"  -> {out}  ({len(data)} bytes per half)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate DigiSlip wordmark C headers.")
    parser.add_argument("--font", metavar="TTF", help="Local path to Syne-ExtraBold.ttf")
    args = parser.parse_args()

    font_path = fetch_font(args.font)
    output_dir = Path(__file__).parent
    print("Generating wordmark headers...")
    write_headers(font_path, output_dir)
    print("Done.")


if __name__ == "__main__":
    main()
