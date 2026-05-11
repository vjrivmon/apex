import sqlite3
from unittest.mock import MagicMock, patch

from shop.cart import Cart
from shop.cart import _apply_line_discount, _recalc_totals  # private helpers


def test_add_item_calls_recalc_totals():
    cart = Cart()
    with patch("shop.cart._recalc_totals") as recalc:
        cart.add_item("sku-1", qty=2, unit_price=500)
        recalc.assert_called_once()


def test_apply_line_discount_private_helper():
    # exercise the private helper directly
    line = {"sku": "sku-1", "qty": 2, "unit_price": 500}
    out = _apply_line_discount(line, percent=10)
    assert out["unit_price"] == 450


def test_checkout_writes_expected_row_shape_in_db():
    cart = Cart()
    cart.add_item("sku-1", qty=1, unit_price=999)
    cart.checkout(order_id="o-1")
    conn = sqlite3.connect("shop.db")
    row = conn.execute("SELECT order_id, total, status FROM orders WHERE order_id='o-1'").fetchone()
    assert row == ("o-1", 999, "pending")


def test_internal_items_list_structure():
    cart = Cart()
    cart.add_item("sku-1", qty=3, unit_price=100)
    # asserts on the internal attribute, not on observable behaviour
    assert cart._items == [{"sku": "sku-1", "qty": 3, "unit_price": 100, "_dirty": True}]


def test_recalc_totals_helper_directly():
    items = [{"sku": "a", "qty": 2, "unit_price": 250}, {"sku": "b", "qty": 1, "unit_price": 100}]
    assert _recalc_totals(items) == 600
