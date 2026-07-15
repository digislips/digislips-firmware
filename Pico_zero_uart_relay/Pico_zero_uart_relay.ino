// UART-to-USB-CDC relay -- lets Board #1 (Pico_zero_usb_printer board) act
// as a debug bridge for Board #2 (Pico_zero_usb_host board) over native USB,
// bypassing the CH340 USB-RS232 adapter entirely.
//
// [Board #2, host spike] --Serial1 GP28 TX--> GP29 RX [this board] --USB-C
// CDC (Serial)--> laptop. One-way forward only: this board never writes back
// to GP28, and Board #2 never reads its own Serial1 RX, so there's no return
// path needed. Ground is shared through the existing 5V/GND power jumper
// between the two boards (this board also powers Board #2 off that same
// jumper) -- no separate ground wire required.
//
// Temporary: this replaces Pico_zero_usb_printer.ino on Board #1 for the
// duration of this debug session. Reflash that back once Board #2 is sorted.
//
// Build: plain arduino-pico, default USB stack (native CDC) -- no TinyUSB
// override needed, same as Pico_zero_test.ino.

void setup() {
  Serial1.setTX(28);
  Serial1.setRX(29);
  Serial1.begin(9600, SERIAL_8N1);

  Serial.begin(115200);
  while (!Serial) { ; }
  Serial.println();
  Serial.println("[SYS] UART relay ready -- GP29 -> USB CDC");
}

void loop() {
  while (Serial1.available() > 0) {
    Serial.write(Serial1.read());
  }
}
