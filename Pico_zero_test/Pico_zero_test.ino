// Quick USB serial echo test for the RP2040-Zero.
// Whatever you type in the Serial Monitor gets echoed straight back.
// Baud in the Serial Monitor doesn't matter for USB CDC — set anything.

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    ; // wait for the USB serial port to be ready
  }
  Serial.println();
  Serial.println("RP2040-Zero echo test ready. Type something...");
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    Serial.write(c); // echo the byte straight back
  }
}
