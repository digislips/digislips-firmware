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
#include <HTTPUpdate.h>
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

const char* WIFI_SSID = "SOMO";
const char* WIFI_PASSWORD = "0836468891";

// Each physical device gets its own ID — change per unit deployed
#define TILL_ID "TILL-01"

// Supabase
#define SUPABASE_URL "https://eivctqjisodfhaitzyiq.supabase.co"
#define SUPABASE_ANON "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVpdmN0cWppc29kZmhhaXR6eWlxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY4MDgxMjIsImV4cCI6MjA5MjM4NDEyMn0._0wu91Zrc3aMrKsO_KUkp64CoOCklwMViYAofYZyCFI"

// Each physical device gets its own token — generated via provision_device() in Supabase
#define DEVICE_TOKEN "92007b7839f6909c07965ac26bd080a673a5ae16b637b237ab63945af0e66431"
#define DEVICE_ID "c42353a3-f383-49ac-aef4-06d054056ae8"
#define MERCHANT_ID "a95ec67b-4c7e-4211-922e-79dd08a9977d"

// QR code base URL — phone app will open  https://digislips.co.za/slip/<slip_uuid>
#define QR_BASE_URL "https://digislips.co.za/slip/"

// NTP
#define NTP_SERVER "pool.ntp.org"
#define TZ_OFFSET 7200  // UTC+2 (SAST) in seconds

// Timeouts
#define CLAIM_TIMEOUT_MS 60000  // 60 s before reverting to IDLE
#define SUPABASE_POLL_MS 2000   // poll Supabase every 2 s for QR claims
#define WIFI_WATCHDOG_MS 10000  // check WiFi health every 10 s
#define SERIAL_SILENCE_MS 500   // gap that signals end of ESC/POS burst

// Minimum bytes to treat a UART burst as a real ESC/POS slip (filters line noise)
#define MIN_SLIP_BYTES 16

// Offline queue
#define OFFLINE_QUEUE_SIZE 5  // max queued transactions when WiFi is down

// Firmware version — must match the GitHub release tag exactly (e.g. "v2.3.0")
#define FIRMWARE_VERSION "v2.3.0"

// =============================================================================
//  ── PIN DEFINITIONS — ONX3248G035 ───────────────────────────────────────────
// =============================================================================

// RS232 interception via UART1 Grove connector
#define UART1_RX 12  // RX from POS (via MAX3232)
#define UART1_TX 13  // TX to Printer (via MAX3232)

// I2C — Grove I2C connector (also used by touch CST826 and RTC internally)
#define I2C_SDA 8
#define I2C_SCL 7

// Button — 24-pin GPIO header, no strapping conflicts on S3
#define BUTTON_PIN 38  // other leg to GND; INPUT_PULLUP used

// Backlight — controlled by board, set HIGH to enable
#define TFT_BL_PIN 6

// =============================================================================
//  ── HARDWARE OBJECTS ─────────────────────────────────────────────────────────
// =============================================================================

// UART1 — used for both POS RX and Printer TX (Grove connector)
HardwareSerial posSerial(1);

// Screen: ST7796, 320×480 portrait
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 480
TFT_eSPI tft = TFT_eSPI();

// Colours (RGB565) — DigiSlip brand palette v2.2
#define COL_BG 0xEF3B        // #E8E4DA warm parchment
#define COL_CARD 0xFFFF      // #FEFDFB off-white
#define COL_FG 0x18C2        // #1C1917 near-black
#define COL_MUTED 0x7B8D     // #78716C grey
#define COL_FAINT 0xD699     // #D6D3CD light grey
#define COL_BLUE 0x12DF      // #1558FF brand blue
#define COL_GREEN 0x064D     // #00C96A brand green
#define COL_GREEN_LT 0xEFFE  // #ECFDF5 soft green background
#define COL_GREEN_BD 0xA79A  // #A7F3D0 green border
#define COL_GREEN_DK 0x04AD  // #059669 dark green text
#define COL_RED 0xD924       // #DC2626 red
#define COL_RED_LT 0xFF9E    // #FEF2F2 soft red background

// Touch — CST826 capacitive controller on internal I2C bus
#define TOUCH_ADDR 0x15

// QR screen button geometry — shared between drawQR() and loop() hit-test
#define BTN_PRINT_X 40
#define BTN_PRINT_Y 356
#define BTN_PRINT_W 240
#define BTN_PRINT_H 48
#define BTN_CANCEL_X 70
#define BTN_CANCEL_Y 414
#define BTN_CANCEL_W 180
#define BTN_CANCEL_H 38

// NFC reader on I2C Grove connector
Adafruit_PN532 nfc(I2C_SDA, I2C_SCL);

Preferences prefs;  // NVS storage

// =============================================================================
//  ── STATE MACHINE ────────────────────────────────────────────────────────────
// =============================================================================

enum SystemState {
  STATE_IDLE,           // show clock / status; waiting for POS data
  STATE_BUFFERING,      // receiving ESC/POS bytes
  STATE_UPLOADING,      // POST to Supabase
  STATE_WAITING_CLAIM,  // show QR, poll Supabase, listen for NFC / button
  STATE_CLAIMED,        // digital claim confirmed — no print
  STATE_CANCELLED,      // 1-second confirmation after cashier cancels
  STATE_PRINTING,       // forwarding buffer to printer
  STATE_OFFLINE_QUEUE,  // WiFi down — store in NVS, retry later
  STATE_OFFLINE,        // WiFi lost >30 s — dedicated offline screen
  STATE_ERROR           // recoverable error display
};

SystemState currentState = STATE_IDLE;

enum ClaimMethod { CLAIM_NONE,
                   CLAIM_NFC,
                   CLAIM_QR };
ClaimMethod claimMethod = CLAIM_NONE;

// =============================================================================
//  ── SESSION DATA ─────────────────────────────────────────────────────────────
// =============================================================================

// Raw ESC/POS print buffer — 8KB, PSRAM available on S3 if needed
uint8_t printBuffer[8192];
int printBufferLen = 0;

// Cleaned text lines extracted from ESC/POS for Supabase
String receiptLines[64];
int receiptLineCount = 0;

// Supabase slip UUID returned after POST
String slipId = "";

// NFC UID of tapped card / phone
String nfcUID = "";

// Timestamps
unsigned long claimWindowStart = 0;
unsigned long lastPollTime = 0;
unsigned long lastWifiCheck = 0;
unsigned long lastIdleRefresh = 0;

// Offline watchdog
unsigned long wifiLostTime = 0;
SystemState preOfflineState = STATE_IDLE;

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
  if (n == 0) {
    prefs.end();
    return "";
  }
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
    if (wifiLostTime == 0) wifiLostTime = millis();
    Serial.println("[WiFi] Lost — reconnecting");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    if (millis() - wifiLostTime > 30000 && currentState != STATE_OFFLINE) {
      preOfflineState = currentState;
      currentState = STATE_OFFLINE;
    }
  } else {
    if (currentState == STATE_OFFLINE) {
      Serial.println("[WiFi] Reconnected — restoring state");
      currentState = preOfflineState;
      lastIdleRefresh = 0;
    }
    wifiLostTime = 0;
  }
}

// =============================================================================
//  ── TFT HELPERS — ONX3248G035 (320×480 portrait, ST7796) ────────────────────
// =============================================================================

bool readTouch(int16_t& x, int16_t& y) {
  Wire.beginTransmission(TOUCH_ADDR);
  Wire.write(0x00);
  if (Wire.endTransmission(false) != 0) return false;  // false = repeated start
  uint8_t n = Wire.requestFrom((uint8_t)TOUCH_ADDR, (uint8_t)7);
  if (n < 7) {
    while (Wire.available()) Wire.read();
    return false;
  }
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
  tft.drawBitmap(xStart, y, db, dw, dh, COL_BLUE, COL_BG);
  tft.drawBitmap(xStart + dw, y, sb, sw, sh, COL_GREEN, COL_BG);
}

void drawPill(int cx, int cy, const char* text,
              uint16_t bg, uint16_t bd, uint16_t tx,
              bool dot, uint16_t dotc) {
  tft.setFreeFont(nullptr);
  tft.setTextSize(2);
  int tw = tft.textWidth(text);
  int pw = tw + 24 + (dot ? 18 : 0);
  int ph = 26;
  int x0 = cx - pw / 2;
  int y0 = cy - ph / 2;
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
  tft.setTextSize(1);
  tft.setTextDatum(MC_DATUM);  // always restore
}

void drawHeader(const char* pillText,
                uint16_t pillBg, uint16_t pillBd, uint16_t pillTx,
                bool dot) {
  tft.fillRect(0, 0, SCREEN_WIDTH, 44, COL_BG);
  int y = (44 - max(DIGI_22_H, SLIPS_22_H)) / 2;
  tft.drawBitmap(18, y, DIGI_22_BITMAP, DIGI_22_W, DIGI_22_H, COL_BLUE, COL_BG);
  tft.drawBitmap(18 + DIGI_22_W, y, SLIPS_22_BITMAP, SLIPS_22_W, SLIPS_22_H, COL_GREEN, COL_BG);
  tft.drawFastHLine(0, 44, SCREEN_WIDTH, COL_FAINT);
  if (pillText) {
    tft.setFreeFont(nullptr);
    tft.setTextSize(2);
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
  tft.setTextSize(1);
  tft.setTextDatum(MC_DATUM);  // always restore
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
  tft.fillRect(60, 268, 200, 3, COL_FAINT);
  if (progress > 0) tft.fillRect(60, 268, (progress * 200) / 100, 3, COL_BLUE);
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString("STARTING UP", SCREEN_WIDTH / 2, 286);
  drawFooter(TILL_ID "  v2.2");
}

void bootProgress(int pct, const char* status) {
  tft.fillRect(60, 265, 200, 9, COL_BG);
  tft.fillRect(60, 268, 200, 3, COL_FAINT);
  if (pct > 0) tft.fillRect(60, 268, (pct * 200) / 100, 3, COL_BLUE);
  tft.fillRect(0, 278, SCREEN_WIDTH, 16, COL_BG);
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString(status, SCREEN_WIDTH / 2, 286);
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
  if (lastIdleRefresh != 0 && millis() - lastIdleRefresh < 60000) return;
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
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_FG, COL_BG);
  tft.drawString("Ready for next sale", SCREEN_WIDTH / 2, 220);

  // READY pill
  drawPill(SCREEN_WIDTH / 2, 258, "READY", COL_GREEN_LT, COL_GREEN_BD, COL_GREEN_DK, true, COL_GREEN);

  // Body copy — reset datum after pill (pill may leave ML_DATUM)
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString("Your slip appears here", SCREEN_WIDTH / 2, 306);
  tft.drawString("scan or tap to save it.", SCREEN_WIDTH / 2, 326);

  // Date / time line
  tft.setTextDatum(MC_DATUM);
  tft.drawString(getDateLine(), SCREEN_WIDTH / 2, 446);

  drawFooter("TILL-01  v2.2");
}

void drawQR(const char* text) {
  tft.fillScreen(COL_BG);
  drawHeader("Awaiting claim", COL_GREEN_LT, COL_GREEN_BD, COL_GREEN_DK, true);

  // Receipt card
  int cardX = 22;
  int cardY = 58;
  int cardW = SCREEN_WIDTH - 44;  // 276px
  int cardH = 256;
  tft.fillRoundRect(cardX, cardY, cardW, cardH, 8, COL_CARD);
  tft.drawRoundRect(cardX, cardY, cardW, cardH, 8, COL_FAINT);

  // QR code — version 5, scale 5 → 185×185px, centred in card
  QRCode qrcode;
  uint8_t qrcodeData[qrcode_getBufferSize(5)];
  qrcode_initText(&qrcode, qrcodeData, 5, 0, text);
  int scale = 5;
  int qrPx = qrcode.size * scale;
  int ox = cardX + (cardW - qrPx) / 2;
  int oy = cardY + 10;
  for (int y = 0; y < qrcode.size; y++) {
    for (int x = 0; x < qrcode.size; x++) {
      uint16_t col = qrcode_getModule(&qrcode, x, y) ? TFT_BLACK : COL_CARD;
      tft.fillRect(ox + x * scale, oy + y * scale, scale, scale, col);
    }
  }

  // Slip label
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_FG, COL_CARD);
  tft.drawString(("Slip #" + String(txCounter)).c_str(),
                 cardX + cardW / 2, oy + qrPx + 16);

  // Caption below card
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString("SCAN QR OR TAP NFC", SCREEN_WIDTH / 2, cardY + cardH + 18);

  // Print button
  tft.fillRoundRect(BTN_PRINT_X, BTN_PRINT_Y, BTN_PRINT_W, BTN_PRINT_H, 10, COL_GREEN);
  tft.setFreeFont(nullptr);
  tft.setTextSize(2);
  tft.setTextColor(0xFFFF, COL_GREEN);
  tft.setTextDatum(MC_DATUM);
  tft.drawString("Print slip", SCREEN_WIDTH / 2, BTN_PRINT_Y + BTN_PRINT_H / 2);

  // Cancel button
  tft.fillRoundRect(BTN_CANCEL_X, BTN_CANCEL_Y, BTN_CANCEL_W, BTN_CANCEL_H, 8, COL_BG);
  tft.drawRoundRect(BTN_CANCEL_X, BTN_CANCEL_Y, BTN_CANCEL_W, BTN_CANCEL_H, 8, COL_FAINT);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString("Cancel", SCREEN_WIDTH / 2, BTN_CANCEL_Y + BTN_CANCEL_H / 2);
  tft.setTextSize(1);
}

// =============================================================================
//  ── PRINTING SCREEN ──────────────────────────────────────────────────────────
// =============================================================================

void drawPrinting() {
  tft.fillScreen(COL_BG);
  drawHeader(nullptr, 0, 0, 0, false);

  // Spinner ring — static faint background
  int cx = SCREEN_WIDTH / 2;
  int cy = 152;
  tft.drawArc(cx, cy, 36, 30, 0, 360, COL_FAINT, COL_BG);

  // Headline
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_FG, COL_BG);
  tft.drawString("Printing slip", SCREEN_WIDTH / 2, 220);

  // Slip sub-label
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString(("Slip #" + String(txCounter)).c_str(), SCREEN_WIDTH / 2, 248);

  drawFooter(TILL_ID "  v2.2");
}

// =============================================================================
//  ── NFC LINKING SCREEN ───────────────────────────────────────────────────────
// =============================================================================

void drawNfcLinking(const String& uid) {
  tft.fillScreen(COL_BG);
  drawHeader(nullptr, 0, 0, 0, false);

  // Concentric rings (outermost first, faint)
  int cx = SCREEN_WIDTH / 2;
  int cy = 150;
  tft.drawCircle(cx, cy, 56, COL_FAINT);
  tft.drawCircle(cx, cy, 44, COL_FAINT);
  tft.drawCircle(cx, cy, 32, COL_FAINT);

  // Blue NFC disc
  tft.fillCircle(cx, cy, 24, COL_BLUE);

  // NFC symbol — three right-facing arcs inside disc
  tft.drawArc(cx, cy, 18, 15, 315, 45, 0xFFFF, COL_BLUE);
  tft.drawArc(cx, cy, 12, 9, 315, 45, 0xFFFF, COL_BLUE);
  tft.drawArc(cx, cy, 6, 3, 315, 45, 0xFFFF, COL_BLUE);

  // Headline
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_FG, COL_BG);
  tft.drawString("Card detected", SCREEN_WIDTH / 2, 224);

  // UID and status
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString(uid.c_str(), SCREEN_WIDTH / 2, 254);
  tft.drawString("Claiming slip...", SCREEN_WIDTH / 2, 274);

  drawFooter("HOLD CARD ON READER");
}

// =============================================================================
//  ── CANCELLED SCREEN ─────────────────────────────────────────────────────────
// =============================================================================

void drawCancelled() {
  tft.fillScreen(COL_BG);
  drawHeader(nullptr, 0, 0, 0, false);

  // X circle
  int cx = SCREEN_WIDTH / 2;
  int cy = 152;
  tft.drawCircle(cx, cy, 40, COL_FAINT);
  tft.drawCircle(cx, cy, 39, COL_FAINT);
  // X arms
  tft.drawLine(cx - 17, cy - 17, cx + 17, cy + 17, COL_MUTED);
  tft.drawLine(cx - 17, cy - 16, cx + 17, cy + 16, COL_MUTED);
  tft.drawLine(cx + 17, cy - 17, cx - 17, cy + 17, COL_MUTED);
  tft.drawLine(cx + 17, cy - 16, cx - 17, cy + 16, COL_MUTED);

  // Headline
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_FG, COL_BG);
  tft.drawString("Print cancelled", SCREEN_WIDTH / 2, 218);

  // Body copy
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString("No paper slip will print.", SCREEN_WIDTH / 2, 252);
  tft.drawString("Digital slip claimable 24h.", SCREEN_WIDTH / 2, 272);

  drawFooter("Returning to idle...");
}

// =============================================================================
//  ── CLAIMED SCREEN ───────────────────────────────────────────────────────────
// =============================================================================

void drawClaimed() {
  tft.fillScreen(COL_BG);
  drawHeader(nullptr, 0, 0, 0, false);

  // Green disc with checkmark
  int cx = SCREEN_WIDTH / 2;
  int cy = 148;
  tft.fillCircle(cx, cy, 44, COL_GREEN_LT);
  tft.drawCircle(cx, cy, 44, COL_GREEN_BD);
  tft.drawCircle(cx, cy, 43, COL_GREEN_BD);
  // Checkmark
  tft.drawLine(cx - 18, cy, cx - 6, cy + 14, COL_GREEN_DK);
  tft.drawLine(cx - 18, cy + 1, cx - 6, cy + 15, COL_GREEN_DK);
  tft.drawLine(cx - 6, cy + 14, cx + 18, cy - 14, COL_GREEN_DK);
  tft.drawLine(cx - 6, cy + 15, cx + 18, cy - 13, COL_GREEN_DK);

  // Headline
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_FG, COL_BG);
  tft.drawString("Slip claimed", SCREEN_WIDTH / 2, 220);

  // Via attribution
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  const char* via = (claimMethod == CLAIM_NFC) ? "Claimed via NFC card"
                                               : "Claimed via QR / App";
  tft.drawString(via, SCREEN_WIDTH / 2, 252);

  // VERIFIED pill
  drawPill(SCREEN_WIDTH / 2, 292, "VERIFIED", COL_GREEN_LT, COL_GREEN_BD, COL_GREEN_DK, true, COL_GREEN);
  tft.setTextDatum(MC_DATUM);

  drawFooter(TILL_ID "  returning to idle");
}

// =============================================================================
//  ── OFFLINE SCREEN ───────────────────────────────────────────────────────────
// =============================================================================

void drawOffline() {
  tft.fillScreen(COL_BG);
  drawHeader("Offline", COL_RED_LT, 0xFE65, COL_RED, true);

  // Red disc
  int cx = SCREEN_WIDTH / 2;
  tft.fillCircle(cx, 130, 36, COL_RED_LT);
  tft.drawCircle(cx, 130, 36, 0xFE65);
  tft.drawCircle(cx, 130, 35, 0xFE65);
  // WiFi-off icon: two arcs + diagonal strike (approx with lines)
  tft.drawLine(cx - 18, cx - 50, cx + 18, cx - 6, COL_RED);  // diagonal slash
  tft.drawLine(cx - 19, cx - 50, cx + 19, cx - 6, COL_RED);

  // Headline
  tft.setFreeFont(&FreeSansBold9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_FG, COL_BG);
  tft.drawString("Lost connection", SCREEN_WIDTH / 2, 196);

  // Body
  tft.setFreeFont(&FreeMono9pt7b);
  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_MUTED, COL_BG);
  tft.drawString("Slips will queue locally and", SCREEN_WIDTH / 2, 226);
  tft.drawString("upload when WiFi returns.", SCREEN_WIDTH / 2, 246);

  drawFooter(TILL_ID "  check router");
}

// =============================================================================
//  ── ESC/POS PARSER ───────────────────────────────────────────────────────────
// =============================================================================

int escParamBytes(uint8_t cmd) {
  switch (cmd) {
    case 0x61:
    case 0x64:
    case 0x45:
    case 0x2D:
    case 0x21:
    case 0x4D:
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
    } else if (b == 0x1D) {
      i++;
      if (i < len) {
        i += 2;
      }
    } else if (b == 0x0A || b == 0x0D) {
      currentLine.trim();
      if (currentLine.length() > 0 && receiptLineCount < 64) {
        receiptLines[receiptLineCount++] = currentLine;
      }
      currentLine = "";
      i++;
    } else if (b >= 0x20 && b < 0x80) {
      currentLine += (char)b;
      i++;
    } else {
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
  doc["device_id"] = DEVICE_ID;
  doc["merchant_id"] = MERCHANT_ID;
  doc["raw_text"] = rawText;
  doc["created_at"] = timestamp;

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
  https.addHeader("apikey", SUPABASE_ANON);
  https.addHeader("Authorization", "Bearer " + String(SUPABASE_ANON));
  https.addHeader("Prefer", "return=representation");

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

  https.addHeader("Content-Type", "application/json");
  https.addHeader("apikey", SUPABASE_ANON);
  https.addHeader("Authorization", "Bearer " + String(SUPABASE_ANON));
  https.addHeader("X-Device-Token", DEVICE_TOKEN);

  DynamicJsonDocument doc(256);
  doc["slip_id"] = slipId;
  doc["uid"] = uid;
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

  https.addHeader("apikey", SUPABASE_ANON);
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
//  ── OTA UPDATE ───────────────────────────────────────────────────────────────
// =============================================================================

// DigiCert Global Root CA — validates api.github.com and objects.githubusercontent.com
// If this cert ever expires or changes, obtain the new one with:
//   openssl s_client -showcerts -connect api.github.com:443 2>/dev/null | openssl x509 -text
static const char GITHUB_ROOT_CA[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
MIIDrzCCApegAwIBAgIQCDvgVpBCRrGhdWrJWZHHSjANBgkqhkiG9w0BAQUFADBh
MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3
d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBD
QTAeFw0wNjExMTAwMDAwMDBaFw0zMTExMTAwMDAwMDBaMGExCzAJBgNVBAYTAlVT
MRUwEzYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5j
b20xIDAeBgNVBAMTF0RpZ2lDZXJ0IEdsb2JhbCBSb290IENBMB4XDTA2MTExMDAw
MDAwMFoXDTMxMTExMDAwMDAwMFowYTELMAkGA1UEBhMCVVMxFTATBgNVBAoTDERp
Z2lDZXJ0IEluYzEZMBcGA1UECxMQd3d3LmRpZ2ljZXJ0LmNvbTEgMB4GA1UEAxMX
RGlnaUNlcnQgR2xvYmFsIFJvb3QgQ0EwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAw
ggEKAoIBAQDiO6qA5dqS4ZkQ6uGwFMBXSZ3B4CZBR7x7kjyFOtPjnX7aBN4AMRJ
DnXJBBhHzEHJB0VQpkYWAHBChCaA3LK+dlBSbI0bVGRbC3o1KvMOLqCLbZmUwlzn
pJYXYa4cFVhZpGm6uDmM6H8f9JiXzgOMmOaTmD5wjFEgPm3BFW0Kki3DvxP7bUXJ
J3+o1eMBknUe7O0ZVyENgJBekBBqbIqWvCEBhjFKSmzOBuFDNQbdnDWnl2Wq31KZ
vvMfcTxIJnFTjJLhYeSPVKe/2XrJcWEBiI7RrCjU7/fCODipkVgHoGHNgCx8RQID
AQABo0IwQDAPBgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBhjAdBgNVHQ4E
FgQUA95QNVbRTLtm8KPiGxvDl7I90VUwDQYJKoZIhvcNAQEFBQADggEBAMaKkG9s
m1SDw+4ULQJQTJ7HjBnzPdRhDjqXJe5DzKLnWQq4lCCxEi3iFjDm4LHf0iNlxO1
-----END CERTIFICATE-----
)EOF";

void checkOTA() {
  WiFiClientSecure client;
  client.setInsecure();  // TODO: replace with client.setCACert(GITHUB_ROOT_CA) once cert verified on hardware

  HTTPClient https;
  https.setTimeout(8000);
  if (!https.begin(client, "https://api.github.com/repos/digislips/digislips-firmware/releases/latest")) {
    Serial.println("[OTA] Check failed — begin");
    return;
  }
  https.addHeader("User-Agent", "DigiSlip/" FIRMWARE_VERSION);

  int code = https.GET();
  if (code != HTTP_CODE_OK) {
    Serial.println("[OTA] Check failed — HTTP " + String(code));
    https.end();
    return;
  }

  String payload = https.getString();
  https.end();

  DynamicJsonDocument doc(8192);
  if (deserializeJson(doc, payload)) {
    Serial.println("[OTA] Check failed — JSON");
    return;
  }

  const char* tag = doc["tag_name"] | "";
  if (!tag[0]) {
    Serial.println("[OTA] Check failed — no tag_name");
    return;
  }

  String binUrl;
  for (JsonObject asset : doc["assets"].as<JsonArray>()) {
    if (strcmp(asset["name"] | "", "DigiSlip_ONX3248G035.bin") == 0) {
      binUrl = asset["browser_download_url"] | "";
      break;
    }
  }

  if (strcmp(tag, FIRMWARE_VERSION) == 0) {
    Serial.println("[OTA] Up to date (" FIRMWARE_VERSION ")");
    return;
  }

  if (binUrl.isEmpty()) {
    Serial.println("[OTA] Check failed — DigiSlip_ONX3248G035.bin not in release");
    return;
  }

  Serial.println("[OTA] Update available: " + String(tag));
  applyOTA(binUrl);
}

void applyOTA(String url) {
  Serial.println("[OTA] Downloading " + url);
  bootProgress(50, "UPDATING...");

  WiFiClientSecure client;
  client.setInsecure();

  httpUpdate.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  httpUpdate.onProgress([](int cur, int total) {
    if (total > 0) bootProgress(map(cur, 0, total, 50, 100), "UPDATING...");
  });

  t_httpUpdate_return ret = httpUpdate.update(client, url);

  if (ret == HTTP_UPDATE_FAILED)
    Serial.println("[OTA] Update failed: " + httpUpdate.getLastErrorString());
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
    digitalWrite(I2C_SCL, HIGH);
    delayMicroseconds(5);
    digitalWrite(I2C_SCL, LOW);
    delayMicroseconds(5);
  }
  pinMode(I2C_SDA, OUTPUT);
  digitalWrite(I2C_SDA, LOW);
  delayMicroseconds(5);
  digitalWrite(I2C_SCL, HIGH);
  delayMicroseconds(5);
  digitalWrite(I2C_SDA, HIGH);
  delayMicroseconds(5);
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

  // ── WiFi — boot screen stays visible throughout ──────────────────────────────
  unsigned long bootStart = millis();
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) {
    bootProgress(5 + i * 2, "CONNECTING...");
    delay(500);
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("[WiFi] Connected: " + WiFi.localIP().toString());
    bootProgress(45, "CHECKING UPDATE...");
    checkOTA();
    bootProgress(48, "SYNCING TIME...");
    configTime(TZ_OFFSET, 0, NTP_SERVER);
    time_t now = 0;
    for (int i = 0; i < 20 && now < 100000; i++) {
      bootProgress(45 + i * 2, "SYNCING TIME...");
      delay(500);
      time(&now);
    }
    if (now > 100000) {
      Serial.println("[NTP] Synced");
      bootProgress(90, "TIME SYNCED");
    } else {
      Serial.println("[NTP] FAILED — will retry");
      bootProgress(90, "TIME FAILED");
    }
  } else {
    Serial.println("[WiFi] FAILED — offline mode");
    bootProgress(50, "OFFLINE MODE");
  }

  bootProgress(100, "READY");

  // Hold boot screen for at least 4 s so user can see it
  long remaining = 4000 - (long)(millis() - bootStart);
  if (remaining > 0) delay((unsigned long)remaining);

  // ── Ready ───────────────────────────────────────────────────────────────────
  currentState = STATE_IDLE;
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
  bool buttonState = digitalRead(BUTTON_PIN);
  bool buttonPressed = (lastButtonState == HIGH && buttonState == LOW);
  if (buttonPressed) delay(50);  // debounce
  lastButtonState = buttonState;

  // ── State machine ────────────────────────────────────────────────────────────
  switch (currentState) {

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_IDLE:
      {
        displayIdle();

        if (posSerial.available()) {
          printBufferLen = 0;
          receiptLineCount = 0;
          slipId = "";
          nfcUID = "";
          currentState = STATE_BUFFERING;
          Serial.println("[UART] Data incoming — buffering");
        }
        break;
      }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_BUFFERING:
      {
        static unsigned long lastByteTime = 0;

        while (posSerial.available() > 0 && printBufferLen < 8192) {
          printBuffer[printBufferLen++] = posSerial.read();
          lastByteTime = millis();
        }

        if (printBufferLen > 0 && lastByteTime == 0) {
          lastByteTime = millis();
        }

        if (printBufferLen > 0 && millis() - lastByteTime >= SERIAL_SILENCE_MS) {
          lastByteTime = 0;
          Serial.println("[UART] " + String(printBufferLen) + " bytes received — parsing");

          if (printBufferLen < MIN_SLIP_BYTES) {
            Serial.println("[UART] Too short — discarding (noise)");
            printBufferLen = 0;
            currentState = STATE_IDLE;
            break;
          }

          parseESCPOS(printBuffer, printBufferLen);

          if (receiptLineCount == 0) {
            Serial.println("[Parser] No text extracted — discarding (noise)");
            printBufferLen = 0;
            currentState = STATE_IDLE;
            break;
          }

          txCounter++;
          saveTxCounter(txCounter);

          currentState = STATE_UPLOADING;
        }
        break;
      }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_UPLOADING:
      {
        String timestamp = getTimestamp();
        String json = buildSupabaseJSON(timestamp);

        Serial.println("[Supabase] Posting slip TX#" + String(txCounter));

        if (WiFi.status() == WL_CONNECTED) {
          slipId = supabasePost(json);

          if (slipId.length() > 0) {
            currentState = STATE_WAITING_CLAIM;
            claimWindowStart = millis();
            lastPollTime = 0;

            String qrURL = String(QR_BASE_URL) + slipId;
            Serial.println("[QR] " + qrURL);
            drawQR(qrURL.c_str());

          } else {
            Serial.println("[Supabase] POST failed — queuing offline");
            offlineQueuePush(json);
            currentState = STATE_WAITING_CLAIM;
            claimWindowStart = millis();
            displayMessage("Upload failed", "Tap Print for paper");
          }
        } else {
          offlineQueuePush(json);
          Serial.println("[Offline] Queued TX#" + String(txCounter));
          currentState = STATE_WAITING_CLAIM;
          claimWindowStart = millis();
          displayMessage("No WiFi", "Tap Print for paper");
        }
        break;
      }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_WAITING_CLAIM:
      {

        unsigned long elapsed = millis() - claimWindowStart;

        // 1. Supabase poll
        if (slipId.length() > 0 && millis() - lastPollTime >= SUPABASE_POLL_MS) {
          lastPollTime = millis();
          if (supabaseIsClaimed(slipId)) {
            Serial.println("[Claim] Slip claimed via QR/app");
            claimMethod = CLAIM_QR;
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
            if (tx >= BTN_PRINT_X && tx < BTN_PRINT_X + BTN_PRINT_W && ty >= BTN_PRINT_Y && ty < BTN_PRINT_Y + BTN_PRINT_H) {
              Serial.println("[BTN] Print tapped");
              currentState = STATE_PRINTING;
              break;
            }
            if (tx >= BTN_CANCEL_X && tx < BTN_CANCEL_X + BTN_CANCEL_W && ty >= BTN_CANCEL_Y && ty < BTN_CANCEL_Y + BTN_CANCEL_H) {
              Serial.println("[BTN] Cancel tapped");
              printBufferLen = 0;
              receiptLineCount = 0;
              slipId = "";
              nfcUID = "";
              currentState = STATE_CANCELLED;
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

          drawNfcLinking(nfcUID);

          if (slipId.length() > 0) {
            bool ok = supabaseNfcClaim(slipId, nfcUID);
            Serial.println(ok ? "[NFC] Slip claimed via NFC card"
                              : "[NFC] nfc-claim failed — slip not linked to user");
          }

          claimMethod = CLAIM_NFC;
          currentState = STATE_CLAIMED;
          break;
        }

        // 5. Timeout — silent return to IDLE (digital slip unaffected, 24h expiry applies)
        if (elapsed >= CLAIM_TIMEOUT_MS) {
          Serial.println("[Timeout] No claim — returning to IDLE");
          Serial.println("[Timeout] Slip " + slipId + " remains unclaimed");
          printBufferLen = 0;
          receiptLineCount = 0;
          slipId = "";
          nfcUID = "";
          currentState = STATE_IDLE;
          lastIdleRefresh = 0;
        }

        // 6. Countdown footer — update once per second
        static unsigned long lastFooterUpdate = 0;
        if (millis() - lastFooterUpdate >= 1000) {
          lastFooterUpdate = millis();
          int remaining = max(0L, (long)(CLAIM_TIMEOUT_MS - elapsed)) / 1000;
          char countdown[32];
          sprintf(countdown, "TILL-01  waiting  %d:%02d", remaining / 60, remaining % 60);
          drawFooter(countdown);
        }

        break;
      }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_CLAIMED:
      {
        static unsigned long claimedAt = 0;
        if (claimedAt == 0) {
          drawClaimed();
          Serial.println("[SYS] Digital claim complete. Print blocked.");
          claimedAt = millis();
        }
        if (millis() - claimedAt >= 9000) {
          claimedAt = 0;
          claimMethod = CLAIM_NONE;
          printBufferLen = 0;
          receiptLineCount = 0;
          slipId = "";
          nfcUID = "";
          currentState = STATE_IDLE;
          lastIdleRefresh = 0;
        }
        break;
      }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_CANCELLED:
      {
        static unsigned long cancelledAt = 0;
        if (cancelledAt == 0) {
          drawCancelled();
          cancelledAt = millis();
        }
        if (millis() - cancelledAt >= 3000) {
          cancelledAt = 0;
          currentState = STATE_IDLE;
          lastIdleRefresh = 0;
        }
        break;
      }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_PRINTING:
      {
        static unsigned long printDoneAt = 0;
        static int spinAngle = 0;
        static unsigned long lastSpin = 0;

        if (printDoneAt == 0) {
          drawPrinting();
          Serial.println("[PRINT] Forwarding " + String(printBufferLen) + " bytes to printer");
          posSerial.write(printBuffer, printBufferLen);
          posSerial.flush();
          Serial.println("[PRINT] Done");
          printBufferLen = 0;
          receiptLineCount = 0;
          slipId = "";
          nfcUID = "";
          printDoneAt = millis();
        }

        // Spinner animation — advance 10° every 28 ms
        if (millis() - lastSpin >= 28) {
          lastSpin = millis();
          int cx = SCREEN_WIDTH / 2;
          int cy = 152;
          tft.drawArc(cx, cy, 36, 30, spinAngle, spinAngle + 90, COL_BLUE, COL_BG);
          tft.drawArc(cx, cy, 36, 30, (spinAngle + 90) % 360, (spinAngle + 180) % 360, COL_FAINT, COL_BG);
          spinAngle = (spinAngle + 10) % 360;
        }

        // Hold for 3 s so user can see the printing screen
        if (millis() - printDoneAt >= 3000) {
          printDoneAt = 0;
          spinAngle = 0;
          currentState = STATE_IDLE;
          lastIdleRefresh = 0;
        }
        break;
      }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_OFFLINE:
      {
        static bool offlineDrawn = false;
        static unsigned long lastOfflineUpdate = 0;
        if (!offlineDrawn) {
          drawOffline();
          offlineDrawn = true;
        }
        // Update info cards every second
        if (millis() - lastOfflineUpdate >= 1000) {
          lastOfflineUpdate = millis();
          int depth = offlineQueueLen();
          char queuedStr[8];
          sprintf(queuedStr, "%d", depth);
          // Info card: queued slips
          tft.setFreeFont(&FreeMono9pt7b);
          tft.setTextDatum(ML_DATUM);
          tft.setTextColor(COL_FG, COL_CARD);
          tft.fillRoundRect(22, 278, SCREEN_WIDTH - 44, 36, 6, COL_CARD);
          tft.drawRoundRect(22, 278, SCREEN_WIDTH - 44, 36, 6, COL_FAINT);
          tft.drawString("Queued slips", 34, 296);
          tft.setTextDatum(MR_DATUM);
          tft.drawString(queuedStr, SCREEN_WIDTH - 34, 296);
          tft.setTextDatum(MC_DATUM);
        }
        // wifiWatchdog handles reconnect and state restore
        if (WiFi.status() == WL_CONNECTED) offlineDrawn = false;
        break;
      }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_ERROR:
      {
        static unsigned long errorTime = 0;
        if (errorTime == 0) errorTime = millis();
        if (millis() - errorTime > 3000) {
          errorTime = 0;
          currentState = STATE_IDLE;
          lastIdleRefresh = 0;
        }
        break;
      }

    default:
      currentState = STATE_IDLE;
      break;
  }
}
