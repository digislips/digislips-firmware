// Per-device credentials — DO NOT COMMIT. This file is gitignored.
// To provision a new device, copy config.h.example → config.h and fill in real values.

#pragma once

// WiFi credentials, device_token, device_id, merchant_id, and till_id are now
// stored in NVS and fetched from Supabase at boot — NOT compiled into the binary.
// Use the captive portal (power on with empty NVS) to provision WiFi + token.

// Supabase
#define SUPABASE_URL   "https://eivctqjisodfhaitzyiq.supabase.co"
#define SUPABASE_ANON  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVpdmN0cWppc29kZmhhaXR6eWlxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY4MDgxMjIsImV4cCI6MjA5MjM4NDEyMn0._0wu91Zrc3aMrKsO_KUkp64CoOCklwMViYAofYZyCFI"

// QR code base URL — phone app will open https://digislips.co.za/slip/<slip_uuid>
#define QR_BASE_URL    "https://digislips.co.za/slip/"

// NTP
#define NTP_SERVER     "pool.ntp.org"
#define TZ_OFFSET      7200  // UTC+2 (SAST) in seconds
