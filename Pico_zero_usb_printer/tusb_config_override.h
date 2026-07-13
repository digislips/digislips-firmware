// Repo-local TinyUSB config for the RP2040-Zero USB printer-bridge firmware.
//
// arduino-pico's core tusb_config.h (packages/rp2040/hardware/rp2040/<ver>/
// include/tusb_config.h) hardcodes CFG_TUD_VENDOR to 0 with no #ifndef
// guard, so it can't be turned on for a single sketch the normal way. This
// file is swapped in instead via the CFG_TUSB_CONFIG_FILE build flag (see
// build.ps1), which TinyUSB checks before falling back to the core default
// for every MCU except ESP32 -- so this override is picked up cleanly.
//
// NCM/HID/MSC/MIDI are left off since this device only needs CDC (Serial,
// for debug output) + Vendor (bulk pipe mirroring the real printer).

#ifndef _TUSB_CONFIG_H_
#define _TUSB_CONFIG_H_

#ifdef __cplusplus
extern "C" {
#endif

#ifndef CFG_TUSB_MCU
  #define CFG_TUSB_MCU OPT_MCU_RP2040
#endif

#define CFG_TUSB_RHPORT0_MODE OPT_MODE_DEVICE
#define CFG_TUSB_OS           OPT_OS_PICO

#ifndef CFG_TUSB_DEBUG
  #define CFG_TUSB_DEBUG 0
#endif

#ifndef CFG_TUSB_MEM_SECTION
  #define CFG_TUSB_MEM_SECTION
#endif

#ifndef CFG_TUSB_MEM_ALIGN
  #define CFG_TUSB_MEM_ALIGN __attribute__((aligned(4)))
#endif

#ifndef CFG_TUD_ENDPOINT0_SIZE
  #define CFG_TUD_ENDPOINT0_SIZE 64
#endif

//------------- CLASS -------------//
#define CFG_TUD_HID    (0)
#define CFG_TUD_CDC    (1)
#define CFG_TUD_MSC    (0)
#define CFG_TUD_MIDI   (0)
#define CFG_TUD_VENDOR (1)
#define CFG_TUD_NCM    (0)

#define CFG_TUD_CDC_RX_BUFSIZE (256)
#define CFG_TUD_CDC_TX_BUFSIZE (256)

// Sized to swallow a whole receipt (~500 bytes) between loop() polls.
#define CFG_TUD_VENDOR_RX_BUFSIZE (512)
#define CFG_TUD_VENDOR_TX_BUFSIZE (512)

#ifdef __cplusplus
}
#endif

#endif
