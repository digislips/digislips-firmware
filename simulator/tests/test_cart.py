from cart import Cart, Product


def test_add_single_item_creates_one_line_at_qty_1():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))

    lines = cart.lines()

    assert len(lines) == 1
    assert lines[0].name == "Sourdough Bread 800g"
    assert lines[0].price == 62.99
    assert lines[0].qty == 1


def test_adding_same_item_again_increments_qty_not_duplicate_line():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.add(Product("Sourdough Bread 800g", 62.99))

    lines = cart.lines()

    assert len(lines) == 1
    assert lines[0].qty == 2


def test_increment_raises_qty_by_one():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))

    cart.increment("Sourdough Bread 800g")

    assert cart.lines()[0].qty == 2


def test_decrement_lowers_qty_but_floors_at_one():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.add(Product("Sourdough Bread 800g", 62.99))

    cart.decrement("Sourdough Bread 800g")
    assert cart.lines()[0].qty == 1

    cart.decrement("Sourdough Bread 800g")
    assert cart.lines()[0].qty == 1


def test_set_qty_sets_directly():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))

    cart.set_qty("Sourdough Bread 800g", 5)

    assert cart.lines()[0].qty == 5


def test_set_qty_clamps_to_one_not_below():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))

    cart.set_qty("Sourdough Bread 800g", 0)
    assert cart.lines()[0].qty == 1

    cart.set_qty("Sourdough Bread 800g", -3)
    assert cart.lines()[0].qty == 1


def test_remove_deletes_line_regardless_of_qty():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.set_qty("Sourdough Bread 800g", 5)

    cart.remove("Sourdough Bread 800g")

    assert cart.lines() == []


def test_clear_empties_the_cart():
    cart = Cart()
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.add(Product("Organic Eggs 12pk", 44.99))

    cart.clear()

    assert cart.lines() == []


def test_subtotal_sums_price_times_qty_across_multiple_lines():
    cart = Cart()
    cart.add(Product("Organic Eggs 12pk", 44.99))
    cart.increment("Organic Eggs 12pk")
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.add(Product("Almond Butter 400g", 99.99))
    cart.add(Product("Sparkling Water 750ml", 14.99))
    cart.set_qty("Sparkling Water 750ml", 3)

    assert cart.subtotal() == 297.93


def test_vat_extracts_15_percent_inclusive_matching_slip_7():
    cart = Cart()
    cart.add(Product("Organic Eggs 12pk", 44.99))
    cart.increment("Organic Eggs 12pk")
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.add(Product("Almond Butter 400g", 99.99))
    cart.add(Product("Sparkling Water 750ml", 14.99))
    cart.set_qty("Sparkling Water 750ml", 3)

    assert cart.vat() == 38.86


def test_total_matches_subtotal_vat_inclusive_style():
    cart = Cart()
    cart.add(Product("Organic Eggs 12pk", 44.99))
    cart.increment("Organic Eggs 12pk")
    cart.add(Product("Sourdough Bread 800g", 62.99))
    cart.add(Product("Almond Butter 400g", 99.99))
    cart.add(Product("Sparkling Water 750ml", 14.99))
    cart.set_qty("Sparkling Water 750ml", 3)

    assert cart.total() == 297.93
    assert cart.total() == cart.subtotal()
