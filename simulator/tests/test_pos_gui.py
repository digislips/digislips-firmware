import ctypes
import random
import sys

import pytest

import Serial_RS232_Driver_v2 as serial_driver
import USB_Only_Driver as usb_driver
import transport
from pos_gui import PosApp, CATALOG
from receipt_builder import build_receipt


@pytest.fixture(scope="module")
def shared_app():
    instance = PosApp()
    yield instance
    instance.destroy()


@pytest.fixture
def app(shared_app):
    shared_app.clear_button.cget("command")()
    shared_app.transport_toggle.set("Serial")
    shared_app._on_transport_changed("Serial")
    shared_app.close_settings()
    return shared_app


def test_app_launches_fullscreen(app):
    assert app.attributes("-fullscreen")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows-only DPI scaling behavior")
def test_fullscreen_window_covers_the_real_screen_resolution(app):
    app.update()
    real_width = ctypes.windll.user32.GetSystemMetrics(0)
    real_height = ctypes.windll.user32.GetSystemMetrics(1)

    assert app.winfo_width() == real_width
    assert app.winfo_height() == real_height


def test_catalog_renders_a_button_per_product(app):
    assert 12 <= len(CATALOG) <= 16
    assert len(app.product_buttons) == len(CATALOG)
    assert set(app.product_buttons.keys()) == {p.name for p in CATALOG}


def test_catalog_fills_the_grid_with_no_empty_gaps(app):
    # 4 columns; a partially filled last row is the "cheap prototype" look this
    # till is meant to avoid.
    assert len(CATALOG) % 4 == 0


def test_tapping_a_product_button_adds_it_to_the_cart(app):
    product = CATALOG[0]

    app.product_buttons[product.name].cget("command")()

    lines = app.cart.lines()
    assert len(lines) == 1
    assert lines[0].name == product.name
    assert lines[0].qty == 1


def test_tapping_the_same_product_button_again_increments_qty_not_duplicate_line(app):
    product = CATALOG[0]

    app.product_buttons[product.name].cget("command")()
    app.product_buttons[product.name].cget("command")()

    lines = app.cart.lines()
    assert len(lines) == 1
    assert lines[0].qty == 2


def test_plus_stepper_increments_qty_and_minus_floors_at_one(app):
    product = CATALOG[0]
    app.product_buttons[product.name].cget("command")()

    line_widgets = app.cart_line_widgets[product.name]
    line_widgets["plus_button"].cget("command")()
    assert app.cart.lines()[0].qty == 2

    line_widgets["minus_button"].cget("command")()
    line_widgets["minus_button"].cget("command")()
    assert app.cart.lines()[0].qty == 1


def test_remove_control_deletes_the_line(app):
    product = CATALOG[0]
    app.product_buttons[product.name].cget("command")()

    app.cart_line_widgets[product.name]["remove_button"].cget("command")()

    assert app.cart.lines() == []
    assert product.name not in app.cart_line_widgets


def test_clear_cart_control_empties_the_basket(app):
    app.product_buttons[CATALOG[0].name].cget("command")()
    app.product_buttons[CATALOG[1].name].cget("command")()

    app.clear_button.cget("command")()

    assert app.cart.lines() == []
    assert app.cart_line_widgets == {}


def test_random_button_fills_the_basket_with_ten_distinct_items(app):
    app.random_button.cget("command")()

    lines = app.cart.lines()
    assert len(lines) == 10
    assert all(line.qty == 1 for line in lines)
    assert len({line.name for line in lines}) == 10
    catalog_names = {p.name for p in CATALOG}
    assert {line.name for line in lines} <= catalog_names


def test_random_button_replaces_the_existing_basket_rather_than_appending(app, monkeypatch):
    app.product_buttons[CATALOG[0].name].cget("command")()
    app.product_buttons[CATALOG[0].name].cget("command")()  # qty 2, to prove it doesn't linger

    monkeypatch.setattr(random, "sample", lambda population, k: list(population)[:k])
    app.random_button.cget("command")()

    lines = app.cart.lines()
    assert len(lines) == 10
    first_line = next(line for line in lines if line.name == CATALOG[0].name)
    assert first_line.qty == 1  # the earlier qty-2 tap was cleared, not carried over


def test_totals_labels_update_live_as_cart_changes(app):
    app.product_buttons[CATALOG[0].name].cget("command")()
    app.product_buttons[CATALOG[1].name].cget("command")()

    assert f"{app.cart.subtotal():.2f}" in app.subtotal_label.cget("text")
    assert f"{app.cart.vat():.2f}" in app.vat_label.cget("text")
    assert f"{app.cart.total():.2f}" in app.total_label.cget("text")

    app.cart_line_widgets[CATALOG[0].name]["plus_button"].cget("command")()

    assert f"{app.cart.subtotal():.2f}" in app.subtotal_label.cget("text")
    assert f"{app.cart.vat():.2f}" in app.vat_label.cget("text")
    assert f"{app.cart.total():.2f}" in app.total_label.cget("text")


def test_include_logo_and_barcode_checkboxes_are_present_and_default_on(app):
    assert app.include_logo_checkbox.get() == 1
    assert app.include_barcode_checkbox.get() == 1


def test_transport_controls_are_hidden_until_settings_is_opened(app):
    # Buyers see this screen during demos; COM ports and baud rates stay out of sight.
    assert not app.serial_controls_frame.winfo_ismapped()
    assert not app.usb_controls_frame.winfo_ismapped()


def test_transport_toggle_defaults_to_serial_and_shows_serial_controls(app):
    app.open_settings()

    assert app.transport_toggle.get() == "Serial"
    assert app.serial_controls_frame.winfo_ismapped()
    assert not app.usb_controls_frame.winfo_ismapped()


def test_settings_can_be_toggled_shut_again(app):
    app.open_settings()
    assert app.serial_controls_frame.winfo_ismapped()

    app.toggle_settings()

    assert not app.serial_controls_frame.winfo_ismapped()


def test_switching_to_usb_shows_usb_controls_and_live_connection_status(app, monkeypatch):
    monkeypatch.setattr(transport, "usb_is_connected", lambda: True)
    app.open_settings()

    app.transport_toggle.set("USB")
    app._on_transport_changed("USB")
    app.update_idletasks()

    assert app.usb_controls_frame.winfo_ismapped()
    assert not app.serial_controls_frame.winfo_ismapped()
    assert "detected" in app.usb_status_label.cget("text").lower()


def test_switching_to_usb_shows_not_detected_when_no_device_found(app, monkeypatch):
    monkeypatch.setattr(transport, "usb_is_connected", lambda: False)

    app.transport_toggle.set("USB")
    app._on_transport_changed("USB")

    assert "not detected" in app.usb_status_label.cget("text").lower()


def test_serial_controls_have_editable_port_and_baud_combo_defaults(app):
    assert app.port_combo.get() != ""
    assert app.baud_combo.get() != ""


def test_baud_combo_is_prepopulated_with_common_baud_rates(app):
    values = app.baud_combo.cget("values")
    assert str(serial_driver.BAUD_RATE) in values
    assert "9600" in values
    assert "115200" in values


def test_scan_ports_button_populates_the_port_combo_and_selects_the_first_found_port(app, monkeypatch):
    monkeypatch.setattr(transport, "scan_serial_ports", lambda: ["COM3", "COM9"])

    app.scan_ports_button.cget("command")()

    assert app.port_combo.cget("values") == ["COM3", "COM9"]
    assert app.port_combo.get() == "COM3"


def test_print_over_serial_sends_receipt_shows_success_and_clears_cart(app, monkeypatch):
    sent = {}

    def fake_send(data, chosen_transport, port=None, baud=None):
        sent["data"] = data
        sent["transport"] = chosen_transport
        sent["port"] = port
        sent["baud"] = baud

    monkeypatch.setattr(transport, "send", fake_send)

    app.product_buttons[CATALOG[0].name].cget("command")()
    expected = build_receipt(app.cart, serial_driver.Receipt, include_logo=True, include_barcode=True)

    app.print_button.cget("command")()

    assert sent["data"] == expected
    assert sent["transport"] is transport.Transport.SERIAL
    assert sent["port"] == app.port_combo.get()
    assert sent["baud"] == int(app.baud_combo.get())
    assert "success" in app.feedback_label.cget("text").lower()
    assert app.cart.lines() == []


def test_unchecked_toggles_are_omitted_from_the_printed_receipt(app, monkeypatch):
    sent = {}
    monkeypatch.setattr(transport, "send", lambda data, t, port=None, baud=None: sent.update(data=data))

    app.include_logo_checkbox.deselect()
    app.include_barcode_checkbox.deselect()
    app.product_buttons[CATALOG[0].name].cget("command")()
    expected = build_receipt(app.cart, serial_driver.Receipt, include_logo=False, include_barcode=False)

    app.print_button.cget("command")()

    assert sent["data"] == expected
    app.include_logo_checkbox.select()
    app.include_barcode_checkbox.select()


def test_print_failure_shows_error_and_leaves_cart_intact(app, monkeypatch):
    def failing_send(data, chosen_transport, port=None, baud=None):
        raise transport.TransportError("Serial error on COM9: device not found")

    monkeypatch.setattr(transport, "send", failing_send)

    app.product_buttons[CATALOG[0].name].cget("command")()
    app.print_button.cget("command")()

    feedback = app.feedback_label.cget("text")
    assert "fail" in feedback.lower()
    assert "device not found" in feedback.lower()
    assert len(app.cart.lines()) == 1
    assert app.cart.lines()[0].name == CATALOG[0].name


def test_print_over_usb_sends_receipt_built_with_usb_driver_and_clears_cart(app, monkeypatch):
    sent = {}

    def fake_send(data, chosen_transport, port=None, baud=None):
        sent["data"] = data
        sent["transport"] = chosen_transport

    monkeypatch.setattr(transport, "send", fake_send)
    monkeypatch.setattr(transport, "usb_is_connected", lambda: True)

    app.transport_toggle.set("USB")
    app._on_transport_changed("USB")
    app.product_buttons[CATALOG[0].name].cget("command")()
    expected = build_receipt(app.cart, usb_driver.Receipt, include_logo=True, include_barcode=True)

    app.print_button.cget("command")()

    assert sent["data"] == expected
    assert sent["transport"] is transport.Transport.USB
    assert "success" in app.feedback_label.cget("text").lower()
    assert app.cart.lines() == []
