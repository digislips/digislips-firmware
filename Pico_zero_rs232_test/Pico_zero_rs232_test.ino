// RS232 echo test for the RP2040-Zero -- console lives on the RS232 pins,
// not on the USB-C CDC port.
//
// GP28/GP29 are UART0 (Serial1) on the RP2040. Wire GP28 (TX) and GP29 (RX)
// through your RS232 transceiver (MAX232 or similar) to a USB-RS232 adapter
// on the PC side, open a terminal on that COM port at 9600 8N1, and
// whatever you type gets echoed straight back. USB-C stays unused for this
// test.
//
// 9600, not the project's usual 19200: the CH340 driver behind this cable
// throws Windows error 31 (SetCommTimeouts rejection) when a caller opens
// the port already configured for 19200 in one call -- Serial_RS232_Driver_v2.py
// only avoids it by opening at 9600 then switching the live handle. Arduino
// Serial Monitor doesn't do that dance, so 9600 here is just to get the
// physical link (cable/transceiver/pins) verified before layering the real
// baud back on.

void setup() {
  Serial1.setTX(28);
  Serial1.setRX(29);
  Serial1.begin(9600, SERIAL_8N1);

  Serial1.println();
  Serial1.println("RP2040-Zero RS232 echo test ready. Type something...");
}

void loop() {
  while (Serial1.available() > 0) {
    char c = Serial1.read();
    Serial1.write(c); // echo the byte straight back
  }
}
