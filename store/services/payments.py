"""Payment simulation and idempotent status recording.

There is no real money movement: the project uses a documented mock gateway
(see ``docs/PAYMENTS.md``).  The same structure maps 1:1 onto a Stripe
PaymentIntent / Paystack / Flutterwave charge: create a reference, record a
PENDING payment, then apply a verified callback.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from ..models import Order, Payment


class PaymentError(Exception):
    def __init__(self, message: str, code: str = 'payment_error'):
        super().__init__(message)
        self.message = message
        self.code = code


def process_mock_payment(order: Order, *, outcome: str = 'success', by=None) -> Payment:
    """Simulate the gateway callback for an order.

    ``outcome`` is ``success`` or ``failure``.  The operation is idempotent:
    replaying a success for an already-paid order returns the paid record and
    does not create a second payment or advance the status twice.
    """
    if outcome not in ('success', 'failure'):
        raise PaymentError('Outcome must be "success" or "failure".', 'invalid_outcome')

    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(order=order)
        except Payment.DoesNotExist as exc:
            raise PaymentError('No payment record exists for this order.', 'not_found') from exc
        order = Order.objects.select_for_update().get(pk=order.pk)

        if payment.status == 'PAID':
            return payment
        if order.status != 'PENDING':
            raise PaymentError(
                f'The order is {order.get_status_display().lower()} and cannot be paid.',
                'invalid_transition',
            )

        payment.attempts += 1
        if outcome == 'success':
            payment.status = 'PAID'
            payment.paid_at = timezone.now()
            payment.provider_reference = f'MOCK-{payment.transaction_ref}'
            payment.failure_reason = ''
            payment.raw_response = {
                'gateway': 'MOCK',
                'event': 'charge.success',
                'reference': payment.transaction_ref,
                'amount': str(payment.amount),
                'currency': payment.currency,
                'test_mode': True,
            }
            payment.save()
            try:
                order.transition_to('PAID', changed_by=by, note='Mock gateway charge succeeded.')
            except Exception as exc:  # transaction rolls back both writes
                raise PaymentError('Could not mark the order as paid.', 'invalid_transition') from exc
        else:
            payment.status = 'FAILED'
            payment.failure_reason = 'Mock gateway declined the card (test failure).'
            payment.raw_response = {
                'gateway': 'MOCK',
                'event': 'charge.failed',
                'reference': payment.transaction_ref,
                'test_mode': True,
            }
            payment.save()
    return payment


def latest_payment(order: Order) -> Payment | None:
    try:
        return order.payment
    except Payment.DoesNotExist:
        return None
