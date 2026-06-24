"""
Source-level tests for raw_escpos base64 encoding in buildSupabaseJSON() (issue #23).
"""

import re
from pathlib import Path

INO    = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")


def _build_json_body():
    m = re.search(r"String\s+buildSupabaseJSON\s*\(.*?\)(.*?)(?=\n// =)", SOURCE, re.DOTALL)
    assert m, "Could not locate buildSupabaseJSON() body"
    return m.group(1)


def test_mbedtls_base64_included():
    assert "#include <mbedtls/base64.h>" in SOURCE, \
        "mbedtls/base64.h not included in sketch"


def test_build_json_doc_size_16384():
    body = _build_json_body()
    assert "DynamicJsonDocument doc(16384)" in body, \
        "buildSupabaseJSON() must use DynamicJsonDocument(16384) to fit base64 payload"


def test_build_json_calls_mbedtls_base64_encode():
    body = _build_json_body()
    assert "mbedtls_base64_encode" in body, \
        "buildSupabaseJSON() does not call mbedtls_base64_encode"


def test_build_json_encodes_print_buffer():
    body = _build_json_body()
    assert "printBuffer" in body, \
        "buildSupabaseJSON() does not pass printBuffer to mbedtls_base64_encode"


def test_build_json_uses_print_buffer_len():
    body = _build_json_body()
    assert "printBufferLen" in body, \
        "buildSupabaseJSON() does not use printBufferLen as the encode length"


def test_build_json_sets_raw_escpos():
    body = _build_json_body()
    assert 'doc["raw_escpos"]' in body, \
        'buildSupabaseJSON() does not set doc["raw_escpos"]'
