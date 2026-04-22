// =============================================================================
//  DigiSlip ESP32 — Full Production Firmware
//  
//  What this device does:
//    • Sits between a POS machine and a thermal printer on RS232
//    • Intercepts the raw ESC/POS byte stream
//    • Strips control codes → clean text → uploads to Supabase
//    • Displays a QR code on OLED so customer can claim slip digitally
//    • Reads NFC card/phone UID to link slip to a user account
//    • Polls Supabase to detect QR-based claims (iPhone users via app)
//    • If claimed digitally → print is blocked (green flow)
//    • If not claimed within 60s → customer may press button for paper slip
//    • Offline queue: if WiFi down, stores up to 5 transactions in NVS
//
//  Wiring:
//    RS232 from POS  → MAX3232 → UART2  RX=GPIO16, TX=GPIO18 (TX unused)
//    RS232 to Printer→ MAX3232 → UART1  RX=GPIO19 (unused), TX=GPIO17
//    OLED (SSD1306)  → I2C  SDA=GPIO21, SCL=GPIO22
//    NFC  (PN532)    → I2C  SDA=GPIO21, SCL=GPIO22  (shared bus)
//    Button          → GPIO4  (other leg to GND, internal pull-up used)
//
//  Libraries (install via Arduino Library Manager):
//    Adafruit SSD1306        — OLED driver
//    Adafruit GFX            — graphics primitives
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
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
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
// Replace this with the token generated when provisioning this unit
#define DEVICE_TOKEN  "REPLACE_WITH_DEVICE_TOKEN"

// QR code base URL — phone app will open  https://digislips.co.za/slip/<slip_uuid>
#define QR_BASE_URL  "https://digislips.co.za/slip/"

// NTP
#define NTP_SERVER   "pool.ntp.org"
#define TZ_OFFSET    7200   // UTC+2 (SAST) in seconds  — adjust for DST if needed

// Timeouts
#define CLAIM_TIMEOUT_MS    60000   // 60 s before reverting to IDLE
#define SUPABASE_POLL_MS     2000   // poll Supabase every 2 s for QR claims
#define WIFI_WATCHDOG_MS    10000   // check WiFi health every 10 s
#define SERIAL_SILENCE_MS     500   // gap that signals end of ESC/POS burst

// Offline queue
#define OFFLINE_QUEUE_SIZE      5   // max queued transactions when WiFi is down

// =============================================================================
//  ── PIN DEFINITIONS ──────────────────────────────────────────────────────────
// =============================================================================

#define UART2_RX    16   // from POS  (via MAX3232)
#define UART2_TX    18   // not used
#define UART1_RX    19   // not used
#define UART1_TX    17   // to Printer (via MAX3232)

#define I2C_SDA     21
#define I2C_SCL     22

#define BUTTON_PIN   4   // tactile button, wired to GND

// =============================================================================
//  ── HARDWARE OBJECTS ─────────────────────────────────────────────────────────
// =============================================================================

HardwareSerial posSerial(2);      // UART2 — from POS
HardwareSerial printerSerial(1);  // UART1 — to Printer

#define SCREEN_WIDTH  128
#define SCREEN_HEIGHT  64
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);

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

// Raw ESC/POS print buffer (4 KB — enough for any receipt)
uint8_t  printBuffer[4096];
int      printBufferLen  = 0;

// Cleaned text lines extracted from ESC/POS for Supabase
String   receiptLines[64];  // up to 64 text lines per receipt
int      receiptLineCount = 0;

// Supabase slip UUID returned after POST (e.g. "550e8400-e29b-41d4-a716-446655440000")
String   slipId = "";

// NFC UID of tapped card / phone
String   nfcUID = "";

// Timestamps
unsigned long claimWindowStart = 0;   // when WAITING_CLAIM began
unsigned long lastPollTime     = 0;   // last Supabase poll
unsigned long lastWifiCheck    = 0;   // last WiFi watchdog check
unsigned long lastIdleRefresh  = 0;   // last OLED idle screen redraw

// NVS-backed transaction counter (survives reboots)
uint32_t txCounter = 0;

// =============================================================================
//  ── OFFLINE QUEUE  (NVS) ─────────────────────────────────────────────────────
//
//  Each queued entry is a serialised JSON string stored under keys
//  "q0" … "q4".  A single key "qlen" tracks how many are pending.
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
    // Shift entries down to make room
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
  if (now > 100000) {
    Serial.println(" OK");
  } else {
    Serial.println(" FAILED (will retry)");
  }
}

// Returns ISO-8601 timestamp string e.g. "2026-04-15T10:23:44Z"
String getTimestamp() {
  time_t now;
  time(&now);
  if (now < 100000) return "unknown";
  struct tm* t = gmtime(&now);
  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", t);
  return String(buf);
}

// Returns HH:MM string for OLED clock
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

// Called from loop — non-blocking watchdog
void wifiWatchdog() {
  if (millis() - lastWifiCheck < WIFI_WATCHDOG_MS) return;
  lastWifiCheck = millis();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] Connection lost — reconnecting...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    // NTP will re-sync next time we get a successful POST or on next reboot
  }
}

// =============================================================================
//  ── OLED HELPERS ─────────────────────────────────────────────────────────────
// =============================================================================

void displayMessage(const char* line1,
                    const char* line2 = "",
                    const char* line3 = "") {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(WHITE);
  display.setCursor(0, 8);  display.println(line1);
  if (strlen(line2) > 0) { display.setCursor(0, 26); display.println(line2); }
  if (strlen(line3) > 0) { display.setCursor(0, 44); display.println(line3); }
  display.display();
}

// IDLE screen: time | WiFi status | last tx number | queue depth
void displayIdle() {
  if (millis() - lastIdleRefresh < 5000) return;  // refresh every 5s
  lastIdleRefresh = millis();

  String timeStr   = getTimeHHMM();
  String wifiStr   = (WiFi.status() == WL_CONNECTED) ? "WiFi: OK" : "WiFi: OFFLINE";
  String txStr     = "TX #" + String(txCounter);
  int    qDepth    = offlineQueueLen();
  if (qDepth > 0) txStr += "  Q:" + String(qDepth);

  display.clearDisplay();
  display.setTextColor(WHITE);

  // Large clock
  display.setTextSize(2);
  display.setCursor(24, 4);
  display.println(timeStr);

  // Divider
  display.drawFastHLine(0, 24, SCREEN_WIDTH, WHITE);

  // Status lines
  display.setTextSize(1);
  display.setCursor(0, 30);
  display.println(wifiStr);
  display.setCursor(0, 42);
  display.println(txStr);
  display.setCursor(0, 54);
  display.println("Ready for next sale");

  display.display();
}

void drawQR(const char* text) {
  QRCode qrcode;
  uint8_t qrcodeData[qrcode_getBufferSize(3)];
  qrcode_initText(&qrcode, qrcodeData, 3, 0, text);

  int size    = qrcode.size;
  int scale   = 2;
  int offsetX = (SCREEN_WIDTH  - size * scale) / 2;
  int offsetY = (SCREEN_HEIGHT - size * scale) / 2;

  display.clearDisplay();
  for (int y = 0; y < size; y++) {
    for (int x = 0; x < size; x++) {
      if (qrcode_getModule(&qrcode, x, y)) {
        display.fillRect(offsetX + x * scale,
                         offsetY + y * scale,
                         scale, scale, WHITE);
      }
    }
  }
  display.display();
}

// Countdown bar drawn at the bottom of the QR screen
void drawClaimCountdown() {
  unsigned long elapsed = millis() - claimWindowStart;
  if (elapsed >= CLAIM_TIMEOUT_MS) return;

  int barWidth = map(elapsed, 0, CLAIM_TIMEOUT_MS, SCREEN_WIDTH, 0);
  display.fillRect(0, 58, SCREEN_WIDTH, 6, BLACK);   // clear previous bar
  display.fillRect(0, 58, barWidth,     6, WHITE);
  display.display();
}

// =============================================================================
//  ── ESC/POS PARSER — strips control codes, returns readable text lines ───────
//
//  ESC/POS commands start with ESC (0x1B) or GS (0x1D) followed by 1–3
//  parameter bytes. We skip those sequences and keep printable ASCII.
//  The result is an array of trimmed, non-empty text lines.
// =============================================================================

// Returns how many parameter bytes follow a given ESC/POS command byte.
// This covers the most common commands for 80mm thermal printers.
int escParamBytes(uint8_t cmd) {
  switch (cmd) {
    // 1-param commands
    case 0x61:                          // ESC a (align)
    case 0x64:                          // ESC d (feed n lines)
    case 0x45:                          // ESC E (bold)
    case 0x2D:                          // ESC - (underline)
    case 0x21:                          // ESC ! (print mode)
    case 0x4D:                          // ESC M (font)
    case 0x56:                          // GS  V (cut) — 1 param
      return 1;
      
    // 2-param commands
    case 0x21 + 0x80:                   // placeholder — not used
      return 2;
      
    // 0-param commands
    case 0x40:                          // ESC @ (init / reinit) — 0 extra bytes
      return 0;
      
    default:
      return 1;  // safe default — skip 1 byte if unknown
  }
}

void parseESCPOS(uint8_t* buf, int len) {
  receiptLineCount = 0;
  String currentLine = "";

  int i = 0;
  while (i < len) {
    uint8_t b = buf[i];

    if (b == 0x1B) {           // ESC — skip command + params
      i++;
      if (i < len) {
        uint8_t cmd = buf[i];
        int skip = escParamBytes(cmd);
        i += 1 + skip;
      }
    }
    else if (b == 0x1D) {      // GS — skip command + params (cut, barcode etc.)
      i++;
      if (i < len) {
        i += 2;  // GS commands typically have 2 bytes (cmd + param)
      }
    }
    else if (b == 0x0A || b == 0x0D) {   // newline / carriage return
      currentLine.trim();
      if (currentLine.length() > 0 && receiptLineCount < 64) {
        receiptLines[receiptLineCount++] = currentLine;
      }
      currentLine = "";
      i++;
    }
    else if (b >= 0x20 && b < 0x80) {    // printable ASCII — keep it
      currentLine += (char)b;
      i++;
    }
    else {
      i++;  // skip non-printable, non-command byte
    }
  }

  // Flush any remaining line without a terminating newline
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
  // Build receipt text as a single string with newlines
  // Supabase stores it in the raw_text column
  String rawText = "";
  for (int i = 0; i < receiptLineCount; i++) {
    rawText += receiptLines[i];
    if (i < receiptLineCount - 1) rawText += "\n";
  }

  // Escape quotes and backslashes in rawText for safe JSON embedding
  rawText.replace("\\", "\\\\");
  rawText.replace("\"", "\\\"");

  DynamicJsonDocument doc(4096);
  doc["device_token"] = DEVICE_TOKEN;
  doc["raw_text"]     = rawText;
  doc["created_at"]   = timestamp;

  String output;
  serializeJson(doc, output);
  return output;
}

// =============================================================================
//  ── SUPABASE — POST (new slip) ───────────────────────────────────────────────
//
//  Posts to /rest/v1/slips via the device_token RPC flow.
//  Returns the new slip UUID on success, "" on failure.
// =============================================================================

String supabasePost(const String& json) {
  if (WiFi.status() != WL_CONNECTED) return "";

  WiFiClientSecure client;
  client.setInsecure();  // swap for CA cert in production

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
    // Response is a JSON array: [{"id":"uuid",...}]
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

  https.addHeader("Content-Type",  "application/json");
  https.addHeader("apikey",         SUPABASE_ANON);
  https.addHeader("Authorization",  "Bearer " + String(SUPABASE_ANON));
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
  // Only fetch the claimed field to keep the response tiny
  String url = String(SUPABASE_URL) + "/rest/v1/slips?id=eq." + id + "&select=claimed";

  if (!https.begin(client, url)) return false;

  https.addHeader("apikey",        SUPABASE_ANON);
  https.addHeader("Authorization", "Bearer " + String(SUPABASE_ANON));

  int code = https.GET();
  bool claimed = false;

  if (code == 200) {
    String body = https.getString();
    // Response: [{"claimed":true}] or [{"claimed":false}]
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
      offlineQueuePush(json);  // put it back — WiFi may have dropped again
      break;
    }
    delay(200);  // small gap between requests
  }
}

// =============================================================================
//  ── SETUP ────────────────────────────────────────────────────────────────────
// =============================================================================

void setup() {
  Serial.begin(115200);
  Serial.println("\n\n=== DigiSlip ESP32 Booting ===");

  // ── Persistent storage ──────────────────────────────────────────────────────
  txCounter = loadTxCounter();
  Serial.println("[NVS] Transaction counter: " + String(txCounter));

  // ── I2C + OLED ──────────────────────────────────────────────────────────────
  Wire.begin(I2C_SDA, I2C_SCL);

  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("[OLED] FAILED — halting");
    while (true) delay(100);
  }
  displayMessage("DigiSlip", "Booting...", "v1.0");
  Serial.println("[OLED] OK");

  // ── NFC ─────────────────────────────────────────────────────────────────────
  nfc.begin();
  uint32_t nfcVer = nfc.getFirmwareVersion();
  if (!nfcVer) {
    Serial.println("[NFC] PN532 not found — check wiring");
    displayMessage("NFC FAIL", "Check wiring");
    while (true) delay(100);
  }
  Serial.printf("[NFC] PN532 firmware v%d.%d\n",
                (nfcVer >> 16) & 0xFF, (nfcVer >> 8) & 0xFF);
  nfc.SAMConfig();
  Serial.println("[NFC] OK");

  // ── Serial ports ────────────────────────────────────────────────────────────
  posSerial.begin(9600,  SERIAL_8N1, UART2_RX, UART2_TX);
  printerSerial.begin(19200, SERIAL_8N1, UART1_RX, UART1_TX);
  Serial.println("[UART] POS RX and Printer TX initialised");

  // ── Button ──────────────────────────────────────────────────────────────────
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  Serial.println("[BTN] Button on GPIO" + String(BUTTON_PIN));

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
  currentState   = STATE_IDLE;
  lastIdleRefresh = 0;  // force immediate idle screen draw
  Serial.println("[SYS] Ready\n");
}

// =============================================================================
//  ── LOOP ─────────────────────────────────────────────────────────────────────
// =============================================================================

// Button edge detection state (persists across loop calls)
bool lastButtonState = HIGH;

void loop() {

  // ── Always-running background tasks ─────────────────────────────────────────
  wifiWatchdog();

  // Try to flush offline queue whenever we have WiFi and are idle
  if (currentState == STATE_IDLE) {
    flushOfflineQueue();
  }

  // ── Button read (edge detection) ────────────────────────────────────────────
  bool buttonState    = digitalRead(BUTTON_PIN);
  bool buttonPressed  = (lastButtonState == HIGH && buttonState == LOW);
  if (buttonPressed) delay(50);  // debounce
  lastButtonState = buttonState;

  // ── State machine ────────────────────────────────────────────────────────────
  switch (currentState) {

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_IDLE: {
      displayIdle();

      // Non-blocking ESC/POS capture — move to BUFFERING on first byte
      if (posSerial.available()) {
        printBufferLen   = 0;
        receiptLineCount = 0;
        slipId      = "";
        nfcUID           = "";
        currentState     = STATE_BUFFERING;
        displayMessage("Receiving", "POS data...");
        Serial.println("[UART] Data incoming — buffering");
      }
      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    //  STATE_BUFFERING
    //  Accumulate bytes from POS. A 500 ms silence signals end-of-job.
    //  Non-blocking: we track the last-byte timestamp and return to loop
    //  each iteration so WiFi watchdog etc. keep running.
    // ──────────────────────────────────────────────────────────────────────────
    case STATE_BUFFERING: {
      static unsigned long lastByteTime = 0;

      // Read all available bytes this iteration
      while (posSerial.available() > 0 && printBufferLen < 4096) {
        printBuffer[printBufferLen++] = posSerial.read();
        lastByteTime = millis();
      }

      // First byte — initialise the silence timer
      if (printBufferLen > 0 && lastByteTime == 0) {
        lastByteTime = millis();
      }

      // Check for silence timeout
      if (printBufferLen > 0 &&
          millis() - lastByteTime >= SERIAL_SILENCE_MS) {
        lastByteTime = 0;  // reset for next time
        Serial.println("[UART] " + String(printBufferLen) +
                       " bytes received — parsing");

        // Parse ESC/POS → clean text lines
        parseESCPOS(printBuffer, printBufferLen);

        // Increment and save transaction counter
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

          // Show QR code — URL that the app will open
          String qrURL = String(QR_BASE_URL) + slipId;
          Serial.println("[QR] " + qrURL);
          drawQR(qrURL.c_str());

          // Overlay "Scan or Tap" hint at the bottom
          display.fillRect(0, 56, SCREEN_WIDTH, 8, BLACK);
          display.setTextSize(1);
          display.setTextColor(WHITE);
          display.setCursor(10, 56);
          display.print("Scan / Tap / Button");
          display.display();

        } else {
          // POST failed even though WiFi appeared up
          Serial.println("[Supabase] POST failed — queuing offline");
          offlineQueuePush(json);
          currentState = STATE_WAITING_CLAIM;  // still show QR for printing option
          claimWindowStart = millis();
          displayMessage("Cloud failed", "Press button", "for paper slip");
        }
      } else {
        // Offline — queue the slip for later
        offlineQueuePush(json);
        Serial.println("[Offline] Queued TX#" + String(txCounter));
        currentState     = STATE_WAITING_CLAIM;
        claimWindowStart = millis();
        displayMessage("No WiFi", "Press button", "for paper slip");
      }
      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    //  STATE_WAITING_CLAIM
    //  Simultaneously:
    //    1. Poll Supabase every 2s for claimed == true (QR/app flow)
    //    2. Poll NFC reader for card/phone tap
    //    3. Watch button for physical print request
    //    4. Update countdown bar on OLED
    //    5. Check 60s timeout
    // ──────────────────────────────────────────────────────────────────────────
    case STATE_WAITING_CLAIM: {

      unsigned long elapsed = millis() - claimWindowStart;

      // ── 1. Supabase poll (QR claim) ────────────────────────────────────────
      if (slipId.length() > 0 &&
          millis() - lastPollTime >= SUPABASE_POLL_MS) {
        lastPollTime = millis();
        if (supabaseIsClaimed(slipId)) {
          Serial.println("[Claim] Slip claimed via QR/app");
          currentState = STATE_CLAIMED;
          break;
        }
      }

      // ── 2. Button — checked BEFORE NFC so a press is never missed ───────────
      //  Direct LOW-level read here instead of relying on the top-of-loop
      //  edge detection. The NFC call blocks for ~50 ms each pass, which is
      //  long enough to swallow a button edge transition entirely.
      if (digitalRead(BUTTON_PIN) == LOW) {
        delay(50);                              // debounce wait
        if (digitalRead(BUTTON_PIN) == LOW) {  // confirm still held
          Serial.println("[BTN] Button pressed — printing");
          currentState = STATE_PRINTING;
          break;
        }
      }

      // ── 3. NFC tap ────────────────────────────────────────────────────────
      uint8_t uid[7];
      uint8_t uidLen = 0;
      // 50 ms timeout — short enough to keep button and countdown responsive
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
          if (ok) {
            Serial.println("[NFC] Slip linked to UID");
          } else {
            Serial.println("[NFC] PATCH failed — UID stored locally only");
          }
        }

        currentState = STATE_CLAIMED;
        break;
      }

      // ── 4. Countdown bar ──────────────────────────────────────────────────
      if (slipId.length() > 0) {
        drawClaimCountdown();
      }

      // ── 5. Timeout — 60 s, slip stays in Supabase as unclaimed ──────────
      if (elapsed >= CLAIM_TIMEOUT_MS) {
        Serial.println("[Timeout] No claim — returning to IDLE");
        Serial.println("[Timeout] Slip " + slipId + " remains unclaimed");
        // Reset session
        printBufferLen   = 0;
        receiptLineCount = 0;
        slipId      = "";
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

      // Clear session
      printBufferLen   = 0;
      receiptLineCount = 0;
      slipId      = "";
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

      printerSerial.write(printBuffer, printBufferLen);
      printerSerial.flush();

      Serial.println("[PRINT] Done");
      displayMessage("Printed!", "Have a great day");
      delay(2000);

      // Clear session
      printBufferLen   = 0;
      receiptLineCount = 0;
      slipId      = "";
      nfcUID           = "";
      currentState     = STATE_IDLE;
      lastIdleRefresh  = 0;
      break;
    }

    // ──────────────────────────────────────────────────────────────────────────
    case STATE_ERROR: {
      // Generic recoverable error — auto-reset after 3 s
      static unsigned long errorTime = 0;
      if (errorTime == 0) errorTime = millis();
      if (millis() - errorTime > 3000) {
        errorTime      = 0;
        currentState   = STATE_IDLE;
        lastIdleRefresh = 0;
      }
      break;
    }

    default:
      currentState = STATE_IDLE;
      break;
  }
}
