# Compile (and optionally upload) the RP2040-Zero USB printer-bridge firmware.
#
# Needed instead of plain Arduino IDE "Verify"/"Upload": this firmware
# requires the CFG_TUSB_CONFIG_FILE override (tusb_config_override.h) to
# turn on TinyUSB's vendor class, which arduino-pico's core hardcodes off
# for RP2040 with no sketch-level way to flip it back on. arduino-cli lets
# us pass that as a build property; the IDE has no equivalent UI for it.
#
# Usage:
#   .\build.ps1            # compile only
#   .\build.ps1 -Upload    # compile and flash (board must already be in
#                           # normal run mode, not BOOTSEL -- UF2 upload
#                           # auto-resets it)

param(
  [switch]$Upload,
  [string]$Port = ""
)

$ErrorActionPreference = "Stop"

$cli  = "C:\Program Files\Arduino CLI\arduino-cli.exe"
$fqbn = "rp2040:rp2040:waveshare_rp2040_zero:usbstack=tinyusb"
$sketchDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir    = Join-Path $sketchDir "build"

# -I is needed because the sketch folder isn't on the include path for
# library-internal (TinyUSB) source files by default -- only for the .ino
# itself. Without it, CFG_TUSB_CONFIG_FILE resolves to nothing.
$tusbFlag = "-I`"$sketchDir`" -DCFG_TUSB_CONFIG_FILE=\`"tusb_config_override.h\`""

$buildProps = @(
  "--build-property", "compiler.c.extra_flags=$tusbFlag",
  "--build-property", "compiler.cpp.extra_flags=$tusbFlag"
)

if ($Upload) {
  if (-not $Port) {
    Write-Host "Pass -Port COMx (check Device Manager) to upload." -ForegroundColor Yellow
    exit 1
  }
  & $cli compile --fqbn $fqbn @buildProps --output-dir $outDir --upload --port $Port $sketchDir
} else {
  & $cli compile --fqbn $fqbn @buildProps --output-dir $outDir $sketchDir
  Write-Host ""
  Write-Host "UF2 written to: $outDir\Pico_zero_usb_printer.ino.uf2" -ForegroundColor Cyan
  Write-Host "Manual flash: hold BOOTSEL, plug in, drag that .uf2 onto the RPI-RP2 drive." -ForegroundColor Cyan
}
