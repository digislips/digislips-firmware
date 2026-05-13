"""
Tests for gen_wordmark.py — the Syne 800 wordmark bitmap generator.

All tests use a bundled fallback font (FreeSans from matplotlib or a tiny
synthetic PIL font) so they run offline without downloading Syne.
The --font path is the production entry point; tests exercise the same
render_bitmap / to_c_header / write_headers API.
"""
import math
import re
import sys
import tempfile
from pathlib import Path

import pytest

# Resolve the path to a font we can use in tests without network access.
# We use PIL's default bitmap font as a stand-in; it renders at any requested
# size and lets us verify packing logic independently of the real typeface.
from PIL import ImageFont

FALLBACK_FONT = ImageFont.load_default()

sys.path.insert(0, str(Path(__file__).parent))
from gen_wordmark import render_bitmap, to_c_header, write_headers, fetch_font


# ── Behavior 1 ────────────────────────────────────────────────────────────────

def test_render_bitmap_returns_nonzero_dimensions():
    w, h, _ = render_bitmap("digi", FALLBACK_FONT, 38)
    assert w > 0
    assert h > 0


# ── Behavior 2 ────────────────────────────────────────────────────────────────

def test_render_bitmap_byte_count_matches_packed_stride():
    w, h, data = render_bitmap("digi", FALLBACK_FONT, 38)
    expected_bytes = math.ceil(w / 8) * h
    assert len(data) == expected_bytes


# ── Behavior 3 ────────────────────────────────────────────────────────────────

def test_to_c_header_contains_required_symbols():
    w, h, data = render_bitmap("digi", FALLBACK_FONT, 38)
    header = to_c_header("DIGI", 38, w, h, data)
    assert "DIGI_38_W" in header
    assert "DIGI_38_H" in header
    assert "DIGI_38_BITMAP" in header


# ── Behavior 4 ────────────────────────────────────────────────────────────────

def test_to_c_header_array_length_matches_data():
    w, h, data = render_bitmap("digi", FALLBACK_FONT, 38)
    header = to_c_header("DIGI", 38, w, h, data)
    # Count comma-separated hex literals inside the braces of the array body.
    match = re.search(r"\{([^}]+)\}", header)
    assert match, "No array body found in header"
    entries = [e.strip() for e in match.group(1).split(",") if e.strip()]
    assert len(entries) == len(data)


# ── Behavior 5 ────────────────────────────────────────────────────────────────

def test_digi_and_slips_bitmaps_are_distinct_and_nonempty():
    _, _, digi_data  = render_bitmap("digi",  FALLBACK_FONT, 38)
    _, _, slips_data = render_bitmap("Slips", FALLBACK_FONT, 38)
    # Neither should be all-zero (blank canvas)
    assert any(b != 0 for b in digi_data),  "digi bitmap is blank"
    assert any(b != 0 for b in slips_data), "Slips bitmap is blank"
    # They must differ (not accidentally identical)
    assert digi_data != slips_data


# ── Behavior 6 ────────────────────────────────────────────────────────────────

@pytest.fixture
def any_ttf_font():
    """Return a Path to any .ttf available on this system, or skip the test."""
    import glob
    candidates = (
        glob.glob("C:/Windows/Fonts/arial.ttf")
        + glob.glob(str(Path(sys.executable).parent / "**/*.ttf"), recursive=True)
    )
    if not candidates:
        pytest.skip("No TTF font available on this system")
    return Path(candidates[0])


def test_write_headers_creates_both_output_files(tmp_path, any_ttf_font):
    write_headers(any_ttf_font, tmp_path)

    assert (tmp_path / "wordmark_38.h").exists()
    assert (tmp_path / "wordmark_22.h").exists()


# ── Behavior 7 ────────────────────────────────────────────────────────────────

def test_each_header_contains_both_digi_and_slips_symbols(tmp_path, any_ttf_font):
    write_headers(any_ttf_font, tmp_path)

    h38 = (tmp_path / "wordmark_38.h").read_text()
    assert "DIGI_38_W" in h38
    assert "SLIPS_38_W" in h38
    assert "DIGI_38_BITMAP" in h38
    assert "SLIPS_38_BITMAP" in h38

    h22 = (tmp_path / "wordmark_22.h").read_text()
    assert "DIGI_22_W" in h22
    assert "SLIPS_22_W" in h22
    assert "DIGI_22_BITMAP" in h22
    assert "SLIPS_22_BITMAP" in h22


# ── Behavior 8 ────────────────────────────────────────────────────────────────

def test_fetch_font_returns_provided_local_path(any_ttf_font):
    result = fetch_font(str(any_ttf_font))
    assert result == any_ttf_font


def test_fetch_font_raises_for_missing_local_path():
    with pytest.raises(FileNotFoundError):
        fetch_font("/does/not/exist.ttf")
