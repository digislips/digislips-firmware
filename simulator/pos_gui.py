import random
import sys
import textwrap
import tkinter

import customtkinter as ctk

import Serial_RS232_Driver_v2 as serial_driver
import USB_Only_Driver as usb_driver
import theme
import transport
from cart import Cart, Product
from receipt_builder import CITY_FRESH_LOGO_PATH, build_receipt

if sys.platform.startswith("win"):
    # customtkinter also requests per-monitor DPI awareness, but only once its
    # own Tk root already exists -- by then Windows has already handed the
    # process a DPI-scaled logical screen size, so "-fullscreen" undershoots
    # the real screen. Requesting it here, before any Tk window exists, makes
    # winfo_screenwidth/height report true pixels.
    import ctypes

    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE

theme.load_font_files()

BAUD_RATES: list[str] = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]

STORE_NAME = "CITY FRESH"

RAIL_WIDTH = 400
GRID_COLUMNS = 4
RANDOM_BASKET_SIZE = 10

CATALOG: list[Product] = [
    Product("Avocado Ready-to-Eat", 12.99, "Produce"),
    Product("Punnet Strawberries 250g", 34.99, "Produce"),
    Product("Baby Spinach 200g", 24.99, "Produce"),
    Product("Banana Bunch 1kg", 19.99, "Produce"),
    Product("Sourdough Bread 800g", 62.99, "Bakery"),
    Product("Croissants 6pk", 45.99, "Bakery"),
    Product("Multigrain Rolls 6pk", 39.99, "Bakery"),
    Product("Organic Eggs 12pk", 44.99, "Dairy"),
    Product("Full Cream Milk 2L", 32.99, "Dairy"),
    Product("Cheddar Cheese Block 400g", 79.99, "Dairy"),
    Product("Sparkling Water 750ml", 14.99, "Drinks"),
    Product("Orange Juice 1L", 29.99, "Drinks"),
    Product("Cold Brew Coffee 330ml", 27.99, "Drinks"),
    Product("Almond Butter 400g", 99.99, "Snacks"),
    Product("Mixed Nuts 200g", 54.99, "Snacks"),
    Product("Dark Chocolate 100g", 39.99, "Snacks"),
]


def _tile_text(product: Product) -> str:
    # break_on_hyphens would split "Ready-to-Eat" across lines. Names are padded to a
    # fixed two lines so every price in the grid lands on the same baseline.
    lines = textwrap.wrap(product.name, 18, break_on_hyphens=False) or [product.name]
    lines += [""] * (2 - len(lines))
    return "\n".join(lines) + f"\n\nR {product.price:.2f}"


def _hairline(master, orientation="horizontal", color=theme.HAIRLINE):
    # A CTkFrame paints nothing below 3px tall, so a true 1px rule has to be a plain
    # Tk frame. Safe here because the till is light-mode only with explicit colours.
    if orientation == "horizontal":
        return tkinter.Frame(master, bg=color, height=1)
    return tkinter.Frame(master, bg=color, width=1)


class PosApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("City Fresh POS")
        ctk.set_appearance_mode("light")
        self.configure(fg_color=theme.PAGE)
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", self._on_escape)
        self.bind("<F10>", lambda event: self.toggle_settings())

        self.fonts = theme.Fonts()
        self.cart = Cart()
        self.product_buttons: dict[str, ctk.CTkButton] = {}
        self.cart_line_widgets: dict[str, dict] = {}
        self._cart_rows: list[ctk.CTkBaseClass] = []
        self._settings_open = False

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_body()
        self._build_settings_panel()
        self._refresh_cart_view()

    # ---------- header ----------

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=0, height=68)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.grid_columnconfigure(1, weight=1)

        logo = self._load_logo()
        if logo is not None:
            ctk.CTkLabel(header, image=logo, text="").grid(row=0, column=0, padx=(26, 0), pady=18)
        else:
            ctk.CTkLabel(
                header, text=STORE_NAME, font=self.fonts.brand(), text_color=theme.TEXT
            ).grid(row=0, column=0, padx=(26, 0), pady=18)

        self.settings_button = ctk.CTkButton(
            header,
            text="⚙",
            width=38,
            height=38,
            corner_radius=8,
            font=(self.fonts.sans, 17),
            fg_color="transparent",
            hover_color=theme.SUBTLE_HOVER,
            text_color=theme.MUTED,
            command=self.toggle_settings,
        )
        self.settings_button.grid(row=0, column=2, padx=(0, 22))

        _hairline(self).grid(row=1, column=0, sticky="ew")

    def _load_logo(self):
        try:
            from PIL import Image

            image = Image.open(CITY_FRESH_LOGO_PATH)
            height = 32
            width = round(image.width * height / image.height)
            return ctk.CTkImage(light_image=image, dark_image=image, size=(width, height))
        except Exception:
            return None

    # ---------- body ----------

    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self._build_catalog(body)
        _hairline(body, "vertical").grid(row=0, column=1, sticky="ns")
        self._build_cart_panel(body)

    def _build_catalog(self, master):
        catalog_frame = ctk.CTkFrame(master, fg_color="transparent", corner_radius=0)
        catalog_frame.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)

        rows = -(-len(CATALOG) // GRID_COLUMNS)
        for column in range(GRID_COLUMNS):
            catalog_frame.grid_columnconfigure(column, weight=1, uniform="tile")
        for row in range(rows):
            catalog_frame.grid_rowconfigure(row, weight=1, uniform="tile")

        for index, product in enumerate(CATALOG):
            fill, hover, _ = theme.CATEGORY_TINTS.get(
                product.category, (theme.SURFACE, theme.SUBTLE_HOVER, theme.MUTED)
            )
            button = ctk.CTkButton(
                catalog_frame,
                text=_tile_text(product),
                font=self.fonts.tile(),
                fg_color=fill,
                hover_color=hover,
                text_color=theme.TEXT,
                corner_radius=12,
                border_width=0,
                command=lambda p=product: self._add_to_cart(p),
            )
            button.grid(
                row=index // GRID_COLUMNS,
                column=index % GRID_COLUMNS,
                sticky="nsew",
                padx=7,
                pady=7,
            )
            self.product_buttons[product.name] = button

    # ---------- cart rail ----------

    def _build_cart_panel(self, master):
        self.cart_frame = ctk.CTkFrame(
            master, fg_color=theme.SURFACE, corner_radius=0, width=RAIL_WIDTH
        )
        self.cart_frame.grid(row=0, column=2, sticky="nsew")
        self.cart_frame.grid_propagate(False)
        self.cart_frame.grid_rowconfigure(1, weight=1)
        self.cart_frame.grid_columnconfigure(0, weight=1)

        basket_header = ctk.CTkFrame(self.cart_frame, fg_color="transparent")
        basket_header.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 12))
        basket_header.grid_columnconfigure(1, weight=1)

        self.basket_title = ctk.CTkLabel(
            basket_header,
            text=theme.tracked("BASKET"),
            font=self.fonts.eyebrow(),
            text_color=theme.MUTED,
        )
        self.basket_title.grid(row=0, column=0, sticky="w")

        self.random_button = ctk.CTkButton(
            basket_header,
            text="🎲 Random",
            width=88,
            height=26,
            corner_radius=6,
            font=self.fonts.meta(),
            fg_color="transparent",
            hover_color=theme.SUBTLE_HOVER,
            text_color=theme.MUTED,
            command=self._add_random_items,
        )
        self.random_button.grid(row=0, column=2, sticky="e", padx=(0, 4))

        self.clear_button = ctk.CTkButton(
            basket_header,
            text="Clear",
            width=54,
            height=26,
            corner_radius=6,
            font=self.fonts.meta(),
            fg_color="transparent",
            hover_color=theme.SUBTLE_HOVER,
            text_color=theme.MUTED,
            command=self._clear_cart,
        )
        self.clear_button.grid(row=0, column=3, sticky="e")

        self.cart_lines_frame = ctk.CTkScrollableFrame(
            self.cart_frame,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_fg_color="transparent",
            scrollbar_button_color=theme.HAIRLINE,
            scrollbar_button_hover_color=theme.MUTED,
        )
        self.cart_lines_frame.grid(row=1, column=0, sticky="nsew", padx=12)
        self.cart_lines_frame.grid_columnconfigure(0, weight=1)

        self._build_totals()
        self._build_print_controls()

    def _build_totals(self):
        totals = ctk.CTkFrame(self.cart_frame, fg_color="transparent")
        totals.grid(row=2, column=0, sticky="ew", padx=22, pady=(8, 0))
        totals.grid_columnconfigure(1, weight=1)

        _hairline(totals, color=theme.DIVIDER).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))

        ctk.CTkLabel(
            totals, text="Subtotal", font=self.fonts.totals_label(), text_color=theme.MUTED
        ).grid(row=1, column=0, sticky="w")
        self.subtotal_label = ctk.CTkLabel(
            totals, text="", font=self.fonts.totals_value(), text_color=theme.MUTED
        )
        self.subtotal_label.grid(row=1, column=1, sticky="e")

        ctk.CTkLabel(
            totals,
            text="VAT @ 15% (incl.)",
            font=self.fonts.totals_label(),
            text_color=theme.MUTED,
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.vat_label = ctk.CTkLabel(
            totals, text="", font=self.fonts.totals_value(), text_color=theme.MUTED
        )
        self.vat_label.grid(row=2, column=1, sticky="e", pady=(4, 0))

        _hairline(totals, color=theme.DIVIDER).grid(row=3, column=0, columnspan=2, sticky="ew", pady=14)

        ctk.CTkLabel(
            totals, text="TOTAL", font=self.fonts.total_label(), text_color=theme.TEXT
        ).grid(row=4, column=0, sticky="w")
        self.total_label = ctk.CTkLabel(
            totals, text="", font=self.fonts.total_value(), text_color=theme.TEXT
        )
        self.total_label.grid(row=4, column=1, sticky="e")

    def _build_print_controls(self):
        actions = ctk.CTkFrame(self.cart_frame, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", padx=22, pady=(18, 22))
        actions.grid_columnconfigure(0, weight=1)

        self.print_button = ctk.CTkButton(
            actions,
            text="Print",
            height=54,
            corner_radius=10,
            font=self.fonts.cta(),
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color=theme.ACCENT_TEXT,
            command=self._on_print,
        )
        self.print_button.grid(row=0, column=0, sticky="ew")

        # Transport errors are long and not ours to shorten, so the toast must wrap.
        # Without a wraplength the label centres and clips the message at both ends.
        self.feedback_label = ctk.CTkLabel(
            actions,
            text="",
            font=self.fonts.toast(),
            text_color=theme.MUTED,
            wraplength=RAIL_WIDTH - 52,
            justify="center",
        )
        self.feedback_label.grid(row=1, column=0, sticky="ew", pady=(10, 0))

    # ---------- settings drawer ----------

    def _combo_style(self) -> dict:
        return dict(
            fg_color=theme.PAGE,
            border_color=theme.HAIRLINE,
            border_width=1,
            button_color=theme.HAIRLINE,
            button_hover_color=theme.SUBTLE_HOVER,
            text_color=theme.TEXT,
            dropdown_fg_color=theme.SURFACE,
            dropdown_hover_color=theme.PAGE,
            dropdown_text_color=theme.TEXT,
        )

    def _build_settings_panel(self):
        self.settings_panel = ctk.CTkFrame(
            self, fg_color=theme.SURFACE, corner_radius=0, width=RAIL_WIDTH
        )
        self.settings_panel.grid_propagate(False)
        self.settings_panel.grid_columnconfigure(0, weight=1)

        _hairline(self.settings_panel, "vertical").place(x=0, rely=0, relheight=1.0)

        title_row = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        title_row.grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 6))
        title_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            title_row, text="Settings", font=self.fonts.brand(), text_color=theme.TEXT
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            title_row,
            text="×",
            width=32,
            height=32,
            corner_radius=6,
            font=(self.fonts.sans, 18),
            fg_color="transparent",
            hover_color=theme.SUBTLE_HOVER,
            text_color=theme.MUTED,
            command=self.close_settings,
        ).grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            self.settings_panel,
            text=theme.tracked("CONNECTION"),
            font=self.fonts.eyebrow(),
            text_color=theme.MUTED,
        ).grid(row=1, column=0, sticky="w", padx=22, pady=(14, 8))

        self.transport_toggle = ctk.CTkSegmentedButton(
            self.settings_panel,
            values=["Serial", "USB"],
            command=self._on_transport_changed,
            font=self.fonts.settings_label(),
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.PAGE,
            unselected_hover_color=theme.SUBTLE_HOVER,
            text_color=theme.TEXT,
            fg_color=theme.PAGE,
        )
        self.transport_toggle.set("Serial")
        self.transport_toggle.grid(row=2, column=0, sticky="ew", padx=22)

        self.serial_controls_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        self.serial_controls_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.serial_controls_frame,
            text="Port",
            font=self.fonts.settings_label(),
            text_color=theme.MUTED,
        ).grid(row=0, column=0, sticky="w", pady=(14, 4))
        self.port_combo = ctk.CTkComboBox(
            self.serial_controls_frame,
            values=[],
            font=self.fonts.settings_label(),
            height=34,
            **self._combo_style(),
        )
        self.port_combo.set(serial_driver.SERIAL_PORT)
        self.port_combo.grid(row=1, column=0, sticky="ew")

        ctk.CTkLabel(
            self.serial_controls_frame,
            text="Baud",
            font=self.fonts.settings_label(),
            text_color=theme.MUTED,
        ).grid(row=2, column=0, sticky="w", pady=(12, 4))
        self.baud_combo = ctk.CTkComboBox(
            self.serial_controls_frame,
            values=BAUD_RATES,
            font=self.fonts.settings_label(),
            height=34,
            **self._combo_style(),
        )
        self.baud_combo.set(str(serial_driver.BAUD_RATE))
        self.baud_combo.grid(row=3, column=0, sticky="ew")

        self.scan_ports_button = ctk.CTkButton(
            self.serial_controls_frame,
            text="Scan ports",
            height=34,
            corner_radius=8,
            font=self.fonts.settings_label(),
            fg_color=theme.PAGE,
            hover_color=theme.SUBTLE_HOVER,
            text_color=theme.TEXT,
            border_width=1,
            border_color=theme.HAIRLINE,
            command=self._scan_ports,
        )
        self.scan_ports_button.grid(row=4, column=0, sticky="ew", pady=(12, 0))

        self.usb_controls_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        self.usb_controls_frame.grid_columnconfigure(0, weight=1)
        self.usb_status_label = ctk.CTkLabel(
            self.usb_controls_frame,
            text="",
            font=self.fonts.settings_label(),
            text_color=theme.MUTED,
        )
        self.usb_status_label.grid(row=0, column=0, sticky="w", pady=14)

        ctk.CTkLabel(
            self.settings_panel,
            text=theme.tracked("SLIP"),
            font=self.fonts.eyebrow(),
            text_color=theme.MUTED,
        ).grid(row=4, column=0, sticky="w", padx=22, pady=(18, 8))

        self.include_logo_checkbox = ctk.CTkCheckBox(
            self.settings_panel,
            text="Include logo",
            font=self.fonts.settings_label(),
            text_color=theme.TEXT,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.HAIRLINE,
            border_width=2,
            checkbox_width=20,
            checkbox_height=20,
        )
        self.include_logo_checkbox.select()
        self.include_logo_checkbox.grid(row=5, column=0, sticky="w", padx=22, pady=4)

        self.include_barcode_checkbox = ctk.CTkCheckBox(
            self.settings_panel,
            text="Include barcode",
            font=self.fonts.settings_label(),
            text_color=theme.TEXT,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            border_color=theme.HAIRLINE,
            border_width=2,
            checkbox_width=20,
            checkbox_height=20,
        )
        self.include_barcode_checkbox.select()
        self.include_barcode_checkbox.grid(row=6, column=0, sticky="w", padx=22, pady=4)

        self._on_transport_changed("Serial")

    def open_settings(self):
        self.settings_panel.place(relx=1.0, rely=0.0, anchor="ne", relheight=1.0)
        self.settings_panel.lift()
        self._settings_open = True
        self.update_idletasks()

    def close_settings(self):
        self.settings_panel.place_forget()
        self._settings_open = False
        self.update_idletasks()

    def toggle_settings(self):
        if self._settings_open:
            self.close_settings()
        else:
            self.open_settings()

    def _on_escape(self, event=None):
        if self._settings_open:
            self.close_settings()
        else:
            self.attributes("-fullscreen", False)

    # ---------- cart behaviour ----------

    def _add_to_cart(self, product: Product):
        self.cart.add(product)
        self._refresh_cart_view()

    def _increment(self, name: str):
        self.cart.increment(name)
        self._refresh_cart_view()

    def _decrement(self, name: str):
        self.cart.decrement(name)
        self._refresh_cart_view()

    def _remove(self, name: str):
        self.cart.remove(name)
        self._refresh_cart_view()

    def _clear_cart(self):
        self.cart.clear()
        self._refresh_cart_view()

    def _add_random_items(self):
        # Replaces rather than appends -- repeat clicks give a fresh random basket
        # instead of an ever-growing one, which is what you want mid-demo.
        self.cart.clear()
        sample_size = min(RANDOM_BASKET_SIZE, len(CATALOG))
        for product in random.sample(CATALOG, sample_size):
            self.cart.add(product)
        self._refresh_cart_view()

    def _refresh_cart_view(self):
        for widget in self._cart_rows:
            widget.destroy()
        self._cart_rows = []
        self.cart_line_widgets = {}

        lines = self.cart.lines()

        if not lines:
            empty = ctk.CTkLabel(
                self.cart_lines_frame,
                text="Basket empty\nTap a product to start",
                font=self.fonts.meta(),
                text_color=theme.MUTED,
                justify="center",
            )
            empty.grid(row=0, column=0, sticky="ew", pady=40)
            self._cart_rows.append(empty)

        for index, line in enumerate(lines):
            row = ctk.CTkFrame(self.cart_lines_frame, fg_color="transparent")
            row.grid(row=index, column=0, sticky="ew", pady=(0, 2))
            row.grid_columnconfigure(0, weight=1)
            self._cart_rows.append(row)

            ctk.CTkLabel(
                row,
                text=line.name,
                font=self.fonts.cart_name(),
                text_color=theme.TEXT,
                anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=(10, 0), pady=(8, 0))

            remove_button = ctk.CTkButton(
                row,
                text="×",
                width=26,
                height=26,
                corner_radius=6,
                font=(self.fonts.sans, 15),
                fg_color="transparent",
                hover_color=theme.SUBTLE_HOVER,
                text_color=theme.MUTED,
                command=lambda n=line.name: self._remove(n),
            )
            remove_button.grid(row=0, column=1, sticky="e", padx=(0, 8), pady=(8, 0))

            stepper = ctk.CTkFrame(row, fg_color="transparent")
            stepper.grid(row=1, column=0, sticky="w", padx=(8, 0), pady=(2, 8))

            minus_button = ctk.CTkButton(
                stepper,
                text="−",
                width=30,
                height=30,
                corner_radius=8,
                font=self.fonts.stepper(),
                fg_color=theme.PAGE,
                hover_color=theme.SUBTLE_HOVER,
                text_color=theme.TEXT,
                command=lambda n=line.name: self._decrement(n),
            )
            minus_button.grid(row=0, column=0)

            ctk.CTkLabel(
                stepper,
                text=str(line.qty),
                font=self.fonts.qty(),
                text_color=theme.TEXT,
                width=32,
            ).grid(row=0, column=1)

            plus_button = ctk.CTkButton(
                stepper,
                text="+",
                width=30,
                height=30,
                corner_radius=8,
                font=self.fonts.stepper(),
                fg_color=theme.PAGE,
                hover_color=theme.SUBTLE_HOVER,
                text_color=theme.TEXT,
                command=lambda n=line.name: self._increment(n),
            )
            plus_button.grid(row=0, column=2)

            ctk.CTkLabel(
                row,
                text=f"R {line.price * line.qty:.2f}",
                font=self.fonts.cart_price(),
                text_color=theme.TEXT,
                anchor="e",
            ).grid(row=1, column=1, sticky="e", padx=(0, 10), pady=(2, 8))

            self.cart_line_widgets[line.name] = {
                "minus_button": minus_button,
                "plus_button": plus_button,
                "remove_button": remove_button,
            }

        count = sum(line.qty for line in lines)
        self.basket_title.configure(
            text=theme.tracked("BASKET") + (f"    {count}" if count else "")
        )
        # CTk offers no fg_color_disabled, so a disabled button keeps its accent fill and
        # only dims the label -- which reads as broken rather than unavailable.
        if lines:
            self.print_button.configure(
                state="normal", fg_color=theme.ACCENT, text_color=theme.ACCENT_TEXT
            )
        else:
            self.print_button.configure(
                state="disabled", fg_color=theme.PAGE, text_color=theme.MUTED
            )

        self.subtotal_label.configure(text=f"R {self.cart.subtotal():.2f}")
        self.vat_label.configure(text=f"R {self.cart.vat():.2f}")
        self.total_label.configure(text=f"R {self.cart.total():.2f}")

    # ---------- printing ----------

    def _on_print(self):
        is_serial = self.transport_toggle.get() == "Serial"
        chosen_transport = transport.Transport.SERIAL if is_serial else transport.Transport.USB
        receipt_cls = serial_driver.Receipt if is_serial else usb_driver.Receipt

        data = build_receipt(
            self.cart,
            receipt_cls,
            include_logo=bool(self.include_logo_checkbox.get()),
            include_barcode=bool(self.include_barcode_checkbox.get()),
        )

        try:
            transport.send(
                data, chosen_transport, port=self.port_combo.get(), baud=int(self.baud_combo.get())
            )
        except transport.TransportError as e:
            self.feedback_label.configure(text=f"Print failed: {e}", text_color=theme.DANGER)
            return

        self.feedback_label.configure(text="Print success", text_color=theme.ACCENT)
        self._clear_cart()

    def _on_transport_changed(self, selected: str):
        if selected == "Serial":
            self.usb_controls_frame.grid_forget()
            self.serial_controls_frame.grid(row=3, column=0, sticky="ew", padx=22)
        else:
            self.serial_controls_frame.grid_forget()
            self.usb_controls_frame.grid(row=3, column=0, sticky="ew", padx=22)
            self._refresh_usb_status()

    def _refresh_usb_status(self):
        connected = transport.usb_is_connected()
        self.usb_status_label.configure(
            text="Printer detected" if connected else "Printer not detected",
            text_color=theme.ACCENT if connected else theme.MUTED,
        )

    def _scan_ports(self):
        ports = transport.scan_serial_ports()
        self.port_combo.configure(values=ports)
        if ports:
            self.port_combo.set(ports[0])


if __name__ == "__main__":
    app = PosApp()
    app.mainloop()
