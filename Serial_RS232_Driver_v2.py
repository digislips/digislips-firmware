import serial
import serial.tools.list_ports
import time
from datetime import datetime

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
SERIAL_PORT   = "COM9"
BAUD_RATE     = 19200
PRINTER_WIDTH = 42
DEFAULT_ENC   = "gb2312"


# ── Persistent connection ──────────────────────────────────────────────────────
# CH340 fix: opening at 9600 then swapping to 19200 avoids the SetCommTimeouts
# call that causes Windows error 31 ("device not functioning") on some CH340
# driver versions. Port is held open across multiple sends so Windows never
# has a chance to re-enter the bad configuration path between receipts.
_ser: serial.Serial | None = None


def open_port(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> serial.Serial:
    """
    Open the COM port using the CH340-safe two-step sequence:
      1. open at 9600 (always accepted)
      2. swap baudrate to the target rate on the live handle

    Also disables DTR so the ESP32 auto-reset circuit is not triggered.
    """
    ser = serial.Serial(
        port     = port,
        baudrate = 9600,          # step 1 — safe open rate
        bytesize = serial.EIGHTBITS,
        parity   = serial.PARITY_NONE,
        stopbits = serial.STOPBITS_ONE,
        timeout  = 5.0,
        write_timeout = None,     # None = block until done; avoids SetCommTimeouts bug
        xonxoff  = False,
        rtscts   = False,
        dsrdtr   = False,
    )
    ser.dtr = False               # prevent ESP32 EN reset on connect
    ser.rts = False
    ser.baudrate = baud           # step 2 — swap to target rate on live handle
    time.sleep(0.05)              # brief settle after rate change
    return ser


def get_connection(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> serial.Serial:
    """Return the shared open connection, opening it if needed."""
    global _ser
    if _ser is None or not _ser.is_open:
        _ser = open_port(port, baud)
        print(f"[COM] Opened {port} @ {baud} baud")
    return _ser


def close_connection() -> None:
    """Explicitly close the shared connection."""
    global _ser
    if _ser and _ser.is_open:
        _ser.close()
        print("[COM] Port closed")
    _ser = None


# ── Low-level send function ────────────────────────────────────────────────────
def print_raw_serial(
    data: bytes,
    port:    str = SERIAL_PORT,
    baud:    int = BAUD_RATE,
    rtscts:  bool = False,
    xonxoff: bool = False,
) -> None:
    """
    Send raw ESC/POS bytes to a legacy printer over RS-232.

    Uses a persistent connection to avoid the CH340 Windows driver bug where
    re-opening the port at 19200 triggers error 31.
    """
    try:
        ser = get_connection(port, baud)

        # CH340 TX FIFO is ~32 bytes — chunk with inter-chunk delay.
        chunk_delay = 32 / baud * 10 * 1.5
        for i in range(0, len(data), 32):
            ser.write(data[i:i + 32])
            time.sleep(chunk_delay)
        ser.flush()
        print(f"[OK] Sent {len(data)} bytes to {port} @ {baud} baud")

    except serial.SerialException as e:
        print(f"[ERROR] Serial error on {port}: {e}")
        print("  -> Connection will be reset on next send")
        close_connection()

    except serial.SerialTimeoutException:
        print(f"[ERROR] Write timed out on {port}")
        close_connection()


# ── Port discovery ─────────────────────────────────────────────────────────────
def find_serial_ports() -> list[str]:
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return []

    print("Available serial ports:")
    names = []
    for p in sorted(ports):
        print(f"  {p.device:<20} | {p.description}")
        names.append(p.device)
    return names


# ── Baud diagnostic ────────────────────────────────────────────────────────────
def diagnose_baud(port: str = SERIAL_PORT) -> None:
    """
    Test whether the port can be configured at common baud rates.
    Useful for confirming the CH340 driver workaround is working.
    """
    test_rates = [9600, 19200, 38400, 57600, 115200]
    print(f"\nBaud rate diagnostics for {port}:")
    print("-" * 40)
    for rate in test_rates:
        try:
            ser = open_port(port, rate)
            ser.close()
            print(f"  {rate:>7} baud  →  OK")
        except serial.SerialException as e:
            short = str(e).split(".")[0]
            print(f"  {rate:>7} baud  →  FAIL  ({short})")
    print("-" * 40)


# ── Receipt builder ────────────────────────────────────────────────────────────
class Receipt:
    """
    Fluent ESC/POS receipt builder for RS-232 / serial printers.

    Chain methods, then call  .print()  to send via the configured COM port.

    Example
    ───────
    Receipt()
        .center().bold().line("MY STORE").bold(False)
        .divider()
        .row("Item A", "R 29.99")
        .divider()
        .bold().row("TOTAL", "R 29.99").bold(False)
        .feed(4).cut()
        .print()
    """

    def __init__(self, width: int = PRINTER_WIDTH, encoding: str = DEFAULT_ENC):
        self._buf      = bytearray(INIT)
        self._width    = width
        self._encoding = encoding

    # ── Text ──────────────────────────────────────────────────────────────────
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

    # ── Alignment ─────────────────────────────────────────────────────────────
    def left(self)   -> "Receipt": self._buf += ALIGN_LEFT;   return self
    def center(self) -> "Receipt": self._buf += ALIGN_CENTER; return self
    def right(self)  -> "Receipt": self._buf += ALIGN_RIGHT;  return self

    # ── Style ─────────────────────────────────────────────────────────────────
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

    # ── Two-column row ─────────────────────────────────────────────────────────
    def row(self, label: str, value: str) -> "Receipt":
        gap = max(1, self._width - len(label) - len(value))
        return self.line(label + " " * gap + value)

    # ── Barcode ───────────────────────────────────────────────────────────────
    def barcode(self, value: str, barcode_type: str = "CODE128") -> "Receipt":
        self._buf += GS + b'\x48\x02'          # GS H 2 — HRI below
        self._buf += GS + b'\x68\x50'          # GS h 80 — height 80 dots
        self._buf += GS + b'\x77\x02'          # GS w 2 — module width narrow
        data = "{B" + value
        self._buf += GS + b'k' + bytes([73, len(data)]) + data.encode("ascii")
        self._buf += FEED_LINE
        return self

    # ── Cut ───────────────────────────────────────────────────────────────────
    def cut(self, partial: bool = False) -> "Receipt":
        self._buf += CUT_PARTIAL if partial else CUT_FULL
        return self

    # ── Build / Print ─────────────────────────────────────────────────────────
    def build(self) -> bytes:
        return bytes(self._buf)

    def print(
        self,
        port:    str = SERIAL_PORT,
        baud:    int = BAUD_RATE,
        rtscts:  bool = False,
        xonxoff: bool = False,
    ) -> None:
        print_raw_serial(self.build(), port=port, baud=baud, rtscts=rtscts, xonxoff=xonxoff)


# ── Ready-made print jobs ──────────────────────────────────────────────────────
def print_test_page(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
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
        .print(port=port, baud=baud)
    )


# ══════════════════════════════════════════════════════════════════════════════
# STRESS-TEST SLIPS  (1 = longest / most complex  →  5 = shortest / simplest)
# ══════════════════════════════════════════════════════════════════════════════

def slip_1_full_tax_invoice(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
    now = datetime.now().strftime("%d/%m/%Y  %H:%M:%S")
    r = (
        Receipt()
        .center()
        .size("big").bold().line("MACRO MART").bold(False).size()
        .line("1 Voortrekker Road, Bellville, 7530")
        .line("Tel: +27 21 945 1100")
        .line("VAT Reg: 4150987632")
        .line("www.macromart.co.za")
        .divider("=")
        .bold().line("TAX INVOICE").bold(False)
        .divider("=")
        .left()
        .row("Date/Time:", now)
        .row("Cashier:", "Emma van Zyl  [EV04]")
        .row("Till:", "#3  |  Trans: 00087421")
        .row("Customer:", "Walk-in")
        .divider()
        .bold().line("QTY  DESCRIPTION            PRICE").bold(False)
        .divider()
        .row("1x  Albany Superior Bread 700g", "R  24.99")
        .row("2x  Clover Full Cream Milk 2L", "R  89.98")
        .row("1x  Nescafe Classic 200g", "R  89.99")
        .row("3x  Simba Chips Orig 120g", "R  74.97")
        .row("1x  Koo Baked Beans 410g", "R  19.99")
        .row("2x  Lucky Star Pilchards 400g", "R  59.98")
        .row("1x  Ina Paarman Pasta Sauce", "R  42.99")
        .row("4x  Sta-Soft Concentrate 500ml", "R 119.96")
        .divider("-")
        .row("1x  Handy Andy Cream 750ml", "R  34.99")
        .row("1x  Sunlight Dishwash Liq 750ml", "R  29.99")
        .row("2x  Glad Zip-Lock Bags 25pk", "R  49.98")
        .row("1x  Energizer AA Batteries 4pk", "R  64.99")
        .divider("-")
        .row("0.65kg  Sliced Polony @ R59.99/kg", "R  38.99")
        .row("0.42kg  Gouda Cheese @ R189.99/kg", "R  79.79")
        .row("1x  Sasko Bread Rolls 6pk", "R  21.99")
        .divider("-")
        .row("1.20kg  Granny Smith Apples", "R  35.88")
        .row("0.80kg  Loose Tomatoes", "R  15.92")
        .row("1x  Bag Baby Spinach 200g", "R  29.99")
        .divider("-")
        .row("1x  McCain Oven Chips 1.5kg", "R  74.99")
        .row("1x  Eskimo Pie Vanilla 8pk", "R  59.99")
        .divider("=")
        .row("Subtotal (20 items):", "R 1 059.35")
        .row("Member Discount (5%):", "-R   52.97")
        .divider()
        .row("Zero-rated goods:", "R  160.77")
        .row("Standard-rated goods:", "R  845.61")
        .row("VAT @ 15%:", "R  110.28")
        .divider()
        .bold().size("wide")
        .row("TOTAL:", "R 1 006.38")
        .size().bold(False)
        .divider("=")
        .bold().line("PAYMENT").bold(False)
        .row("Cash tendered:", "R 1 100.00")
        .row("Change:", "-R    93.62")
        .divider()
        .center()
        .bold().line("SMART SHOPPER POINTS").bold(False)
        .row("Points earned this visit:", "    1 006")
        .row("Points balance:", "   47 832")
        .row("Rand value:", "R  478.32")
        .divider("=")
        .center()
        .line("Goods may be exchanged within 30 days")
        .line("with original receipt. No cash refunds")
        .line("on perishables. E&OE.")
        .blank()
        .line("For complaints / compliments:")
        .line("0800 111 222 (toll-free)")
        .line("service@macromart.co.za")
        .blank()
        .underline().line("macromart.co.za/terms").underline(False)
        .blank()
        .bold().line("THANK YOU FOR SHOPPING WITH US!").bold(False)
        .line("Please come again.")
        .feed(4).cut()
    )
    r.print(port=port, baud=baud)


def slip_2_restaurant_order(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
    now = datetime.now().strftime("%d/%m/%Y  %H:%M:%S")
    (
        Receipt()
        .center()
        .size("big").bold().line("THE HARBOUR GRILL").bold(False).size()
        .line("Waterfront Promenade, Cape Town")
        .line("Tel: +27 21 418 9999")
        .line("VAT: 4180123456")
        .divider("=")
        .row("Table:", "14 (Patio)")
        .row("Covers:", "4")
        .row("Waiter:", "Sipho M.  [SM09]")
        .row("Opened:", "18:42")
        .row("Printed:", now)
        .row("Bill No:", "B-20240417-0231")
        .divider("=")
        .left()
        .bold().line("STARTERS").bold(False)
        .row("Calamari Fritti (x2)", "R 179.00")
        .line("   > lemon aioli, rocket")
        .row("Soup of the Day", "R  95.00")
        .line("   > butternut, creme fraiche")
        .row("Beef Carpaccio", "R 145.00")
        .line("   > shaved parmesan, capers")
        .divider()
        .bold().line("MAIN COURSES").bold(False)
        .row("Grilled Kingklip (x2)", "R 520.00")
        .line("   > chips & salad  |  medium")
        .row("Ribeye 400g", "R 345.00")
        .line("   > pepper sauce  |  medium-rare")
        .row("Mushroom Risotto (v)", "R 195.00")
        .line("   > truffle oil, parmesan")
        .divider()
        .bold().line("DESSERTS").bold(False)
        .row("Malva Pudding (x2)", "R 130.00")
        .line("   > custard & ice cream")
        .row("Cheese Board", "R 145.00")
        .line("   > brie, cheddar, preserve")
        .divider()
        .bold().line("BEVERAGES").bold(False)
        .row("Waterfront White 750ml", "R 220.00")
        .row("Heineken 340ml (x4)", "R 180.00")
        .row("Still Water 500ml (x3)", "R  75.00")
        .row("Cappuccino (x2)", "R  80.00")
        .row("Rooibos Tea", "R  30.00")
        .divider("=")
        .row("Food Subtotal:", "R 1 754.00")
        .row("Beverage Subtotal:", "R   585.00")
        .row("Service Charge (10%):", "R   233.90")
        .row("VAT (incl.):", "R   335.79")
        .divider()
        .bold().size("wide")
        .row("TOTAL DUE:", "R 2 572.90")
        .size().bold(False)
        .divider("=")
        .bold().line("PAYMENT").bold(False)
        .row("Visa **** 4821:", "R 2 000.00")
        .row("Cash:", "R   572.90")
        .row("Balance:", "R     0.00")
        .divider()
        .center()
        .line("Additional gratuity (optional):")
        .blank()
        .line("Amount: R _____________")
        .blank()
        .line("Signature: ____________")
        .blank()
        .line("Thank you for dining with us!")
        .line("Please review us on TripAdvisor")
        .line("tripadvisor.com/harbourgrillct")
        .feed(4).cut()
        .print(port=port, baud=baud)
    )


def slip_3_fuel_receipt(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
    now = datetime.now().strftime("%d/%m/%Y  %H:%M:%S")
    (
        Receipt()
        .center()
        .size("big").bold().line("SUNCOAST ENGEN").bold(False).size()
        .line("N2 Northbound, Strand, 7140")
        .line("Tel: +27 21 853 7700")
        .line("VAT Reg: 4290765432")
        .divider("=")
        .left()
        .row("Date/Time:", now)
        .row("Shift:", "#2  |  Attendant: Andile K")
        .row("Pump:", "#5  |  Trans: FP-88321")
        .row("Vehicle Reg:", "CA 447 891")
        .divider()
        .bold().line("FUEL").bold(False)
        .row("Grade:", "95 Unleaded (ULP)")
        .row("Litres:", "       62.31 L")
        .row("Price/Litre:", "   R  22.18")
        .divider()
        .bold().size("wide").row("Fuel Total:", "R 1 382.08").size().bold(False)
        .divider()
        .bold().line("SHOP ITEMS").bold(False)
        .row("Coca-Cola 500ml", "R  22.99")
        .row("Castrol GTX 1L top-up", "R 159.99")
        .divider()
        .row("Shop Subtotal:", "R  182.98")
        .row("VAT @ 15% (incl.):", "R   23.87")
        .divider("=")
        .bold().size("wide").row("GRAND TOTAL:", "R 1 565.06").size().bold(False)
        .divider("=")
        .bold().line("PAYMENT").bold(False)
        .row("Fleet Card (Wesbank):", "R 1 382.08")
        .row("Visa **** 3341:", "R   182.98")
        .divider()
        .bold().line("ENGEN REWARDS").bold(False)
        .row("Points earned:", "     1 565")
        .row("Points balance:", "    24 310")
        .divider("=")
        .center()
        .line("Drive safe!")
        .line("Next service due: 15 000 km")
        .line("or 6 months from today")
        .blank()
        .line("engen.co.za  |  0800 ENGEN1")
        .feed(4).cut()
        .print(port=port, baud=baud)
    )


def slip_4_parking_ticket(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
    now = datetime.now().strftime("%d/%m/%Y  %H:%M")
    (
        Receipt()
        .center()
        .size("big").bold().line("CITY PARK").bold(False).size()
        .line("Hertzog Boulevard Parkade")
        .line("Cape Town CBD")
        .divider("=")
        .left()
        .row("Ticket No:", "CPT-20240417-4892")
        .row("Entry:", "17 Apr 2024  09:14")
        .row("Exit:", f"17 Apr 2024  {now.split()[1]}")
        .row("Duration:", "4 hrs 23 min")
        .row("Bay:", "B-047  (Covered)")
        .divider()
        .row("Base rate (0-2 hrs):", "R  25.00")
        .row("Additional (2.38 hrs):", "R  47.50")
        .divider()
        .bold().size("wide").row("TOTAL PAID:", "R  72.50").size().bold(False)
        .divider()
        .row("Payment:", "Tap-to-Pay  Mastercard")
        .row("Card:", "**** **** **** 9104")
        .row("Auth:", "TXN-887341")
        .divider("=")
        .center()
        .line("Validated by: Canal Walk")
        .line("Max stay: 24 hrs")
        .blank()
        .line("citypark.co.za")
        .feed(4).cut()
        .print(port=port, baud=baud)
    )


def slip_5_quick_sale(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
    now = datetime.now().strftime("%d/%m/%Y  %H:%M")
    (
        Receipt()
        .center()
        .bold().size("big").line("BEAN THERE").size().bold(False)
        .line("Gardens Centre, Cape Town")
        .divider()
        .left()
        .row(now, "Till: #1")
        .divider()
        .row("Flat White (Reg)", "R 38.00")
        .divider()
        .bold().row("TOTAL", "R 38.00").bold(False)
        .row("Cash", "R 50.00")
        .row("Change", "R 12.00")
        .divider()
        .center()
        .line("Enjoy your coffee!")
        .feed(4).cut()
        .print(port=port, baud=baud)
    )


def slip_6_barcode_test(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
    now = datetime.now().strftime("%d/%m/%Y  %H:%M:%S")
    (
        Receipt()
        .center()
        .size("big").bold().line("PEP STORES").bold(False).size()
        .line("Shop 14, Bellville Square")
        .line("Voortrekker Rd, Bellville, 7530")
        .line("Tel: +27 21 945 3300")
        .line("VAT Reg: 4150234987")
        .divider("=")
        .left()
        .row("Date/Time:", now)
        .row("Cashier:", "Fatima D.  [FD02]")
        .row("Till:", "#2  |  Trans: 00034817")
        .divider()
        .bold().line("QTY  DESCRIPTION            PRICE").bold(False)
        .divider()
        .row("2x  School Shirt Size 12", "R  79.98")
        .row("1x  Denim Shorts 10-11 yrs", "R  89.99")
        .row("3x  Cotton Socks 3-pk", "R  89.97")
        .row("1x  Backpack 30L Navy", "R 149.99")
        .divider("=")
        .row("Subtotal (7 items):", "R  409.93")
        .row("VAT @ 15% (incl.):", "R   53.47")
        .divider()
        .bold().size("wide").row("TOTAL:", "R  409.93").size().bold(False)
        .divider("=")
        .bold().line("PAYMENT").bold(False)
        .row("Cash tendered:", "R  420.00")
        .row("Change:", "-R   10.07")
        .divider("=")
        .center()
        .bold().line("PEP REWARDS").bold(False)
        .line("Scan your card to earn points")
        .blank()
        .barcode("9782504938271")
        .blank()
        .line("Thank you for shopping at Pep!")
        .line("Goods exchangeable within 30 days")
        .line("with original receipt.")
        .feed(4).cut()
        .print(port=port, baud=baud)
    )


# ── Slip registry ──────────────────────────────────────────────────────────────
SLIPS = {
    "1": {
        "fn":   slip_1_full_tax_invoice,
        "name": "Full Tax Invoice (Supermarket, 20 items)",
        "size": "LONGEST  ~2.5 m",
    },
    "2": {
        "fn":   slip_2_restaurant_order,
        "name": "Restaurant Bill + Split Payment",
        "size": "LONG     ~1.5 m",
    },
    "3": {
        "fn":   slip_3_fuel_receipt,
        "name": "Filling Station Fuel Receipt",
        "size": "MEDIUM   ~0.9 m",
    },
    "4": {
        "fn":   slip_4_parking_ticket,
        "name": "Parking Garage Ticket",
        "size": "SHORT    ~0.5 m",
    },
    "5": {
        "fn":   slip_5_quick_sale,
        "name": "Quick Coffee Shop Sale (1 item)",
        "size": "SHORTEST ~0.2 m",
    },
    "6": {
        "fn":   slip_6_barcode_test,
        "name": "Retail Slip + Code128 Loyalty Barcode",
        "size": "BARCODE  ~0.6 m",
    },
    "0": {
        "fn":   print_test_page,
        "name": "Printer Test Page (font/style check)",
        "size": "TEST",
    },
}


# ── Interactive menu ──────────────────────────────────────────────────────────
def run_menu(port: str = SERIAL_PORT, baud: int = BAUD_RATE) -> None:
    while True:
        print()
        print("=" * 52)
        print("  RS-232 PRINTER STRESS-TEST MENU  [v2]")
        print(f"  Port: {port}  |  Baud: {baud}")
        print("=" * 52)
        for key, info in SLIPS.items():
            print(f"  [{key}]  {info['size']:<16}  {info['name']}")
        print("  [A]  ALL slips in sequence (full stress test)")
        print("  [D]  Diagnose baud rates on this port")
        print("  [P]  Scan / list available COM ports")
        print("  [Q]  Quit")
        print("=" * 52)

        choice = input("  Enter choice: ").strip().upper()
        print()

        if choice == "Q":
            close_connection()
            print("Goodbye.")
            break

        elif choice == "P":
            find_serial_ports()

        elif choice == "D":
            diagnose_baud(port)

        elif choice == "A":
            print("Printing ALL 5 slips in sequence...")
            print("Press ENTER after the device returns to idle before each slip.\n")
            keys = ["1", "2", "3", "4", "5"]
            for i, key in enumerate(keys):
                info = SLIPS[key]
                if i > 0:
                    input(f"  [Press ENTER when device is idle to send next slip] ")
                print(f"\n--- Sending: {info['name']} ---")
                info["fn"](port=port, baud=baud)
            print("\n[DONE] All slips sent.")

        elif choice in SLIPS:
            info = SLIPS[choice]
            print(f"Sending: {info['name']}")
            info["fn"](port=port, baud=baud)

        else:
            print("[!] Invalid choice. Please enter 0–6, A, D, P, or Q.")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Scanning for serial ports...")
    find_serial_ports()
    print()
    print(f"Default port : {SERIAL_PORT} @ {BAUD_RATE} baud")
    print(f"Paper width  : {PRINTER_WIDTH} chars (80mm)")
    print()
    print("TIP: Select [D] from the menu to test baud rate support on this port.")
    print()

    run_menu(port=SERIAL_PORT, baud=BAUD_RATE)
