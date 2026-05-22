# DigiSlip Firmware — Context

## What This Repo Is

Arduino/ESP32 firmware for the DigiSlip hardware device. The device sits inline between a POS machine and a thermal printer on RS232. It intercepts the raw ESC/POS byte stream, strips control codes to extract readable receipt text, uploads to the Supabase backend, and shows a QR code so the customer can claim their receipt digitally instead of printing.

**Board:** Nextion ONX3248G035 (ESP32-S3R8, 3.5" IPS ST7796 display 320×480 portrait, ~165 DPI, CST826 capacitive touch, PN532 NFC reader via Grove I2C)

**One firmware file:** `DigiSlip_ONX3248G035/DigiSlip_ONX3248G035.ino`

**Per-device credentials:** `DigiSlip_ONX3248G035/config.h` (gitignored — never committed). Copy `config.h.example` → `config.h` and fill in WiFi, Supabase, and device values before flashing.

**Firmware version:** v2.3.1 (OTA update support added, May 2026)

**OTA release checklist** — must follow this order every release or devices will boot-loop:
1. Make code changes
2. Bump `#define FIRMWARE_VERSION` in the `.ino` to match the new tag (e.g. `"v2.4.0"`)
3. Sketch → Export Compiled Binary → produces `DigiSlip_ONX3248G035.ino.bin`
4. Rename to `DigiSlip_ONX3248G035.bin`
5. Publish GitHub release tagged `v2.4.0` with the `.bin` attached
6. Devices update on next power cycle

---

## Glossary

| Term | Meaning |
|------|---------|
| **slip** | A single receipt transaction — raw ESC/POS text stripped to clean ASCII, stored in Supabase `slips` table with a UUID |
| **claim** | A user linking a slip to their account. Can happen via QR scan (app or browser), NFC card tap at the device, or in-app QR scanner |
| **claim window** | The 60-second period after a slip is uploaded where the device shows the QR screen. After 60s the device returns to IDLE silently |
| **digital slip** | The slip record in Supabase — independent of whether a physical paper copy printed |
| **print** | Forwarding the buffered raw ESC/POS bytes to the thermal printer via UART1 |
| **TILL-ID** | Per-device identifier defined in `config.h` (e.g. `TILL-01`); corresponds to a device record in Supabase |
| **device token** | 64-char hex secret defined in `config.h` per device; validates device identity in Supabase edge functions |
| **NFC claim** | PN532 reads card UID → firmware calls `nfc-claim` edge function → resolves UID to user account → `STATE_CLAIMED` |
| **ESC/POS** | Epson receipt printer command language. The raw byte stream from the POS. The firmware strips control sequences, preserves printable ASCII and line breaks |
| **offline queue** | NVS-backed FIFO (up to 5 transactions) used when WiFi is down. Flushed to Supabase when reconnected |
| **STATE_WAITING_CLAIM** | The primary interactive state: QR displayed, polling Supabase, listening for touch/NFC/button |
| **ClaimMethod** | Enum (`CLAIM_NONE`, `CLAIM_NFC`, `CLAIM_QR`) set before transitioning to `STATE_CLAIMED` — controls "via" text on the claimed screen |

---

## State Machine

```
STATE_IDLE
  → (UART1 data arrives) → STATE_BUFFERING

STATE_BUFFERING
  → (500ms silence, < 16 bytes) → STATE_IDLE  [noise discard]
  → (500ms silence, 0 text lines parsed) → STATE_IDLE  [noise discard]
  → (500ms silence, ≥ 16 bytes, ≥ 1 text line) → STATE_UPLOADING

STATE_UPLOADING
  → (POST succeeds) → STATE_WAITING_CLAIM  [draws QR screen]
  → (offline / POST failed) → STATE_WAITING_CLAIM  [shows error message]

STATE_WAITING_CLAIM
  → (Supabase poll returns claimed=true) → STATE_CLAIMED  [claimMethod=CLAIM_QR]
  → (touch "Print Slip" or IO38 button) → STATE_PRINTING
  → (touch "Cancel") → STATE_CANCELLED
  → (NFC tap) → STATE_CLAIMED  [claimMethod=CLAIM_NFC]
  → (60s timeout) → STATE_IDLE  [silent]

STATE_CLAIMED
  → (9s display) → STATE_IDLE

STATE_CANCELLED
  → (3s display) → STATE_IDLE

STATE_PRINTING
  → (forward buffer + 3s spinner hold) → STATE_IDLE

STATE_OFFLINE
  → (WiFi reconnects) → preOfflineState  [restored automatically]
  ← (any state, WiFi lost >30s) → STATE_OFFLINE
```

---

## Key Constraints

### CST826 Touch Controller

- I2C address `0x15` on Wire (SDA=IO8, SCL=IO7) — same bus as PN532 (0x24)
- **Must read exactly 7 bytes** from register `0x00` — reading 6 physically locks SDA low, requires power cycle
- **Must use `endTransmission(false)`** (repeated start) — `true` (STOP) also breaks it
- **`Wire.setClock(400000)` required** — 100kHz is unreliable
- I2C bus recovery (9 SCL pulses + manual STOP) must run before `Wire.begin()`
- Debounce: 300ms minimum

### UART Noise Filtering

Two guards in `STATE_BUFFERING` prevent serial noise from triggering a slip upload:

1. **Minimum byte count (`MIN_SLIP_BYTES = 16`):** If the burst is fewer than 16 bytes after the 500ms silence gap, it is discarded and the device returns to `STATE_IDLE`. A real ESC/POS slip is always many times longer.
2. **Zero text lines:** After `parseESCPOS()`, if `receiptLineCount == 0` (no printable ASCII was extracted), the buffer is discarded and the device returns to `STATE_IDLE`.

Neither guard increments `txCounter`. Log messages: `[UART] Too short — discarding (noise)` and `[Parser] No text extracted — discarding (noise)`.

### Print/Cancel Separation

Print and Cancel only control the physical paper copy. The digital slip in Supabase is never deleted by these actions. A customer who cancels (or nobody presses anything) still has a scannable slip URL for 24 hours.

### Serial Output

Verbose Serial output is intentional — the device is still in active development and the developer monitors serial during testing. Do not simplify or remove Serial.println calls.

### Display — Font and Rendering Rules (ONX3248G035, ~165 DPI)

FreeFonts render much larger than desktop pt sizes suggest at 165 DPI. Confirmed working sizes:

| Role | Font | Safe length |
|------|------|-------------|
| Body / labels | `FreeMono9pt7b` | ~22 chars max centered |
| Headlines | `FreeSansBold9pt7b` | ~19 chars max |
| Pill labels | `setFreeFont(nullptr)` + `setTextSize(2)` | ~26 chars |
| Wordmark | `drawWordmark()` bitmap | n/a |

- `FreeSansBold12pt7b` or larger for strings >12 chars **overflows 320px** — do not use
- `FreeSans9pt7b` for pill labels renders ~20px tall — too large for pill chrome; use bitmap `setTextSize(2)` instead
- **Datum reset rule:** `drawPill(dot=true)` and `drawHeader(dot=true)` leave `ML_DATUM` set. Always call `tft.setTextDatum(MC_DATUM)` explicitly after these helpers

### Arduino IDE Partition Scheme

The ONX3248G035 has **16MB flash** (not 4MB). Arduino IDE must be configured correctly:

- **Flash Size:** `16MB (128Mb)` — changing this first unlocks the correct partition options
- **Partition Scheme:** `16M Flash (3MB APP/9.9MB FATFS)` — required for OTA (dual-partition needs ~3MB per app slot)
- At 3MB APP budget, the sketch compiles to ~36% usage (leaving headroom for future growth)
- The default 4MB partition scheme produces `88% usage` and OTA will fail (no space for second slot)

### TFT_eSPI FreeFonts

Do **not** add `#include <Fonts/GFXFF/FreeSansBold9pt7b.h>` (or any FreeFonts header) to the sketch. `TFT_eSPI.h` pulls in `gfxfont.h` unconditionally which includes every GFXFF font. Double-include causes "redefinition of const uint8_t …Bitmaps" compile errors.

---

## Design System v2.2

### Colour Palette (RGB565)

| Constant | Hex | RGB565 | Use |
|----------|-----|--------|-----|
| `COL_BG` | `#E8E4DA` | `0xEF3B` | Screen background |
| `COL_CARD` | `#FEFDFB` | `0xFFFF` | Card surface (QR screen) |
| `COL_FG` | `#1C1917` | `0x18C2` | Primary text |
| `COL_MUTED` | `#78716C` | `0x7B8D` | Secondary text |
| `COL_FAINT` | `#D6D3CD` | `0xD699` | Borders, dividers |
| `COL_BLUE` | `#1558FF` | `0x12DF` | Brand blue, "digi" wordmark half |
| `COL_GREEN` | `#00C96A` | `0x064D` | Brand green, "Slips" wordmark half |
| `COL_GREEN_LT` | `#ECFDF5` | `0xEFFE` | Green badge / pill background |
| `COL_GREEN_BD` | `#A7F3D0` | `0xA79A` | Green badge border |
| `COL_GREEN_DK` | `#059669` | `0x04AD` | Green badge text / icon |
| `COL_RED` | `#DC2626` | `0xD924` | Error / offline states |
| `COL_RED_LT` | `#FEF2F2` | `0xFF9E` | Red badge background |

### Helper Functions

| Function | Purpose |
|----------|---------|
| `drawWordmark(cx, y, size)` | Renders two-tone bitmap wordmark (38px or 22px) |
| `drawHeader(pillText, pillBg, pillBd, pillTx, dot)` | 44px header with left wordmark and optional right pill |
| `drawFooter(text)` | FreeMono9pt, BC_DATUM, muted, bottom of screen |
| `drawPill(cx, cy, text, bg, bd, tx, dot, dotc)` | Rounded pill chip with optional coloured dot |
| `displayBoot(progress)` | Full boot screen draw (initial call) |
| `bootProgress(pct, status)` | Updates boot bar + status text without full redraw |
| `getDateLine()` | Returns `"Mon 13 May · 09:45"` formatted string |

### Screen Inventory

| Screen function | State | Description |
|----------------|-------|-------------|
| `displayBoot()` | startup | Wordmark centred, animated 200px progress bar (0→100%), status text, ≥4s hold |
| `displayIdle()` | `STATE_IDLE` | Wordmark hero, "Ready for next sale", READY green pill, date line, throttled 60s |
| `drawQR()` | `STATE_WAITING_CLAIM` | Receipt card with QR, Slip# label, Print/Cancel buttons, countdown footer |
| `drawNfcLinking()` | NFC tap moment | Blue NFC disc + concentric rings, "Card detected", UID, "Claiming slip…" |
| `drawClaimed()` | `STATE_CLAIMED` | Green checkmark disc, "Slip claimed", NFC vs QR attribution, VERIFIED pill, 9s hold |
| `drawCancelled()` | `STATE_CANCELLED` | X-circle, "Print cancelled", 24h claimability note, 3s hold |
| `drawPrinting()` | `STATE_PRINTING` | faint ring + drawArc spinner, "Printing slip", Slip#, 3s post-print hold |
| `drawOffline()` | `STATE_OFFLINE` | Red disc, "Lost connection", queue depth card, "check router" footer |

### Boot Sequence

`setup()` keeps the boot screen visible throughout startup:
1. `displayBoot(0)` — full draw
2. WiFi connect loop (0→45%) with "CONNECTING..." status
3. `bootProgress(45, "CHECKING UPDATE...")` → `checkOTA()` runs (GitHub Releases API, downloads + flashes if newer tag found, reboots)
4. NTP sync loop (48→90%) with "SYNCING TIME..." status
5. `bootProgress(100, "READY")`, hold for ≥4s total
6. Transition to `STATE_IDLE`

The "Connecting to WiFi", "WiFi OK / IP / Time synced", "Receiving...", "Loading..." screens from v2.1 are **removed**. The boot screen is the only startup screen.

---

## External Dependencies

| System | Details |
|--------|---------|
| **Supabase** | `https://eivctqjisodfhaitzyiq.supabase.co` — REST API for slip insert/poll, edge functions for NFC claim |
| **Web claim page** | `https://digislips.co.za/slip/<uuid>` — Vercel-hosted static HTML, reads Supabase |
| **Firmware repo** | `digislips/digislips-firmware` (GitHub digislips org) — this repo, public |
| **Backend repo** | `digislips/digislip-backend` (GitHub digislips org) — edge function source |
| **App repo** | `digislips/digislip-app` (GitHub digislips org) — React Native (Expo) mobile app |

---

## TDD Test Suite

**88 source-level pytest tests across 2 files.** No hardware needed — tests parse the `.ino` source directly.

| File | Tests | Covers |
|------|-------|--------|
| `test_firmware_design_system.py` | 62 | Palette constants + RGB565 values, helper function definitions, screen layout choices, state machine wiring, timing, config.h structure |
| `test_ota.py` | 17 | `checkOTA()` (GitHub API, version compare, Serial logs), `applyOTA()` (HTTPUpdate, progress, redirects) |

Run all: `cd DigiSlip_ONX3248G035 && python -m pytest -v`
