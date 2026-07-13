// RP2040-Zero USB printer-bridge test firmware.
//
// Enumerates as a composite CDC + vendor-class (FFh) USB device mirroring
// the real thermal printer's identity confirmed via simulator/USB_Only_Driver.py
// (VID 0x1FC9 / PID 0x2016, raw bulk-OUT, no standard Printer Class 07h).
// Point USB_Only_Driver.py at this board and its ESC/POS bytes should show
// up here exactly as they would on the real printer.
//
// CDC (Serial) carries debug output to the Arduino IDE / arduino-cli Serial
// Monitor -- same physical USB connection as the vendor bulk pipe.
//
// POS --USB--> [this board] --UART--> ESP32-S3 main board. Captured USB
// bytes stream out UART0 (GP28 TX) to the ESP32-S3's existing posSerial RX
// pin (IO12) as they arrive, at the same 19200 baud/8N1 framing -- the ESP32
// needs no firmware changes, it already buffers and parses on that pin. The
// CDC debug print (hex dump + parseESCPOS(), ported from
// DigiSlip_ONX3248G035.ino) stays as a passive tap, silence-gated, so its
// output is directly comparable to what the ESP32 already logs.
//
// Build: must be compiled with the CFG_TUSB_CONFIG_FILE override in this
// folder (tusb_config_override.h) -- see build.ps1. The Arduino IDE alone
// cannot enable CFG_TUD_VENDOR for RP2040; use build.ps1 instead.

#include "Adafruit_TinyUSB.h"

// ---------------------------------------------------------------------------
// Vendor-class USB interface: raw bulk-OUT/IN pipe mirroring the real printer.
// ---------------------------------------------------------------------------
class USBVendorPrinter : public Adafruit_USBD_Interface {
public:
  USBVendorPrinter() {
    setStringDescriptor("DigiSlips USB Bridge (test)");
  }

  uint16_t getInterfaceDescriptor(uint8_t itfnum_deprecated, uint8_t* buf, uint16_t bufsize) override {
    (void)itfnum_deprecated;
    uint8_t itfnum = 0, ep_out = 0, ep_in = 0;

    // null buf: caller just wants the descriptor length
    if (buf) {
      itfnum = TinyUSBDevice.allocInterface(1);
      ep_out = TinyUSBDevice.allocEndpoint(TUSB_DIR_OUT);
      ep_in  = TinyUSBDevice.allocEndpoint(TUSB_DIR_IN);
    }

    uint8_t const desc[] = {TUD_VENDOR_DESCRIPTOR(itfnum, _strid, ep_out, ep_in, 64)};
    uint16_t const len = sizeof(desc);

    if (buf) {
      if (bufsize < len) return 0;
      memcpy(buf, desc, len);
    }
    return len;
  }
};

static USBVendorPrinter usbVendor;

// ---------------------------------------------------------------------------
// ESC/POS byte-stripping parser -- ported from DigiSlip_ONX3248G035.ino's
// escParamBytes()/parseESCPOS() so [USB]/[Parser] output here is directly
// comparable to the ESP32's own [UART]/[Parser] log lines.
// ---------------------------------------------------------------------------
#define RX_BUFFER_SIZE 8192
#define RX_SILENCE_MS  50  // gap that marks "end of this print job"
#define MAX_LINES      64

static uint8_t rxBuffer[RX_BUFFER_SIZE];
static size_t rxLen = 0;
static unsigned long lastByteTime = 0;

static String receiptLines[MAX_LINES];
static int receiptLineCount = 0;

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
      if (i < len) i += 2;
    } else if (b == 0x0A || b == 0x0D) {
      currentLine.trim();
      if (currentLine.length() > 0 && receiptLineCount < MAX_LINES) {
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
  if (currentLine.length() > 0 && receiptLineCount < MAX_LINES) {
    receiptLines[receiptLineCount++] = currentLine;
  }
}

void printHexDump(const uint8_t* buf, size_t len) {
  for (size_t i = 0; i < len; i++) {
    if (buf[i] < 0x10) Serial.print('0');
    Serial.print(buf[i], HEX);
    Serial.print(' ');
    if ((i + 1) % 16 == 0) Serial.println();
  }
  Serial.println();
}

// ---------------------------------------------------------------------------
void setup() {
  TinyUSBDevice.setID(0x1FC9, 0x2016);  // mirror the real printer's VID/PID
  TinyUSBDevice.setManufacturerDescriptor("DigiSlips");
  TinyUSBDevice.setProductDescriptor("DigiSlips USB Bridge (test)");

  TinyUSBDevice.addInterface(usbVendor);

  // If CDC already enumerated before the vendor interface was added, force
  // re-enumeration so the host sees the full composite descriptor.
  if (TinyUSBDevice.mounted()) {
    TinyUSBDevice.detach();
    delay(10);
    TinyUSBDevice.attach();
  }

  // UART0 -> ESP32-S3 IO12 (posSerial RX). Simplex: only TX is wired.
  // FIFO sized to hold one full job so write() never blocks mid-transfer
  // waiting for the 19200-baud link to drain (~4s for a full 8KB buffer) --
  // the interrupt-driven UART drains it in the background while loop()
  // keeps servicing tud_task().
  Serial1.setTX(28);
  Serial1.setRX(29);
  Serial1.setFIFOSize(RX_BUFFER_SIZE);
  Serial1.begin(19200, SERIAL_8N1);

  Serial.begin(115200);
  while (!Serial) { ; }
  Serial.println();
  Serial.println("[SYS] RP2040-Zero USB printer bridge test ready");
  Serial.println("[SYS] Vendor class FFh, VID 0x1FC9 PID 0x2016 -- point USB_Only_Driver.py at me");
}

void loop() {
  while (tud_vendor_available() && rxLen < RX_BUFFER_SIZE) {
    uint32_t chunk = tud_vendor_read(rxBuffer + rxLen, RX_BUFFER_SIZE - rxLen);
    Serial1.write(rxBuffer + rxLen, chunk);
    rxLen += chunk;
    lastByteTime = millis();
  }

  if (rxLen > 0 && millis() - lastByteTime >= RX_SILENCE_MS) {
    Serial.println("[USB] " + String(rxLen) + " bytes received -- parsing");

    Serial.println("[USB] Hex dump:");
    printHexDump(rxBuffer, rxLen);

    parseESCPOS(rxBuffer, rxLen);
    Serial.println("[Parser] Extracted " + String(receiptLineCount) + " text lines");
    for (int j = 0; j < receiptLineCount; j++) {
      Serial.println("  [" + String(j) + "] " + receiptLines[j]);
    }

    rxLen = 0;
  }
}
