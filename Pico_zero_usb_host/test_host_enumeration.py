"""
Source-level tests for the RP2040-Zero USB-host spike firmware.

Parses Pico_zero_usb_host.ino and verifies structural requirements that
would otherwise need hardware (real TinyUSB host-mode enumeration, a real
printer plugged in) to observe -- same pattern as
Pico_zero_usb_printer/test_uart_forward.py and DigiSlip_ONX3248G035/test_ota.py.
"""

import re
from pathlib import Path

INO = Path(__file__).parent / "Pico_zero_usb_host.ino"
SOURCE = INO.read_text(encoding="utf-8")


def _function_body(name):
    m = re.search(r"void\s+" + name + r"\s*\([^)]*\)\s*\{(.*?)\n\}", SOURCE, re.DOTALL)
    assert m, f"Could not locate {name}() body"
    return m.group(1)


# =============================================================================
#  Compile-time guard -- fail loud if built with the wrong USB Stack menu
# =============================================================================

def test_fails_fast_if_not_built_as_tinyusb_host():
    assert re.search(r"#ifndef\s+USE_TINYUSB_HOST", SOURCE), \
        "Sketch must #error out if Tools -> USB Stack isn't set to " \
        "'Adafruit TinyUSB Host' -- otherwise it silently compiles as a " \
        "device-mode sketch and nothing in this file makes sense"
    assert "#error" in SOURCE


# =============================================================================
#  Debug output -- Serial1 (UART), since native USB is now the host port
# =============================================================================

def test_serial1_used_for_debug_not_native_serial():
    setup = _function_body("setup")
    assert "Serial1.begin(" in setup, \
        "Debug output must go over Serial1 (UART) -- native USB is the " \
        "host connection to the printer now, there's no CDC to print to"
    assert re.search(r"(?<!1)\bSerial\.begin\(", SOURCE) is None, \
        "Native Serial (CDC) is not available in host mode -- don't call " \
        "Serial.begin()"


def test_serial1_pins_set_to_gp28_gp29():
    setup = _function_body("setup")
    assert re.search(r"Serial1\.setTX\(\s*28\s*\)", setup), \
        "Serial1 TX must be set to GP28 -- the board's stock default " \
        "(GP0/GP1) didn't work on the bench; GP28/29 is the known-good " \
        "pair already proven on the device-bridge board"
    assert re.search(r"Serial1\.setRX\(\s*29\s*\)", setup), \
        "Serial1 RX must be set to GP29"
    tx_pos = setup.index("Serial1.setTX(")
    begin_pos = setup.index("Serial1.begin(")
    assert tx_pos < begin_pos, \
        "setTX()/setRX() must be called before Serial1.begin()"


def test_serial1_begins_at_9600():
    setup = _function_body("setup")
    assert re.search(r"Serial1\.begin\(\s*9600\s*\)", setup), \
        "Serial1 should start at 9600 -- lowered from 115200 to rule out " \
        "baud-related issues while debugging the CH340 RS232 link"


# =============================================================================
#  USB host init/task wiring
# =============================================================================

def test_usbhost_object_declared():
    assert re.search(r"Adafruit_USBH_Host\s+USBHost\s*;", SOURCE), \
        "Must declare a global Adafruit_USBH_Host USBHost object"


def test_usbhost_begins_on_native_rhport0_in_setup():
    setup = _function_body("setup")
    assert re.search(r"USBHost\.begin\(\s*0\s*\)", setup), \
        "USBHost.begin(0) must be called in setup() to init the host " \
        "stack on the native roothub port"


def test_usbhost_task_polled_every_loop():
    loop = _function_body("loop")
    assert "USBHost.task()" in loop, \
        "USBHost.task() must be called every loop() iteration to pump the " \
        "TinyUSB host stack"


# =============================================================================
#  Device enumeration -- tuh_mount_cb fetches + prints the device descriptor
# =============================================================================

def test_known_printer_vid_pid_constants_defined():
    assert re.search(r"#define\s+PRINTER_VID\s+0x1FC9", SOURCE, re.IGNORECASE), \
        "PRINTER_VID must be #defined as 0x1FC9 (not just mentioned in a " \
        "comment) so it can actually be compared against in code"
    assert re.search(r"#define\s+PRINTER_PID\s+0x2016", SOURCE, re.IGNORECASE), \
        "PRINTER_PID must be #defined as 0x2016 (not just mentioned in a " \
        "comment) so it can actually be compared against in code"


def test_mount_cb_fetches_device_descriptor():
    mount = _function_body("tuh_mount_cb")
    assert "tuh_descriptor_get_device_sync(" in mount, \
        "tuh_mount_cb() must fetch the device descriptor via " \
        "tuh_descriptor_get_device_sync() so VID/PID/class can be printed"


def test_mount_cb_highlights_known_printer_match():
    mount = _function_body("tuh_mount_cb")
    assert re.search(r"idVendor\s*==\s*PRINTER_VID", mount) or \
           re.search(r"PRINTER_VID\s*==.*idVendor", mount), \
        "tuh_mount_cb() must compare the enumerated device's idVendor " \
        "against the known printer VID and print a clear match/no-match " \
        "line -- this is the whole point of the spike"


# =============================================================================
#  Configuration descriptor -- two-step fetch (9-byte header for
#  wTotalLength, then a full-length fetch), since the true size isn't known
#  up front
# =============================================================================

def _print_config_descriptor_body():
    return _function_body("print_config_descriptor")


def test_config_descriptor_header_fetched_first():
    body = _print_config_descriptor_body()
    assert re.search(
        r"tuh_descriptor_get_configuration_sync\(\s*daddr\s*,\s*0\s*,\s*&?\w+\s*,\s*sizeof\(\s*tusb_desc_configuration_t\s*\)\s*\)",
        body,
    ), \
        "Must first fetch just the 9-byte configuration descriptor header " \
        "(sizeof(tusb_desc_configuration_t)) to read wTotalLength -- the " \
        "real total size (interfaces + endpoints) isn't known up front"


def test_config_descriptor_full_fetch_uses_wtotallength():
    body = _print_config_descriptor_body()
    m = re.search(r"(\w+)\s*=\s*\w+->wTotalLength\s*;", body)
    assert m, \
        "wTotalLength from the header fetch must be captured into a " \
        "variable so the real total size can be requested"
    len_var = m.group(1)

    calls = re.findall(
        r"tuh_descriptor_get_configuration_sync\(\s*daddr\s*,\s*0\s*,\s*\w+\s*,\s*([^)]+)\)",
        body,
    )
    assert len(calls) == 2, \
        "Expected exactly two tuh_descriptor_get_configuration_sync() calls " \
        "(header probe, then full fetch)"
    assert len_var in calls[1] and "sizeof" not in calls[1], \
        "Second fetch must request a length derived from wTotalLength " \
        f"(variable '{len_var}'), not just the 9-byte header size again"


def test_mount_cb_calls_print_config_descriptor():
    mount = _function_body("tuh_mount_cb")
    assert "print_config_descriptor(daddr)" in mount, \
        "tuh_mount_cb() must call print_config_descriptor(daddr) after the " \
        "device descriptor so interfaces/endpoints are dumped too"


# =============================================================================
#  Device removal
# =============================================================================

def test_umount_cb_logs_removal():
    umount = _function_body("tuh_umount_cb")
    assert "Serial1.print" in umount, \
        "tuh_umount_cb() must log the disconnect over Serial1 -- otherwise " \
        "an unplug during the bench test looks identical to a hang"
