// RP2040-Zero USB-host spike -- printer-facing leg of the bridge chain.
//
// POS --USB--> [Pico_zero_usb_printer, device] --UART--> ESP32-S3 --UART-->
// [this board, USB HOST] --USB--> real thermal printer.
//
// This spike only proves the last hop: native RP2040 USB-C port acting as
// TinyUSB host, enumerating the real printer (vendor class FFh, VID 0x1FC9 /
// PID 0x2016) and dumping its device + configuration descriptors. No ESP32,
// no bulk-OUT relay yet -- see USB_PRINTER_BRIDGE_HANDOFF.md.
//
// Build: Tools -> USB Stack -> "Adafruit TinyUSB Host (native)"
// (FQBN usbstack=tinyusb_host). Unlike the device-side sketch, no
// CFG_TUSB_CONFIG_FILE override is needed -- host mode is a first-class
// board menu option on arduino-pico >=3.6.3 / installed core 5.6.1.
//
// Debug output goes out Serial1 (UART), not the native USB port -- that
// port is now the host connection to the printer, so there's no CDC.
// Wire Serial1 TX/RX through an RS232 adapter to the laptop.

#include "Adafruit_TinyUSB.h"

#ifndef USE_TINYUSB_HOST
  #error This sketch requires Tools -> USB Stack -> "Adafruit TinyUSB Host"
#endif

// The real thermal printer's identity, per USB_PRINTER_BRIDGE_HANDOFF.md --
// same VID/PID Pico_zero_usb_printer.ino mimics on the device side.
#define PRINTER_VID 0x1FC9
#define PRINTER_PID 0x2016

Adafruit_USBH_Host USBHost;

void setup() {
  // Board's stock default (GP0/GP1) gave garbled output on the bench;
  // switched to GP28/29, the UART0 pair already proven working on the
  // device-bridge board (Pico_zero_usb_printer.ino).
  Serial1.setTX(28);
  Serial1.setRX(29);
  Serial1.begin(9600);
  Serial1.println();
  Serial1.println("[SYS] RP2040 USB-host spike -- native rhport0");

  USBHost.begin(0);
}

void loop() {
  USBHost.task();
  Serial1.flush();
}

// ---------------------------------------------------------------------------
// TinyUSB host callbacks
// ---------------------------------------------------------------------------
void tuh_mount_cb(uint8_t daddr) {
  Serial1.printf("[USB] Device attached, address = %u\r\n", daddr);

  tusb_desc_device_t desc;
  if (tuh_descriptor_get_device_sync(daddr, &desc, sizeof(desc)) != XFER_RESULT_SUCCESS) {
    Serial1.println("[USB] Failed to get device descriptor");
    return;
  }

  Serial1.printf("[USB] Device %u: ID %04x:%04x\r\n", daddr, desc.idVendor, desc.idProduct);
  if (desc.idVendor == PRINTER_VID && desc.idProduct == PRINTER_PID) {
    Serial1.println("[USB] *** MATCH -- this is the DigiSlips printer VID/PID ***");
  } else {
    Serial1.println("[USB] No match -- not the expected printer VID/PID");
  }

  print_config_descriptor(daddr);
}

// Configuration descriptor's real size (interfaces + endpoints) isn't known
// up front -- fetch the 9-byte header first to read wTotalLength, then
// re-fetch that many bytes.
#define CONFIG_DESC_MAX_LEN 256

void print_config_descriptor(uint8_t daddr) {
  uint8_t buf[CONFIG_DESC_MAX_LEN];
  tusb_desc_configuration_t* cfg_hdr = (tusb_desc_configuration_t*)buf;

  if (tuh_descriptor_get_configuration_sync(daddr, 0, buf, sizeof(tusb_desc_configuration_t)) != XFER_RESULT_SUCCESS) {
    Serial1.println("[USB] Failed to get configuration descriptor header");
    return;
  }

  uint16_t total_len = cfg_hdr->wTotalLength;
  if (total_len > sizeof(buf)) total_len = sizeof(buf);

  if (tuh_descriptor_get_configuration_sync(daddr, 0, buf, total_len) != XFER_RESULT_SUCCESS) {
    Serial1.println("[USB] Failed to get full configuration descriptor");
    return;
  }

  Serial1.printf("[USB] Config: %u interface(s), wTotalLength=%u\r\n",
                 cfg_hdr->bNumInterfaces, cfg_hdr->wTotalLength);

  uint8_t const* p = buf + sizeof(tusb_desc_configuration_t);
  uint8_t const* end = buf + total_len;
  while (p < end) {
    uint8_t desc_len = p[0];
    uint8_t desc_type = p[1];
    if (desc_len == 0) break;

    if (desc_type == TUSB_DESC_INTERFACE) {
      tusb_desc_interface_t const* itf = (tusb_desc_interface_t const*)p;
      Serial1.printf("[USB]   Interface %u: class=0x%02x subclass=0x%02x proto=0x%02x%s\r\n",
                     itf->bInterfaceNumber, itf->bInterfaceClass, itf->bInterfaceSubClass,
                     itf->bInterfaceProtocol,
                     itf->bInterfaceClass == 0xFF ? "  (vendor-specific)" : "");
    } else if (desc_type == TUSB_DESC_ENDPOINT) {
      tusb_desc_endpoint_t const* ep = (tusb_desc_endpoint_t const*)p;
      bool is_in = (ep->bEndpointAddress & 0x80) != 0;
      static const char* xfer_names[] = {"Control", "Isochronous", "Bulk", "Interrupt"};
      Serial1.printf("[USB]     Endpoint 0x%02x: %s %s, wMaxPacketSize=%u\r\n",
                     ep->bEndpointAddress, xfer_names[ep->bmAttributes.xfer],
                     is_in ? "IN" : "OUT", ep->wMaxPacketSize);
    }

    p += desc_len;
  }
}

void tuh_umount_cb(uint8_t daddr) {
  Serial1.printf("[USB] Device removed, address = %u\r\n", daddr);
}
