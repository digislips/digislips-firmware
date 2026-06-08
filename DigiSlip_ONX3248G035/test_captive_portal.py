"""
Source-level tests for captive portal provisioning — issue #18.

Verifies WiFiManager softAP setup, custom Device Token parameter,
credential persistence to NVS, reboot behaviour, and the 5-second
touch-hold re-provisioning trigger on the idle screen.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")


def _portal_body():
    m = re.search(r"void\s+startProvisioningPortal\s*\(\s*\)(.*?)(?=\n\S)", SOURCE, re.DOTALL)
    assert m, "Could not locate startProvisioningPortal() body"
    return m.group(1)


def _setup_body():
    m = re.search(r"void\s+setup\s*\(\s*\)(.*?)(?=void\s+loop\s*\()", SOURCE, re.DOTALL)
    assert m, "Could not locate setup() body"
    return m.group(1)


def _idle_state_body():
    m = re.search(r"case\s+STATE_IDLE\s*:(.*?)(?=case\s+STATE_|\bdefault\b)", SOURCE, re.DOTALL)
    assert m, "Could not locate STATE_IDLE body"
    return m.group(1)


# ── AC 1: WiFiManager.h included ─────────────────────────────────────────────

def test_wifi_manager_included():
    assert "#include <WiFiManager.h>" in SOURCE, \
        "WiFiManager.h not included in sketch"


# ── AC 2: startProvisioningPortal() defined ───────────────────────────────────

def test_start_provisioning_portal_defined():
    assert re.search(r"\bvoid\s+startProvisioningPortal\s*\(\s*\)", SOURCE), \
        "startProvisioningPortal() not defined"


# ── AC 3: displayProvisioningPortal() defined ─────────────────────────────────

def test_display_provisioning_portal_defined():
    assert re.search(r"\bvoid\s+displayProvisioningPortal\s*\(", SOURCE), \
        "displayProvisioningPortal() not defined"


# ── AC 4: AP name uses DigiSlips-Setup- prefix ────────────────────────────────

def test_ap_name_prefix():
    body = _portal_body()
    assert "DigiSlips-Setup-" in body, \
        "AP name does not use 'DigiSlips-Setup-' prefix"


# ── AC 5: AP name derived from MAC address ────────────────────────────────────

def test_ap_name_uses_mac():
    body = _portal_body()
    assert "macAddress" in body, \
        "AP name not derived from MAC address"


# ── AC 6: Device Token custom parameter added with key 'token' ───────────────

def test_device_token_custom_param():
    body = _portal_body()
    assert '"token"' in body, \
        "Device Token custom parameter (key 'token') not added to WiFiManager"


# ── AC 7: credsWrite() called inside portal to persist all three values ───────

def test_portal_calls_creds_write():
    body = _portal_body()
    assert "credsWrite(" in body, \
        "startProvisioningPortal() does not call credsWrite()"


# ── AC 8: ESP.restart() called after provisioning ────────────────────────────

def test_portal_restarts_after_provisioning():
    body = _portal_body()
    assert "ESP.restart()" in body, \
        "startProvisioningPortal() does not call ESP.restart()"


# ── AC 9: setup() calls startProvisioningPortal() when not provisioned ────────

def test_setup_calls_portal_when_not_provisioned():
    body = _setup_body()
    m = re.search(
        r"!credsAreProvisioned\s*\(\s*\).*?startProvisioningPortal\s*\(",
        body, re.DOTALL
    )
    assert m, \
        "setup() does not call startProvisioningPortal() when not provisioned"


# ── AC 10: 5 s touch hold in STATE_IDLE triggers credsClear + ESP.restart ─────

def test_idle_touch_hold_clears_creds_and_reboots():
    body = _idle_state_body()
    assert "5000" in body, \
        "5000 ms touch hold threshold not found in STATE_IDLE"
    assert "credsClear()" in body, \
        "credsClear() not called in 5 s touch hold branch of STATE_IDLE"
    assert "ESP.restart()" in body, \
        "ESP.restart() not called in 5 s touch hold branch of STATE_IDLE"
