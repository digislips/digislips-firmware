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
    assert "60000" in body, \
        "60000 ms throttle not found in displayIdle()"
    assert "lastIdleRefresh" in body, \
        "lastIdleRefresh not referenced in displayIdle()"


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


# =============================================================================
#  Issue #6 — Cancelled screen + STATE_CANCELLED hold
# =============================================================================

def _cancelled_body():
    m = re.search(r"void\s+drawCancelled\s*\(\s*\)(.*?)(?=\nvoid\s+\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate drawCancelled() body"
    return m.group(1)

def _cancelled_state_body():
    m = re.search(r"case\s+STATE_CANCELLED\s*:(.*?)(?=case\s+STATE_|\bdefault\b)", SOURCE, re.DOTALL)
    assert m, "Could not locate STATE_CANCELLED body"
    return m.group(1)

def _cancel_touch_branch():
    m = re.search(r"Cancel tapped(.*?)(?=//\s*\d+\.|break\s*;\s*\})", SOURCE, re.DOTALL)
    assert m, "Could not locate cancel-tapped branch"
    return m.group(1)


# ── Behavior 1: STATE_CANCELLED in enum, Cancel button uses it ───────────────

def test_state_cancelled_in_enum_and_cancel_button():
    assert "STATE_CANCELLED" in SOURCE, "STATE_CANCELLED not added to enum"
    branch = _cancel_touch_branch()
    assert "STATE_CANCELLED" in branch, \
        "Cancel touch branch does not set STATE_CANCELLED"


# ── Behavior 2: drawCancelled() defined and wired to STATE_CANCELLED ─────────

def test_drawCancelled_defined_and_called():
    assert re.search(r"\bvoid\s+drawCancelled\s*\(\s*\)", SOURCE), \
        "drawCancelled() not defined"
    body = _cancelled_state_body()
    assert "drawCancelled(" in body, \
        "drawCancelled() not called in STATE_CANCELLED"


# ── Behavior 3: header with no pill ──────────────────────────────────────────

def test_cancelled_header_no_pill():
    body = _cancelled_body()
    m = re.search(r"drawHeader\s*\(\s*(.*?)\s*,", body)
    assert m, "drawHeader() not found in drawCancelled()"
    assert m.group(1).strip() == "nullptr", \
        "drawCancelled() should call drawHeader(nullptr, …) — no pill"


# ── Behavior 4: "Print cancelled" headline ───────────────────────────────────

def test_cancelled_headline_text():
    body = _cancelled_body()
    assert "Print cancelled" in body, \
        '"Print cancelled" headline not found in drawCancelled()'


# ── Behavior 5: body copy mentions 24h claimability ──────────────────────────

def test_cancelled_body_mentions_24h():
    body = _cancelled_body()
    assert "24" in body, \
        "drawCancelled() body does not mention 24h claimability"


# ── Behavior 6: footer reads "Returning to idle" ─────────────────────────────

def test_cancelled_footer_returning_to_idle():
    body = _cancelled_body()
    assert re.search(r"[Rr]eturning\s+to\s+idle", body), \
        'Footer "Returning to idle" not found in drawCancelled()'


# ── Behavior 7: STATE_CANCELLED holds ~1 s then goes to STATE_IDLE ───────────

def test_cancelled_state_holds_then_idle():
    body = _cancelled_state_body()
    assert re.search(r"3000", body), \
        "3000 ms hold not found in STATE_CANCELLED"
    assert "STATE_IDLE" in body, \
        "STATE_CANCELLED does not transition to STATE_IDLE"


# =============================================================================
#  Issue #7 — Offline screen + STATE_OFFLINE + WiFi watchdog
# =============================================================================

def _offline_body():
    m = re.search(r"void\s+drawOffline\s*\(\s*\)(.*?)(?=\nvoid\s+\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate drawOffline() body"
    return m.group(1)

def _offline_state_body():
    m = re.search(r"case\s+STATE_OFFLINE\s*:(.*?)(?=case\s+STATE_|\bdefault\b)", SOURCE, re.DOTALL)
    assert m, "Could not locate STATE_OFFLINE body"
    return m.group(1)

def _watchdog_body():
    m = re.search(r"void\s+wifiWatchdog\s*\(\s*\)(.*?)(?=\n\S)", SOURCE, re.DOTALL)
    assert m, "Could not locate wifiWatchdog() body"
    return m.group(1)


# ── Behavior 1: globals wifiLostTime + preOfflineState declared ───────────────

def test_offline_globals_declared():
    assert "wifiLostTime" in SOURCE, "wifiLostTime global not found"
    assert "preOfflineState" in SOURCE, "preOfflineState global not found"


# ── Behavior 2: wifiWatchdog transitions to STATE_OFFLINE after 30 s ─────────

def test_watchdog_transitions_offline_after_30s():
    body = _watchdog_body()
    assert "STATE_OFFLINE" in body, \
        "wifiWatchdog() does not transition to STATE_OFFLINE"
    assert "30000" in body, \
        "30 s threshold (30000 ms) not found in wifiWatchdog()"


# ── Behavior 3: preOfflineState saved before entering STATE_OFFLINE ──────────

def test_watchdog_saves_pre_offline_state():
    body = _watchdog_body()
    assert "preOfflineState" in body, \
        "preOfflineState not saved in wifiWatchdog()"


# ── Behavior 4: reconnect restores preOfflineState ───────────────────────────

def test_watchdog_restores_state_on_reconnect():
    body = _watchdog_body()
    assert re.search(r"currentState\s*=\s*preOfflineState", body), \
        "currentState not restored to preOfflineState on reconnect in wifiWatchdog()"


# ── Behavior 5: drawOffline() defined and called from STATE_OFFLINE ──────────

def test_drawOffline_defined_and_called():
    assert re.search(r"\bvoid\s+drawOffline\s*\(\s*\)", SOURCE), \
        "drawOffline() not defined"
    body = _offline_state_body()
    assert "drawOffline(" in body, \
        "drawOffline() not called in STATE_OFFLINE"


# ── Behavior 6: header has "Offline" red pill ────────────────────────────────

def test_offline_header_has_offline_pill():
    body = _offline_body()
    m = re.search(r"drawHeader\s*\(\s*(.*?)\s*,", body)
    assert m, "drawHeader() not found in drawOffline()"
    assert m.group(1).strip() != "nullptr", \
        "drawHeader() called with nullptr in drawOffline() — expected Offline pill"
    assert "Offline" in body, \
        '"Offline" pill text not found in drawOffline()'


# ── Behavior 7: "Lost connection" headline ───────────────────────────────────

def test_offline_headline_text():
    body = _offline_body()
    assert "Lost connection" in body, \
        '"Lost connection" headline not found in drawOffline()'


# ── Behavior 8: queued slip count shown in STATE_OFFLINE ─────────────────────

def test_offline_shows_queue_depth():
    body = _offline_state_body()
    assert "offlineQueueLen" in body, \
        "offlineQueueLen() not called in STATE_OFFLINE — queue depth not shown"


# ── Behavior 9: footer reads "check router" ──────────────────────────────────

def test_offline_footer_check_router():
    body = _offline_body()
    assert "check router" in body, \
        'Footer "check router" not found in drawOffline()'


# =============================================================================
#  Issue #8 — Claimed screen with ClaimMethod attribution
# =============================================================================

def _claimed_body():
    m = re.search(r"void\s+drawClaimed\s*\(\s*\)(.*?)(?=\nvoid\s+\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate drawClaimed() body"
    return m.group(1)

def _claimed_state_body():
    m = re.search(r"case\s+STATE_CLAIMED\s*:(.*?)(?=case\s+STATE_|\bdefault\b)", SOURCE, re.DOTALL)
    assert m, "Could not locate STATE_CLAIMED body"
    return m.group(1)


# ── Behavior 1: ClaimMethod enum and global declared ─────────────────────────

def test_claim_method_enum_declared():
    assert "CLAIM_NFC" in SOURCE, "CLAIM_NFC not found in ClaimMethod enum"
    assert "CLAIM_QR" in SOURCE, "CLAIM_QR not found in ClaimMethod enum"
    assert re.search(r"\bclaimMethod\b", SOURCE), "claimMethod global not declared"


# ── Behavior 2: NFC path sets CLAIM_NFC before STATE_CLAIMED ─────────────────

def test_nfc_path_sets_claim_nfc():
    m = re.search(
        r"NFC\] Slip claimed(.*?)currentState\s*=\s*STATE_CLAIMED",
        SOURCE, re.DOTALL
    )
    assert m, "Could not find NFC claim → STATE_CLAIMED block"
    assert "CLAIM_NFC" in m.group(1), \
        "NFC path does not set claimMethod = CLAIM_NFC before STATE_CLAIMED"


# ── Behavior 3: QR/poll path sets CLAIM_QR before STATE_CLAIMED ──────────────

def test_qr_path_sets_claim_qr():
    m = re.search(
        r"QR/app(.*?)currentState\s*=\s*STATE_CLAIMED",
        SOURCE, re.DOTALL
    )
    assert m, "Could not find QR/app claim → STATE_CLAIMED block"
    assert "CLAIM_QR" in m.group(1), \
        "QR/app poll path does not set claimMethod = CLAIM_QR before STATE_CLAIMED"


# ── Behavior 4: drawClaimed() defined and called from STATE_CLAIMED ──────────

def test_drawClaimed_defined_and_called():
    assert re.search(r"\bvoid\s+drawClaimed\s*\(\s*\)", SOURCE), \
        "drawClaimed() not defined"
    body = _claimed_state_body()
    assert "drawClaimed(" in body, \
        "drawClaimed() not called in STATE_CLAIMED"


# ── Behavior 5: header with no pill ──────────────────────────────────────────

def test_claimed_header_no_pill():
    body = _claimed_body()
    m = re.search(r"drawHeader\s*\(\s*(.*?)\s*,", body)
    assert m, "drawHeader() not found in drawClaimed()"
    assert m.group(1).strip() == "nullptr", \
        "drawClaimed() should call drawHeader(nullptr, …) — no pill"


# ── Behavior 6: "Slip claimed" headline ──────────────────────────────────────

def test_claimed_headline_text():
    body = _claimed_body()
    assert "Slip claimed" in body, \
        '"Slip claimed" headline not found in drawClaimed()'


# ── Behavior 7: claimMethod read in drawClaimed() for "via" string ───────────

def test_claimed_reads_claim_method():
    body = _claimed_body()
    assert "claimMethod" in body, \
        "claimMethod not read in drawClaimed() — via attribution missing"
    assert "CLAIM_NFC" in body, \
        "CLAIM_NFC branch not found in drawClaimed()"


# ── Behavior 8: footer "returning to idle" ───────────────────────────────────

def test_claimed_footer_returning_to_idle():
    body = _claimed_body()
    assert re.search(r"returning\s+to\s+idle", body, re.IGNORECASE), \
        'Footer "returning to idle" not found in drawClaimed()'


# ── Behavior 9: STATE_CLAIMED holds 3 s then returns to STATE_IDLE ───────────

def test_claimed_state_holds_9s_then_idle():
    body = _claimed_state_body()
    assert re.search(r"9000", body), \
        "9000 ms hold not found in STATE_CLAIMED"
    assert "STATE_IDLE" in body, \
        "STATE_CLAIMED does not transition to STATE_IDLE"
