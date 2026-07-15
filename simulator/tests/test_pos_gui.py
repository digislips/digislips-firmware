import ctypes
import sys

import pytest

from pos_gui import PosApp, CATALOG


@pytest.fixture(scope="module")
def shared_app():
    instance = PosApp()
    yield instance
    instance.destroy()


@pytest.fixture
def app(shared_app):
    shared_app.clear_button.cget("command")()
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
