"""
Source-level tests for the NVS credentials module — issue #15.

Verifies that credsAreProvisioned(), credsRead(), credsWrite(), and
credsClear() are defined in the sketch using the 'creds' Preferences
namespace, and that the 'system' and 'queue' namespaces are untouched.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")


def _creds_section():
    """Return the NVS CREDENTIALS section of the source."""
    m = re.search(
        r"NVS CREDENTIALS.*?(?=// =====)",
        SOURCE, re.DOTALL
    )
    assert m, "Could not locate NVS CREDENTIALS section in source"
    return m.group(0)


def _fn_body(name: str) -> str:
    """Return the body of a named function."""
    m = re.search(
        rf"\b{re.escape(name)}\b[^{{]*\{{(.*?)(?=\n\}}\s*\n)",
        SOURCE, re.DOTALL
    )
    assert m, f"Could not locate {name}() body"
    return m.group(1)


# ── Behavior 1: credsAreProvisioned() defined ────────────────────────────────

def test_creds_are_provisioned_defined():
    assert re.search(r"\bcredsAreProvisioned\s*\(", SOURCE), \
        "credsAreProvisioned() not defined"


# ── Behavior 2: credsAreProvisioned opens 'creds' in read-only mode ──────────

def test_creds_are_provisioned_uses_creds_namespace_readonly():
    body = _fn_body("credsAreProvisioned")
    assert 'prefs.begin("creds", true)' in body, \
        'credsAreProvisioned() does not open "creds" namespace in read-only mode'


# ── Behavior 3: credsAreProvisioned checks wifi_ssid as provisioning gate ────

def test_creds_are_provisioned_checks_wifi_ssid():
    body = _fn_body("credsAreProvisioned")
    assert "wifi_ssid" in body, \
        "credsAreProvisioned() does not check wifi_ssid as provisioning indicator"


# ── Behavior 4: credsRead() defined ──────────────────────────────────────────

def test_creds_read_defined():
    assert re.search(r"\bcredsRead\s*\(", SOURCE), \
        "credsRead() not defined"


# ── Behavior 5: credsRead opens 'creds' in read-only mode ────────────────────

def test_creds_read_opens_creds_namespace_readonly():
    body = _fn_body("credsRead")
    assert 'prefs.begin("creds", true)' in body, \
        'credsRead() does not open "creds" namespace in read-only mode'


# ── Behavior 6: credsRead reads all three keys ───────────────────────────────

def test_creds_read_reads_all_three_keys():
    body = _fn_body("credsRead")
    for key in ("wifi_ssid", "wifi_pass", "device_token"):
        assert key in body, f'credsRead() does not read "{key}"'


# ── Behavior 7: credsWrite() defined ─────────────────────────────────────────

def test_creds_write_defined():
    assert re.search(r"\bcredsWrite\s*\(", SOURCE), \
        "credsWrite() not defined"


# ── Behavior 8: credsWrite opens 'creds' in write mode ───────────────────────

def test_creds_write_opens_creds_namespace_write():
    body = _fn_body("credsWrite")
    assert 'prefs.begin("creds", false)' in body, \
        'credsWrite() does not open "creds" namespace in write mode'


# ── Behavior 9: credsWrite writes all three keys ─────────────────────────────

def test_creds_write_writes_all_three_keys():
    body = _fn_body("credsWrite")
    for key in ("wifi_ssid", "wifi_pass", "device_token"):
        assert key in body, f'credsWrite() does not write "{key}"'


# ── Behavior 10: credsClear() defined ────────────────────────────────────────

def test_creds_clear_defined():
    assert re.search(r"\bcredsClear\s*\(", SOURCE), \
        "credsClear() not defined"


# ── Behavior 11: credsClear opens 'creds' in write mode ──────────────────────

def test_creds_clear_opens_creds_namespace_write():
    body = _fn_body("credsClear")
    assert 'prefs.begin("creds", false)' in body, \
        'credsClear() does not open "creds" namespace in write mode'


# ── Behavior 12: credsClear removes all three keys ───────────────────────────

def test_creds_clear_removes_all_three_keys():
    body = _fn_body("credsClear")
    for key in ("wifi_ssid", "wifi_pass", "device_token"):
        assert key in body, f'credsClear() does not remove "{key}"'


# ── Behavior 13: creds functions do not touch 'system' namespace ─────────────

def test_creds_functions_do_not_touch_system_namespace():
    section = _creds_section()
    assert '"system"' not in section, \
        'NVS CREDENTIALS section references the "system" namespace — must not touch txcount'


# ── Behavior 14: creds functions do not touch 'queue' namespace ──────────────

def test_creds_functions_do_not_touch_queue_namespace():
    section = _creds_section()
    assert '"queue"' not in section, \
        'NVS CREDENTIALS section references the "queue" namespace'
