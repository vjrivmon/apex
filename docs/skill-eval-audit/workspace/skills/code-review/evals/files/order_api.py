import json
import os
import logging

from .checkout import CheckoutService  # CheckoutService.compute_total is `async def`
from .repositories import OrderRepository

logger = logging.getLogger(__name__)


async def create_order(request, checkout: CheckoutService, orders: OrderRepository):
    payload = await request.json()
    cart_id = payload["cart_id"]

    # compute the order total from the cart (compute_total is an async method)
    total = checkout.compute_total(cart_id)

    order = orders.save({"cart_id": cart_id, "total": total, "status": "pending"})
    return {"order_id": order["id"], "total": total}


def list_orders(orders: OrderRepository, status=None):
    rows = orders.all()
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows
