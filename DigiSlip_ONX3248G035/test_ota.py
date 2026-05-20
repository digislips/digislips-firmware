"""
Source-level tests for OTA firmware update support (issue #11 + #12).

Parses DigiSlip_ONX3248G035.ino and verifies structural requirements
that would otherwise need hardware to observe.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")


def _check_ota_body():
    m = re.search(r"void\s+checkOTA\s*\(\s*\)(.*?)(?=\nvoid\s+\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate checkOTA() body"
    return m.group(1)


def _setup_body():
    m = re.search(r"void\s+setup\s*\(\s*\)(.*?)(?=void\s+loop\s*\()", SOURCE, re.DOTALL)
    assert m, "Could not locate setup() body"
    return m.group(1)


# =============================================================================
#  Issue #11 — checkOTA(): detect available firmware update
# =============================================================================

# ── Behavior 1: FIRMWARE_VERSION define ──────────────────────────────────────

def test_firmware_version_define_exists():
    assert re.search(r'#define\s+FIRMWARE_VERSION\s+"v\d+\.\d+\.\d+"', SOURCE), \
        'FIRMWARE_VERSION not defined or not in "vMAJOR.MINOR.PATCH" format'


# ── Behavior 2: root CA cert constant ────────────────────────────────────────

def test_root_ca_cert_constant_exists():
    assert "-----BEGIN CERTIFICATE-----" in SOURCE, \
        "Root CA PEM certificate not found in source"


# ── Behavior 3: checkOTA() function defined ───────────────────────────────────

def test_check_ota_defined():
    assert re.search(r"\bvoid\s+checkOTA\s*\(\s*\)", SOURCE), \
        "checkOTA() not defined"


# ── Behavior 4: checkOTA() called in setup() WiFi-connected branch ────────────

def test_check_ota_called_in_setup():
    setup = _setup_body()
    assert "checkOTA(" in setup, \
        "checkOTA() not called in setup()"


# ── Behavior 5: GitHub Releases API URL present ───────────────────────────────

def test_check_ota_uses_github_releases_api():
    body = _check_ota_body()
    assert "api.github.com" in body, \
        "GitHub Releases API URL not found in checkOTA()"
    assert "releases/latest" in body, \
        '"releases/latest" endpoint not found in checkOTA()'


# ── Behavior 6: asset filename referenced ────────────────────────────────────

def test_check_ota_references_bin_asset_name():
    body = _check_ota_body()
    assert "DigiSlip_ONX3248G035.bin" in body, \
        '"DigiSlip_ONX3248G035.bin" asset name not referenced in checkOTA()'


# ── Behavior 7: Serial log — up to date ──────────────────────────────────────

def test_check_ota_logs_up_to_date():
    body = _check_ota_body()
    assert "[OTA] Up to date" in body, \
        '"[OTA] Up to date" Serial log not found in checkOTA()'


# ── Behavior 8: Serial log — update available ────────────────────────────────

def test_check_ota_logs_update_available():
    body = _check_ota_body()
    assert "[OTA] Update available:" in body, \
        '"[OTA] Update available:" Serial log not found in checkOTA()'


# ── Behavior 9: Serial log — check failed ────────────────────────────────────

def test_check_ota_logs_check_failed():
    body = _check_ota_body()
    assert "[OTA] Check failed" in body, \
        '"[OTA] Check failed" Serial log not found in checkOTA()'


# =============================================================================
#  Issue #12 — applyOTA(): download, flash, boot screen progress
# =============================================================================

def _apply_ota_body():
    m = re.search(r"void\s+applyOTA\s*\(.*?\)(.*?)(?=\nvoid\s+\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate applyOTA() body"
    return m.group(1)


# ── Behavior 1: HTTPUpdate included ──────────────────────────────────────────

def test_http_update_included():
    assert "#include <HTTPUpdate.h>" in SOURCE, \
        "#include <HTTPUpdate.h> not found in includes"


# ── Behavior 2: applyOTA() defined ───────────────────────────────────────────

def test_apply_ota_defined():
    assert re.search(r"\bvoid\s+applyOTA\s*\(", SOURCE), \
        "applyOTA() not defined"


# ── Behavior 3: checkOTA() calls applyOTA() when update available ─────────────

def test_check_ota_calls_apply_ota():
    body = _check_ota_body()
    assert "applyOTA(" in body, \
        "checkOTA() does not call applyOTA() — stub not replaced"


# ── Behavior 4: applyOTA() drives bootProgress with UPDATING... ───────────────

def test_apply_ota_calls_boot_progress_updating():
    body = _apply_ota_body()
    assert "bootProgress(" in body, \
        "bootProgress() not called in applyOTA()"
    assert "UPDATING..." in body, \
        '"UPDATING..." message not found in applyOTA()'


# ── Behavior 5: applyOTA() calls httpUpdate.update() ─────────────────────────

def test_apply_ota_calls_http_update():
    body = _apply_ota_body()
    assert "httpUpdate.update(" in body, \
        "httpUpdate.update() not called in applyOTA()"


# ── Behavior 6: applyOTA() sets follow redirects ──────────────────────────────

def test_apply_ota_sets_follow_redirects():
    body = _apply_ota_body()
    assert "setFollowRedirects(" in body, \
        "setFollowRedirects() not called in applyOTA() — GitHub CDN redirects will fail"


# ── Behavior 7: Serial log — download start ──────────────────────────────────

def test_apply_ota_logs_downloading():
    body = _apply_ota_body()
    assert "[OTA] Downloading" in body, \
        '"[OTA] Downloading" Serial log not found in applyOTA()'


# ── Behavior 8: Serial log — update failed ───────────────────────────────────

def test_apply_ota_logs_update_failed():
    body = _apply_ota_body()
    assert "[OTA] Update failed" in body, \
        '"[OTA] Update failed" Serial log not found in applyOTA()'
