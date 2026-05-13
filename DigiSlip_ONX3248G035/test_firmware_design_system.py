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
    "FreeMono9pt7b",   # used in drawPill / drawHeader / drawFooter / displayBoot
    # FreeSansBold and FreeMono12pt are tested in the screen-function issues (#3-#8)
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


# ── Behavior 4: FreeFonts symbols used ───────────────────────────────────────

def test_freefonts_used():
    for fname in REQUIRED_FREEFONTS:
        assert fname in SOURCE, f"FreeFonts symbol not referenced: {fname}"


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


# ── Behavior 7: displayBoot does not use setTextSize for body text ────────────

def test_no_setTextSize_in_displayBoot():
    # displayBoot is the one helper that must stay FreeFont-only for body text.
    m = re.search(r"(void\s+displayBoot\s*\(.*?)(?=void\s+displayMessage\s*\()", SOURCE, re.DOTALL)
    assert m, "Could not locate displayBoot() body"
    assert "setTextSize" not in m.group(1), \
        "setTextSize() found in displayBoot() — use setFreeFont() instead"


# =============================================================================
#  Issue #3 — Idle screen redesign
# =============================================================================

def _idle_body():
    """Return the body of displayIdle() as a string, or fail the test."""
    m = re.search(r"void\s+displayIdle\s*\(\s*\)(.*?)(?=\nvoid\s+\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate displayIdle() body"
    return m.group(1)


# ── Behavior 1: getDateLine defined ──────────────────────────────────────────

def test_getDateLine_defined():
    assert re.search(r"\bgetDateLine\s*\(", SOURCE), "getDateLine() not defined"


# ── Behavior 2: getDateLine format ───────────────────────────────────────────

def test_getDateLine_format():
    m = re.search(r"String\s+getDateLine\s*\(\s*\)(.*?)(?=\n\S)", SOURCE, re.DOTALL)
    assert m, "Could not locate getDateLine() body"
    body = m.group(1)
    assert "%a" in body, "Missing %a (weekday) in getDateLine strftime"
    assert "%d" in body, "Missing %d (day) in getDateLine strftime"
    assert "%b" in body, "Missing %b (month) in getDateLine strftime"
    assert "%H:%M" in body, "Missing %H:%M (time) in getDateLine strftime"
    assert "\xb7" in body or "\\xC2\\xB7" in body or "·" in body, \
        "Missing middle dot separator in getDateLine"


# ── Behavior 3: old idle elements removed ────────────────────────────────────

def test_old_idle_elements_removed():
    body = _idle_body()
    assert "getTimeHHMM" not in body, "Large clock (getTimeHHMM) still in displayIdle()"
    assert "txCounter" not in body,   "TX counter still in displayIdle()"
    assert "offlineQueueLen" not in body, "Offline queue chip still in displayIdle()"


# ── Behavior 4: 38px wordmark hero ───────────────────────────────────────────

def test_idle_draws_wordmark_38():
    body = _idle_body()
    assert re.search(r"drawWordmark\s*\(.*?,\s*38\s*\)", body), \
        "drawWordmark() not called with size 38 in displayIdle()"


# ── Behavior 5: READY pill with green palette ─────────────────────────────────

def test_idle_ready_pill_green():
    body = _idle_body()
    assert "drawPill(" in body, "drawPill() not called in displayIdle()"
    assert "COL_GREEN" in body, "COL_GREEN not used in displayIdle() pill"


# ── Behavior 6: getDateLine called ───────────────────────────────────────────

def test_idle_calls_getDateLine():
    body = _idle_body()
    assert "getDateLine(" in body, "getDateLine() not called in displayIdle()"


# ── Behavior 7: drawFooter called ────────────────────────────────────────────

def test_idle_calls_drawFooter():
    body = _idle_body()
    assert "drawFooter(" in body, "drawFooter() not called in displayIdle()"


# ── Behavior 8: refresh throttle ≥ 60 s ──────────────────────────────────────

def test_idle_refresh_throttle_60s():
    body = _idle_body()
    m = re.search(r"lastIdleRefresh\s*<\s*(\d+)", body)
    assert m, "Could not find lastIdleRefresh throttle in displayIdle()"
    assert int(m.group(1)) >= 60000, \
        f"Idle refresh throttle is {m.group(1)} ms — should be ≥ 60000"


# ── Behavior 9: Online pill passed to drawHeader ─────────────────────────────

def test_idle_header_has_online_pill():
    body = _idle_body()
    m = re.search(r"drawHeader\s*\(\s*(.*?)\s*,", body)
    assert m, "drawHeader() not found in displayIdle()"
    first_arg = m.group(1).strip()
    assert first_arg != "nullptr", \
        "drawHeader() called with nullptr pill in displayIdle() — expected Online pill"


# =============================================================================
#  Issue #4 — Claim screen redesign
# =============================================================================

def _qr_body():
    m = re.search(r"void\s+drawQR\s*\(.*?\)(.*?)(?=\nvoid\s+\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate drawQR() body"
    return m.group(1)

def _waiting_claim_body():
    m = re.search(r"case\s+STATE_WAITING_CLAIM\s*:(.*?)(?=case\s+STATE_|\}\s*$)", SOURCE, re.DOTALL)
    assert m, "Could not locate STATE_WAITING_CLAIM body"
    return m.group(1)


# ── Behavior 1: header has Awaiting claim pill ────────────────────────────────

def test_qr_header_has_awaiting_claim_pill():
    body = _qr_body()
    m = re.search(r"drawHeader\s*\(\s*(.*?)\s*,", body)
    assert m, "drawHeader() not found in drawQR()"
    assert m.group(1).strip() != "nullptr", \
        "drawHeader() called with nullptr in drawQR() — expected Awaiting claim pill"


# ── Behavior 2: QR rendered at scale 5 ───────────────────────────────────────

def test_qr_scale_5():
    body = _qr_body()
    assert re.search(r"\bscale\s*=\s*5\b", body), \
        "QR scale not set to 5 in drawQR()"


# ── Behavior 3: receipt card at x=22 ─────────────────────────────────────────

def test_qr_card_at_x22():
    body = _qr_body()
    assert re.search(r"cardX\s*=\s*22\b", body), \
        "Receipt card x-origin (cardX) not 22 in drawQR()"


# ── Behavior 4: txCounter in Slip label ──────────────────────────────────────

def test_qr_slip_label_uses_txCounter():
    body = _qr_body()
    assert "txCounter" in body, "txCounter not used in Slip label in drawQR()"


# ── Behavior 5: Print button at BTN_PRINT_X / BTN_PRINT_Y ───────────────────

def test_qr_print_button_geometry():
    body = _qr_body()
    assert "BTN_PRINT_X" in body and "BTN_PRINT_Y" in body, \
        "Print button not using BTN_PRINT_X / BTN_PRINT_Y in drawQR()"


# ── Behavior 6: Cancel button at BTN_CANCEL_X / BTN_CANCEL_Y ────────────────

def test_qr_cancel_button_geometry():
    body = _qr_body()
    assert "BTN_CANCEL_X" in body and "BTN_CANCEL_Y" in body, \
        "Cancel button not using BTN_CANCEL_X / BTN_CANCEL_Y in drawQR()"


# ── Behavior 7: NFC in scan caption ──────────────────────────────────────────

def test_qr_caption_mentions_nfc():
    body = _qr_body()
    assert "NFC" in body, "Scan caption does not mention NFC in drawQR()"


# ── Behavior 8: drawFooter called in STATE_WAITING_CLAIM ─────────────────────

def test_waiting_claim_calls_drawFooter():
    body = _waiting_claim_body()
    assert "drawFooter(" in body, \
        "drawFooter() not called in STATE_WAITING_CLAIM loop"


# =============================================================================
#  Issue #5 — Printing screen with spinner animation
# =============================================================================

def _printing_body():
    m = re.search(r"void\s+drawPrinting\s*\(\s*\)(.*?)(?=\nvoid\s+\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate drawPrinting() body"
    return m.group(1)

def _printing_state_body():
    m = re.search(r"case\s+STATE_PRINTING\s*:(.*?)(?=case\s+STATE_|\bdefault\b)", SOURCE, re.DOTALL)
    assert m, "Could not locate STATE_PRINTING body"
    return m.group(1)


# ── Behavior 1: drawPrinting() defined and called from STATE_PRINTING ─────────

def test_drawPrinting_defined_and_called():
    assert re.search(r"\bvoid\s+drawPrinting\s*\(\s*\)", SOURCE), \
        "drawPrinting() not defined"
    body = _printing_state_body()
    assert "drawPrinting(" in body, \
        "drawPrinting() not called in STATE_PRINTING"


# ── Behavior 2: header drawn with no pill ─────────────────────────────────────

def test_printing_header_no_pill():
    body = _printing_body()
    m = re.search(r"drawHeader\s*\(\s*(.*?)\s*,", body)
    assert m, "drawHeader() not found in drawPrinting()"
    assert m.group(1).strip() == "nullptr", \
        "drawPrinting() should call drawHeader(nullptr, …) — no pill"


# ── Behavior 3: "Printing slip" headline ──────────────────────────────────────

def test_printing_headline_text():
    body = _printing_body()
    assert "Printing slip" in body, \
        '"Printing slip" headline not found in drawPrinting()'


# ── Behavior 4: txCounter in Slip sub-label ───────────────────────────────────

def test_printing_slip_label_uses_txCounter():
    body = _printing_body()
    assert "txCounter" in body, \
        "txCounter not used in Slip sub-label in drawPrinting()"


# ── Behavior 5: drawFooter called ────────────────────────────────────────────

def test_printing_draws_footer():
    body = _printing_body()
    assert "drawFooter(" in body, \
        "drawFooter() not called in drawPrinting()"


# ── Behavior 6: drawArc used for spinner ring ─────────────────────────────────

def test_printing_spinner_uses_drawArc():
    body = _printing_body()
    assert "drawArc(" in body, \
        "drawArc() not found in drawPrinting() — spinner ring missing"


# ── Behavior 7: spinAngle advances every 28 ms in STATE_PRINTING ─────────────

def test_printing_spinner_rate_28ms():
    body = _printing_state_body()
    assert "spinAngle" in body, \
        "spinAngle not found in STATE_PRINTING — spinner not animated"
    assert "28" in body, \
        "28 ms frame interval not found in STATE_PRINTING spinner logic"


# ── Behavior 8: STATE_PRINTING transitions to STATE_IDLE ─────────────────────

def test_printing_state_returns_to_idle():
    body = _printing_state_body()
    assert "STATE_IDLE" in body, \
        "STATE_PRINTING does not transition to STATE_IDLE"
