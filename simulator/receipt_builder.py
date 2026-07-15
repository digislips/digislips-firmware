import os

from cart import Cart

CITY_FRESH_LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_logo.png")
LOYALTY_BARCODE = "9782504938271"


def build_receipt(cart: Cart, receipt_cls, *, include_logo: bool = False, include_barcode: bool = False) -> bytes:
    r = receipt_cls()
    if include_logo:
        r.logo(CITY_FRESH_LOGO_PATH)
    for line in cart.lines():
        r.row(f"{line.qty}x  {line.name}", f"R  {line.price * line.qty:.2f}")
    r.row("Subtotal:", f"R  {cart.subtotal():.2f}")
    r.row("VAT @ 15% (incl.):", f"R  {cart.vat():.2f}")
    r.row("TOTAL:", f"R  {cart.total():.2f}")
    r.row("Tap-to-Pay Visa:", f"R  {cart.total():.2f}")
    if include_barcode:
        r.barcode(LOYALTY_BARCODE)
    return r.build()
