"""Order lifecycle, cancellation and shipment handling."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..models import (
    Inventory,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_SHIPPED,
    Order,
    Payment,
    Shipment,
)


class OrderError(Exception):
    def __init__(self, message: str, code: str = 'order_error'):
        super().__init__(message)
        self.message = message
        self.code = code


def _restore_stock(order: Order) -> None:
    """Return reserved units to inventory exactly once.

    Called only while the order row is locked and only for orders that were not
    already cancelled, so stock cannot be double-restored.
    """
    for item in order.items.all():
        if item.product_id:
            Inventory.objects.filter(product_id=item.product_id).update(
                stock_quantity=F('stock_quantity') + item.quantity
            )


def cancel_order(order: Order, *, by=None, reason: str = 'Cancelled by customer') -> Order:
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status not in (ORDER_STATUS_PENDING, ORDER_STATUS_PAID):
            raise OrderError(
                f'An order that is {order.get_status_display().lower()} can no longer be cancelled.',
                'invalid_transition',
            )
        payment = getattr(order, 'payment', None)
        if payment is not None:
            if payment.status == 'PAID':
                payment.status = 'REFUNDED'
                payment.failure_reason = 'Order cancelled; mock refund issued.'
            elif payment.status in ('PENDING', 'FAILED'):
                payment.status = 'CANCELLED'
            payment.save(update_fields=['status', 'failure_reason', 'updated_at'])
        _restore_stock(order)
        shipment = getattr(order, 'shipment', None)
        if shipment is not None:
            shipment.status = Shipment.Status.FAILED
            shipment.notes = (shipment.notes + '\nOrder cancelled.').strip()
            shipment.save(update_fields=['status', 'notes', 'updated_at'])
        order.cancellation_reason = reason[:255]
        order.save(update_fields=['cancellation_reason', 'updated_at'])
        order.transition_to(ORDER_STATUS_CANCELLED, changed_by=by, note=reason)
    return order


def transition_order(
    order: Order,
    new_status: str,
    *,
    by=None,
    note: str = '',
    courier: str = '',
    tracking_number: str = '',
) -> Order:
    """Move an order through its controlled lifecycle.

    Only ``SHIPPED`` and ``DELIVERED`` are started here.  ``PAID`` is set by the
    payment service and ``CANCELLED`` by :func:`cancel_order`, both of which
    have side effects (payment records, stock restoration).
    """
    if new_status == ORDER_STATUS_CANCELLED:
        return cancel_order(order, by=by, reason=note or 'Cancelled by administrator')

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if new_status not in order.allowed_next_statuses():
            raise OrderError(
                f'Cannot move an order from {order.get_status_display()} to {new_status.title()}.',
                'invalid_transition',
            )

        if new_status == ORDER_STATUS_SHIPPED:
            payment = getattr(order, 'payment', None)
            if payment is None or payment.status != 'PAID':
                raise OrderError('Only paid orders can be shipped.', 'unpaid_order')
            shipment, _ = Shipment.objects.get_or_create(order=order)
            shipment.courier = courier or shipment.courier or 'Rukomeza Express'
            shipment.tracking_number = tracking_number or shipment.tracking_number or (
                'RMX-' + order.reference.replace('RM-', '')
            )
            shipment.status = Shipment.Status.DISPATCHED
            shipment.shipped_at = shipment.shipped_at or timezone.now()
            shipment.save()

        if new_status == ORDER_STATUS_DELIVERED:
            if order.status != ORDER_STATUS_SHIPPED:
                raise OrderError('Only shipped orders can be marked delivered.', 'invalid_transition')
            shipment, _ = Shipment.objects.get_or_create(order=order)
            shipment.status = Shipment.Status.DELIVERED
            shipment.delivered_at = timezone.now()
            shipment.save()

        order.transition_to(new_status, changed_by=by, note=note)
    return order


def mark_paid(order: Order, *, by=None) -> Order:
    """Used by the payment service after a successful gateway callback."""
    if order.status != ORDER_STATUS_PENDING:
        raise OrderError('This order is no longer awaiting payment.', 'invalid_transition')
    try:
        return order.transition_to(ORDER_STATUS_PAID, changed_by=by, note='Payment confirmed (mock gateway).')
    except ValidationError as exc:
        raise OrderError('Payment could not be applied to this order.', 'invalid_transition') from exc
