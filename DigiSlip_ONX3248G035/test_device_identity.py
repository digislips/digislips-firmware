"""
Source-level tests for runtime device identity fetch — issue #19.

Verifies that DEVICE_ID, MERCHANT_ID, TILL_ID, and DEVICE_TOKEN compile-time
defines are gone, replaced by RAM globals populated from Supabase at boot.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")

EXAMPLE = Path(__file__).parent / "config.h.example"
EXAMPLE_TEXT = EXAMPLE.read_text(encoding="utf-8")


def _fetch_body():
    m = re.search(
        r"bool\s+fetchDeviceIdentity\s*\(.*?\)\s*\{(.*?)\n\}",
        SOURCE, re.DOTALL
    )
    assert m, "Could not locate fetchDeviceIdentity() body"
    return m.group(1)


def _setup_body():
    m = re.search(r"void\s+setup\s*\(\s*\)(.*?)(?=void\s+loop\s*\()", SOURCE, re.DOTALL)
    assert m, "Could not locate setup() body"
    return m.group(1)


def _build_json_body():
    m = re.search(r"String\s+buildSupabaseJSON\s*\(.*?\)(.*?)(?=\n// =)", SOURCE, re.DOTALL)
    assert m, "Could not locate buildSupabaseJSON() body"
    return m.group(1)


def _nfc_claim_body():
    m = re.search(r"bool\s+supabaseNfcClaim\s*\(.*?\)(.*?)(?=\n// =)", SOURCE, re.DOTALL)
    assert m, "Could not locate supabaseNfcClaim() body"
    return m.group(1)


def _provisioned_body():
    m = re.search(r"bool\s+credsAreProvisioned\s*\(\s*\)\s*\{(.*?)\n\}", SOURCE, re.DOTALL)
    assert m, "Could not locate credsAreProvisioned() body"
    return m.group(1)


# ── AC 1: compile-time defines gone from sketch ───────────────────────────────

def test_device_id_define_removed():
    assert "DEVICE_ID" not in SOURCE, \
        "DEVICE_ID still referenced in sketch — must use g_deviceId global"


def test_merchant_id_define_removed():
    assert "MERCHANT_ID" not in SOURCE, \
        "MERCHANT_ID still referenced in sketch — must use g_merchantId global"


def test_till_id_define_removed():
    assert "TILL_ID" not in SOURCE, \
        "TILL_ID still referenced in sketch — must use g_tillId global"


def test_device_token_define_removed():
    assert "DEVICE_TOKEN" not in SOURCE, \
        "DEVICE_TOKEN still referenced in sketch — must use g_deviceToken global"


# ── AC 2: RAM globals declared ───────────────────────────────────────────────

def test_g_device_id_declared():
    assert re.search(r"\bg_deviceId\b", SOURCE), "g_deviceId global not declared"


def test_g_merchant_id_declared():
    assert re.search(r"\bg_merchantId\b", SOURCE), "g_merchantId global not declared"


def test_g_till_id_declared():
    assert re.search(r"\bg_tillId\b", SOURCE), "g_tillId global not declared"


def test_g_device_token_declared():
    assert re.search(r"\bg_deviceToken\b", SOURCE), "g_deviceToken global not declared"


# ── AC 3: fetchDeviceIdentity() defined and queries devices table ─────────────

def test_fetch_device_identity_defined():
    assert re.search(r"\bbool\s+fetchDeviceIdentity\s*\(", SOURCE), \
        "fetchDeviceIdentity() not defined"


def test_fetch_queries_devices_table():
    body = _fetch_body()
    assert "/rest/v1/devices" in body, \
        "fetchDeviceIdentity() does not query /rest/v1/devices"


def test_fetch_filters_by_device_token():
    body = _fetch_body()
    assert "device_token" in body, \
        "fetchDeviceIdentity() does not filter by device_token"


# ── AC 4: fetch populates all three globals ───────────────────────────────────

def test_fetch_populates_globals():
    body = _fetch_body()
    for g in ("g_deviceId", "g_merchantId", "g_tillId"):
        assert g in body, f"fetchDeviceIdentity() does not populate {g}"


# ── AC 5: buildSupabaseJSON uses runtime globals ──────────────────────────────

def test_build_json_uses_g_device_id():
    body = _build_json_body()
    assert "g_deviceId" in body, \
        "buildSupabaseJSON() does not use g_deviceId"


def test_build_json_uses_g_merchant_id():
    body = _build_json_body()
    assert "g_merchantId" in body, \
        "buildSupabaseJSON() does not use g_merchantId"


# ── AC 6: supabaseNfcClaim uses g_deviceToken ─────────────────────────────────

def test_nfc_claim_uses_g_device_token():
    body = _nfc_claim_body()
    assert "g_deviceToken" in body, \
        "supabaseNfcClaim() does not use g_deviceToken"


# ── AC 7: setup() sets g_deviceToken from NVS creds ──────────────────────────

def test_setup_sets_g_device_token():
    body = _setup_body()
    assert "g_deviceToken" in body, \
        "setup() does not assign g_deviceToken from NVS credentials"


# ── AC 8: setup() calls fetchDeviceIdentity after WiFi connects ──────────────

def test_setup_calls_fetch_after_wifi():
    body = _setup_body()
    pos_wifi = body.find("WL_CONNECTED")
    pos_fetch = body.find("fetchDeviceIdentity(")
    assert pos_fetch != -1, "fetchDeviceIdentity() not called in setup()"
    assert pos_fetch > pos_wifi, \
        "fetchDeviceIdentity() must be called after WiFi connect in setup()"


# ── AC 9: setup() halts with error if fetch fails ────────────────────────────

def test_setup_halts_on_identity_error():
    body = _setup_body()
    m = re.search(
        r"fetchDeviceIdentity\s*\(.*?while\s*\(\s*true\s*\)",
        body, re.DOTALL
    )
    assert m, \
        "setup() does not halt with while(true) when fetchDeviceIdentity() fails"


# ── AC 10: credsAreProvisioned checks device_token as well ───────────────────

def test_creds_provisioned_checks_device_token():
    body = _provisioned_body()
    assert "device_token" in body, \
        "credsAreProvisioned() does not check device_token — missing token should trigger portal"


# ── AC 11: DEVICE_ID / MERCHANT_ID / TILL_ID / DEVICE_TOKEN removed from example

def test_defines_removed_from_example():
    for key in ("DEVICE_ID", "MERCHANT_ID", "TILL_ID", "DEVICE_TOKEN"):
        assert re.search(rf"#define\s+{key}\b", EXAMPLE_TEXT) is None, \
            f"{key} still in config.h.example"
