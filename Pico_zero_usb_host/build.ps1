# Compile (and optionally upload) the RP2040-Zero USB-host spike firmware.
#
# Unlike Pico_zero_usb_printer's build.ps1, no CFG_TUSB_CONFIG_FILE override
# is needed here -- "Adafruit TinyUSB Host (native)" is a first-class Tools
# -> USB Stack board option (usbstack=tinyusb_host) on the installed
# rp2040:rp2040 5.6.1 core, so a plain FQBN selection is enough.
#
# Usage:
#   .\build.ps1            # compile only
#   .\build.ps1 -Upload -Port COMx   # compile and flash

param(
  [switch]$Upload,
  [string]$Port = ""
)

$ErrorActionPreference = "Stop"

$cli  = "C:\Program Files\Arduino CLI\arduino-cli.exe"
$fqbn = "rp2040:rp2040:waveshare_rp2040_zero:usbstack=tinyusb_host"
$sketchDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir    = Join-Path $sketchDir "build"

if ($Upload) {
  if (-not $Port) {
    Write-Host "Pass -Port COMx (check Device Manager) to upload." -ForegroundColor Yellow
    exit 1
  }
  & $cli compile --fqbn $fqbn --output-dir $outDir --upload --port $Port $sketchDir
} else {
  & $cli compile --fqbn $fqbn --output-dir $outDir $sketchDir
  Write-Host ""
  Write-Host "UF2 written to: $outDir\Pico_zero_usb_host.ino.uf2" -ForegroundColor Cyan
  Write-Host "Manual flash: hold BOOTSEL, plug in, drag that .uf2 onto the RPI-RP2 drive." -ForegroundColor Cyan
}
