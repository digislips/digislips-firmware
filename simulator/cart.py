from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    name: str
    price: float


@dataclass
class CartLine:
    name: str
    price: float
    qty: int


class Cart:
    def __init__(self):
        self._lines: list[CartLine] = []

    def lines(self) -> list[CartLine]:
        return list(self._lines)

    def add(self, product: Product) -> None:
        existing = self._find(product.name)
        if existing is not None:
            existing.qty += 1
            return
        self._lines.append(CartLine(product.name, product.price, 1))

    def increment(self, name: str) -> None:
        self._find(name).qty += 1

    def decrement(self, name: str) -> None:
        line = self._find(name)
        if line.qty > 1:
            line.qty -= 1

    def set_qty(self, name: str, qty: int) -> None:
        self._find(name).qty = max(1, qty)

    def remove(self, name: str) -> None:
        self._lines = [line for line in self._lines if line.name != name]

    def subtotal(self) -> float:
        return round(self._raw_subtotal(), 2)

    def vat(self) -> float:
        return round(self._raw_subtotal() * 15 / 115, 2)

    def total(self) -> float:
        return self.subtotal()

    def clear(self) -> None:
        self._lines = []

    def _raw_subtotal(self) -> float:
        return sum(line.price * line.qty for line in self._lines)

    def _find(self, name: str) -> CartLine | None:
        for line in self._lines:
            if line.name == name:
                return line
        return None
