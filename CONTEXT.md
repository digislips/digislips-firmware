# DigiSlip Firmware — Context

## What This Repo Is

Arduino/ESP32 firmware for the DigiSlip hardware device. The device sits inline between a POS machine and a thermal printer on RS232. It intercepts the raw ESC/POS byte stream, strips control codes to extract readable receipt text, uploads to the Supabase backend, and shows a QR code so the customer can claim their receipt digitally instead of printing.

**Board:** Nextion ONX3248G035 (ESP32-S3R8, 3.5" IPS ST7796 display 320×480 portrait, CST826 capacitive touch, PN532 NFC reader via Grove I2C)

**One firmware file:** `DigiSlip_ONX3248G035/DigiSlip_ONX3248G035.ino`

---

## Glossary

| Term | Meaning |
|------|---------|
| **slip** | A single receipt transaction — raw ESC/POS text stripped to clean ASCII, stored in Supabase `slips` table with a UUID |
| **claim** | A user linking a slip to their account. Can happen via QR scan (app or browser), NFC card tap at the device, or in-app QR scanner |
| **claim window** | The 60-second period after a slip is uploaded where the device shows the QR screen. After 60s the device returns to IDLE silently |
| **digital slip** | The slip record in Supabase — independent of whether a physical paper copy printed |
| **print** | Forwarding the buffered raw ESC/POS bytes to the thermal printer via UART1 |
| **TILL-ID** | Per-device identifier hardcoded in firmware (e.g. `TILL-01`); corresponds to a device record in Supabase |
| **device token** | 64-char hex secret hardcoded per device; validates device identity in Supabase edge functions |
| **NFC claim** | CST826 path: PN532 reads the card UID → firmware calls `nfc-claim` edge function → resolves UID to user account |
| **ESC/POS** | Epson receipt printer command language. The raw byte stream from the POS. The firmware strips control sequences, preserves printable ASCII and line breaks |
| **offline queue** | NVS-backed FIFO (up to 5 transactions) used when WiFi is down. Flushed to Supabase when reconnected |
| **STATE_WAITING_CLAIM** | The primary interactive state: QR displayed, polling Supabase, listening for touch/NFC/button |

---

## State Machine

```
STATE_IDLE
  → (UART1 data arrives) → STATE_BUFFERING
  
STATE_BUFFERING
  → (500ms silence after last byte) → STATE_UPLOADING

STATE_UPLOADING
  → (POST succeeds) → STATE_WAITING_CLAIM  [draws QR screen]
  → (offline / POST failed) → STATE_WAITING_CLAIM  [shows "Tap Print for paper"]

STATE_WAITING_CLAIM
  → (Supabase poll returns claimed=true) → STATE_CLAIMED
  → (touch "Print Slip" or IO38 button) → STATE_PRINTING
  → (touch "Cancel") → STATE_IDLE
  → (NFC tap) → STATE_CLAIMED
  → (60s timeout) → STATE_IDLE  [silent, no splash]

STATE_CLAIMED
  → (2.5s display) → STATE_IDLE

STATE_PRINTING
  → (forward buffer to printer, 2s display) → STATE_IDLE
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

### Print/Cancel Separation

Print and Cancel only control the physical paper copy. The digital slip in Supabase is never deleted by these actions. A customer who cancels (or nobody presses anything) still has a scannable slip URL for 24 hours.

### Serial Output

Verbose Serial output is intentional — the device is still in active development and the developer monitors serial during testing. Do not simplify or remove Serial.println calls.

### On-Screen Messages

Keep on-screen status text brief and user-facing (e.g. "Loading...", "Linking...", "Claimed!"). The detailed diagnostic information lives in Serial, not on screen.

---

## External Dependencies

| System | Details |
|--------|---------|
| **Supabase** | `https://eivctqjisodfhaitzyiq.supabase.co` — REST API for slip insert/poll, edge functions for NFC claim |
| **Web claim page** | `https://digislips.co.za/slip/<uuid>` — Vercel-hosted static HTML, reads Supabase |
| **Backend repo** | `digislip-backend` (GitHub JoeBurd-code) — edge function source |
| **App repo** | `digislip-app` — React Native (Expo) mobile app, theme constants at `src/constants/theme.ts` |

---

## Brand Palette (RGB565 — from digislip-app/src/constants/theme.ts)

| Name | Hex | RGB565 | Use |
|------|-----|--------|-----|
| `COL_BG` | `#E8E4DA` | `0xEF3B` | Screen background |
| `COL_CARD` | `#FEFDFB` | `0xFFFF` | QR card surface |
| `COL_FG` | `#1C1917` | `0x18C2` | Dark text |
| `COL_ACCENT` | `#1558FF` | `0x12DF` | Brand blue — header bar, clock |
| `COL_SUCCESS` | `#00C96A` | `0x064D` | Print button, claimed state |
| `COL_ERROR` | `#DC2626` | `0xD924` | Error states |
| `COL_MUTED` | `#78716C` | `0x7B8D` | Secondary text, Cancel button outline |
| `COL_FAINT` | `#D6D3CD` | `0xD699` | Dividers, footer text |
