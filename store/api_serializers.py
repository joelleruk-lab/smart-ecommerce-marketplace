"""JSON serialisers shared by the REST endpoints (and used by tests)."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from .models import Cart, Order, Payment, Product, Review, SellerProfile


def money(value) -> str:
    if value is None:
        return '0.00'
    return f'{Decimal(value):.2f}'


def iso(dt):
    return dt.isoformat() if dt else None


def user_payload(user) -> dict:
    return {
        'id': user.pk,
        'username': user.username,
        'email': user.email,
        'full_name': user.get_full_name(),
        'role': user.role,
        'phone_number': user.phone_number,
        'is_active': user.is_active,
        'is_blocked': user.is_blocked,
        'date_joined': iso(user.date_joined),
    }


def seller_payload(seller: SellerProfile) -> dict:
    return {
        'id': seller.pk,
        'store_name': seller.store_name,
        'slug': seller.slug,
        'description': seller.store_description,
        'is_approved': seller.is_approved,
        'is_suspended': seller.is_suspended,
        'status': seller.status,
        'approved_at': iso(seller.approved_at),
    }


def category_payload(category) -> dict:
    return {
        'id': category.pk,
        'name': category.name,
        'slug': category.slug,
        'icon': category.icon,
        'description': category.description,
        'is_active': category.is_active,
        'product_count': getattr(category, 'product_count', None),
    }


def product_payload(product: Product, *, detail: bool = False) -> dict:
    inventory = getattr(product, 'inventory', None)
    stock = getattr(product, 'stock_quantity', None)
    if stock is None:
        stock = inventory.stock_quantity if inventory else 0
    images = [
        {
            'id': image.pk,
            'url': image.external_url or (image.image.url if image.image else ''),
            'alt_text': image.alt_text,
            'is_primary': image.is_primary,
        }
        for image in product.images.all()
    ]
    rating = getattr(product, 'rating_average', None)
    if rating is None:
        rating = product.average_rating
    reviews_total = getattr(product, 'reviews_total', None)
    if reviews_total is None:
        reviews_total = product.review_count
    payload = {
        'id': product.pk,
        'name': product.name,
        'sku': product.sku,
        'price': money(product.price),
        'currency': 'UGX',
        'stock': stock,
        'low_stock': stock <= product.low_stock_threshold,
        'is_active': product.is_active,
        'category': {'id': product.category_id, 'name': product.category.name, 'slug': product.category.slug},
        'seller': {'id': product.seller_id, 'store_name': product.seller.store_name, 'slug': product.seller.slug},
        'primary_image': product.display_image_url or None,
        'rating': round(rating, 2) if rating else None,
        'review_count': reviews_total,
        'created_at': iso(product.created_at),
    }
    if detail:
        payload.update({
            'description': product.description,
            'images': images,
            'low_stock_threshold': product.low_stock_threshold,
            'seller': {
                **payload['seller'],
                'description': product.seller.store_description,
                'is_approved': product.seller.is_approved,
            },
            'updated_at': iso(product.updated_at),
        })
    return payload


def review_payload(review: Review) -> dict:
    return {
        'id': review.pk,
        'customer': {'id': review.customer_id, 'username': review.customer.username},
        'product_id': review.product_id,
        'rating': review.rating,
        'comment': review.comment,
        'is_verified_purchase': review.is_verified_purchase,
        'created_at': iso(review.created_at),
    }


def cart_payload(cart: Cart | None) -> dict:
    if cart is None:
        return {'items': [], 'item_count': 0, 'subtotal': '0.00', 'total': '0.00'}
    items = cart.items.select_related('product', 'product__seller', 'product__inventory').order_by('product__name')
    rows = []
    subtotal = Decimal('0.00')
    for item in items:
        inventory = getattr(item.product, 'inventory', None)
        line_total = item.product.price * item.quantity
        subtotal += line_total
        rows.append({
            'product_id': item.product_id,
            'name': item.product.name,
            'price': money(item.product.price),
            'quantity': item.quantity,
            'line_total': money(line_total),
            'stock': inventory.stock_quantity if inventory else 0,
            'seller': item.product.seller.store_name,
            'primary_image': item.product.display_image_url or None,
            'available': bool(inventory and inventory.stock_quantity >= item.quantity),
        })
    return {
        'items': rows,
        'item_count': sum(row['quantity'] for row in rows),
        'subtotal': money(subtotal),
        'total': money(subtotal),
    }


def payment_payload(payment: Payment | None) -> dict | None:
    if payment is None:
        return None
    return {
        'id': payment.pk,
        'order_id': payment.order_id,
        'gateway': payment.gateway,
        'reference': payment.transaction_ref,
        'provider_reference': payment.provider_reference,
        'amount': money(payment.amount),
        'currency': payment.currency,
        'status': payment.status,
        'attempts': payment.attempts,
        'failure_reason': payment.failure_reason,
        'paid_at': iso(payment.paid_at),
        'created_at': iso(payment.created_at),
    }


def shipment_payload(order: Order) -> dict | None:
    shipment = getattr(order, 'shipment', None)
    if shipment is None:
        return None
    return {
        'courier': shipment.courier,
        'tracking_number': shipment.tracking_number,
        'status': shipment.status,
        'shipped_at': iso(shipment.shipped_at),
        'delivered_at': iso(shipment.delivered_at),
    }


def order_payload(order: Order, *, detail: bool = False, seller_id: int | None = None) -> dict:
    items = order.items.all()
    if seller_id is not None:
        items = [item for item in items if item.seller_id == seller_id]
    item_rows = [
        {
            'id': item.pk,
            'product_id': item.product_id,
            'name': item.product_name_snapshot,
            'sku': item.sku_snapshot,
            'seller': item.seller_name_snapshot,
            'quantity': item.quantity,
            'unit_price': money(item.unit_price_snapshot),
            'line_total': money(item.line_total),
        }
        for item in items
    ]
    cargo = {
        'id': order.pk,
        'reference': order.reference,
        'status': order.status,
        'status_display': order.get_status_display(),
        'subtotal': money(order.subtotal),
        'shipping_fee': money(order.shipping_fee),
        'total': money(order.total_amount),
        'item_count': sum(row['quantity'] for row in item_rows),
        'items': item_rows,
        'created_at': iso(order.created_at),
        'paid_at': iso(order.paid_at),
        'shipped_at': iso(order.shipped_at),
        'delivered_at': iso(order.delivered_at),
        'cancelled_at': iso(order.cancelled_at),
        'can_be_cancelled': order.can_be_cancelled,
        'payment': payment_payload(getattr(order, 'payment', None)),
        'customer': {'id': order.customer_id, 'username': order.customer.username},
    }
    if seller_id is not None:
        # A seller only sees the value of their own lines, not the whole
        # multi-vendor basket or other sellers' revenue.
        seller_total = sum((item.line_total for item in items), Decimal('0.00'))
        cargo['seller_subtotal'] = money(seller_total)
        cargo['subtotal'] = money(seller_total)
        cargo['shipping_fee'] = '0.00'
        cargo['total'] = money(seller_total)
    if detail:
        cargo['shipping'] = {
            'full_name': order.shipping_full_name,
            'phone': order.shipping_phone,
            'address': order.shipping_address,
            'city': order.shipping_city,
        }
        cargo['shipment'] = shipment_payload(order)
        cargo['cancellation_reason'] = order.cancellation_reason
        cargo['status_history'] = [
            {
                'from': event.from_status,
                'to': event.to_status,
                'note': event.note,
                'at': iso(event.created_at),
            }
            for event in order.status_events.all()
        ]
        cargo['disputes'] = [
            {
                'id': dispute.pk,
                'reason': dispute.reason,
                'status': dispute.status,
                'description': dispute.description,
                'resolution_note': dispute.resolution_note,
                'created_at': iso(dispute.created_at),
            }
            for dispute in order.disputes.all()
        ]
    return cargo


def paginated(rows, *, page: int, page_size: int, total: int, **extra) -> dict:
    return {
        'results': rows,
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total': total,
            'pages': max(1, -(-total // page_size)),
            'generated_at': timezone.now().isoformat(),
        },
        **extra,
    }
