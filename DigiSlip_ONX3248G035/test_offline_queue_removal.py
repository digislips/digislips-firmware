"""
Source-level tests for NVS offline queue removal — issue #16.

Verifies that all offline queue code has been deleted and that slips
received while offline are forwarded immediately to the printer.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")


def _offline_state_body():
    m = re.search(r"case\s+STATE_OFFLINE\s*:(.*?)(?=case\s+STATE_|\bdefault\b)", SOURCE, re.DOTALL)
    assert m, "Could not locate STATE_OFFLINE body"
    return m.group(1)


# ── AC 1: offlineQueuePush deleted ───────────────────────────────────────────

def test_offline_queue_push_deleted():
    assert "offlineQueuePush" not in SOURCE, \
        "offlineQueuePush() still present — offline queue not removed"


# ── AC 2: offlineQueuePop deleted ────────────────────────────────────────────

def test_offline_queue_pop_deleted():
    assert "offlineQueuePop" not in SOURCE, \
        "offlineQueuePop() still present — offline queue not removed"


# ── AC 3: offlineQueueLen deleted ────────────────────────────────────────────

def test_offline_queue_len_deleted():
    assert not re.search(r"\bofflineQueueLen\b", SOURCE), \
        "offlineQueueLen() still present — offline queue not removed"


# ── AC 4: STATE_OFFLINE_QUEUE removed from state machine ─────────────────────

def test_state_offline_queue_removed():
    assert "STATE_OFFLINE_QUEUE" not in SOURCE, \
        "STATE_OFFLINE_QUEUE still in state machine enum"


# ── AC 5: OFFLINE_QUEUE_SIZE define deleted ───────────────────────────────────

def test_offline_queue_size_define_deleted():
    assert "OFFLINE_QUEUE_SIZE" not in SOURCE, \
        "OFFLINE_QUEUE_SIZE define still present"


# ── AC 6: 'queue' NVS namespace never opened ──────────────────────────────────

def test_queue_nvs_namespace_not_opened():
    assert 'prefs.begin("queue"' not in SOURCE, \
        '"queue" NVS namespace is still opened — queue namespace must be removed'


# ── AC 7: WiFi-down path in STATE_UPLOADING goes to STATE_PRINTING ───────────

def test_offline_slip_forwarded_to_printer():
    # Find the offline-path serial log then check state transition
    m = re.search(r'No WiFi.*?currentState\s*=\s*(\w+)', SOURCE, re.DOTALL)
    assert m, "Could not find 'No WiFi' branch in STATE_UPLOADING"
    assert m.group(1) == "STATE_PRINTING", \
        f"No-WiFi path transitions to {m.group(1)!r}, expected STATE_PRINTING"


# ── AC 8: STATE_OFFLINE no longer renders queue depth card ───────────────────

def test_offline_state_no_queue_card():
    body = _offline_state_body()
    assert "offlineQueueLen" not in body, \
        "STATE_OFFLINE still calls offlineQueueLen() — queue depth card not removed"
    assert "Queued slips" not in body, \
        'STATE_OFFLINE still renders "Queued slips" card'
