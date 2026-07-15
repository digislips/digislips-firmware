"""Thin dispatch wrapper so the demo GUI can send bytes and check connection
status without knowing which underlying driver (serial vs USB) is selected.

Neither Serial_RS232_Driver_v2.print_raw_serial nor USB_Only_Driver.print_raw_usb
raise or return a result on failure -- both just print an "[ERROR] ..." line and
return None, so their CLI behavior can stay untouched. This module captures that
printed output (while still echoing it through to the real stdout) and turns an
"[ERROR]" line into a raised TransportError, which is the only way the GUI can
tell success from failure.
"""

import contextlib
import io
import sys
from enum import Enum

import Serial_RS232_Driver_v2 as serial_driver
import USB_Only_Driver as usb_driver


class Transport(Enum):
    SERIAL = "serial"
    USB = "usb"


class TransportError(Exception):
    pass


def send(data: bytes, transport: Transport, port: str = serial_driver.SERIAL_PORT,
          baud: int = serial_driver.BAUD_RATE) -> None:
    """Send `data` over the selected transport. Raises TransportError on failure."""
    if transport is Transport.SERIAL:
        _run_and_check(serial_driver.print_raw_serial, data, port, baud)
    elif transport is Transport.USB:
        _run_and_check(usb_driver.print_raw_usb, data)
    else:
        raise TransportError(f"Unknown transport: {transport}")


def scan_serial_ports() -> list[str]:
    return serial_driver.find_serial_ports()


def usb_is_connected() -> bool:
    dev = usb_driver.usb.core.find(
        idVendor=usb_driver.USB_VENDOR_ID, idProduct=usb_driver.USB_PRODUCT_ID
    )
    return dev is not None


def _run_and_check(fn, *args) -> None:
    buf = io.StringIO()
    with contextlib.redirect_stdout(_Tee(sys.stdout, buf)):
        fn(*args)
    output = buf.getvalue()
    if "[ERROR]" in output:
        message = next((line for line in output.splitlines() if "[ERROR]" in line), output.strip())
        raise TransportError(message)


class _Tee(io.TextIOBase):
    """Writes to both a live stream and a capture buffer, so the driver's
    existing console output isn't swallowed while we inspect it for failure."""

    def __init__(self, live, capture):
        self._live = live
        self._capture = capture

    def write(self, s: str) -> int:
        self._live.write(s)
        return self._capture.write(s)

    def flush(self) -> None:
        self._live.flush()
