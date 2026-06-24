import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import Serial_RS232_Driver_v2 as sim

GS_V_0   = b'\x1d\x76\x30'
GS_K_128 = b'\x1d\x6b\x49'
CUT_FULL = b'\x1d\x56\x00'


def _capture_slip(fn) -> bytes:
    captured = []
    original = sim.print_raw_serial
    sim.print_raw_serial = lambda data, **kw: captured.append(data)
    try:
        fn()
    finally:
        sim.print_raw_serial = original
    return captured[0]


def test_slip_8_exists():
    assert hasattr(sim, 'slip_8_combined_test')


def test_slip_8_in_slips_registry():
    assert '8' in sim.SLIPS


def test_slip_8_sends_bytes():
    data = _capture_slip(sim.slip_8_combined_test)
    assert len(data) > 0


def test_slip_8_contains_logo():
    data = _capture_slip(sim.slip_8_combined_test)
    assert GS_V_0 in data


def test_slip_8_contains_barcode():
    data = _capture_slip(sim.slip_8_combined_test)
    assert GS_K_128 in data


def test_slip_8_logo_before_barcode():
    data = _capture_slip(sim.slip_8_combined_test)
    assert data.index(GS_V_0) < data.index(GS_K_128)


def test_slip_8_contains_store_name():
    data = _capture_slip(sim.slip_8_combined_test)
    assert b'CITY FRESH' in data


def test_slip_8_barcode_value():
    data = _capture_slip(sim.slip_8_combined_test)
    assert b'9782504938271' in data


def test_slip_8_ends_with_full_cut():
    data = _capture_slip(sim.slip_8_combined_test)
    assert data.endswith(CUT_FULL)


def test_slip_8_buffer_larger_than_slip_7():
    data_8 = _capture_slip(sim.slip_8_combined_test)
    data_7 = _capture_slip(sim.slip_7_logo_test)
    assert len(data_8) > len(data_7)
