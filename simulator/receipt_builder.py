import os
from datetime import datetime

from cart import Cart

CITY_FRESH_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_logo.png")
LOYALTY_BARCODE = "9782504938271"

STORE_NAME    = "CITY FRESH"
STORE_ADDR    = ["Shop 3, Greenpoint Market", "Main Road, Cape Town, 8005"]
STORE_TEL     = "Tel: +27 21 439 7700"
STORE_VAT_REG = "VAT Reg: 4320876543"
CASHIER       = "Lerato M.  [LM01]"
TILL          = "#1  |  Trans: 00012345"


def build_receipt(cart: Cart, receipt_cls, *, include_logo: bool = False, include_barcode: bool = False) -> bytes:
    now = datetime.now().strftime("%d/%m/%Y  %H:%M:%S")
    r = receipt_cls()

    r.center()
    if include_logo:
        r.logo(CITY_FRESH_LOGO_PATH).blank()

    r.size("big").bold().line(STORE_NAME).bold(False).size()
    for line in STORE_ADDR:
        r.line(line)
    r.line(STORE_TEL)
    r.line(STORE_VAT_REG)
    r.divider("=")

    r.left()
    r.row("Date/Time:", now)
    r.row("Cashier:", CASHIER)
    r.row("Till:", TILL)
    r.divider()

    r.bold().line("QTY  DESCRIPTION            PRICE").bold(False)
    r.divider()
    for line in cart.lines():
        r.row(f"{line.qty}x  {line.name}", f"R  {line.price * line.qty:.2f}")
    r.divider("=")

    r.row("Subtotal:", f"R  {cart.subtotal():.2f}")
    r.row("VAT @ 15% (incl.):", f"R  {cart.vat():.2f}")
    r.divider()
    r.bold().size("wide")
    r.row("TOTAL:", f"R  {cart.total():.2f}")
    r.size().bold(False)
    r.divider("=")

    r.bold().line("PAYMENT").bold(False)
    r.row("Tap-to-Pay Visa:", f"R  {cart.total():.2f}")
    r.divider("=")

    r.center()
    if include_barcode:
        r.bold().line(f"{STORE_NAME} REWARDS").bold(False)
        r.line("Scan your card to earn points")
        r.blank()
        r.barcode(LOYALTY_BARCODE)
        r.blank()
    r.line("Thank you for shopping fresh!")
    r.line("cityfresh.co.za")
    r.feed(4).cut()

    return r.build()
