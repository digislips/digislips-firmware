import pytest

import Serial_RS232_Driver_v2 as serial_driver
import USB_Only_Driver as usb_driver
from cart import Cart, Product
from receipt_builder import build_receipt


def test_item_rows_reflect_name_qty_and_price():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.add(Product("Organic Eggs 12pk", 44.99))
    cart.increment("Organic Eggs 12pk")

    buf = build_receipt(cart, serial_driver.Receipt)
    text = buf.decode("gb2312", errors="replace")

    assert "1x" in text and "Sourdough Bread 800g" in text and "62.99" in text
    assert "2x" in text and "Organic Eggs 12pk" in text and "89.98" in text


def test_totals_match_carts_own_calculations():
    cart = Cart()
    cart.add(Product("Organic Eggs 12pk", 44.99))
    cart.increment("Organic Eggs 12pk")
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.add(Product("Almond Butter 400g", 99.99))
    cart.add(Product("Sparkling Water 750ml", 14.99))
    cart.set_qty("Sparkling Water 750ml", 3)

    buf = build_receipt(cart, serial_driver.Receipt)
    text = buf.decode("gb2312", errors="replace")

    assert f"{cart.subtotal():.2f}" in text
    assert f"{cart.vat():.2f}" in text
    assert f"{cart.total():.2f}" in text


def test_payment_line_shows_tap_to_pay_visa_matching_total():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))

    buf = build_receipt(cart, serial_driver.Receipt)
    text = buf.decode("gb2312", errors="replace")

    assert "Tap-to-Pay Visa" in text
    payment_line = next(line for line in text.splitlines() if "Tap-to-Pay Visa" in line)
    assert f"{cart.total():.2f}" in payment_line


def test_include_logo_true_emits_gs_v_0_raster_command():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))

    buf = build_receipt(cart, serial_driver.Receipt, include_logo=True)

    assert serial_driver.GS + b'\x76\x30\x00' in buf


def test_include_logo_false_omits_gs_v_0_raster_command():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))

    buf = build_receipt(cart, serial_driver.Receipt, include_logo=False)

    assert serial_driver.GS + b'\x76\x30\x00' not in buf


def test_include_barcode_true_emits_gs_k_with_fixed_loyalty_code():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))

    buf = build_receipt(cart, serial_driver.Receipt, include_barcode=True)

    assert serial_driver.GS + b'k' in buf
    assert b"9782504938271" in buf


def test_include_barcode_false_omits_gs_k_command():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))

    buf = build_receipt(cart, serial_driver.Receipt, include_barcode=False)

    assert serial_driver.GS + b'k' not in buf


@pytest.mark.parametrize("receipt_cls", [serial_driver.Receipt, usb_driver.Receipt])
@pytest.mark.parametrize("include_logo", [True, False])
@pytest.mark.parametrize("include_barcode", [True, False])
def test_all_logo_barcode_combinations_across_both_drivers(receipt_cls, include_logo, include_barcode):
    cart = Cart()
    cart.add(Product("Organic Eggs 12pk", 44.99))
    cart.increment("Organic Eggs 12pk")
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.add(Product("Almond Butter 400g", 99.99))
    cart.add(Product("Sparkling Water 750ml", 14.99))
    cart.set_qty("Sparkling Water 750ml", 3)

    buf = build_receipt(
        cart, receipt_cls, include_logo=include_logo, include_barcode=include_barcode
    )

    assert (serial_driver.GS + b'\x76\x30\x00' in buf) is include_logo
    assert (serial_driver.GS + b'k' in buf) is include_barcode

    text = buf.decode("cp437", errors="replace")
    assert f"{cart.subtotal():.2f}" in text
    assert f"{cart.vat():.2f}" in text
    assert f"{cart.total():.2f}" in text
