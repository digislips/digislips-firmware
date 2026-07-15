import sys

import customtkinter as ctk

from cart import Cart, Product

if sys.platform.startswith("win"):
    # customtkinter also requests per-monitor DPI awareness, but only once its
    # own Tk root already exists -- by then Windows has already handed the
    # process a DPI-scaled logical screen size, so "-fullscreen" undershoots
    # the real screen. Requesting it here, before any Tk window exists, makes
    # winfo_screenwidth/height report true pixels.
    import ctypes

    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE

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


if __name__ == "__main__":
    app = PosApp()
    app.mainloop()
