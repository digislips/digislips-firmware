// =============================================================================
//  DigiSlip — ONX3248G035 (ESP32-S3, 3.5" ST7796, 320×480 portrait)
//
//  What this device does:
//    • Sits between a POS machine and a thermal printer on RS232
//    • Intercepts the raw ESC/POS byte stream
//    • Strips control codes → clean text → uploads to Supabase
//    • Displays a QR code on TFT so customer can claim slip digitally
//    • Reads NFC card/phone UID to link slip to a user account
//    • Polls Supabase to detect QR-based claims (iPhone users via app)
//    • If claimed digitally → print is blocked (green flow)
//    • Touch buttons: Print (forward to printer) / Cancel (discard)
//    • If neither tapped within 60s → device returns to IDLE (no print)
//    • Offline queue: if WiFi down, stores up to 5 transactions in NVS
//
//  Board: ONX3248G035 (Nextion Genius Series)
//    MCU:     ESP32-S3R8 (8MB PSRAM, 16MB Flash)
//    Display: 3.5" IPS, ST7796 driver, 320×480, capacitive touch (CST826)
//
//  Wiring (external peripherals only — TFT is internal to board):
//    RS232 from POS   → MAX3232 → UART1 Grove connector → IO12 (RX)
//    RS232 to Printer → MAX3232 → UART1 Grove connector → IO13 (TX)
//    NFC (PN532 I2C)  → I2C Grove connector → IO8 (SDA), IO7 (SCL)
//    Button           → IO38 (24-pin header), other leg to GND
//
//  TFT_eSPI User_Setup.h must define:
//    #define ST7796_DRIVER
//    #define TFT_WIDTH  320
//    #define TFT_HEIGHT 480
//    (SPI pins are internal — let the board BSP handle them)
//
//  Libraries (install via Arduino Library Manager):
//    TFT_eSPI                — TFT display driver (configure User_Setup.h first)
//    Adafruit PN532          — NFC reader
//    QRCodeGenerator         — QR rendering
//    ArduinoJson (v6)        — JSON building
//    WiFi, WiFiClientSecure, HTTPClient — built-in for ESP32
//    Preferences             — built-in NVS wrapper for ESP32
//    time.h                  — built-in NTP / SNTP
// =============================================================================

#include <Wire.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <TFT_eSPI.h>  // gfxfont.h (pulled in by TFT_eSPI) already includes all FreeFonts
#include <Adafruit_PN532.h>
#include <QRCodeGenerator.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <time.h>
#include "wordmark_38.h"
#include "wordmark_22.h"

// =============================================================================
//  ── CONFIGURATION — edit these for each device ──────────────────────────────
// =============================================================================

const char* WIFI_SSID      = "SOMO";
const char* WIFI_PASSWORD  = "0836468891";

// Each physical device gets its own ID — change per unit deployed
#define TILL_ID   "TILL-01"

// Supabase
#define SUPABASE_URL   "https://eivctqjisodfhaitzyiq.supabase.co"
#define SUPABASE_ANON  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVpdmN0cWppc29kZmhhaXR6eWlxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY4MDgxMjIsImV4cCI6MjA5MjM4NDEyMn0._0wu91Zrc3aMrKsO_KUkp64CoOCklwMViYAofYZyCFI"

// Each physical device gets its own token — generated via provision_device() in Supabase
#define DEVICE_TOKEN   "92007b7839f6909c07965ac26bd080a673a5ae16b637b237ab63945af0e66431"
#define DEVICE_ID      "c42353a3-f383-49ac-aef4-06d054056ae8"
#define MERCHANT_ID    "0fa9f01d-c384-43df-9819-d1265c0ca556"

// QR code base URL — phone app will open  https://digislips.co.za/slip/<slip_uuid>
#define QR_BASE_URL  "https://digislips.co.za/slip/"

// NTP
#define NTP_SERVER   "pool.ntp.org"
#define TZ_OFFSET    7200   // UTC+2 (SAST) in seconds

// Timeouts
#define CLAIM_TIMEOUT_MS    60000   // 60 s before reverting to IDLE
#define SUPABASE_POLL_MS     2000   // poll Supabase every 2 s for QR claims
#define WIFI_WATCHDOG_MS    10000   // check WiFi health every 10 s
#define SERIAL_SILENCE_MS     500   // gap that signals end of ESC/POS burst

// Offline queue
#define OFFLINE_QUEUE_SIZE      5   // max queued transactions when WiFi is down

// =============================================================================
//  ── PIN DEFINITIONS — ONX3248G035 ───────────────────────────────────────────
// =============================================================================

// RS232 interception via UART1 Grove connector
#define UART1_RX    12   // RX from POS (via MAX3232)
#define UART1_TX    13   // TX to Printer (via MAX3232)

// I2C — Grove I2C connector (also used by touch CST826 and RTC internally)
#define I2C_SDA      8
#define I2C_SCL      7

// Button — 24-pin GPIO header, no strapping conflicts on S3
#define BUTTON_PIN  38   // other leg to GND; INPUT_PULLUP used

// Backlight — controlled by board, set HIGH to enable
#define TFT_BL_PIN   6

// =============================================================================
//  ── HARDWARE OBJECTS ─────────────────────────────────────────────────────────
// =============================================================================

// UART1 — used for both POS RX and Printer TX (Grove connector)
HardwareSerial posSerial(1);

// Screen: ST7796, 320×480 portrait
#define SCREEN_WIDTH  320
#define SCREEN_HEIGHT 480
TFT_eSPI tft = TFT_eSPI();

// Colours (RGB565) — DigiSlip brand palette v2.2
#define COL_BG       0xEF3B   // #E8E4DA warm parchment
#define COL_CARD     0xFFFF   // #FEFDFB off-white
#define COL_FG       0x18C2   // #1C1917 near-black
#define COL_MUTED    0x7B8D   // #78716C grey
#define COL_FAINT    0xD699   // #D6D3CD light grey
#define COL_BLUE     0x12DF   // #1558FF brand blue
#define COL_GREEN    0x064D   // #00C96A brand green
#define COL_GREEN_LT 0xEFFE   // #ECFDF5 soft green background
#define COL_GREEN_BD 0xA79A   // #A7F3D0 green border
#define COL_GREEN_DK 0x04AD   // #059669 dark green text
#define COL_RED      0xD924   // #DC2626 red
#define COL_RED_LT   0xFF9E   // #FEF2F2 soft red background

// Touch — CST826 capacitive controller on internal I2C bus
#define TOUCH_ADDR   0x15

// QR screen button geometry — shared between drawQR() and loop() hit-test
#define BTN_PRINT_X   40
#define BTN_PRINT_Y   356
#define BTN_PRINT_W   240
#define BTN_PRINT_H   48
#define BTN_CANCEL_X  70
#define BTN_CANCEL_Y  414
#define BTN_CANCEL_W  180
#define BTN_CANCEL_H  38

// NFC reader on I2C Grove connector
Adafruit_PN532 nfc(I2C_SDA, I2C_SCL);

Preferences prefs;  // NVS storage

// =============================================================================
//  ── STATE MACHINE ────────────────────────────────────────────────────────────
// =============================================================================

enum SystemState {
  STATE_IDLE,            // show clock / status; waiting for POS data
  STATE_BUFFERING,       // receiving ESC/POS bytes
  STATE_UPLOADING,       // POST to Supabase
  STATE_WAITING_CLAIM,   // show QR, poll Supabase, listen for NFC / button
  STATE_CLAIMED,         // digital claim confirmed — no print
  STATE_PRINTING,        // forwarding buffer to printer
  STATE_OFFLINE_QUEUE,   // WiFi down — store in NVS, retry later
  STATE_ERROR            // recoverable error display
};

SystemState currentState = STATE_IDLE;

// =============================================================================
//  ── SESSION DATA ─────────────────────────────────────────────────────────────
// =============================================================================

// Raw ESC/POS print buffer — 8KB, PSRAM available on S3 if needed
uint8_t  printBuffer[8192];
int      printBufferLen  = 0;

// Cleaned text lines extracted from ESC/POS for Supabase
String   receiptLines[64];
int      receiptLineCount = 0;

// Supabase slip UUID returned after POST
String   slipId = "";

// NFC UID of tapped card / phone
String   nfcUID = "";

// Timestamps
unsigned long claimWindowStart = 0;
unsigned long lastPollTime     = 0;
unsigned long lastWifiCheck    = 0;
unsigned long lastIdleRefresh  = 0;

// NVS-backed transaction counter (survives reboots)
uint32_t txCounter = 0;

// =============================================================================
//  ── OFFLINE QUEUE  (NVS) ─────────────────────────────────────────────────────
// =============================================================================

int offlineQueueLen() {
  prefs.begin("queue", true);
  int n = prefs.getInt("qlen", 0);
  prefs.end();
  return n;
}

bool offlineQueuePush(const String& json) {
  prefs.begin("queue", false);
  int n = prefs.getInt("qlen", 0);
  if (n >= OFFLINE_QUEUE_SIZE) {
    prefs.end();
    Serial.println("[Queue] Full — dropping oldest");
    prefs.begin("queue", false);
    for (int i = 0; i < OFFLINE_QUEUE_SIZE - 1; i++) {
      String val = prefs.getString(("q" + String(i + 1)).c_str(), "");
      prefs.putString(("q" + String(i)).c_str(), val);
    }
    n = OFFLINE_QUEUE_SIZE - 1;
  }
  prefs.putString(("q" + String(n)).c_str(), json);
  prefs.putInt("qlen", n + 1);
  prefs.end();
  Serial.println("[Queue] Stored. Depth: " + String(n + 1));
  return true;
}

String offlineQueuePop() {
  prefs.begin("queue", false);
  int n = prefs.getInt("qlen", 0);
  if (n == 0) { prefs.end(); return ""; }
  String val = prefs.getString("q0", "");
  for (int i = 0; i < n - 1; i++) {
    String next = prefs.getString(("q" + String(i + 1)).c_str(), "");
    prefs.putString(("q" + String(i)).c_str(), next);
  }
  prefs.putInt("qlen", n - 1);
  prefs.end();
  return val;
}

// =============================================================================
//  ── NVS TRANSACTION COUNTER ──────────────────────────────────────────────────
// =============================================================================

uint32_t loadTxCounter() {
  prefs.begin("system", true);
  uint32_t n = prefs.getUInt("txcount", 0);
  prefs.end();
  return n;
}

void saveTxCounter(uint32_t n) {
  prefs.begin("system", false);
  prefs.putUInt("txcount", n);
  prefs.end();
}

// =============================================================================
//  ── NTP / TIME ───────────────────────────────────────────────────────────────
// =============================================================================

void syncNTP() {
  configTime(TZ_OFFSET, 0, NTP_SERVER);
  Serial.print("[NTP] Syncing");
  int attempts = 0;
  time_t now = 0;
  while (now < 100000 && attempts < 20) {
    delay(500);
    Serial.print(".");
    time(&now);
    attempts++;
  }
  Serial.println(now > 100000 ? " OK" : " FAILED (will retry)");
}

String getTimestamp() {
  time_t now;
  time(&now);
  if (now < 100000) return "unknown";
  struct tm* t = gmtime(&now);
  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", t);
  return String(buf);
}

String getTimeHHMM() {
  time_t now;
  time(&now);
  if (now < 100000) return "--:--";
  struct tm* t = localtime(&now);
  char buf[6];
  strftime(buf, sizeof(buf), "%H:%M", t);
  return String(buf);
}

String getDateLine() {
  time_t now;
  time(&now);
  if (now < 100000) return "--";
  struct tm* t = localtime(&now);
  char buf[32];
  strftime(buf, sizeof(buf), "%a %d %b \xC2\xB7 %H:%M", t);
  return String(buf);
}

// =============================================================================
//  ── WIFI MANAGEMENT ──────────────────────────────────────────────────────────
// =============================================================================

void wifiConnect() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[WiFi] Connecting");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Connected: " + WiFi.localIP().toString());
    syncNTP();
  } else {
    Serial.println("\n[WiFi] FAILED — offline mode active");
  }
}

void wifiWatchdog() {
  if (millis() - lastWifiCheck < WIFI_WATCHDOG_MS) return;
  lastWifiCheck = millis();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Lost — reconnecting");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
}

// =============================================================================
//  ── TFT HELPERS — ONX3248G035 (320×480 portrait, ST7796) ────────────────────
// =============================================================================

bool readTouch(int16_t &x, int16_t &y) {
  Wire.beginTransmission(TOUCH_ADDR);
  Wire.write(0x00);
  if (Wire.endTransmission(false) != 0) return false;  // false = repeated start
  uint8_t n = Wire.requestFrom((uint8_t)TOUCH_ADDR, (uint8_t)7);
  if (n < 7) { while (Wire.available()) Wire.read(); return false; }
  uint8_t buf[7];
  for (int i = 0; i < 7; i++) buf[i] = Wire.read();
  // buf: [pad | gesture | count | xH | xL | yH | yL]
  if (buf[2] == 0) return false;
  x = ((uint16_t)(buf[3] & 0x0F) << 8) | buf[4];
  y = ((uint16_t)(buf[5] & 0x0F) << 8) | buf[6];
  return true;
}

// =============================================================================
//  ── DESIGN SYSTEM HELPERS ───────────────────────────────────────────────────
// =============================================================================

void drawWordmark(int cx, int y, int size) {
  int dw = (size == 38) ? DIGI_38_W : DIGI_22_W;
  int dh = (size == 38) ? DIGI_38_H : DIGI_22_H;
  int sw = (size == 38) ? SLIPS_38_W : SLIPS_22_W;
  int sh = (size == 38) ? SLIPS_38_H : SLIPS_22_H;
  const uint8_t* db = (size == 38) ? DIGI_38_BITMAP : DIGI_22_BITMAP;
  const uint8_t* sb = (size == 38) ? SLIPS_38_BITMAP : SLIPS_22_BITMAP;
  int xStart = cx - (dw + sw) / 2;
  tft.drawBitmap(xStart,       y, db, dw, dh, COL_BLUE,  COL_BG);
  tft.drawBitmap(xStart + dw,  y, sb, sw, sh, COL_GREEN, COL_BG);
}

void drawPill(int cx, int cy, const char* text,
              uint16_t bg, uint16_t bd, uint16_t tx,
              bool dot, uint16_t dotc) {
  tft.setFreeFont(&FreeMono9pt7b);
  int tw  = tft.textWidth(text);
  int pw  = tw + 24 + (dot ? 18 : 0);
  int ph  = 26;
  int x0  = cx - pw / 2;
  int y0  = cy - ph / 2;
  tft.fillRoundRect(x0, y0, pw, ph, 11, bg);
  tft.drawRoundRect(x0, y0, pw, ph, 11, bd);
  if (dot) {
    tft.fillCircle(x0 + 14, cy, 4, dotc);
    tft.setTextDatum(ML_DATUM);
    tft.setTextColor(tx, bg);
    tft.drawString(text, x0 + 24, cy);
  } else {
    tft.setTextDatum(MC_DATUM);
    tft.setTextColor(tx, bg);
    tft.drawString(text, cx, cy);
  }
}

void drawHeader(const char* pillText,
                uint16_t pillBg, uint16_t pillBd, uint16_t pillTx,
                bool dot) {
  tft.fillRect(0, 0, SCREEN_WIDTH, 44, COL_BG);
  int y = (44 - max(DIGI_22_H, SLIPS_22_H)) / 2;
  tft.drawBitmap(18,              y, DIGI_22_BITMAP,  DIGI_22_W,  DIGI_22_H,  COL_BLUE,  COL_BG);
  tft.drawBitmap(18 + DIGI_22_W,  y, SLIPS_22_BITMAP, SLIPS_22_W, SLIPS_22_H, COL_GREEN, COL_BG);
  tft.drawFastHLine(0, 44, SCREEN_WIDTH, COL_FAINT);
  if (pillText) {
    tft.setFreeFont(&FreeMono9pt7b);
    int tw = tft.textWidth(pillText);
    int pw = tw + 24 + (dot ? 18 : 0);
    int ph = 24;
    int x0 = SCREEN_WIDTH - 18 - pw;
    int y0 = (44 - ph) / 2;
    tft.fillRoundRect(x0, y0, pw, ph, 10, pillBg);
    tft.drawRoundRect(x0, y0, pw, ph, 10, pillBd);
    if (dot) {
      tft.fillCircle(x0 + 12, 22, 4, pillTx);
      tft.setTextDatum(ML_DATUM);
      tft.setTextColor(pillTx, pillBg);
      tft.drawString(pillText, x0 + 22, 22);
    } else {
      tft.setTextDatum(MC_DATUM);
      tft.setTextColor(pillTx, pillBg);
      tft.drawString(pillText, x0 + pw / 2, 22);
    }
  }
}

void drawFooter(const char* text) {
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(BC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString(text, SCREEN_WIDTH / 2, SCREEN_HEIGHT - 6);
  tft.setTextDatum(MC_DATUM);
}

void displayBoot(int progress) {
  tft.fillScreen(COL_BG);
  drawWordmark(SCREEN_WIDTH / 2, 215, 38);
  tft.fillRect(110, 268, 100, 3, COL_FAINT);
  if (progress > 0) tft.fillRect(110, 268, progress, 3, COL_BLUE);
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString("STARTING UP", SCREEN_WIDTH / 2, 286);
  drawFooter("v2.2  " TILL_ID "  ESP32-S3");
}

void displayMessage(const char* line1,
                    const char* line2 = "",
                    const char* line3 = "") {
  tft.fillScreen(COL_BG);
  drawHeader(nullptr, 0, 0, 0, false);
  tft.setTextDatum(MC_DATUM);

  tft.setTextColor(COL_BLUE, COL_BG);
  tft.setTextSize(3);
  tft.drawString(line1, SCREEN_WIDTH / 2, 195);

  if (strlen(line2) > 0) {
    tft.setTextColor(COL_FG, COL_BG);
    tft.setTextSize(2);
    tft.drawString(line2, SCREEN_WIDTH / 2, 255);
  }

  if (strlen(line3) > 0) {
    tft.setTextColor(COL_MUTED, COL_BG);
    tft.setTextSize(2);
    tft.drawString(line3, SCREEN_WIDTH / 2, 295);
  }
}

void displayIdle() {
  if (millis() - lastIdleRefresh < 60000) return;
  lastIdleRefresh = millis();

  tft.fillScreen(COL_BG);

  // Header with Online pill
  drawHeader("Online", COL_GREEN_LT, COL_GREEN_BD, COL_GREEN_DK, true);

  // Wordmark hero
  drawWordmark(SCREEN_WIDTH / 2, 92, 38);

  // Tagline
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString("PAPERLESS TILL SLIPS", SCREEN_WIDTH / 2, 148);

  // Headline
  tft.setFreeFont(&FreeSansBold18pt7b);
  tft.setTextColor(COL_FG, COL_BG);
  tft.drawString("Ready for next sale", SCREEN_WIDTH / 2, 220);

  // READY pill
  drawPill(SCREEN_WIDTH / 2, 258, "READY", COL_GREEN_LT, COL_GREEN_BD, COL_GREEN_DK, true, COL_GREEN);

  // Body copy
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString("Your slip will appear here \x97", SCREEN_WIDTH / 2, 306);
  tft.drawString("scan or tap to save it.", SCREEN_WIDTH / 2, 326);

  // Date / time line
  tft.drawString(getDateLine(), SCREEN_WIDTH / 2, 446);

  drawFooter("TILL-01  v2.2");
}

void drawQR(const char* text) {
  tft.fillScreen(COL_BG);
  drawHeader(nullptr, 0, 0, 0, false);

  QRCode qrcode;
  uint8_t qrcodeData[qrcode_getBufferSize(5)];
  qrcode_initText(&qrcode, qrcodeData, 5, 0, text);

  int size = qrcode.size;   // 37 modules for version 5
  int scale = 7;
  int qrPx  = size * scale;  // 259px
  int pad   = 8;
  int cardX = (SCREEN_WIDTH - qrPx) / 2 - pad;
  int cardY = 50;
  int cardW = qrPx + pad * 2;
  int cardH = qrPx + pad * 2;

  // White card (scanners need high contrast — don't use warm beige here)
  tft.fillRoundRect(cardX, cardY, cardW, cardH, 6, COL_CARD);

  int ox = cardX + pad;
  int oy = cardY + pad;
  for (int y = 0; y < size; y++) {
    for (int x = 0; x < size; x++) {
      uint16_t col = qrcode_getModule(&qrcode, x, y) ? COL_FG : COL_CARD;
      tft.fillRect(ox + x * scale, oy + y * scale, scale, scale, col);
    }
  }

  // Subtitle
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.setTextSize(2);
  tft.drawString("Scan or tap to claim", SCREEN_WIDTH / 2, cardY + cardH + 16);

  // Print button (filled green)
  tft.fillRoundRect(BTN_PRINT_X, BTN_PRINT_Y, BTN_PRINT_W, BTN_PRINT_H, 10, COL_GREEN);
  tft.setTextColor(0xFFFF, COL_GREEN);
  tft.setTextSize(2);
  tft.drawString("Print Slip", SCREEN_WIDTH / 2, BTN_PRINT_Y + BTN_PRINT_H / 2);

  // Cancel button (outlined)
  tft.fillRoundRect(BTN_CANCEL_X, BTN_CANCEL_Y, BTN_CANCEL_W, BTN_CANCEL_H, 8, COL_BG);
  tft.drawRoundRect(BTN_CANCEL_X, BTN_CANCEL_Y, BTN_CANCEL_W, BTN_CANCEL_H, 8, COL_MUTED);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.setTextSize(2);
  tft.drawString("Cancel", SCREEN_WIDTH / 2, BTN_CANCEL_Y + BTN_CANCEL_H / 2);

  // NFC hint
  tft.setTextSize(1);
  tft.setTextColor(COL_FAINT, COL_BG);
  tft.drawString("or tap NFC card", SCREEN_WIDTH / 2,
                 BTN_CANCEL_Y + BTN_CANCEL_H + 14);
}

// =============================================================================
//  ── ESC/POS PARSER ───────────────────────────────────────────────────────────
// =============================================================================

int escParamBytes(uint8_t cmd) {
  switch (cmd) {
    case 0x61: case 0x64: case 0x45:
    case 0x2D: case 0x21: case 0x4D:
    case 0x56:
      return 1;
    case 0x40:
      return 0;
    default:
      return 1;
  }
}

void parseESCPOS(uint8_t* buf, int len) {
  receiptLineCount = 0;
  String currentLine = "";

  int i = 0;
  while (i < len) {
    uint8_t b = buf[i];

    if (b == 0x1B) {
      i++;
      if (i < len) {
        uint8_t cmd = buf[i];
        int skip = escParamBytes(cmd);
        i += 1 + skip;
      }
    }
    else if (b == 0x1D) {
      i++;
      if (i < len) {
        i += 2;
      }
    }
    else if (b == 0x0A || b == 0x0D) {
      currentLine.trim();
      if (currentLine.length() > 0 && receiptLineCount < 64) {
        receiptLines[receiptLineCount++] = currentLine;
      }
      currentLine = "";
      i++;
    }
    else if (b >= 0x20 && b < 0x80) {
      currentLine += (char)b;
      i++;
    }
    else {
      i++;
    }
  }

  currentLine.trim();
  if (currentLine.length() > 0 && receiptLineCount < 64) {
    receiptLines[receiptLineCount++] = currentLine;
  }

  Serial.println("[Parser] Extracted " + String(receiptLineCount) + " text lines");
  for (int j = 0; j < receiptLineCount; j++) {
    Serial.println("  [" + String(j) + "] " + receiptLines[j]);
  }
}

// =============================================================================
//  ── SUPABASE — build JSON payload ────────────────────────────────────────────
// =============================================================================

String buildSupabaseJSON(const String& timestamp) {
  String rawText = "";
  for (int i = 0; i < receiptLineCount; i++) {
    rawText += receiptLines[i];
    if (i < receiptLineCount - 1) rawText += "\n";
  }
  rawText.replace("\\", "\\\\");
  rawText.replace("\"", "\\\"");

  DynamicJsonDocument doc(4096);
  doc["device_id"]   = DEVICE_ID;
  doc["merchant_id"] = MERCHANT_ID;
  doc["raw_text"]    = rawText;
  doc["created_at"]  = timestamp;

  String output;
  serializeJson(doc, output);
  return output;
}

// =============================================================================
//  ── SUPABASE — POST (new slip) ───────────────────────────────────────────────
// =============================================================================

String supabasePost(const String& json) {
  if (WiFi.status() != WL_CONNECTED) return "";

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient https;
  String url = String(SUPABASE_URL) + "/rest/v1/slips";

  if (!https.begin(client, url)) {
    Serial.println("[Supabase] begin() failed");
    return "";
  }

  https.addHeader("Content-Type", "application/json");
  https.addHeader("apikey",        SUPABASE_ANON);
  https.addHeader("Authorization", "Bearer " + String(SUPABASE_ANON));
  https.addHeader("Prefer",        "return=representation");

  int code = https.POST(json);

  String newSlipId = "";
  if (code >= 200 && code < 300) {
    String body = https.getString();
    DynamicJsonDocument doc(1024);
    if (deserializeJson(doc, body) == DeserializationError::Ok) {
      newSlipId = doc[0]["id"].as<String>();
    }
    Serial.println("[Supabase] POST OK → " + body);
  } else {
    Serial.println("[Supabase] POST failed: " + String(code) + " " + https.getString());
  }

  https.end();
  return newSlipId;
}

// =============================================================================
//  ── SUPABASE — NFC claim (calls nfc-claim edge function) ─────────────────────
//  Looks up the NFC card UID in nfc_cards, inserts a claims row for that user,
//  and marks the slip as claimed — all server-side with service role access.
// =============================================================================

bool supabaseNfcClaim(const String& slipId, const String& uid) {
  if (WiFi.status() != WL_CONNECTED) return false;

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient https;
  String url = String(SUPABASE_URL) + "/functions/v1/nfc-claim";

  if (!https.begin(client, url)) return false;

  https.addHeader("Content-Type",  "application/json");
  https.addHeader("apikey",         SUPABASE_ANON);
  https.addHeader("Authorization",  "Bearer " + String(SUPABASE_ANON));
  https.addHeader("X-Device-Token", DEVICE_TOKEN);

  DynamicJsonDocument doc(256);
  doc["slip_id"] = slipId;
  doc["uid"]     = uid;
  String json;
  serializeJson(doc, json);

  int code = https.POST(json);
  Serial.println("[NFC] nfc-claim → " + String(code) + " " + https.getString());
  https.end();
  return (code >= 200 && code < 300);
}

// =============================================================================
//  ── SUPABASE — GET (poll for claim status) ───────────────────────────────────
// =============================================================================

bool supabaseIsClaimed(const String& id) {
  if (WiFi.status() != WL_CONNECTED) return false;

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient https;
  String url = String(SUPABASE_URL) + "/rest/v1/slips?id=eq." + id + "&select=claimed";

  if (!https.begin(client, url)) return false;

  https.addHeader("apikey",        SUPABASE_ANON);
  https.addHeader("Authorization", "Bearer " + String(SUPABASE_ANON));

  int code = https.GET();
  bool claimed = false;

  if (code == 200) {
    String body = https.getString();
    DynamicJsonDocument doc(256);
    if (deserializeJson(doc, body) == DeserializationError::Ok) {
      claimed = doc[0]["claimed"].as<bool>();
    }
    Serial.println("[Poll] claimed=" + String(claimed));
  }

  https.end();
  return claimed;
}

// =============================================================================
//  ── OFFLINE QUEUE FLUSH ───────────────────────────────────────────────────────
// =============================================================================

void flushOfflineQueue() {
  if (WiFi.status() != WL_CONNECTED) return;
  int depth = offlineQueueLen();
  if (depth == 0) return;

  Serial.println("[Queue] Flushing " + String(depth) + " queued slips");

  while (offlineQueueLen() > 0) {
    String json = offlineQueuePop();
    if (json.length() == 0) break;
    String id = supabasePost(json);
    if (id.length() > 0) {
      Serial.println("[Queue] Flushed → " + id);
    } else {
      Serial.println("[Queue] Flush failed — re-queuing");
      offlineQueuePush(json);
      break;
    }
    delay(200);
  }
}

// =============================================================================
//  ── SETUP ────────────────────────────────────────────────────────────────────
// =============================================================================

void setup() {
  Serial.begin(115200);
  Serial.println("\n\n=== DigiSlip ONX3248G035 Booting ===");

  // ── Persistent storage ──────────────────────────────────────────────────────
  txCounter = loadTxCounter();
  Serial.println("[NVS] TX counter: " + String(txCounter));

  // ── Backlight ───────────────────────────────────────────────────────────────
  pinMode(TFT_BL_PIN, OUTPUT);
  digitalWrite(TFT_BL_PIN, HIGH);

  // ── TFT display ─────────────────────────────────────────────────────────────
  tft.init();
  tft.setRotation(0);  // portrait — 320 wide, 480 tall
  displayBoot(0);
  Serial.println("[TFT] OK — ST7796 320x480 portrait");

  // ── I2C — Grove I2C connector ───────────────────────────────────────────────
  // Bus recovery before Wire.begin() frees any device holding SDA low
  pinMode(I2C_SDA, INPUT_PULLUP);
  pinMode(I2C_SCL, OUTPUT);
  for (int i = 0; i < 9; i++) {
    digitalWrite(I2C_SCL, HIGH); delayMicroseconds(5);
    digitalWrite(I2C_SCL, LOW);  delayMicroseconds(5);
  }
  pinMode(I2C_SDA, OUTPUT);
  digitalWrite(I2C_SDA, LOW);  delayMicroseconds(5);
  digitalWrite(I2C_SCL, HIGH); delayMicroseconds(5);
  digitalWrite(I2C_SDA, HIGH); delayMicroseconds(5);
  pinMode(I2C_SCL, INPUT_PULLUP);
  pinMode(I2C_SDA, INPUT_PULLUP);
  delay(10);

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  Serial.println("[I2C] SDA=IO8 SCL=IO7 @ 400kHz");

  // ── NFC ─────────────────────────────────────────────────────────────────────
  nfc.begin();
  uint32_t nfcVer = nfc.getFirmwareVersion();
  if (!nfcVer) {
    Serial.println("[NFC] PN532 not found — check Grove I2C wiring");
    displayMessage("NFC Error", "Check Grove I2C", "SDA=IO8 SCL=IO7");
    while (true) delay(100);
  }
  Serial.printf("[NFC] PN532 v%d.%d\n",
                (nfcVer >> 16) & 0xFF, (nfcVer >> 8) & 0xFF);
  nfc.SAMConfig();

  // ── UART1 — Grove UART connector (POS RX + Printer TX) ──────────────────────
  // Both directions on the same UART — IO12=RX from POS, IO13=TX to Printer
  posSerial.begin(9600, SERIAL_8N1, UART1_RX, UART1_TX);
  posSerial.setRxBufferSize(4096);
  Serial.println("[UART1] RX=IO12 TX=IO13 @ 9600");

  // ── Button — 24-pin header IO38 ─────────────────────────────────────────────
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  // ── WiFi ────────────────────────────────────────────────────────────────────
  displayMessage("Connecting", "to WiFi...");
  wifiConnect();

  if (WiFi.status() == WL_CONNECTED) {
    displayMessage("WiFi OK", WiFi.localIP().toString().c_str(), "Time synced");
  } else {
    displayMessage("WiFi Failed", "Offline mode", "Queue active");
  }
  delay(1500);

  // ── Ready ───────────────────────────────────────────────────────────────────
  currentState    = STATE_IDLE;
  lastIdleRefresh = 0;
  Serial.println("[SYS] Ready\n");
}

// =============================================================================
//  ── LOOP ─────────────────────────────────────────────────────────────────────
// =============================================================================

bool lastButtonState = HIGH;

void loop() {

  // ── Always-running background tasks ─────────────────────────────────────────
  wifiWatchdog();

  if (currentState == STATE_IDLE) {
    flushOfflineQueue();
  }

  // ── Button edge detection ────────────────────────────────────────────────────
  bool buttonState   = digitalRead(BUTTON_PIN);
  bool buttonPressed = (lastButtonState == HIGH && buttonState == LOW);
  if (buttonPressed) delay(50);  // debounce
  lastButtonState = buttonState;

  // ── State machine ────────────────────────────────────────────────────────────
  switch (currentState) {

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_IDLE: {
      displayIdle();

      if (posSerial.available()) {
        printBufferLen   = 0;
        receiptLineCount = 0;
        slipId           = "";
        nfcUID           = "";
        currentState     = STATE_BUFFERING;
        displayMessage("Receiving...");
        Serial.println("[UART] Data incoming — buffering");
      }
      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_BUFFERING: {
      static unsigned long lastByteTime = 0;

      while (posSerial.available() > 0 && printBufferLen < 8192) {
        printBuffer[printBufferLen++] = posSerial.read();
        lastByteTime = millis();
      }

      if (printBufferLen > 0 && lastByteTime == 0) {
        lastByteTime = millis();
      }

      if (printBufferLen > 0 &&
          millis() - lastByteTime >= SERIAL_SILENCE_MS) {
        lastByteTime = 0;
        Serial.println("[UART] " + String(printBufferLen) +
                       " bytes received — parsing");

        parseESCPOS(printBuffer, printBufferLen);

        txCounter++;
        saveTxCounter(txCounter);

        currentState = STATE_UPLOADING;
        displayMessage("Loading...", ("TX #" + String(txCounter)).c_str());
      }
      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_UPLOADING: {
      String timestamp = getTimestamp();
      String json      = buildSupabaseJSON(timestamp);

      Serial.println("[Supabase] Posting slip TX#" + String(txCounter));

      if (WiFi.status() == WL_CONNECTED) {
        slipId = supabasePost(json);

        if (slipId.length() > 0) {
          currentState     = STATE_WAITING_CLAIM;
          claimWindowStart = millis();
          lastPollTime     = 0;

          String qrURL = String(QR_BASE_URL) + slipId;
          Serial.println("[QR] " + qrURL);
          drawQR(qrURL.c_str());

        } else {
          Serial.println("[Supabase] POST failed — queuing offline");
          offlineQueuePush(json);
          currentState     = STATE_WAITING_CLAIM;
          claimWindowStart = millis();
          displayMessage("Upload failed", "Tap Print for paper");
        }
      } else {
        offlineQueuePush(json);
        Serial.println("[Offline] Queued TX#" + String(txCounter));
        currentState     = STATE_WAITING_CLAIM;
        claimWindowStart = millis();
        displayMessage("No WiFi", "Tap Print for paper");
      }
      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_WAITING_CLAIM: {

      unsigned long elapsed = millis() - claimWindowStart;

      // 1. Supabase poll
      if (slipId.length() > 0 &&
          millis() - lastPollTime >= SUPABASE_POLL_MS) {
        lastPollTime = millis();
        if (supabaseIsClaimed(slipId)) {
          Serial.println("[Claim] Slip claimed via QR/app");
          currentState = STATE_CLAIMED;
          break;
        }
      }

      // 2. Touch buttons (debounced 300ms)
      static unsigned long lastTouchTime = 0;
      if (millis() - lastTouchTime > 300) {
        int16_t tx, ty;
        if (readTouch(tx, ty)) {
          lastTouchTime = millis();
          if (tx >= BTN_PRINT_X && tx < BTN_PRINT_X + BTN_PRINT_W &&
              ty >= BTN_PRINT_Y && ty < BTN_PRINT_Y + BTN_PRINT_H) {
            Serial.println("[BTN] Print tapped");
            currentState = STATE_PRINTING;
            break;
          }
          if (tx >= BTN_CANCEL_X && tx < BTN_CANCEL_X + BTN_CANCEL_W &&
              ty >= BTN_CANCEL_Y && ty < BTN_CANCEL_Y + BTN_CANCEL_H) {
            Serial.println("[BTN] Cancel tapped");
            printBufferLen   = 0;
            receiptLineCount = 0;
            slipId           = "";
            nfcUID           = "";
            currentState     = STATE_IDLE;
            lastIdleRefresh  = 0;
            break;
          }
        }
      }

      // 3. Physical button IO38 — Print fallback
      if (digitalRead(BUTTON_PIN) == LOW) {
        delay(50);
        if (digitalRead(BUTTON_PIN) == LOW) {
          Serial.println("[BTN] Physical button — printing");
          currentState = STATE_PRINTING;
          break;
        }
      }

      // 4. NFC tap
      uint8_t uid[7];
      uint8_t uidLen = 0;
      if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLen, 50)) {
        nfcUID = "";
        for (uint8_t i = 0; i < uidLen; i++) {
          if (uid[i] < 0x10) nfcUID += "0";
          nfcUID += String(uid[i], HEX);
          if (i < uidLen - 1) nfcUID += ":";
        }
        nfcUID.toUpperCase();
        Serial.println("[NFC] UID: " + nfcUID);

        displayMessage("Linking...", nfcUID.substring(0, 17).c_str());

        if (slipId.length() > 0) {
          bool ok = supabaseNfcClaim(slipId, nfcUID);
          Serial.println(ok ? "[NFC] Slip claimed via NFC card"
                            : "[NFC] nfc-claim failed — slip not linked to user");
        }

        currentState = STATE_CLAIMED;
        break;
      }

      // 5. Timeout — silent return to IDLE (digital slip unaffected, 24h expiry applies)
      if (elapsed >= CLAIM_TIMEOUT_MS) {
        Serial.println("[Timeout] No claim — returning to IDLE");
        Serial.println("[Timeout] Slip " + slipId + " remains unclaimed");
        printBufferLen   = 0;
        receiptLineCount = 0;
        slipId           = "";
        nfcUID           = "";
        currentState     = STATE_IDLE;
        lastIdleRefresh  = 0;
      }

      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_CLAIMED: {
      displayMessage("Claimed!", "Saved to your app");
      Serial.println("[SYS] Digital claim complete. Print blocked.");
      delay(2500);

      printBufferLen   = 0;
      receiptLineCount = 0;
      slipId           = "";
      nfcUID           = "";
      currentState     = STATE_IDLE;
      lastIdleRefresh  = 0;
      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_PRINTING: {
      displayMessage("Printing...", ("TX #" + String(txCounter)).c_str());
      Serial.println("[PRINT] Forwarding " +
                     String(printBufferLen) + " bytes to printer");

      posSerial.write(printBuffer, printBufferLen);
      posSerial.flush();

      Serial.println("[PRINT] Done");
      displayMessage("Printed", "Have a great day");
      delay(2000);

      printBufferLen   = 0;
      receiptLineCount = 0;
      slipId           = "";
      nfcUID           = "";
      currentState     = STATE_IDLE;
      lastIdleRefresh  = 0;
      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_ERROR: {
      static unsigned long errorTime = 0;
      if (errorTime == 0) errorTime = millis();
      if (millis() - errorTime > 3000) {
        errorTime       = 0;
        currentState    = STATE_IDLE;
        lastIdleRefresh = 0;
      }
      break;
    }

    default:
      currentState = STATE_IDLE;
      break;
  }
}
