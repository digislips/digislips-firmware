"""
Source-level tests for supabaseIsClaimed() — issue #7.

Verifies that the function calls the get-slip Edge Function instead of
the Data API after the anon_select_slips RLS policy was removed.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "DigiSlip_ONX3248G035.ino"
SOURCE = INO.read_text(encoding="utf-8")


def _is_claimed_body():
    m = re.search(r"bool\s+supabaseIsClaimed\s*\(.*?\)(.*?)(?=\n\w)", SOURCE, re.DOTALL)
    assert m, "Could not locate supabaseIsClaimed() body"
    return m.group(1)


# =============================================================================
#  Behavior 1: uses the get-slip Edge Function path
# =============================================================================

def test_uses_edge_function_path():
    body = _is_claimed_body()
    assert "/functions/v1/get-slip" in body, \
        "supabaseIsClaimed() does not use the /functions/v1/get-slip Edge Function path"


# =============================================================================
#  Behavior 2: does NOT use the Data API path
# =============================================================================

def test_does_not_use_data_api_path():
    body = _is_claimed_body()
    assert "/rest/v1/slips" not in body, \
        "supabaseIsClaimed() still references the /rest/v1/slips Data API path"


# =============================================================================
#  Behavior 3: does NOT send an apikey header
# =============================================================================

def test_no_apikey_header():
    body = _is_claimed_body()
    assert '"apikey"' not in body, \
        'supabaseIsClaimed() still sends an "apikey" header'


# =============================================================================
#  Behavior 4: does NOT send an Authorization header
# =============================================================================

def test_no_authorization_header():
    body = _is_claimed_body()
    assert '"Authorization"' not in body, \
        'supabaseIsClaimed() still sends an "Authorization" header'


# =============================================================================
#  Behavior 5: parses doc["claimed"] (plain object, not array index 0)
# =============================================================================

def test_parses_plain_object_claimed():
    body = _is_claimed_body()
    assert 'doc["claimed"]' in body, \
        'supabaseIsClaimed() does not parse doc["claimed"] from a plain JSON object'


# =============================================================================
#  Behavior 6: does NOT reference doc[0] anywhere in its body
# =============================================================================

def test_no_doc_array_index():
    body = _is_claimed_body()
    assert "doc[0]" not in body, \
        "supabaseIsClaimed() still references doc[0] (array response); should parse plain object"


# =============================================================================
#  Behavior 7: still logs [Poll] claimed= to Serial
# =============================================================================

def test_logs_poll_claimed():
    body = _is_claimed_body()
    assert "[Poll] claimed=" in body, \
        'supabaseIsClaimed() does not log "[Poll] claimed=" to Serial'
