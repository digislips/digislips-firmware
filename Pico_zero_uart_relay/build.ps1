# Compile the RP2040-Zero UART-to-USB-CDC relay.
#
# Plain arduino-pico sketch, no TinyUSB override needed -- default USB stack
# gives native CDC (Serial) same as Pico_zero_test.ino.
#
# Usage:
#   .\build.ps1            # compile only, UF2 lands in .\build\
#   .\build.ps1 -Upload    # compile and flash over USB (board must already
#                           # be in normal run mode, not BOOTSEL)

param(
  [switch]$Upload,
  [string]$Port = ""
)

$ErrorActionPreference = "Stop"

$cli  = "C:\Program Files\Arduino CLI\arduino-cli.exe"
$fqbn = "rp2040:rp2040:waveshare_rp2040_zero"
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
  Write-Host "UF2 written to: $outDir\Pico_zero_uart_relay.ino.uf2" -ForegroundColor Cyan
  Write-Host "Manual flash: hold BOOTSEL, plug in, drag that .uf2 onto the RPI-RP2 drive." -ForegroundColor Cyan
}
