import sys

import customtkinter as ctk

import Serial_RS232_Driver_v2 as serial_driver
import USB_Only_Driver as usb_driver
import transport
from cart import Cart, Product
from receipt_builder import build_receipt

if sys.platform.startswith("win"):
    # customtkinter also requests per-monitor DPI awareness, but only once its
    # own Tk root already exists -- by then Windows has already handed the
    # process a DPI-scaled logical screen size, so "-fullscreen" undershoots
    # the real screen. Requesting it here, before any Tk window exists, makes
    # winfo_screenwidth/height report true pixels.
    import ctypes

    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE

BAUD_RATES: list[str] = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]

CATALOG: list[Product] = [
    Product("Avocado Ready-to-Eat", 12.99),
    Product("Punnet Strawberries 250g", 34.99),
    Product("Baby Spinach 200g", 24.99),
    Product("Sourdough Bread 800g", 62.99),
    Product("Croissants 6pk", 45.99),
    Product("Organic Eggs 12pk", 44.99),
    Product("Full Cream Milk 2L", 32.99),
    Product("Cheddar Cheese Block 400g", 79.99),
    Product("Sparkling Water 750ml", 14.99),
    Product("Orange Juice 1L", 29.99),
    Product("Cold Brew Coffee 330ml", 27.99),
    Product("Almond Butter 400g", 99.99),
    Product("Mixed Nuts 200g", 54.99),
    Product("Dark Chocolate 100g", 39.99),
]


class PosApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("DigiSlip POS Simulator")
        self.attributes("-fullscreen", True)
        self.bind("<Escape>", lambda event: self.attributes("-fullscreen", False))
        self.cart = Cart()
        self.product_buttons: dict[str, ctk.CTkButton] = {}
        self.cart_line_widgets: dict[str, dict] = {}

        self._build_catalog()
        self._build_cart_panel()
        self._build_print_controls()

    def _build_catalog(self):
        catalog_frame = ctk.CTkFrame(self)
        catalog_frame.pack(side="left", fill="both", expand=True)

        for product in CATALOG:
            button = ctk.CTkButton(
                catalog_frame,
                text=f"{product.name}\nR {product.price:.2f}",
                command=lambda p=product: self._add_to_cart(p),
            )
            button.pack(fill="x", padx=4, pady=2)
            self.product_buttons[product.name] = button

    def _build_cart_panel(self):
        self.cart_frame = ctk.CTkFrame(self)
        self.cart_frame.pack(side="right", fill="both", expand=True)

        self.cart_lines_frame = ctk.CTkFrame(self.cart_frame)
        self.cart_lines_frame.pack(fill="both", expand=True)

        self.clear_button = ctk.CTkButton(self.cart_frame, text="Clear cart", command=self._clear_cart)
        self.clear_button.pack(fill="x")

        self.subtotal_label = ctk.CTkLabel(self.cart_frame, text="")
        self.subtotal_label.pack(fill="x")
        self.vat_label = ctk.CTkLabel(self.cart_frame, text="")
        self.vat_label.pack(fill="x")
        self.total_label = ctk.CTkLabel(self.cart_frame, text="")
        self.total_label.pack(fill="x")

        self._refresh_cart_view()

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

    def _refresh_cart_view(self):
        for widget in self.cart_lines_frame.winfo_children():
            widget.destroy()
        self.cart_line_widgets = {}

        for line in self.cart.lines():
            row = ctk.CTkFrame(self.cart_lines_frame)
            row.pack(fill="x")

            ctk.CTkLabel(row, text=f"{line.qty}x  {line.name}").pack(side="left")

            minus_button = ctk.CTkButton(
                row, text="-", width=28, command=lambda n=line.name: self._decrement(n)
            )
            minus_button.pack(side="left")

            plus_button = ctk.CTkButton(
                row, text="+", width=28, command=lambda n=line.name: self._increment(n)
            )
            plus_button.pack(side="left")

            ctk.CTkLabel(row, text=f"R {line.price * line.qty:.2f}").pack(side="left")

            remove_button = ctk.CTkButton(
                row, text="x", width=28, command=lambda n=line.name: self._remove(n)
            )
            remove_button.pack(side="left")

            self.cart_line_widgets[line.name] = {
                "minus_button": minus_button,
                "plus_button": plus_button,
                "remove_button": remove_button,
            }

        self.subtotal_label.configure(text=f"Subtotal: R {self.cart.subtotal():.2f}")
        self.vat_label.configure(text=f"VAT @ 15% (incl.): R {self.cart.vat():.2f}")
        self.total_label.configure(text=f"TOTAL: R {self.cart.total():.2f}")

    def _build_print_controls(self):
        self.print_frame = ctk.CTkFrame(self.cart_frame)
        self.print_frame.pack(fill="x")

        self.include_logo_checkbox = ctk.CTkCheckBox(self.print_frame, text="Include logo")
        self.include_logo_checkbox.select()
        self.include_logo_checkbox.pack(fill="x")

        self.include_barcode_checkbox = ctk.CTkCheckBox(self.print_frame, text="Include barcode")
        self.include_barcode_checkbox.select()
        self.include_barcode_checkbox.pack(fill="x")

        self.transport_toggle = ctk.CTkSegmentedButton(
            self.print_frame, values=["Serial", "USB"], command=self._on_transport_changed
        )
        self.transport_toggle.set("Serial")
        self.transport_toggle.pack(fill="x")

        self.serial_controls_frame = ctk.CTkFrame(self.print_frame)

        self.port_combo = ctk.CTkComboBox(self.serial_controls_frame, values=[])
        self.port_combo.set(serial_driver.SERIAL_PORT)
        self.port_combo.pack(fill="x")

        self.baud_combo = ctk.CTkComboBox(self.serial_controls_frame, values=BAUD_RATES)
        self.baud_combo.set(str(serial_driver.BAUD_RATE))
        self.baud_combo.pack(fill="x")

        self.scan_ports_button = ctk.CTkButton(
            self.serial_controls_frame, text="Scan ports", command=self._scan_ports
        )
        self.scan_ports_button.pack(fill="x")

        self.usb_controls_frame = ctk.CTkFrame(self.print_frame)
        self.usb_status_label = ctk.CTkLabel(self.usb_controls_frame, text="")
        self.usb_status_label.pack(fill="x")

        self._on_transport_changed("Serial")

        self.print_button = ctk.CTkButton(self.print_frame, text="Print", command=self._on_print)
        self.print_button.pack(fill="x")

        self.feedback_label = ctk.CTkLabel(self.print_frame, text="")
        self.feedback_label.pack(fill="x")

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
            transport.send(data, chosen_transport, port=self.port_combo.get(), baud=int(self.baud_combo.get()))
        except transport.TransportError as e:
            self.feedback_label.configure(text=f"Print failed: {e}")
            return

        self.feedback_label.configure(text="Print success")
        self._clear_cart()

    def _on_transport_changed(self, selected: str):
        if selected == "Serial":
            self.usb_controls_frame.pack_forget()
            self.serial_controls_frame.pack(fill="x")
        else:
            self.serial_controls_frame.pack_forget()
            self.usb_controls_frame.pack(fill="x")
            self._refresh_usb_status()

    def _refresh_usb_status(self):
        connected = transport.usb_is_connected()
        text = "Printer detected" if connected else "Printer not detected"
        self.usb_status_label.configure(text=text)

    def _scan_ports(self):
        ports = transport.scan_serial_ports()
        self.port_combo.configure(values=ports)
        if ports:
            self.port_combo.set(ports[0])


if __name__ == "__main__":
    app = PosApp()
    app.mainloop()
