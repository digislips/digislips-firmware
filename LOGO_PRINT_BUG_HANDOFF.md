# Debugging handoff — logo/barcode RS-232 print failure via device path

**Last updated:** 2026-06-25
**Status:** Root cause narrowed to **hardware (outgoing RS-232 driver stage or printer cable)**. Firmware is proven correct and needs no further changes. Next action is a hardware bisection (see "When you resume").

---

## TL;DR (the current conclusion)

The device receives, stores, and **transmits all bytes of a logo slip perfectly** — proven three independent ways (serial logs, Supabase payload, and a laptop loopback capture of exactly 6549 bytes). The logo still fails to print **only when the device drives the real printer**. The fault is therefore downstream of the firmware: the **outgoing MAX232 driver under sustained load** and/or the **device→printer cable**. The laptop (a lighter load + more forgiving CH340 receiver) accepts the device's output fine; the printer (heavier load + stricter receiver) drops bytes during the sustained bitmap.

**There is nothing left to fix in firmware.** Resume on the bench with a multimeter/scope and cable swaps.

---

## Project overview

**Repo:** `digislips/digislips-firmware` (local: `C:\Users\SOMO-CAD\Documents\digislip-firmware`)

**Hardware:** ONX3248G035 ESP32 touchscreen device. Sits between a POS cash register and a legacy RS-232 thermal receipt printer. It intercepts ESC/POS bytes from the POS, uploads the slip to Supabase, waits for an NFC/QR claim, then forwards the buffered bytes to the printer if a paper copy is requested.

### ⚠️ Which firmware file is real (critical — cost this session hours)

There are **two** `.ino` files. Only one is flashed:

| | `DigiSlip_ESP32/DigiSlip_ESP32.ino` | `DigiSlip_ONX3248G035/DigiSlip_ONX3248G035.ino` |
|---|---|---|
| Status | **DEAD / legacy — do not edit** | **REAL — this is flashed** |
| `raw_escpos` base64 (#23) | absent | present (~line 1118–1149) |
| Serial design | two ports (UART2 RX @9600 + UART1 TX @19200) | **single UART1, RX+TX, @19200** |
| `printBuffer` | 12288 | 8192 |
| `setRxBufferSize` | none | 4096 (line ~1469) |

The session summary's mental model (POS→UART2@9600→UART1@19200) describes the **dead** file. The real device is **one UART1 at 19200 baud doing both RX and TX**.

### Real serial chain (as built)

```
POS / laptop sim  --RS232-->  MAX232 #1 (RS232->TTL receiver)  -->  ESP32 UART1_RX
ESP32 UART1_TX    -->  MAX232 #2 (TTL->RS232 driver)  --RS232 cable-->  Printer
```

- One ESP32 UART (`HardwareSerial posSerial(1)`), `posSerial.begin(19200, SERIAL_8N1, UART1_RX, UART1_TX)`.
- Two **separate** MAX232 chips / connectors: #1 incoming (receiver), #2 outgoing (driver).
- Consequence: the device **cannot hear anything the printer sends back** (no RX wire from printer). Flow-control return signals from the printer are physically invisible to the device.

### Key firmware locations (real file)

- Buffering state machine: `STATE_BUFFERING` ~lines 1568–1607 (reads all available, 500 ms silence = end-of-job, 8192 cap).
- ESC/POS text extraction: `parseESCPOS()` ~line 441-ish region (read-only; does **not** mutate `printBuffer`).
- Base64 of raw buffer for backend: `buildSupabaseJSON()` ~lines 1118–1149 (read-only on `printBuffer`).
- **Forward to printer:** `STATE_PRINTING` ~lines 1789–1794:
  ```cpp
  posSerial.write(printBuffer, printBufferLen);
  posSerial.flush();
  ```
- `#define SERIAL_SILENCE_MS 500` (line 64).

---

## The Python simulator

`simulator/Serial_RS232_Driver_v2.py` — fluent `Receipt` builder that emits ESC/POS byte buffers and sends them over RS-232 via a **CH340 USB adapter on COM9 @ 19200**. Connects **directly to the printer**, bypassing the device. Stands in for the POS.

- Slips 1–8 defined. Slip 7 = logo + text. Slip 8 (`slip_8_combined_test`) = logo + full receipt + Code128 barcode.
- `open_port()` uses a **CH340 workaround**: open at 9600, then swap baud to 19200 on the live handle (avoids Windows error 31). DTR/RTS forced low to avoid ESP32 auto-reset.
- Serial params: `xonxoff=False, rtscts=False, dsrdtr=False` — **no flow control of any kind** (lines 63–65). This is important: the working path uses zero flow control, so the printer does **not** require flow control.
- `print_raw_serial()` sends in 32-byte chunks, `ser.flush()` each, `chunk_delay = 32/baud*10*1.5 ≈ 25 ms` (lines ~109–117). On Windows the OS appears to batch these, so the effective stream is closer to continuous than the per-chunk delay implies.

---

## The bug — symptoms

- **Slips 1–6 (text only):** print correctly via both the direct path and the device path.
- **Slips 7 & 8 (logo at top):** print correctly via the **direct** path (laptop→printer), but **fail via the device path**:
  - Printer does **3 chirps then stalls** (a *clean* logo print is **4 chirps** — the printer batches the bitmap into ~4 passes, so 3 chirps = it only got ~¾ of the raster).
  - The logo doesn't complete.
  - The **next ~2 slips** sent through the device print as **garbled bitmap noise** (the printer consumes them as the missing raster bytes it's still waiting for), then it recovers to normal.
- A photo earlier showed slip 5 (coffee shop) sent after slip 7: a black noisy bitmap block, then `12.00` and `Enjoy your coffee!` printed normally once the printer's declared byte count was satisfied.

**Mechanism:** `GS v 0` declares N bitmap bytes; the printer receives fewer than N; it waits mid-command and eats subsequent slips until the count is satisfied. Classic short-byte-count-after-raster-header behaviour.

---

## Key measurements

```
test_logo.png:               200 x 60 px  ->  scaled 384 x 115 px
bitmap bytes per row:        48   (ceil(384/8))
total bitmap bytes:          5520 (48 x 115)
GS v 0 header:               8 bytes
slip 7 full buffer:          6549 bytes
slip 8 full buffer:          6635 bytes
forward time (device):       3.38 s  ==  exact 19200-baud wire time for 6549 bytes
```

`printBuffer[8192]` and `setRxBufferSize(4096)` both comfortably exceed one slip. (At 19200, 4096 B = 2.13 s of data; a slip takes ~3.4 s, and the loop drains RX continuously, so RX cannot overflow.)

---

## Test setup / cabling (as described by user)

- **Laptop (sim) → device:** USB-to-RS232 cable into device's incoming MAX232 (#1). **Receive works perfectly.**
- **Laptop → printer (direct):** USB-to-RS232 cable. **Works perfectly (4 chirps + completes).**
- **Device → printer:** "regular RS-232 cable" from device's outgoing MAX232 (#2). **This is the failing path.**
- COM ports: `COM9 = USB-SERIAL CH340` (the adapter used for sim + loopback). `COM5 = USB-SERIAL CH340K` (other).

---

## Investigation log — what was tried and the outcome

1. **Simulator `ser.flush()` per 32-byte chunk** — *No effect.* Targeted the already-working direct path.
2. **`printBuffer` 4096→12288 in `DigiSlip_ESP32.ino`** — *No effect.* **Wrong file** (dead legacy file, never flashed).
3. **`posSerial.setRxBufferSize(8192)` in `DigiSlip_ESP32.ino`** — *No effect.* **Wrong file again.** (Real file already had 4096; RX was never the problem anyway.)
4. **Pace the forward in the REAL file** (32-byte chunks, `flush()` each, `delay(25)`) — *Made it WORSE* (5 chirps, still failed, still needed ~2 recovery slips). **Reverted.** Lesson: the printer wants the bitmap delivered continuously; added gaps hurt. This also ruled out "printer input buffer overflow from raw speed" (slowing down would have helped — it didn't).

### Decisive evidence (this is what cracked it)

**Serial monitor, one slip-7 send through the device:**
```
[UART] Data incoming — buffering
[UART] 6549 bytes received — parsing      <- device RECEIVED all bytes
[Parser] Extracted 28 text lines
[BTN] Print tapped
[PRINT] Forwarding 6549 bytes to printer  <- device FORWARDED all bytes
[PRINT] Done            (3.38 s later = exact wire time -> flush completed)
```

**Supabase row:** `raw_escpos` base64 is byte-perfect; `parsed_content` = `{"barcodes": [], "has_logo": true}`. Confirms the device's buffer is intact.

**Loopback capture (device's outgoing port → laptop, `simulator/loopback_capture.py`):**
```
[CAP] Received 6549 bytes  (expected 6549 for slip 7)
[CAP] FULL - every byte crossed the outgoing link intact.
```
The device emits all 6549 bytes cleanly **into a laptop**.

### Conclusion from the evidence

Firmware + ESP32 UART + outgoing MAX232 deliver **all** bytes to a **light load** (laptop, sensitive CH340 receiver). The failure is **load- and receiver-dependent** at the printer:
- The printer's input + the "regular RS-232 cable" load the MAX232 driver more heavily than the laptop did.
- The printer's receiver is stricter than a CH340.
- A weak MAX232 charge pump can sag under the sustained 6 KB bitmap → marginal levels the CH340 still reads but the printer rejects → printer drops bytes.

This reconciles everything: text→printer OK (short bursts, pump recovers); bitmap→printer fails (sustained load, pump sags); bitmap→laptop FULL (light load, tolerant receiver).

**Why it's NOT flow control:** the working sim path uses `xonxoff/rtscts/dsrdtr = False`, so the printer demonstrably does not require flow control.

---

## Open questions (not yet resolved)

1. **Which cable was used for the loopback?** Cable-vs-printer is not yet isolated. If the loopback used a *different* cable than the device→printer run, the "regular RS-232 cable" itself is still an untested suspect.
2. **Voltage sag not yet measured.** No scope/meter reading of the outgoing MAX232 RS-232 TX pin under sustained load.
3. **Byte-accuracy of the capture** confirmed only by *count* (6549), not byte-for-byte content. (Corruption wouldn't explain the symptom, which is a short *count*, so this is low priority.)

---

## When you resume — next steps (hardware bisection, cheapest first)

1. **Isolate cable vs printer:** re-run the loopback using the **exact** "regular RS-232 cable" that goes device→printer (plugged into the laptop). If still 6549 → cable is good, suspect = driver/printer. If short → the cable is bad (cheapest possible fix).
2. **Measure the sag:** multimeter/scope on the **outgoing MAX232's RS-232 TX pin** vs GND while sending slip 7 **to the printer**. Idle should be **−7 to −9 V**; if it collapses toward **−3 to −5 V** during the bitmap, that's the charge-pump smoking gun.
3. **Hardware fixes (in order of likelihood):**
   - **Charge-pump caps on the OUTGOING MAX232:** use **1 µF** for a true MAX232 (0.1 µF only on MAX232A/MAX3232). Wrong/small caps here is the #1 cause; bumping to 1 µF (or 10 µF) often fixes it outright.
   - **Swap the outgoing driver to a MAX3232** (stronger/faster, happy at 19200 into a load).
   - **Solid common ground** device↔printer; try a **shorter** printer cable.
4. **If hardware checks out and it still fails:** revisit whether the printer needs a specific quirk (e.g., it *does* assert a busy line the device can't see). But note the sim disproves a flow-control *requirement*, so this is unlikely.

---

## Tooling — `simulator/loopback_capture.py`

Measures how many bytes actually arrive from the device's **outgoing** port (laptop stands in for the printer). Reuses the sim's CH340-safe open (9600→swap to 19200, DTR/RTS off).

**Run it (do NOT use the VS Code ▷ Run button — it spawns stray instances that hold COM9):**
```powershell
python simulator/loopback_capture.py            # defaults to COM9
python simulator/loopback_capture.py COM7       # if adapter is on another port
```
Wait for `Waiting for data...`, then tap **Print** on the device. Stop with `Ctrl+C`. Raw bytes dumped to `simulator/loopback_capture.bin`.

**If you get `Access is denied` on COM9:** a stray process holds it. Find & kill:
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*loopback_capture*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
List ports: `python -c "import serial.tools.list_ports as p; [print(x.device,'-',x.description) for x in p.comports()]"`

**Wiring for the loopback:** device outgoing port → laptop USB-RS232 adapter. Both are "senders" by default, so if you get *no data*, add a **null-modem (crossover)** so device-TX reaches adapter-RX (pins 2↔3). GND common.

---

## Current file state

- `DigiSlip_ONX3248G035/DigiSlip_ONX3248G035.ino` — **unchanged / clean** (pacing experiment was reverted; net zero). This is the real firmware.
- `DigiSlip_ESP32/DigiSlip_ESP32.ino` — **unchanged** (dead file; earlier edits reverted). Ignore.
- `simulator/Serial_RS232_Driver_v2.py` — has the per-chunk `ser.flush()` change (modified, uncommitted; harmless, direct path works).
- `simulator/loopback_capture.py` — **new, uncommitted** (the diagnostic tool above).
- Nothing committed this session.

Recent commits for context:
```
cb0cef9 chore: move RS-232 simulator and tests into simulator/ folder
77715d9 feat: add slip_8_combined_test (logo + barcode) and 10 TDD tests
5a7092b feat: add logo() GS v 0 raster bitmap to simulator and 12 TDD tests — closes #24
a70ff91 feat: base64-encode printBuffer as raw_escpos in create-slip POST (#23)
```
