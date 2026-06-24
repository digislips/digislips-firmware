import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from Serial_RS232_Driver_v2 import Receipt


def test_barcode_returns_self():
    r = Receipt()
    assert r.barcode("TEST") is r


def test_barcode_emits_gs_k():
    data = Receipt().barcode("TEST").build()
    assert b'\x1d\x6b' in data


def test_barcode_code128_type_byte():
    data = Receipt().barcode("TEST").build()
    assert b'\x1d\x6b\x49' in data


def test_barcode_length_byte_is_value_plus_two():
    # "{B" prefix = 2 bytes; "HELLO" = 5 bytes; n = 7
    data = Receipt().barcode("HELLO").build()
    assert b'\x1d\x6b\x49\x07' in data


def test_barcode_code_set_b_prefix():
    # '{' = 0x7b, 'B' = 0x42
    data = Receipt().barcode("TEST").build()
    assert b'\x7b\x42' in data


def test_barcode_value_ascii_encoded():
    data = Receipt().barcode("ABC123").build()
    assert b'ABC123' in data


def test_barcode_hri_below():
    # GS H 2 = print human-readable text below barcode
    data = Receipt().barcode("TEST").build()
    assert b'\x1d\x48\x02' in data


def test_barcode_height_set():
    # GS h 80 = barcode height 80 dots
    data = Receipt().barcode("TEST").build()
    assert b'\x1d\x68\x50' in data


def test_slip_6_contains_barcode():
    import Serial_RS232_Driver_v2 as sim
    assert hasattr(sim, 'slip_6_barcode_test')
    # Capture the bytes by monkey-patching print_raw_serial
    captured = []
    original = sim.print_raw_serial
    sim.print_raw_serial = lambda data, **kw: captured.append(data)
    try:
        sim.slip_6_barcode_test()
    finally:
        sim.print_raw_serial = original
    assert captured, "slip_6_barcode_test did not send any bytes"
    assert b'\x1d\x6b' in captured[0]
