"""
Regression tests for parseESCPOS()'s handling of variable-length GS payloads
(GS v 0 logo raster, GS k barcode) in DigiSlip_ONX3248G035.ino.

The real function skipped a fixed 2 bytes after any GS command, which only
holds for short single-parameter commands (GS H 2, GS h 80, GS w 2, cut).
GS v 0 and GS k carry variable-length payloads and were falling through into
the generic byte-by-byte text loop, so bitmap/barcode bytes were misread as
printable text (observed on hardware as a "0s" line followed by bitmap noise).

Since the .ino can't be executed directly from pytest, _parse_escpos() below
is a line-for-line Python port of the fixed C++ skip logic. It is exercised
against real ESC/POS bytes produced by the simulator's own Receipt.logo()/
.barcode() methods, so a regression in either side shows up here without
needing hardware.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "simulator"))
from PIL import Image
from Serial_RS232_Driver_v2 import Receipt, GS

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")


# =============================================================================
#  Python port of the fixed parseESCPOS() GS-byte handling
# =============================================================================

def _esc_param_bytes(cmd: int) -> int:
    return {0x61: 1, 0x64: 1, 0x45: 1, 0x2D: 1, 0x21: 1, 0x4D: 1, 0x56: 1, 0x40: 0}.get(cmd, 1)


def parse_escpos(buf: bytes) -> list[str]:
    lines: list[str] = []
    current = ""
    i = 0
    length = len(buf)

    while i < length:
        b = buf[i]
        if b == 0x1B:
            i += 1
            if i < length:
                skip = _esc_param_bytes(buf[i])
                i += 1 + skip
        elif b == 0x1D:
            i += 1
            if i < length:
                gs_cmd = buf[i]
                if gs_cmd == 0x76 and i + 1 < length and buf[i + 1] == 0x30:
                    # GS v 0 m xL xH yL yH <bitmap data>
                    if i + 6 < length:
                        bytes_per_row = buf[i + 3] | (buf[i + 4] << 8)
                        rows = buf[i + 5] | (buf[i + 6] << 8)
                        i += 7 + (bytes_per_row * rows)
                    else:
                        i = length
                elif gs_cmd == 0x6B:
                    # GS k m [n d1..dn] (function B) or GS k m d1..dn NUL (function A)
                    m = buf[i + 1] if i + 1 < length else 0
                    if m >= 65 and i + 2 < length:
                        n = buf[i + 2]
                        i += 3 + n
                    else:
                        j = i + 2
                        while j < length and buf[j] != 0x00:
                            j += 1
                        i = j + 1 if j < length else length
                else:
                    i += 2
        elif b in (0x0A, 0x0D):
            current = current.strip()
            if current:
                lines.append(current)
            current = ""
            i += 1
        elif 0x20 <= b < 0x80:
            current += chr(b)
            i += 1
        else:
            i += 1

    current = current.strip()
    if current:
        lines.append(current)
    return lines


# =============================================================================
#  Fixtures
# =============================================================================

def _solid_png(width: int, height: int, color: int = 255) -> str:
    img = Image.new("L", (width, height), color)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(path)
    return path


# =============================================================================
#  Behavior: logo bitmap bytes must not leak into extracted text lines
# =============================================================================

def test_logo_does_not_leak_bitmap_bytes_as_text():
    # Solid black -> worst case, every bitmap byte is 0xFF (non-printable, but
    # the header math below is what actually mattered on real hardware).
    path = _solid_png(200, 60, color=0)
    try:
        data = bytes(Receipt().center().logo(path).line("CITY FRESH").build())
    finally:
        os.unlink(path)

    lines = parse_escpos(data)
    assert lines and lines[0] == "CITY FRESH", (
        f"Expected 'CITY FRESH' as the first extracted line, got {lines!r} — "
        "bitmap bytes are leaking into text extraction"
    )
    assert not any(line.startswith("0s") for line in lines), (
        f"Found the known '0s'-prefixed garbage line in {lines!r}"
    )


def test_logo_skip_length_is_exact():
    # Build a GS v 0 command by hand for a 384px-wide / 115px-tall image
    # (the exact dimensions test_logo.png scales to) and fill the ENTIRE
    # bitmap payload with 0x0A bytes -- the nastiest possible case. With the
    # old fixed 2-byte skip, every one of these would be misread as a line
    # terminator. With the fix, the parser must jump clean over all of them.
    bytes_per_row, rows = 48, 115
    header = GS + b'\x76\x30\x00' + bytes([
        bytes_per_row & 0xFF, (bytes_per_row >> 8) & 0xFF,
        rows & 0xFF, (rows >> 8) & 0xFF,
    ])
    payload = b'\x0a' * (bytes_per_row * rows)
    data = header + payload + b'MARKER\n'

    lines = parse_escpos(data)
    assert lines == ["MARKER"], f"Expected only the marker line, got {lines!r}"


# =============================================================================
#  Behavior: barcode payload bytes must not leak into extracted text lines
# =============================================================================

def test_barcode_value_does_not_leak_as_text_line():
    data = bytes(Receipt().barcode("9782504938271").line("AFTER BARCODE").build())
    lines = parse_escpos(data)

    assert "AFTER BARCODE" in lines
    assert not any("9782504938271" in line for line in lines), (
        f"Barcode payload leaked into extracted text lines: {lines!r}"
    )


def test_combined_logo_and_barcode_slip_extracts_clean_lines():
    logo_path = _solid_png(200, 60, color=128)
    try:
        data = bytes(
            Receipt()
            .center()
            .logo(logo_path)
            .line("CITY FRESH")
            .barcode("9782504938271")
            .line("THANK YOU")
            .build()
        )
    finally:
        os.unlink(logo_path)

    lines = parse_escpos(data)
    assert lines == ["CITY FRESH", "THANK YOU"], (
        f"Expected clean text lines with no bitmap/barcode noise, got {lines!r}"
    )


# =============================================================================
#  Structural guard: pin the fix in source so a future refactor can't
#  silently reintroduce the fixed 2-byte GS skip.
# =============================================================================

def test_source_handles_gs_v_0_variable_length():
    m = re.search(r"void\s+parseESCPOS\s*\(.*?\n\}", SOURCE, re.DOTALL)
    assert m, "Could not locate parseESCPOS() body"
    body = m.group(0)
    assert "0x76" in body and "bytesPerRow" in body and "rows" in body, (
        "parseESCPOS() no longer appears to compute a variable-length skip "
        "for GS v 0 (logo raster) — regression to the fixed 2-byte skip?"
    )


def test_source_handles_gs_k_variable_length():
    m = re.search(r"void\s+parseESCPOS\s*\(.*?\n\}", SOURCE, re.DOTALL)
    assert m, "Could not locate parseESCPOS() body"
    body = m.group(0)
    assert "0x6B" in body or "0x6b" in body, (
        "parseESCPOS() no longer appears to special-case GS k (barcode) — "
        "regression to the fixed 2-byte skip?"
    )
