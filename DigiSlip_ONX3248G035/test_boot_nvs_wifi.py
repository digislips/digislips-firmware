"""
Source-level tests for NVS-backed WiFi boot — issue #17.

Verifies that WIFI_SSID / WIFI_PASSWORD compile-time constants are gone,
setup() reads credentials from NVS, shows a setup-needed screen and halts
if empty, and wifiWatchdog() reconnects using NVS credentials.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")

CONFIG_H = Path(__file__).parent / "config.h"
CONFIG_H_TEXT = CONFIG_H.read_text(encoding="utf-8")


def _setup_body():
    m = re.search(r"void\s+setup\s*\(\s*\)(.*?)(?=void\s+loop\s*\()", SOURCE, re.DOTALL)
    assert m, "Could not locate setup() body"
    return m.group(1)


def _watchdog_body():
    m = re.search(r"void\s+wifiWatchdog\s*\(\s*\)(.*?)(?=\n\S)", SOURCE, re.DOTALL)
    assert m, "Could not locate wifiWatchdog() body"
    return m.group(1)


# ── AC 1: WIFI_SSID macro gone from sketch ────────────────────────────────────

def test_wifi_ssid_removed_from_sketch():
    assert "WIFI_SSID" not in SOURCE, \
        "WIFI_SSID still referenced in sketch — must use NVS"


# ── AC 2: WIFI_PASSWORD macro gone from sketch ────────────────────────────────

def test_wifi_password_removed_from_sketch():
    assert "WIFI_PASSWORD" not in SOURCE, \
        "WIFI_PASSWORD still referenced in sketch — must use NVS"


# ── AC 3: No WiFi.begin with hardcoded credential constants ──────────────────

def test_no_hardcoded_wifi_begin():
    assert "WiFi.begin(WIFI_SSID" not in SOURCE, \
        "WiFi.begin(WIFI_SSID, ...) still in sketch"


# ── AC 4: displaySetupNeeded() defined ───────────────────────────────────────

def test_display_setup_needed_defined():
    assert re.search(r"\bvoid\s+displaySetupNeeded\s*\(\s*\)", SOURCE), \
        "displaySetupNeeded() not defined"


# ── AC 5: setup() calls credsAreProvisioned() before WiFi.begin ──────────────

def test_setup_checks_provisioning_before_wifi():
    body = _setup_body()
    pos_check = body.find("credsAreProvisioned()")
    pos_wifi  = body.find("WiFi.begin(")
    assert pos_check != -1, "credsAreProvisioned() not called in setup()"
    assert pos_wifi  != -1, "WiFi.begin() not found in setup()"
    assert pos_check < pos_wifi, \
        "credsAreProvisioned() must be called before WiFi.begin() in setup()"


# ── AC 6: setup() starts captive portal when not provisioned (not a bare halt) ─

def test_setup_starts_portal_when_empty():
    body = _setup_body()
    assert "startProvisioningPortal()" in body, \
        "setup() does not call startProvisioningPortal() when creds are empty"


# ── AC 7: setup() loads NVS creds before WiFi.begin ──────────────────────────

def test_setup_loads_nvs_creds():
    body = _setup_body()
    assert "credsRead()" in body, \
        "setup() does not call credsRead() to load WiFi credentials from NVS"


# ── AC 8: wifiWatchdog reconnects using NVS credentials ──────────────────────

def test_watchdog_uses_nvs_creds_for_reconnect():
    body = _watchdog_body()
    assert "wifi_ssid" in body or "credsRead()" in body, \
        "wifiWatchdog() does not use NVS credentials for WiFi reconnect"


# ── AC 9: WIFI_SSID absent from config.h ─────────────────────────────────────

def test_wifi_ssid_removed_from_config_h():
    assert re.search(r"#define\s+WIFI_SSID\b", CONFIG_H_TEXT) is None, \
        "WIFI_SSID still in config.h"


# ── AC 10: WIFI_PASSWORD absent from config.h ────────────────────────────────

def test_wifi_password_removed_from_config_h():
    assert re.search(r"#define\s+WIFI_PASSWORD\b", CONFIG_H_TEXT) is None, \
        "WIFI_PASSWORD still in config.h"
