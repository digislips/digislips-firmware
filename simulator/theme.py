"""City Fresh till styling: palette, category tints, and font resolution.

The till is deliberately *not* DigiSlips-branded. DigiSlips sells itself on
working with any POS, so the demo reads better when the till on screen is
plainly a retailer's own and DigiSlips is invisible at the counter.
"""

import os
from tkinter import font as tkfont

from customtkinter import FontManager

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")

PAGE = "#F7F7F5"
SURFACE = "#FFFFFF"
TEXT = "#111111"
MUTED = "#6B6B6B"
HAIRLINE = "#E4E4E1"
# HAIRLINE is tuned as a border against PAGE; on a white rail it disappears, so
# structural rules use a darker tone.
DIVIDER = "#DCDCD6"
ACCENT = "#157F4B"
ACCENT_HOVER = "#10643B"
ACCENT_TEXT = "#FFFFFF"
DANGER = "#B3261E"
SUBTLE_HOVER = "#F0F0EE"

# category -> (tile fill, tile hover, label)
CATEGORY_TINTS: dict[str, tuple[str, str, str]] = {
    "Produce": ("#E9F4EC", "#DCEDE2", "#3D7F55"),
    "Bakery": ("#FBF1E3", "#F5E6CF", "#9A6B2C"),
    "Dairy": ("#EAF1FA", "#DBE7F5", "#456F9E"),
    "Drinks": ("#E7F3F4", "#D8EAEC", "#3B7C84"),
    "Snacks": ("#F3EDF6", "#E9DFEF", "#6F5388"),
}

CATEGORY_ORDER = ["Produce", "Bakery", "Dairy", "Drinks", "Snacks"]


def load_font_files() -> None:
    """Privately register the bundled TTFs with the OS. Safe to call before Tk exists."""
    for name in (
        "Inter-Regular.ttf",
        "Inter-Medium.ttf",
        "Inter-SemiBold.ttf",
        "JetBrainsMono-Regular.ttf",
        "JetBrainsMono-Bold.ttf",
    ):
        path = os.path.join(FONT_DIR, name)
        if os.path.exists(path):
            FontManager.load_font(path)


def _resolves(family: str) -> bool:
    # Tk silently substitutes a missing family (Arial, on Windows) rather than
    # raising, so asking what it actually resolved to is the only honest check.
    return tkfont.Font(family=family, size=12).actual("family").lower() == family.lower()


def _first_resolving(*candidates: str) -> str:
    for candidate in candidates:
        if _resolves(candidate):
            return candidate
    return candidates[-1]


class Fonts:
    """Resolved family names plus the type scale. Construct only after a Tk root exists."""

    def __init__(self):
        self.sans = _first_resolving("Inter", "Segoe UI", "Arial")
        self.sans_medium = _first_resolving("Inter Medium", "Segoe UI Semibold", self.sans)
        self.sans_semibold = _first_resolving("Inter SemiBold", "Segoe UI Semibold", self.sans)
        self.mono = _first_resolving("JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New")

    @property
    def using_bundled(self) -> bool:
        return self.sans == "Inter" and self.mono == "JetBrains Mono"

    def brand(self):
        return (self.sans_semibold, 19)

    def meta(self):
        return (self.sans, 12)

    def eyebrow(self):
        return (self.sans_semibold, 11)

    def tile(self):
        return (self.sans_medium, 14)

    def cart_name(self):
        return (self.sans_medium, 13)

    def cart_price(self):
        return (self.mono, 13)

    def qty(self):
        return (self.mono, 13)

    def stepper(self):
        return (self.sans_medium, 15)

    def totals_label(self):
        return (self.sans, 12)

    def totals_value(self):
        return (self.mono, 12)

    def total_label(self):
        return (self.sans_semibold, 16)

    def total_value(self):
        return (self.mono, 24, "bold")

    def cta(self):
        return (self.sans_semibold, 16)

    def toast(self):
        return (self.sans_medium, 12)

    def settings_label(self):
        return (self.sans_medium, 12)


def tracked(text: str) -> str:
    """Fake letter-spacing for small uppercase labels. Tk exposes no tracking control."""
    return " ".join(text)
