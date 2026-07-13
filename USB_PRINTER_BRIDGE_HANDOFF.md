# USB printer-bridge handoff — RP2040-Zero POS-facing firmware

**Last updated:** 2026-07-13
**Status:** POS-facing bridge board firmware **hardware-confirmed working** at its current scope (standalone USB enumeration + bulk-OUT capture). ESP32-S3 UART integration **not started**.

---

## TL;DR

The RP2040-Zero ("Pico Zero") now runs firmware that enumerates as a composite USB device — a CDC serial port (for debug output) plus a vendor-class (FFh) bulk endpoint that exactly mirrors the real thermal printer's USB identity (VID `0x1FC9` / PID `0x2016`). `simulator/USB_Only_Driver.py`, pointed at the board instead of the real printer, successfully sent a 206-byte ESC/POS test receipt; the board buffered it, stripped the ESC/GS control codes, and printed the extracted text lines to the Serial Monitor — proving the whole POS→bridge-board pipe works.

**Two real toolchain/OS problems were hit and solved** (not obvious, worth reading before repeating this on a second board): the Arduino IDE cannot build this firmware at all (needs `arduino-cli` + a specific build flag), and reusing the real printer's VID/PID broke Windows driver binding until Zadig was re-run per-interface. Both are detailed below.

**Not yet done:** forwarding the captured bytes over UART to the ESP32-S3 main board. That's the next milestone and needs its own design pass (which GPIOs, what data path) — see "Next steps."

---

## Project context

**Repo:** `digislips/digislips-firmware` (local: `C:\Users\SOMO-CAD\Documents\digislip-firmware`)

**Why this exists:** the ONX3248G035 main board's only USB-C port is hard-wired to a CH340K bridge into UART0 (flash/debug only) — the ESP32-S3's native USB pins are physically unrouted on this board. It can never act as a USB device itself. The plan is a 3-node USB bridge chain:

```
POS (Host) --USB--> [RP2040-Zero, USB device]  --UART-->  ESP32-S3 main board  --SPI/UART-->  [host board, USB host]  --USB-->  Printer
                     ^^^^ this document ^^^^                (unchanged)              (separate, undesigned)
```

Full architecture options/reasoning: see memory `project_usb_printer_bridge_architecture` (or ask for it — this doc only covers the RP2040-Zero firmware built this session).

---

## What was built

### Files
- **`Pico_zero_usb_printer/Pico_zero_usb_printer.ino`** — the firmware.
- **`Pico_zero_usb_printer/tusb_config_override.h`** — TinyUSB config override (see toolchain section).
- **`Pico_zero_usb_printer/build.ps1`** — compile/upload wrapper. **Must be used instead of the Arduino IDE** (see below).
- **`simulator/USB_Only_Driver.py`** — copied in from `Dropbox\zDump Site\KSC\Joe 1\Digi slip python code\USB_Only_Driver.py` (original left in place there). This is the tool that originally proved the real printer's USB identity (VID/PID, vendor class, no Windows print spooler involved) — it's what let us build an exact software mimic before any physical printer access was needed for bench testing.
- **`Pico_zero_test/Pico_zero_test.ino`** — the earlier plain-CDC echo test (first proof the board/toolchain could flash at all). Superseded by the above for USB-bridge purposes but kept as a minimal known-good reference.

### Design decisions (from a `/grill-me` session this same day)
1. **Vendor-class FFh persona first, not Printer-class 07h.** The architecture memory's long-term plan was a jumper-selectable dual persona; we deferred that and built only the FFh path, because it has an immediate known-good validation tool (`USB_Only_Driver.py`) whereas 07h would need the real POS to test against.
2. **Reused the real printer's exact VID `0x1FC9` / PID `0x2016`** rather than a placeholder ID — closer simulation of the real device, and (in theory) reuses Windows' existing WinUSB driver association. In practice this caused the driver conflict documented below — a real cost of this decision, not just a theoretical one.
3. **Composite USB device** (CDC + Vendor on one physical connection), modeled on Adafruit_TinyUSB_Arduino's bundled `examples/Vendor/i2c_tiny_usb_adapter` — custom `Adafruit_USBD_Interface` subclass + `TinyUSBDevice.addInterface()` + a detach/attach re-enumerate call in `setup()`.
4. **Firmware logic reuses `DigiSlip_ONX3248G035.ino`'s `escParamBytes()`/`parseESCPOS()` verbatim**, plus its `STATE_BUFFERING`-style silence-timeout accumulation pattern (ported to 50ms instead of 500ms, and driven by `tud_vendor_available()` instead of `posSerial.available()`), so debug output (`[USB] N bytes received` → `[Parser] Extracted N lines`) is directly comparable to what the ESP32 firmware already logs for the same kind of data.

---

## Toolchain problem #1 — Arduino IDE cannot build this firmware

**Symptom this would produce if attempted:** compile errors like `'tud_vendor_available' was not declared in this scope`.

**Root cause:** arduino-pico's core hardcodes `CFG_TUD_VENDOR` to `0` in `packages/rp2040/hardware/rp2040/<ver>/include/tusb_config.h`, with **no `#ifndef` guard** — unlike SAMD/nRF52 Adafruit_TinyUSB ports, RP2040's "built-in support" routes through this one global, non-overridable file shared by every RP2040 sketch on the machine. A sketch-level `#define CFG_TUD_VENDOR 1` before `#include <Adafruit_TinyUSB.h>` does **not** work — `vendor_device.c` etc. are compiled as separate translation units by the core library using the core's own `tusb_config.h`, unaffected by anything the `.ino` preprocessor sees.

**The fix:** TinyUSB's `tusb_option.h` checks `#ifdef CFG_TUSB_CONFIG_FILE` *before* falling back to the per-MCU default (true for every MCU except ESP32, which has a special case). So:
1. `tusb_config_override.h` in the sketch folder — a **full replacement** of the config (not additive), with `CFG_TUD_CDC=1` and `CFG_TUD_VENDOR=1`, everything else off (HID/MSC/MIDI/NCM not needed).
2. Build with `compiler.c.extra_flags` **and** `compiler.cpp.extra_flags` (TinyUSB has both .c and .cpp sources) set to:
   ```
   -I"<sketch folder>" -DCFG_TUSB_CONFIG_FILE=\"tusb_config_override.h\"
   ```
   The `-I` is required too — the sketch folder is only automatically on the include path for the `.ino` itself, not for library-internal sources, so without it the flag resolves to nothing and you get `fatal error: tusb_config_override.h: No such file or directory`.
3. This requires **`arduino-cli`** — the Arduino IDE has no UI for per-sketch extra build flags. Installed this session via `winget install --id ArduinoSA.CLI`; lives at `C:\Program Files\Arduino CLI\arduino-cli.exe` (not on PATH in already-open shells — use the full path or open a fresh terminal). It shares the same `%LOCALAPPDATA%\Arduino15` data directory as the IDE, so it already sees the installed `rp2040:rp2040` 5.6.1 core and all boards/libraries with no separate setup.

**Why not just hand-edit the installed core file?** That was the initial instinct (quick, one line, works immediately in the IDE) — but it's a machine-global edit living outside the git repo. It would silently vanish the next time Arduino Boards Manager updates the rp2040 core, and isn't reproducible on a clean machine or in CI. Since this is production firmware for a commercial product, not a throwaway test, the repo-local `CFG_TUSB_CONFIG_FILE` + `arduino-cli` route is the correct one — the fix travels with the code.

**Usage:**
```powershell
cd Pico_zero_usb_printer
.\build.ps1                        # compile only, writes .uf2 to build\
.\build.ps1 -Upload -Port COMx     # compile and flash over an existing serial port
```
For flashing when the board is already sitting in BOOTSEL mode (see below), skip `-Upload` and drag the `.uf2` from `build\` onto the `RPI-RP2` drive manually instead.

**FQBN used:** `rp2040:rp2040:waveshare_rp2040_zero:usbstack=tinyusb`

---

## Toolchain problem #2 — VID/PID reuse broke COM port enumeration

After flashing, the board showed up in Device Manager as a single generic "USBDevice" entry with **no COM port** — even though the firmware's descriptor includes a CDC interface that should produce one.

**Root cause:** Windows had a **cached WinUSB driver package** from the earlier Zadig install done on the *real printer* (same VID `0x1FC9` / PID `0x2016`, per decision #2 above). `pnputil /enum-devices <id> /drivers` showed two competing matches:

| Driver | Matches on | Rank | Status |
|---|---|---|---|
| `oem22.inf` (`usb_printing_support.inf`, provider **libwdi** = Zadig's engine) | `USB\VID_1FC9&PID_2016` (whole device, no interface qualifier) | `00FF0001` | **Best Ranked / Installed** |
| `usb.inf` (Microsoft's composite-device driver) | `USB\COMPOSITE` | `00FF2006` | Outranked |

Windows always prefers the more specific device-ID match, so the cached WinUSB driver claimed the *entire* device before `usbccgp.sys` ever got a chance to split it into interfaces — which is why the CDC interface never received `usbser.sys` and no COM port appeared.

**This is a real, ongoing cost of decision #2 (VID/PID reuse), not a one-time fluke:** the real printer and this bridge board can never both be plugged in and working via raw VID/PID matching on the same Windows machine without redoing driver surgery each time you switch which one you're testing.

**Fix (two steps, both needed):**

1. **Remove the whole-device driver binding** — from an **elevated** PowerShell (a non-admin session runs the `/uninstall` half silently but the actual driver-store deletion fails with "Access is denied" while still reporting partial success, which is misleading):
   ```powershell
   pnputil /delete-driver oem22.inf /uninstall /force
   ```
   Then unplug/replug the board. Windows falls back to `usb.inf`, splits the device into interfaces (`MI_00` = CDC → gets a COM port, `MI_02` = Vendor — the CDC ACM interface pair `MI_00`/`MI_01` from the IAD, plus our added Vendor interface at `MI_02`), but the vendor interface now has **no driver at all** (Windows Error Code 28 — "drivers for this device are not installed"). That's expected; vendor-class interfaces never get a built-in Windows driver.

2. **Re-run Zadig, targeting the vendor interface specifically** — not the whole device:
   - Zadig → **Options → List All Devices** (required to see individual interfaces of an already-partially-working composite device).
   - Select the entry for **interface `MI_02`** specifically (shown separately from the `MI_00`/`MI_01` CDC pair once "List All Devices" is on).
   - Driver: **WinUSB**. Install.

   This correctly matches on `USB\VID_1FC9&PID_2016&MI_02` (interface-specific) rather than the whole-device ID, so it doesn't re-create the original conflict with the CDC interface.

**Verifying it worked** (useful commands if this needs re-diagnosing):
```powershell
# Find all devices for a VID
Get-PnpDevice | Where-Object { $_.InstanceId -match "VID_1FC9" } | Select-Object Status, Class, FriendlyName, InstanceId

# Full driver-ranking detail for one device instance
pnputil /enum-devices /instanceid "<InstanceId>" /drivers

# Quick error-code check
Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -eq "<InstanceId>" } | Select-Object Name, ConfigManagerErrorCode, Status
```

---

## Gotcha: `while (!Serial)` blocks `setup()` until DTR is asserted

Arduino-Pico/Adafruit TinyUSB's `while (!Serial) { ; }` idiom (used in this firmware, same as the original echo test) blocks until something asserts DTR on the CDC port. If a host script opens the port without asserting DTR — e.g. .NET's `System.IO.Ports.SerialPort` defaults `DtrEnable=false` — the board sits stuck before `loop()` ever runs, and bulk-OUT data sent in that state just accumulates unread in TinyUSB's internal vendor RX FIFO. Not an issue with the Arduino IDE's own Serial Monitor (it asserts DTR on connect), but worth knowing if scripting serial reads for testing.

---

## Hardware-confirmed test (2026-07-13)

With both toolchain problems fixed and the firmware flashed via UF2 drag-and-drop, `USB_Only_Driver.py` was pointed at the board and ran `print_test_page()`. Arduino IDE Serial Monitor on COM12 (115200 baud) showed:

```
[USB] 206 bytes received -- parsing
[USB] Hex dump:
1B 40 1B 61 01 1B 45 01 2A 2A 2A 20 50 52 49 4E
54 45 52 20 54 45 53 54 20 2A 2A 2A 0A 1B 45 00
... (full ESC/POS byte stream) ...
[Parser] Extracted 9 text lines
  [0] *** PRINTER TEST ***
  [1] Normal text
  [2] Bold text
  [3] Underlined text
  [4] Big
  [5] Wide text
  [6] Centered text
  [7] --------------------------------------------
  [8] PASS - printer is working
```

Every line matches `print_test_page()`'s content exactly. This confirms: USB enumeration, WinUSB/CDC driver binding, the bulk-OUT transfer, silence-timeout buffering, and the ported `parseESCPOS()` logic all work correctly together on real hardware.

---

## Next steps (not started)

1. **UART link from this board to the ESP32-S3 main board**, forwarding the captured bulk-OUT bytes instead of (or in addition to) the local debug print. Needs its own design pass — this is a new decision tree, not a continuation of the ones already closed:
   - Which ESP32-S3 GPIOs to dedicate (camera FPC header `J8` pins IO17/18/21/38/39/40/41/42/45/46/47/48 were the leading unused candidates as of the original architecture discussion, not finalized).
   - Which RP2040-Zero GPIOs for that UART (default UART0 is TX=GP0/RX=GP1 if going that route).
   - Whether the ESP32-S3 side needs new firmware changes, and how much of `DigiSlip_ONX3248G035.ino`'s existing `posSerial`-based state machine can be reused as-is vs needs a second UART input path.
2. **Printer-facing side of the chain** (ESP32-S3 → USB host → real printer) — still undecided between the Adafruit USB Host FeatherWing (SPI, MAX3421E) and a second RP2040 board running TinyUSB host stack. Not touched this session.
3. Per project convention ([[feedback_grill_before_implement]] / [[feedback_test_before_moving_on]] in memory) — **do not start step 1 without an explicit go-ahead and its own grilling session.** This document exists so that session can start with full context instead of re-deriving it.

---

## Quick reference — commands used this session

```powershell
# Install arduino-cli (one-time, already done)
winget install --id ArduinoSA.CLI -e --accept-source-agreements --accept-package-agreements

# Compile / flash
cd Pico_zero_usb_printer
.\build.ps1                        # compile, .uf2 lands in build\
.\build.ps1 -Upload -Port COMx     # compile + flash via existing COM port

# Manual UF2 flash (used for the first flash of this firmware)
# 1. Hold BOOTSEL, plug in USB, release after ~2s -> RPI-RP2 drive appears
# 2. Drag build\Pico_zero_usb_printer.ino.uf2 onto RPI-RP2

# Run the test sender against the board
python simulator\USB_Only_Driver.py

# Driver conflict diagnosis/fix (elevated PowerShell for the delete)
pnputil /enum-devices /instanceid "<InstanceId>" /drivers
pnputil /delete-driver oem22.inf /uninstall /force
# then Zadig -> Options -> List All Devices -> select the MI_xx vendor interface -> WinUSB
```
