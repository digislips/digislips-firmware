// =============================================================================
//  DigiSlip — ONX3248G035 (ESP32-S3, 3.5" ST7796, 320×480)
//
//  What this device does:
//    • Sits between a POS machine and a thermal printer on RS232
//    • Intercepts the raw ESC/POS byte stream
//    • Strips control codes → clean text → uploads to Supabase
//    • Displays a QR code on TFT so customer can claim slip digitally
//    • Reads NFC card/phone UID to link slip to a user account
//    • Polls Supabase to detect QR-based claims (iPhone users via app)
//    • If claimed digitally → print is blocked (green flow)
//    • If not claimed within 60s → customer may press button for paper slip
//    • Offline queue: if WiFi down, stores up to 5 transactions in NVS
//
//  Board: ONX3248G035 (Nextion Genius Series)
//    MCU:     ESP32-S3R8 (8MB PSRAM, 16MB Flash)
//    Display: 3.5" ST7796, 320×480, capacitive touch (CST826)
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
//    (SPI pins are internal — let the board BSP handle them,
//     or use the Nextion example User_Setup.h from their GitHub)
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
#include <TFT_eSPI.h>
#include <Adafruit_PN532.h>
#include <QRCodeGenerator.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <time.h>

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

// Screen: ST7796, 320×480 portrait native, used landscape = 480×320
// TFT_eSPI is configured via User_Setup.h — internal SPI to board display
#define SCREEN_WIDTH  480   // landscape width
#define SCREEN_HEIGHT 320   // landscape height
TFT_eSPI tft = TFT_eSPI();

// Colours (RGB565)
#define COL_BG       0x0000   // Black
#define COL_FG       0xFFFF   // White
#define COL_ACCENT   0x07FF   // Cyan
#define COL_SUCCESS  0x07E0   // Green
#define COL_ERROR    0xF800   // Red
#define COL_BAR      0x07FF   // Cyan progress bar

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
    Serial.println("[Queue] Full — dropping oldest entry");
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
  Serial.println("[Queue] Stored offline. Queue depth: " + String(n + 1));
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
    Serial.println("[WiFi] Connection lost — reconnecting...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
}

// =============================================================================
//  ── TFT HELPERS — ONX3248G035 (480×320 landscape, ST7796) ───────────────────
// =============================================================================

void displayMessage(const char* line1,
                    const char* line2 = "",
                    const char* line3 = "") {
  tft.fillScreen(COL_BG);
  tft.setTextDatum(MC_DATUM);

  tft.setTextColor(COL_ACCENT, COL_BG);
  tft.setTextSize(3);
  tft.drawString(line1, SCREEN_WIDTH / 2, 110);

  if (strlen(line2) > 0) {
    tft.setTextColor(COL_FG, COL_BG);
    tft.setTextSize(2);
    tft.drawString(line2, SCREEN_WIDTH / 2, 170);
  }

  if (strlen(line3) > 0) {
    tft.setTextColor(COL_FG, COL_BG);
    tft.setTextSize(2);
    tft.drawString(line3, SCREEN_WIDTH / 2, 215);
  }
}

void displayIdle() {
  if (millis() - lastIdleRefresh < 5000) return;
  lastIdleRefresh = millis();

  String timeStr = getTimeHHMM();
  String wifiStr = (WiFi.status() == WL_CONNECTED) ? "WiFi: OK" : "WiFi: OFFLINE";
  String txStr   = "TX #" + String(txCounter);
  int    qDepth  = offlineQueueLen();
  if (qDepth > 0) txStr += "   Q:" + String(qDepth);

  tft.fillScreen(COL_BG);
  tft.setTextDatum(MC_DATUM);

  // Large clock — 480×320 landscape, push it up a bit
  tft.setTextColor(COL_ACCENT, COL_BG);
  tft.setTextSize(6);
  tft.drawString(timeStr, SCREEN_WIDTH / 2, 95);

  // Divider
  tft.drawFastHLine(20, 155, SCREEN_WIDTH - 40, COL_ACCENT);

  // Status lines
  tft.setTextColor(COL_FG, COL_BG);
  tft.setTextSize(2);
  tft.drawString(wifiStr,              SCREEN_WIDTH / 2, 190);
  tft.drawString(txStr,                SCREEN_WIDTH / 2, 225);
  tft.drawString("Ready for next sale", SCREEN_WIDTH / 2, 265);

  // Board label bottom-right (handy during dev)
  tft.setTextDatum(BR_DATUM);
  tft.setTextSize(1);
  tft.setTextColor(0x4208, COL_BG);  // dark grey
  tft.drawString("ONX3248G035", SCREEN_WIDTH - 4, SCREEN_HEIGHT - 4);
  tft.setTextDatum(MC_DATUM);
}

void drawQR(const char* text) {
  QRCode qrcode;
  uint8_t qrcodeData[qrcode_getBufferSize(5)];
  qrcode_initText(&qrcode, qrcodeData, 5, 0, text);

  int size    = qrcode.size;
  int scale   = 7;  // 480px wide — scale 7 gives ~287px QR, easily scannable
  int offsetX = (SCREEN_WIDTH  - size * scale) / 2;
  int offsetY = (SCREEN_HEIGHT - size * scale) / 2 - 15;

  tft.fillScreen(COL_FG);  // white background for QR

  for (int y = 0; y < size; y++) {
    for (int x = 0; x < size; x++) {
      uint16_t colour = qrcode_getModule(&qrcode, x, y) ? COL_BG : COL_FG;
      tft.fillRect(offsetX + x * scale,
                   offsetY + y * scale,
                   scale, scale, colour);
    }
  }

  tft.setTextDatum(MC_DATUM);
  tft.setTextColor(COL_BG, COL_FG);
  tft.setTextSize(2);
  tft.drawString("Scan or Tap to claim", SCREEN_WIDTH / 2, SCREEN_HEIGHT - 16);
}

void drawClaimCountdown() {
  unsigned long elapsed = millis() - claimWindowStart;
  if (elapsed >= CLAIM_TIMEOUT_MS) return;

  int barWidth = map(elapsed, 0, CLAIM_TIMEOUT_MS, SCREEN_WIDTH, 0);
  tft.fillRect(0, SCREEN_HEIGHT - 8, SCREEN_WIDTH, 8, COL_BG);
  tft.fillRect(0, SCREEN_HEIGHT - 8, barWidth,     8, COL_BAR);
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
    Serial.println("[Supabase] POST OK → " + body);
    DynamicJsonDocument doc(1024);
    if (deserializeJson(doc, body) == DeserializationError::Ok) {
      newSlipId = doc[0]["id"].as<String>();
    }
  } else {
    Serial.println("[Supabase] POST failed: " + String(code) + " " + https.getString());
  }

  https.end();
  return newSlipId;
}

// =============================================================================
//  ── SUPABASE — PATCH (mark slip claimed via NFC) ─────────────────────────────
// =============================================================================

bool supabasePatch(const String& id, const String& uid) {
  if (WiFi.status() != WL_CONNECTED) return false;

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient https;
  String url = String(SUPABASE_URL) + "/rest/v1/slips?id=eq." + id;

  if (!https.begin(client, url)) return false;

  https.addHeader("Content-Type",           "application/json");
  https.addHeader("apikey",                  SUPABASE_ANON);
  https.addHeader("Authorization",           "Bearer " + String(SUPABASE_ANON));
  https.addHeader("X-HTTP-Method-Override", "PATCH");

  String json = "{\"claimed\":true}";
  int code = https.POST(json);

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

  Serial.println("[Queue] WiFi restored — flushing " + String(depth) + " queued slips");

  while (offlineQueueLen() > 0) {
    String json = offlineQueuePop();
    if (json.length() == 0) break;
    String id = supabasePost(json);
    if (id.length() > 0) {
      Serial.println("[Queue] Flushed slip → id: " + id);
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
  Serial.println("[NVS] Transaction counter: " + String(txCounter));

  // ── Backlight ───────────────────────────────────────────────────────────────
  pinMode(TFT_BL_PIN, OUTPUT);
  digitalWrite(TFT_BL_PIN, HIGH);

  // ── TFT display ─────────────────────────────────────────────────────────────
  tft.init();
  tft.setRotation(1);  // landscape — 480 wide, 320 tall
  tft.fillScreen(COL_BG);
  displayMessage("DigiSlip", "Booting...", "v2.1 S3");
  Serial.println("[TFT] OK — ST7796 480x320");

  // ── I2C — Grove I2C connector ───────────────────────────────────────────────
  Wire.begin(I2C_SDA, I2C_SCL);
  Serial.println("[I2C] SDA=IO8 SCL=IO7");

  // ── NFC ─────────────────────────────────────────────────────────────────────
  nfc.begin();
  uint32_t nfcVer = nfc.getFirmwareVersion();
  if (!nfcVer) {
    Serial.println("[NFC] PN532 not found — check Grove I2C wiring");
    displayMessage("NFC FAIL", "Check Grove I2C", "SDA=IO8 SCL=IO7");
    while (true) delay(100);
  }
  Serial.printf("[NFC] PN532 firmware v%d.%d\n",
                (nfcVer >> 16) & 0xFF, (nfcVer >> 8) & 0xFF);
  nfc.SAMConfig();
  Serial.println("[NFC] OK");

  // ── UART1 — Grove UART connector (POS RX + Printer TX) ──────────────────────
  // Both directions on the same UART — IO12=RX from POS, IO13=TX to Printer
  posSerial.begin(9600, SERIAL_8N1, UART1_RX, UART1_TX);
  posSerial.setRxBufferSize(4096);  // S3 PSRAM available — use it
  Serial.println("[UART1] POS RX=IO12 @ 9600, Printer TX=IO13 @ 9600");
  // NOTE: printer baud must match POS baud on shared UART.
  // If your printer needs 19200, change both POS and printer to 19200.

  // ── Button — 24-pin header IO38 ─────────────────────────────────────────────
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  Serial.println("[BTN] Button on IO38");

  // ── WiFi ────────────────────────────────────────────────────────────────────
  displayMessage("Connecting", "to WiFi...");
  wifiConnect();

  if (WiFi.status() == WL_CONNECTED) {
    displayMessage("WiFi OK", WiFi.localIP().toString().c_str(), "NTP synced");
  } else {
    displayMessage("WiFi FAILED", "Offline mode", "Queue active");
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
        displayMessage("Receiving", "POS data...");
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
        displayMessage("Uploading...", ("TX #" + String(txCounter)).c_str());
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
          Serial.println("[Supabase] Slip ID: " + slipId);
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
          displayMessage("Cloud failed", "Press button", "for paper slip");
        }
      } else {
        offlineQueuePush(json);
        Serial.println("[Offline] Queued TX#" + String(txCounter));
        currentState     = STATE_WAITING_CLAIM;
        claimWindowStart = millis();
        displayMessage("No WiFi", "Press button", "for paper slip");
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

      // 2. Button check before NFC (NFC blocks ~50ms per pass)
      if (digitalRead(BUTTON_PIN) == LOW) {
        delay(50);
        if (digitalRead(BUTTON_PIN) == LOW) {
          Serial.println("[BTN] Button pressed — printing");
          currentState = STATE_PRINTING;
          break;
        }
      }

      // 3. NFC tap
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

        displayMessage("Card detected!", nfcUID.substring(0, 17).c_str(),
                       "Linking slip...");

        if (slipId.length() > 0) {
          bool ok = supabasePatch(slipId, nfcUID);
          Serial.println(ok ? "[NFC] Slip linked to UID"
                            : "[NFC] PATCH failed — UID local only");
        }

        currentState = STATE_CLAIMED;
        break;
      }

      // 4. Countdown bar
      if (slipId.length() > 0) {
        drawClaimCountdown();
      }

      // 5. Timeout
      if (elapsed >= CLAIM_TIMEOUT_MS) {
        Serial.println("[Timeout] No claim — returning to IDLE");
        Serial.println("[Timeout] Slip " + slipId + " remains unclaimed");
        printBufferLen   = 0;
        receiptLineCount = 0;
        slipId           = "";
        nfcUID           = "";
        currentState     = STATE_IDLE;
        lastIdleRefresh  = 0;
        displayMessage("Timeout", "Slip saved", "No print");
        delay(1500);
      }

      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_CLAIMED: {
      displayMessage("Slip claimed!", "Sent to app :)", "No paper needed");
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

      // TX on same UART1 — IO13 to printer via MAX3232
      posSerial.write(printBuffer, printBufferLen);
      posSerial.flush();

      Serial.println("[PRINT] Done");
      displayMessage("Printed!", "Have a great day");
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
