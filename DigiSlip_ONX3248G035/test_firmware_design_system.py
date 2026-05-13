"""
Source-level tests for the DigiSlip v2.2 design system changes.

These tests parse DigiSlip_ONX3248G035.ino and verify structural
requirements that would otherwise need hardware to observe:
  - palette constants (names + correct RGB565 values)
  - FreeFonts includes
  - helper function definitions
  - boot screen wiring in setup()
  - absence of setTextSize() in helper section

Each test targets one acceptance criterion from issue #2.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")

# ── helpers ───────────────────────────────────────────────────────────────────

def rgb565(hex_color: str) -> int:
    """Calculate correct RGB565 from a #RRGGBB string."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

REQUIRED_PALETTE = {
    "COL_BG":       "#E8E4DA",
    "COL_CARD":     "#FEFDFB",
    "COL_FG":       "#1C1917",
    "COL_MUTED":    "#78716C",
    "COL_FAINT":    "#D6D3CD",
    "COL_BLUE":     "#1558FF",
    "COL_GREEN":    "#00C96A",
    "COL_GREEN_LT": "#ECFDF5",
    "COL_GREEN_BD": "#A7F3D0",
    "COL_GREEN_DK": "#059669",
    "COL_RED":      "#DC2626",
    "COL_RED_LT":   "#FEF2F2",
}

REMOVED_CONSTANTS = ["COL_ACCENT", "COL_SUCCESS", "COL_ERROR", "COL_ON_GREEN"]

REQUIRED_FREEFONTS = [
    "FreeSansBold18pt7b.h",
    "FreeSansBold24pt7b.h",
    "FreeMono9pt7b.h",
    "FreeMono12pt7b.h",
]

REQUIRED_HELPERS = [
    "drawWordmark",
    "drawHeader",
    "drawFooter",
    "drawPill",
    "displayBoot",
]


# ── Behavior 1: required palette names ───────────────────────────────────────

def test_all_required_color_constants_present():
    for name in REQUIRED_PALETTE:
        pattern = rf"#define\s+{name}\b"
        assert re.search(pattern, SOURCE), f"Missing colour constant: {name}"


# ── Behavior 2: removed palette names ────────────────────────────────────────

def test_removed_color_constants_absent():
    for name in REMOVED_CONSTANTS:
        pattern = rf"#define\s+{name}\b"
        assert not re.search(pattern, SOURCE), f"Obsolete colour constant still present: {name}"


# ── Behavior 3: correct RGB565 values ────────────────────────────────────────

def test_color_constants_have_correct_rgb565_values():
    for name, hex_color in REQUIRED_PALETTE.items():
        expected = rgb565(hex_color)
        pattern = rf"#define\s+{name}\s+(0x[0-9A-Fa-f]{{4}})"
        m = re.search(pattern, SOURCE)
        assert m, f"Could not parse value for {name}"
        actual = int(m.group(1), 16)
        assert actual == expected, (
            f"{name}: expected 0x{expected:04X} for {hex_color}, got 0x{actual:04X}"
        )


# ── Behavior 4: FreeFonts includes ───────────────────────────────────────────

def test_freefonts_included():
    for fname in REQUIRED_FREEFONTS:
        assert fname in SOURCE, f"Missing FreeFonts include: {fname}"


# ── Behavior 5: helper functions defined ─────────────────────────────────────

def test_helper_functions_defined():
    for fn in REQUIRED_HELPERS:
        pattern = rf"\b{fn}\s*\("
        assert re.search(pattern, SOURCE), f"Missing helper function: {fn}"


# ── Behavior 6: displayBoot called in setup() ────────────────────────────────

def test_displayBoot_called_in_setup():
    setup_match = re.search(r"void\s+setup\s*\(\s*\)(.*?)(?=void\s+loop\s*\()", SOURCE, re.DOTALL)
    assert setup_match, "Could not locate setup() body"
    assert "displayBoot(" in setup_match.group(1), "displayBoot() not called in setup()"


# ── Behavior 7: no setTextSize in helper section ─────────────────────────────

def test_no_setTextSize_in_helpers():
    # Only check the 5 design-system helpers, not the legacy screen functions.
    helper_section_match = re.search(
        r"(void\s+drawWordmark\s*\(.*?)(?=void\s+displayMessage\s*\()",
        SOURCE,
        re.DOTALL,
    )
    assert helper_section_match, "Could not locate design-system helper section"
    assert "setTextSize" not in helper_section_match.group(1), \
        "setTextSize() found in design-system helpers — use setFreeFont() instead"
