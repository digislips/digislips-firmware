import usb.core
import usb.util

# ── ESC/POS command constants ──────────────────────────────────────────────────
ESC = b'\x1b'
GS  = b'\x1d'

INIT          = ESC + b'\x40'
FEED_LINE     = b'\n'
CUT_FULL      = GS  + b'\x56\x00'
CUT_PARTIAL   = GS  + b'\x56\x01'

ALIGN_LEFT    = ESC + b'\x61\x00'
ALIGN_CENTER  = ESC + b'\x61\x01'
ALIGN_RIGHT   = ESC + b'\x61\x02'

BOLD_ON       = ESC + b'\x45\x01'
BOLD_OFF      = ESC + b'\x45\x00'

UNDERLINE_ON  = ESC + b'\x2d\x01'
UNDERLINE_OFF = ESC + b'\x2d\x00'

DOUBLE_HEIGHT = ESC + b'\x21\x10'
DOUBLE_WIDTH  = ESC + b'\x21\x20'
DOUBLE_BOTH   = ESC + b'\x21\x30'
FONT_NORMAL   = ESC + b'\x21\x00'


# ── Printer config ─────────────────────────────────────────────────────────────
USB_VENDOR_ID  = 0x1FC9
USB_PRODUCT_ID = 0x2016
PRINTER_WIDTH  = 42
DEFAULT_ENC    = "cp437"


# ── USB send ───────────────────────────────────────────────────────────────────
USB_PRINTER_CLASS = 0x07
VENDOR_CLASS = 0xFF


def find_bulk_out_endpoint(dev):
    """Scan every interface in the active config for a bulk OUT endpoint,
    instead of assuming it's interface 0 -- on a composite device (e.g. CDC +
    Vendor on the RP2040-Zero bridge board) the relevant interface can land
    at any index. Accepts either a vendor-class (FFh) interface (the bridge
    board) or a standard USB-printer-class (07h) interface (real thermal
    printers, which Windows recognizes and binds usbprint.sys to)."""
    cfg = dev.get_active_configuration()
    for intf in cfg:
        if intf.bInterfaceClass not in (USB_PRINTER_CLASS, VENDOR_CLASS):
            continue
        ep = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
        )
        if ep is not None:
            return ep
    return None


def print_raw_usb(data: bytes) -> None:
    dev = usb.core.find(idVendor=USB_VENDOR_ID, idProduct=USB_PRODUCT_ID)

    if dev is None:
        print(f"[ERROR] Printer not found (VID={hex(USB_VENDOR_ID)} PID={hex(USB_PRODUCT_ID)})")
        print("  -> Is the USB cable plugged in?")
        print("  -> Did you install WinUSB via Zadig?")
        return

    # is_kernel_driver_active is Linux/Mac only — skip on Windows
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except NotImplementedError:
        pass

    try:
        dev.set_configuration()
    except (usb.core.USBError, NotImplementedError) as e:
        print(f"[ERROR] Could not open USB device: {e}")
        print("  -> Windows is likely using its built-in printer driver (usbprint.sys) for this device")
        print("  -> Install WinUSB for this device via Zadig, then unplug/replug")
        return

    ep = find_bulk_out_endpoint(dev)

    if ep is None:
        print("[ERROR] Could not find a USB OUT endpoint on a printer-class or vendor-class interface")
        return

    try:
        ep.write(data)
        print(f"[OK] Sent {len(data)} bytes via USB")
    except usb.core.USBError as e:
        print(f"[ERROR] USB write failed: {e}")
    finally:
        usb.util.dispose_resources(dev)


# ── USB device scanner ─────────────────────────────────────────────────────────
def find_usb_printers() -> None:
    """Scan all USB devices — useful for confirming VID/PID and Zadig install."""
    devices = usb.core.find(find_all=True)
    print("Connected USB devices:")
    for dev in devices:
        try:
            manufacturer = usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else "?"
            product      = usb.util.get_string(dev, dev.iProduct)      if dev.iProduct      else "?"
        except Exception:
            manufacturer = "?"
            product      = "?"
        print(f"  VID={hex(dev.idVendor):<8} PID={hex(dev.idProduct):<8} | {manufacturer} - {product}")


# ── Receipt builder ────────────────────────────────────────────────────────────
class Receipt:
    """Fluent ESC/POS receipt builder. Chain methods then call .print()"""

    def __init__(self, width: int = PRINTER_WIDTH, encoding: str = DEFAULT_ENC):
        self._buf      = bytearray(INIT)
        self._width    = width
        self._encoding = encoding

    def text(self, content: str, encoding: str = None) -> "Receipt":
        self._buf += content.encode(encoding or self._encoding, errors="replace")
        return self

    def line(self, content: str = "", encoding: str = None) -> "Receipt":
        return self.text(content + "\n", encoding)

    def blank(self, count: int = 1) -> "Receipt":
        self._buf += FEED_LINE * count
        return self

    def feed(self, lines: int = 3) -> "Receipt":
        self._buf += ESC + b'\x64' + bytes([lines])
        return self

    def divider(self, char: str = "-") -> "Receipt":
        return self.line(char * self._width)

    def left(self)   -> "Receipt": self._buf += ALIGN_LEFT;   return self
    def center(self) -> "Receipt": self._buf += ALIGN_CENTER; return self
    def right(self)  -> "Receipt": self._buf += ALIGN_RIGHT;  return self

    def bold(self, on: bool = True) -> "Receipt":
        self._buf += BOLD_ON if on else BOLD_OFF
        return self

    def underline(self, on: bool = True) -> "Receipt":
        self._buf += UNDERLINE_ON if on else UNDERLINE_OFF
        return self

    def size(self, mode: str = "normal") -> "Receipt":
        """mode: 'normal' | 'wide' | 'tall' | 'big'"""
        self._buf += {
            "normal": FONT_NORMAL,
            "wide":   DOUBLE_WIDTH,
            "tall":   DOUBLE_HEIGHT,
            "big":    DOUBLE_BOTH,
        }.get(mode, FONT_NORMAL)
        return self

    def row(self, label: str, value: str) -> "Receipt":
        """Left-aligned label, right-aligned value on one line."""
        gap = max(1, self._width - len(label) - len(value))
        return self.line(label + " " * gap + value)

    def logo(self, path: str) -> "Receipt":
        """Load a PNG, scale to 384px wide, and emit GS v 0 raster bitmap bytes."""
        import math
        from PIL import Image

        img = Image.open(path).convert("L")
        orig_w, orig_h = img.size
        target_width = 384
        new_h = max(1, round(orig_h * target_width / orig_w))
        img = img.resize((target_width, new_h), Image.LANCZOS)

        width, height = img.size
        bytes_per_row = math.ceil(width / 8)

        xL = bytes_per_row & 0xFF
        xH = (bytes_per_row >> 8) & 0xFF
        yL = height & 0xFF
        yH = (height >> 8) & 0xFF

        # GS v 0  m=0 (normal density)  xL xH yL yH  data
        self._buf += GS + b'\x76\x30\x00' + bytes([xL, xH, yL, yH])

        pixels = img.load()
        for y in range(height):
            row = bytearray(bytes_per_row)
            for x in range(width):
                if pixels[x, y] < 128:        # dark pixel → print dot
                    row[x // 8] |= (0x80 >> (x % 8))
            self._buf += bytes(row)

        return self

    def barcode(self, value: str, barcode_type: str = "CODE128") -> "Receipt":
        self._buf += GS + b'\x48\x02'          # GS H 2 — HRI below
        self._buf += GS + b'\x68\x50'          # GS h 80 — height 80 dots
        self._buf += GS + b'\x77\x02'          # GS w 2 — module width narrow
        data = "{B" + value
        self._buf += GS + b'k' + bytes([73, len(data)]) + data.encode("ascii")
        self._buf += FEED_LINE
        return self

    def cut(self, partial: bool = False) -> "Receipt":
        self._buf += CUT_PARTIAL if partial else CUT_FULL
        return self

    def build(self) -> bytes:
        return bytes(self._buf)

    def print(self) -> None:
        print_raw_usb(self.build())


# ── Ready-made print jobs ──────────────────────────────────────────────────────
def print_test_page() -> None:
    (
        Receipt()
        .center().bold().line("*** PRINTER TEST ***").bold(False)
        .left()
        .line("Normal text")
        .bold().line("Bold text").bold(False)
        .underline().line("Underlined text").underline(False)
        .size("big").line("Big").size()
        .size("wide").line("Wide text").size()
        .center().line("Centered text")
        .divider()
        .left().line("PASS - printer is working")
        .feed(4).cut()
        .print()
    )


def print_example_receipt(
    store_name: str  = "MY STORE",
    store_addr: str  = "123 Main Street, Cape Town",
    store_tel:  str  = "Tel: +27 21 000 0000",
    items:      list = None,
    subtotal:   str  = "R 0.00",
    vat:        str  = "R 0.00",
    total:      str  = "R 0.00",
    footer:     str  = "Thank you for your purchase!",
) -> None:
    if items is None:
        items    = [("Item A", "R  29.99"), ("Item B", "R  49.99"), ("Item C x3", "R  89.97")]
        subtotal = "R 169.95"
        vat      = "R  25.49"
        total    = "R 195.44"

    r = (
        Receipt()
        .center()
        .size("big").bold().line(store_name).bold(False).size()
        .line(store_addr)
        .line(store_tel)
        .divider()
        .left()
        .bold().line("SALE").bold(False)
    )

    for label, price in items:
        r.row(label, price)

    (
        r.divider()
        .row("Subtotal",  subtotal)
        .row("VAT (15%)", vat)
        .bold().row("TOTAL", total).bold(False)
        .divider()
        .center()
        .line(footer)
        .line("Returns within 30 days with receipt")
        .feed(4).cut()
        .print()
    )


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":

    # Uncomment to confirm printer is visible after Zadig install:
    # find_usb_printers()

    print_test_page()

    # Uncomment to print example receipt:
    # print_example_receipt()

    # Uncomment to print custom receipt:
    # print_example_receipt(
    #     store_name = "BOB'S CAFE",
    #     store_addr = "45 Long Street, Cape Town",
    #     store_tel  = "Tel: +27 21 111 2222",
    #     items      = [
    #         ("Espresso",  "R 28.00"),
    #         ("Croissant", "R 35.00"),
    #         ("OJ x2",     "R 50.00"),
    #     ],
    #     subtotal   = "R 113.00",
    #     vat        = "R  16.95",
    #     total      = "R 129.95",
    #     footer     = "Enjoy your coffee!",
    # )