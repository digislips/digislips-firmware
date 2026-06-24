import sys
import os
import math
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from PIL import Image
from Serial_RS232_Driver_v2 import Receipt

GS_V_0 = b'\x1d\x76\x30'
TARGET_WIDTH = 384
BYTES_PER_ROW = math.ceil(TARGET_WIDTH / 8)  # 48


def _make_png(width: int, height: int, color: int = 255) -> str:
    """Save a solid-colour PNG to a temp file; caller must os.unlink."""
    img = Image.new("L", (width, height), color)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(path)
    return path


def _header_offset(data: bytes) -> int:
    return data.index(GS_V_0)


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


def test_logo_mode_byte_is_zero():
    path = _make_png(200, 60)
    try:
        data = Receipt().logo(path).build()
        idx = _header_offset(data)
        assert data[idx + 3] == 0   # m = 0 (normal density)
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


def test_logo_height_bytes_match_scaled_image():
    # 200×60 scaled to 384 wide → height = round(60 * 384 / 200) = 115
    path = _make_png(200, 60)
    try:
        data = Receipt().logo(path).build()
        idx = _header_offset(data)
        yL = data[idx + 6]
        yH = data[idx + 7]
        height = yL + (yH << 8)
        expected = max(1, round(60 * TARGET_WIDTH / 200))
        assert height == expected
    finally:
        os.unlink(path)


def test_logo_data_length_matches_dimensions():
    path = _make_png(200, 60)
    try:
        data = Receipt().logo(path).build()
        idx = _header_offset(data)
        bytes_per_row = data[idx + 4] + (data[idx + 5] << 8)
        height = data[idx + 6] + (data[idx + 7] << 8)
        # bitmap data begins at idx + 8; there must be exactly bytes_per_row * height bytes
        bitmap = data[idx + 8 : idx + 8 + bytes_per_row * height]
        assert len(bitmap) == bytes_per_row * height
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


def test_slip_7_exists():
    import Serial_RS232_Driver_v2 as sim
    assert hasattr(sim, 'slip_7_logo_test')


def test_slip_7_in_slips_registry():
    import Serial_RS232_Driver_v2 as sim
    assert '7' in sim.SLIPS


def test_slip_7_sends_bytes():
    import Serial_RS232_Driver_v2 as sim
    captured = []
    original = sim.print_raw_serial
    sim.print_raw_serial = lambda data, **kw: captured.append(data)
    try:
        sim.slip_7_logo_test()
    finally:
        sim.print_raw_serial = original
    assert captured, "slip_7_logo_test did not send any bytes"


def test_slip_7_sends_gs_v_0():
    import Serial_RS232_Driver_v2 as sim
    captured = []
    original = sim.print_raw_serial
    sim.print_raw_serial = lambda data, **kw: captured.append(data)
    try:
        sim.slip_7_logo_test()
    finally:
        sim.print_raw_serial = original
    assert GS_V_0 in captured[0]
