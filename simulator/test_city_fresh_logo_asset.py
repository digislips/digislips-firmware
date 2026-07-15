import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from PIL import Image
from Serial_RS232_Driver_v2 import Receipt

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_logo.png")
OLD_PLACEHOLDER_SHA256 = "a4993b705c393b021603f3aecd82280c6cde9206535a0fce476725626dce0209"


def test_logo_replaces_generic_placeholder():
    with open(LOGO_PATH, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    assert digest != OLD_PLACEHOLDER_SHA256, "test_logo.png is still the generic box/bars placeholder"


def test_logo_footprint_matches_receipt_header():
    # Acceptance criteria: "similar footprint to the existing placeholder, roughly 200x60"
    img = Image.open(LOGO_PATH)
    width, height = img.size
    assert 150 <= width <= 260
    assert 40 <= height <= 90
    aspect = width / height
    assert 2.0 <= aspect <= 4.5


def _print_bitmap():
    data = Receipt().logo(LOGO_PATH).build()
    idx = data.index(b'\x1d\x76\x30')
    bytes_per_row = data[idx + 4] + (data[idx + 5] << 8)
    height = data[idx + 6] + (data[idx + 7] << 8)
    bitmap = data[idx + 8: idx + 8 + bytes_per_row * height]
    return bitmap, bytes_per_row, height


def test_logo_survives_threshold_with_visible_ink():
    # Not blank after 1-bit conversion -- some dark content made it through
    bitmap, _, _ = _print_bitmap()
    assert any(b != 0x00 for b in bitmap)


def test_logo_survives_threshold_without_becoming_solid_block():
    # Not fully inked either -- real contrast/whitespace survived, not a black rectangle
    bitmap, _, _ = _print_bitmap()
    assert any(b != 0xFF for b in bitmap)


def test_logo_ink_ratio_in_legible_range():
    # Proxy for "legible mark, not noise and not a near-empty smudge"
    bitmap, bytes_per_row, height = _print_bitmap()
    total_bits = bytes_per_row * 8 * height
    on_bits = sum(bin(b).count("1") for b in bitmap)
    ratio = on_bits / total_bits
    assert 0.03 <= ratio <= 0.65
