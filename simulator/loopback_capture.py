"""
Loopback capture — measures how many bytes actually arrive from the DEVICE's
outgoing RS-232 port.

Purpose: the device forwards a full 6549-byte slip (confirmed in firmware logs),
but the printer only receives part of the logo bitmap. This script lets the
LAPTOP stand in for the printer so we can count the bytes that survive the
device's outgoing MAX232 driver + cable.

Wiring:
  Device OUTGOING port (the one that normally goes to the printer)
     --> regular RS-232 cable --> laptop USB-RS232 adapter (COM9)
  The device transmits on its TX line; the laptop must receive on its RX line.
  If you see "no data" below, add a null-modem (crossover) adapter between them
  so device-TX reaches adapter-RX (pins 2<->3 swapped). GND must be common.

Usage:
  1. Unplug the printer from the device's outgoing port.
  2. Connect the device's outgoing port to the laptop adapter (COM9).
  3. Close the main simulator (only one program can hold COM9).
  4. Run:  python simulator/loopback_capture.py
  5. When it says "Waiting for data", tap PRINT on the device for slip 7.
  6. Read the byte count it prints.
"""

import serial
import sys
import time

PORT      = sys.argv[1] if len(sys.argv) > 1 else "COM9"
BAUD      = 19200
EXPECTED  = 6549          # slip 7 full buffer size
OUT_FILE  = "loopback_capture.bin"
IDLE_END  = 3.0           # seconds of silence (after data starts) => transfer done
NO_DATA_TIMEOUT = 90.0    # give up if nothing arrives at all


def open_port(port: str, baud: int) -> serial.Serial:
    """CH340-safe open: start at 9600, swap to target baud on the live handle."""
    ser = serial.Serial(
        port     = port,
        baudrate = 9600,
        bytesize = serial.EIGHTBITS,
        parity   = serial.PARITY_NONE,
        stopbits = serial.STOPBITS_ONE,
        timeout  = 0.2,
        write_timeout = None,
        xonxoff  = False,
        rtscts   = False,
        dsrdtr   = False,
    )
    ser.dtr = False
    ser.rts = False
    ser.baudrate = baud
    time.sleep(0.05)
    return ser


def main() -> None:
    ser = open_port(PORT, BAUD)
    print(f"[CAP] Listening on {PORT} @ {BAUD} baud.")
    print("[CAP] Now tap PRINT on the device to send slip 7.")
    print("[CAP] Waiting for data...  (Ctrl+C to abort)")

    data = bytearray()
    last_rx = None
    start = time.time()

    while True:
        chunk = ser.read(4096)
        if chunk:
            if not data:
                print("[CAP] Receiving...")
            data += chunk
            last_rx = time.time()
        else:
            if last_rx is not None and (time.time() - last_rx) >= IDLE_END:
                break
            if last_rx is None and (time.time() - start) >= NO_DATA_TIMEOUT:
                print("[CAP] No data received. Check wiring — you likely need a")
                print("      null-modem (crossover) so device-TX reaches adapter-RX.")
                ser.close()
                return

    ser.close()

    with open(OUT_FILE, "wb") as f:
        f.write(data)

    print()
    print(f"[CAP] Received {len(data)} bytes  (expected {EXPECTED} for slip 7)")
    if len(data) == EXPECTED:
        print("[CAP] FULL - every byte crossed the outgoing link intact.")
        print("      The outgoing MAX232 driver is clean; the fault is the cable")
        print("      to the printer or the printer's own input. Look there next.")
    elif len(data) < EXPECTED:
        print(f"[CAP] SHORT by {EXPECTED - len(data)} bytes - the outgoing MAX232")
        print("      driver is dropping bytes under sustained load. Hardware fix:")
        print("      check charge-pump caps on the OUTGOING MAX232 (1uF for MAX232,")
        print("      0.1uF for MAX3232), solid common ground, shorter cable.")
    else:
        print(f"[CAP] LONGER than expected (+{len(data) - EXPECTED}) - likely line")
        print("      noise / framing junk on an idle floating input. Re-check wiring.")
    print(f"[CAP] Raw bytes saved to {OUT_FILE}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[CAP] Aborted.")
