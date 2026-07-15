import sys
import os
import math
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from PIL import Image
from USB_Only_Driver import Receipt

GS_V_0 = b'\x1d\x76\x30'
GS_K_128 = b'\x1d\x6b\x49'
CUT_FULL = b'\x1d\x56\x00'
TARGET_WIDTH = 384
BYTES_PER_ROW = math.ceil(TARGET_WIDTH / 8)  # 48


def _header_offset(data: bytes) -> int:
    return data.index(GS_V_0)


def _make_png(width: int, height: int, color: int = 255) -> str:
    """Save a solid-colour PNG to a temp file; caller must os.unlink."""
    img = Image.new("L", (width, height), color)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(path)
    return path


def test_logo_returns_self():
    path = _make_png(100, 50)
    try:
        r = Receipt()
        assert r.logo(path) is r
    finally:
        os.unlink(path)


def test_logo_emits_gs_v_0():
    path = _make_png(100, 50)
    try:
        data = Receipt().logo(path).build()
        assert GS_V_0 in data
    finally:
        os.unlink(path)


def test_logo_bytes_per_row_matches_ceil_width_8():
    # Any source PNG is scaled to 384px wide → 48 bytes per row
    path = _make_png(200, 60)
    try:
        data = Receipt().logo(path).build()
        idx = _header_offset(data)
        xL = data[idx + 4]
        xH = data[idx + 5]
        assert xL + (xH << 8) == BYTES_PER_ROW
    finally:
        os.unlink(path)


def test_logo_white_image_zero_filled():
    # All-white PNG → no dots printed → every bitmap byte is 0x00
    path = _make_png(200, 10, color=255)
    try:
        data = Receipt().logo(path).build()
        idx = _header_offset(data)
        bytes_per_row = data[idx + 4] + (data[idx + 5] << 8)
        height = data[idx + 6] + (data[idx + 7] << 8)
        bitmap = data[idx + 8 : idx + 8 + bytes_per_row * height]
        assert all(b == 0x00 for b in bitmap)
    finally:
        os.unlink(path)


def test_logo_black_image_all_ones():
    # All-black PNG (384 cols = 48 full bytes per row) → every bitmap byte is 0xFF
    path = _make_png(200, 10, color=0)
    try:
        data = Receipt().logo(path).build()
        idx = _header_offset(data)
        bytes_per_row = data[idx + 4] + (data[idx + 5] << 8)
        height = data[idx + 6] + (data[idx + 7] << 8)
        bitmap = data[idx + 8 : idx + 8 + bytes_per_row * height]
        assert all(b == 0xFF for b in bitmap)
    finally:
        os.unlink(path)


def test_barcode_returns_self():
    r = Receipt()
    assert r.barcode("TEST") is r


def test_barcode_emits_gs_k_code128():
    data = Receipt().barcode("TEST").build()
    assert GS_K_128 in data


def test_barcode_value_ascii_encoded():
    data = Receipt().barcode("ABC123").build()
    assert b'ABC123' in data


def test_barcode_hri_below():
    # GS H 2 = print human-readable text below barcode
    data = Receipt().barcode("TEST").build()
    assert b'\x1d\x48\x02' in data


def test_logo_barcode_cut_chain_builds_nonempty_with_expected_sequences():
    # Acceptance criteria: Receipt().logo(path).barcode(value).cut() builds
    # successfully and produces non-empty bytes containing GS v 0 and GS k.
    path = _make_png(100, 50)
    try:
        data = Receipt().logo(path).barcode("9782504938271").cut().build()
        assert len(data) > 0
        assert GS_V_0 in data
        assert GS_K_128 in data
        assert data.index(GS_V_0) < data.index(GS_K_128)
        assert data.endswith(CUT_FULL)
    finally:
        os.unlink(path)
