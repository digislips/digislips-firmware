"""
Source-level tests for device-side UUID generation and return=minimal POST (issue #6).

Parses DigiSlip_ONX3248G035.ino and verifies structural requirements
that would otherwise need hardware to observe.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")


def _generate_uuid_body():
    m = re.search(r"String\s+generateUUID\s*\(\s*\)(.*?)(?=\n\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate generateUUID() body"
    return m.group(1)


def _build_supabase_json_signature():
    m = re.search(r"String\s+buildSupabaseJSON\s*\(([^)]*)\)", SOURCE)
    assert m, "Could not locate buildSupabaseJSON() signature"
    return m.group(1)


def _build_supabase_json_body():
    m = re.search(r"String\s+buildSupabaseJSON\s*\(.*?\)(.*?)(?=\n// =)", SOURCE, re.DOTALL)
    assert m, "Could not locate buildSupabaseJSON() body"
    return m.group(1)


def _supabase_post_body():
    m = re.search(r"String\s+supabasePost\s*\(.*?\)(.*?)(?=\n// =)", SOURCE, re.DOTALL)
    assert m, "Could not locate supabasePost() body"
    return m.group(1)


def _state_uploading_body():
    m = re.search(r"case STATE_UPLOADING:\s*\{(.*?)\}", SOURCE, re.DOTALL)
    assert m, "Could not locate STATE_UPLOADING block"
    return m.group(1)


# =============================================================================
#  Behavior 1: generateUUID() function is defined
# =============================================================================

def test_generate_uuid_defined():
    assert re.search(r"\bString\s+generateUUID\s*\(\s*\)", SOURCE), \
        "generateUUID() function not defined"


# =============================================================================
#  Behavior 2: generateUUID() uses esp_random() for entropy
# =============================================================================

def test_generate_uuid_uses_esp_random():
    body = _generate_uuid_body()
    assert "esp_random()" in body, \
        "generateUUID() does not use esp_random() for entropy"


# =============================================================================
#  Behavior 3: generateUUID() sets the version 4 bits (| 0x40)
# =============================================================================

def test_generate_uuid_sets_version_bits():
    body = _generate_uuid_body()
    assert "0x40" in body, \
        "generateUUID() does not set version 4 bits (| 0x40)"


# =============================================================================
#  Behavior 4: generateUUID() sets the RFC 4122 variant bits (| 0x80)
# =============================================================================

def test_generate_uuid_sets_variant_bits():
    body = _generate_uuid_body()
    assert "0x80" in body, \
        "generateUUID() does not set RFC 4122 variant bits (| 0x80)"


# =============================================================================
#  Behavior 5: generateUUID() uses a 37-byte buffer (36 UUID chars + null)
# =============================================================================

def test_generate_uuid_buffer_size():
    body = _generate_uuid_body()
    assert "snprintf" in body, \
        "generateUUID() does not use snprintf for UUID formatting"
    assert "buf[37]" in body, \
        "generateUUID() buffer is not 37 bytes — UUID is 36 chars + null terminator"


# =============================================================================
#  Behavior 6: buildSupabaseJSON() accepts a uuid parameter (second parameter)
# =============================================================================

def test_build_supabase_json_accepts_uuid_param():
    sig = _build_supabase_json_signature()
    # Expect two parameters — timestamp and uuid
    assert sig.count(",") >= 1, \
        "buildSupabaseJSON() does not have a second (uuid) parameter"
    assert "uuid" in sig, \
        'buildSupabaseJSON() signature does not include a "uuid" parameter'


# =============================================================================
#  Behavior 7: buildSupabaseJSON() embeds "id" in the JSON document
# =============================================================================

def test_build_supabase_json_embeds_id():
    body = _build_supabase_json_body()
    assert re.search(r'doc\["id"\]', body), \
        'buildSupabaseJSON() does not set doc["id"] in the JSON document'


# =============================================================================
#  Behavior 8: supabasePost() sends return=minimal (not return=representation)
# =============================================================================

def test_supabase_post_sends_return_minimal():
    body = _supabase_post_body()
    assert "return=minimal" in body, \
        'supabasePost() does not send "Prefer: return=minimal"'


# =============================================================================
#  Behavior 9: supabasePost() does NOT reference return=representation anywhere
# =============================================================================

def test_supabase_post_no_return_representation():
    body = _supabase_post_body()
    assert "return=representation" not in body, \
        'supabasePost() still references "return=representation" — not fully replaced'


# =============================================================================
#  Behavior 10: supabasePost() reads the ID from the input JSON (doc["id"])
# =============================================================================

def test_supabase_post_reads_id_from_input_json():
    body = _supabase_post_body()
    assert re.search(r'doc\["id"\]', body), \
        'supabasePost() does not parse doc["id"] from the input JSON to obtain the slip ID'


# =============================================================================
#  Behavior 11: STATE_UPLOADING calls generateUUID() before buildSupabaseJSON()
# =============================================================================

def test_state_uploading_calls_generate_uuid_before_build_json():
    body = _state_uploading_body()
    pos_uuid = body.find("generateUUID()")
    pos_build = body.find("buildSupabaseJSON(")
    assert pos_uuid != -1, \
        "STATE_UPLOADING block does not call generateUUID()"
    assert pos_build != -1, \
        "STATE_UPLOADING block does not call buildSupabaseJSON()"
    assert pos_uuid < pos_build, \
        "STATE_UPLOADING: generateUUID() must be called before buildSupabaseJSON()"
