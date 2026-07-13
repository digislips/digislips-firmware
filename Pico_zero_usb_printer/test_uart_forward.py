"""
Source-level tests for the RP2040-Zero -> ESP32-S3 UART forward path.

Parses Pico_zero_usb_printer.ino and verifies structural requirements that
would otherwise need hardware (real UART timing, real tud_vendor_read()) to
observe -- same pattern as DigiSlip_ONX3248G035/test_ota.py.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "Pico_zero_usb_printer.ino"
SOURCE = INO.read_text(encoding="utf-8")


def _setup_body():
    m = re.search(r"void\s+setup\s*\(\s*\)(.*?)(?=\nvoid\s+loop\s*\()", SOURCE, re.DOTALL)
    assert m, "Could not locate setup() body"
    return m.group(1)


# =============================================================================
#  UART0 (Serial1) pin configuration — GP28 TX -> ESP32 IO12, simplex
# =============================================================================

def test_serial1_tx_set_to_gp28():
    setup = _setup_body()
    assert re.search(r"Serial1\.setTX\(\s*28\s*\)", setup), \
        "Serial1 TX not set to GP28 in setup()"


def test_serial1_rx_set_to_gp29():
    setup = _setup_body()
    assert re.search(r"Serial1\.setRX\(\s*29\s*\)", setup), \
        "Serial1 RX not set to GP29 in setup()"


def test_serial1_fifo_sized_to_hold_a_full_job():
    setup = _setup_body()
    m = re.search(r"Serial1\.setFIFOSize\(\s*(\w+)\s*\)", setup)
    assert m, "Serial1 FIFO size not configured in setup()"
    size_token = m.group(1)
    size = int(size_token) if size_token.isdigit() else None
    assert size_token == "RX_BUFFER_SIZE" or (size is not None and size >= 8192), \
        "Serial1 FIFO must be sized to hold a full job (>= RX_BUFFER_SIZE) or " \
        "it will block mid-transfer once the default 32-byte buffer fills"


def test_serial1_begin_matches_posserial_baud_and_framing():
    setup = _setup_body()
    assert re.search(r"Serial1\.begin\(\s*19200\s*(,\s*SERIAL_8N1\s*)?\)", setup), \
        "Serial1 must be started at 19200 baud (8N1 default) to match the " \
        "ESP32's posSerial.begin(19200, SERIAL_8N1, ...)"


# =============================================================================
#  Forward path — every USB chunk streamed to Serial1 as it arrives,
#  independent of the RX_SILENCE_MS debug-buffering timeout
# =============================================================================

def _vendor_drain_loop_body():
    m = re.search(
        r"while\s*\(\s*tud_vendor_available\(\).*?\)\s*\{(.*?)\n  \}",
        SOURCE, re.DOTALL,
    )
    assert m, "Could not locate the tud_vendor_available() drain while-loop"
    return m.group(1)


def test_every_usb_chunk_forwarded_to_serial1_in_drain_loop():
    drain_body = _vendor_drain_loop_body()
    assert re.search(r"Serial1\.write\(", drain_body), \
        "Serial1.write() must be called inside the tud_vendor_read() drain " \
        "loop so bytes stream to the ESP32 as they arrive, not gated behind " \
        "the RX_SILENCE_MS debug-buffering timeout"


def _silence_gated_body():
    m = re.search(
        r"if\s*\(\s*rxLen > 0 && millis\(\) - lastByteTime >= RX_SILENCE_MS\s*\)\s*\{(.*?)\n  \}",
        SOURCE, re.DOTALL,
    )
    assert m, "Could not locate the RX_SILENCE_MS-gated debug/parse block"
    return m.group(1)


def test_silence_gated_debug_parse_path_untouched():
    debug_body = _silence_gated_body()
    assert "printHexDump(" in debug_body and "parseESCPOS(" in debug_body, \
        "The RX_SILENCE_MS-gated block must remain a passive CDC debug tap " \
        "(hex dump + parseESCPOS) — it must not gate or absorb the new " \
        "Serial1 forward path"
    assert "Serial1.write(" not in debug_body, \
        "Forwarding must happen in the drain loop as bytes arrive, not " \
        "here — this block should stay silence-gated debug-only"
