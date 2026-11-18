"""Concurrency-safe checkout.

Guarantees
----------
1. Stock is checked and decremented **inside one database transaction**.
2. The inventory row is locked with ``SELECT ... FOR UPDATE`` on databases that
   support it (PostgreSQL, MySQL), and *always* the decrement is a single
   conditional ``UPDATE ... WHERE stock_quantity >= qty``.  The conditional
   update is what makes overselling impossible even on SQLite, where
   ``select_for_update`` is a no-op: if two requests race, exactly one update
   matches a row, the loser sees ``updated == 0`` and the whole order rolls
   back.
3. Totals are recalculated from the database.  Client-supplied prices are
   ignored; an optional ``expected_total`` lets the API detect a stale price and
   return a 409 instead of silently charging a different amount.
4. ``OrderItem`` rows store a snapshot of the product name, SKU, seller and
   unit price, so future catalogue edits never alter historical orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import time
import uuid

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.db.models import F
from django.utils import timezone

from ..models import (
    Cart,
    Inventory,
    Order,
    OrderItem,
    OrderStatusEvent,
    Payment,
    Product,
)


class CheckoutError(Exception):
    def __init__(self, message: str, code: str = 'checkout_error', details=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


@dataclass
class CheckoutResult:
    order: Order
    payment: Payment


def _new_transaction_ref() -> str:
    return 'PAY-' + uuid.uuid4().hex[:16].upper()


def _shipping_fee() -> Decimal:
    return Decimal(str(getattr(settings, 'SHIPPING_FEE', '0')))


def create_order(**kwargs) -> CheckoutResult:
    """Create an order, retrying only on SQLite write-lock contention.

    SQLite serialises writers and (unlike PostgreSQL) cannot block on row locks,
    so a burst of concurrent checkouts can surface ``database is locked``.
    Retrying the whole atomic block is safe because a failed attempt rolls back
    completely.  PostgreSQL/MySQL use row locks and take the fast path.
    """
    last_error: OperationalError | None = None
    for attempt in range(6):
        try:
            return _create_order_once(**kwargs)
        except OperationalError as exc:
            last_error = exc
            if connection.vendor != 'sqlite' or attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))
    raise last_error  # pragma: no cover - defensive


def _create_order_once(
    *,
    user,
    cart: Cart,
    full_name: str,
    phone: str,
    address: str,
    city: str,
    gateway: str = 'MOCK',
    expected_total: Decimal | str | None = None,
) -> CheckoutResult:
    """Turn a cart into a PENDING order and decrement stock atomically."""
    items = list(
        cart.items.select_related('product', 'product__seller', 'product__inventory').order_by('product_id')
    )
    if not items:
        raise CheckoutError('Your cart is empty.', 'empty_cart')

    if not all(str(value).strip() for value in (full_name, phone, address, city)):
        raise CheckoutError('Delivery name, phone, address and city are required.', 'invalid_shipping')

    product_ids = sorted(item.product_id for item in items)

    try:
        with transaction.atomic():
            # Lock inventory rows.  ``order_by`` gives a deterministic lock
            # order, preventing deadlocks between concurrent checkouts.
            locked = list(
                Inventory.objects.select_for_update()
                .filter(product_id__in=product_ids)
                .order_by('product_id')
            )
            inventories = {row.product_id: row for row in locked}
            if len(inventories) != len(product_ids):
                raise CheckoutError(
                    'One or more products are no longer available.',
                    'product_unavailable',
                )

            products = {
                product.pk: product
                for product in Product.objects.select_related('seller', 'category')
                .filter(pk__in=product_ids, is_active=True, seller__is_approved=True, seller__is_suspended=False)
            }
            if len(products) != len(product_ids):
                raise CheckoutError(
                    'One or more products are no longer for sale.',
                    'product_unavailable',
                )

            subtotal = Decimal('0.00')
            for item in items:
                product = products[item.product_id]
                inventory = inventories[item.product_id]
                if item.quantity < 1:
                    raise CheckoutError('Invalid quantity in cart.', 'invalid_quantity')
                if item.quantity > getattr(settings, 'MAX_ORDER_LINE_QUANTITY', 99):
                    raise CheckoutError(
                        f'At most {getattr(settings, "MAX_ORDER_LINE_QUANTITY", 99)} units per item can be ordered.',
                        'quantity_limit',
                    )
                if inventory.stock_quantity < item.quantity:
                    raise CheckoutError(
                        f'Only {inventory.stock_quantity} unit(s) of {product.name} remain in stock.',
                        'insufficient_stock',
                        {'product_id': product.pk, 'available': inventory.stock_quantity},
                    )
                subtotal += product.price * item.quantity

            shipping_fee = _shipping_fee()
            total = subtotal + shipping_fee

            if expected_total is not None:
                try:
                    expected = Decimal(str(expected_total)).quantize(Decimal('0.01'))
                except Exception as exc:  # noqa: BLE001 - surfaced as a validation error
                    raise CheckoutError('Invalid expected total.', 'invalid_total') from exc
                if expected != total:
                    raise CheckoutError(
                        'Prices changed while you were checking out. Please review your cart.',
                        'price_changed',
                        {'server_total': str(total), 'expected_total': str(expected)},
                    )

            order = Order.objects.create(
                customer=user,
                status='PENDING',
                subtotal=subtotal,
                shipping_fee=shipping_fee,
                total_amount=total,
                shipping_full_name=full_name.strip(),
                shipping_phone=phone.strip(),
                shipping_address=address.strip(),
                shipping_city=city.strip(),
            )

            for item in items:
                product = products[item.product_id]
                # The atomic guard: the WHERE clause is evaluated by the
                # database at write time, not from the earlier read.
                updated = Inventory.objects.filter(
                    product_id=item.product_id,
                    stock_quantity__gte=item.quantity,
                ).update(stock_quantity=F('stock_quantity') - item.quantity)
                if updated != 1:
                    raise CheckoutError(
                        f'Stock for {product.name} changed during checkout. Please try again.',
                        'stock_conflict',
                        {'product_id': product.pk},
                    )

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    seller=product.seller,
                    product_name_snapshot=product.name,
                    sku_snapshot=product.sku,
                    seller_name_snapshot=product.seller.store_name,
                    quantity=item.quantity,
                    unit_price_snapshot=product.price,
                )

            payment = Payment.objects.create(
                order=order,
                gateway=gateway,
                transaction_ref=_new_transaction_ref(),
                amount=total,
                status='PENDING',
            )

            OrderStatusEvent.objects.create(
                order=order,
                from_status='',
                to_status='PENDING',
                note='Order placed by customer.',
                changed_by=user,
            )

            cart.items.all().delete()
    except CheckoutError:
        raise

    return CheckoutResult(order=order, payment=payment)


def cart_has_stock_conflict(cart: Cart) -> bool:
    """Return True when any cart line exceeds current stock (for UI hints)."""
    items = cart.items.select_related('product', 'product__inventory')
    for item in items:
        product = item.product
        if not product.is_active or not product.seller.is_open_for_business:
            return True
        inventory = getattr(product, 'inventory', None)
        if inventory is None or item.quantity > inventory.stock_quantity:
            return True
    return False
