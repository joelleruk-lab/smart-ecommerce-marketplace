"""Reporting queries used by the admin dashboard and the API.

Only paid-like orders (PAID, SHIPPED, DELIVERED) count towards revenue; pending
and cancelled orders are excluded.  All aggregations use the historical
``OrderItem`` snapshots, never current product prices.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, DecimalField, F, Sum
from django.db.models.functions import Coalesce, TruncDate, TruncMonth, TruncWeek, TruncYear
from django.utils import timezone

from ..models import (
    Category,
    Inventory,
    Order,
    OrderItem,
    Payment,
    Product,
    Review,
    SellerProfile,
)


User = get_user_model()

REVENUE_STATUSES = ('PAID', 'SHIPPED', 'DELIVERED')
MONEY = DecimalField(max_digits=14, decimal_places=2)

TRUNCS = {
    'day': TruncDate,
    'week': TruncWeek,
    'month': TruncMonth,
    'year': TruncYear,
}


def _line_revenue():
    return Sum(F('quantity') * F('unit_price_snapshot'), output_field=MONEY)


def revenue_orders():
    return Order.objects.filter(status__in=REVENUE_STATUSES)


def sales_per_seller():
    rows = (
        OrderItem.objects.filter(order__status__in=REVENUE_STATUSES)
        .values('seller_id', 'seller__store_name')
        .annotate(
            units=Sum('quantity'),
            revenue=_line_revenue(),
            orders=Count('order_id', distinct=True),
        )
        .order_by('-revenue', 'seller__store_name')
    )
    for row in rows:
        row['store_name'] = row.pop('seller__store_name') or 'Deleted seller'
        row['revenue'] = row['revenue'] or Decimal('0.00')
    return list(rows)


def revenue_per_period(period: str = 'month', start=None, end=None):
    trunc = TRUNCS.get(period, TruncMonth)
    orders = revenue_orders()
    if start:
        orders = orders.filter(created_at__gte=start)
    if end:
        orders = orders.filter(created_at__lte=end)
    rows = (
        orders.annotate(bucket=trunc('created_at'))
        .values('bucket')
        .annotate(revenue=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=MONEY), orders=Count('id'))
        .order_by('bucket')
    )
    return [
        {
            'period': row['bucket'].isoformat() if row['bucket'] else None,
            'revenue': row['revenue'],
            'orders': row['orders'],
        }
        for row in rows
    ]


def best_sellers(limit: int = 10):
    rows = (
        OrderItem.objects.filter(order__status__in=REVENUE_STATUSES)
        .values('product_id', 'product_name_snapshot', 'sku_snapshot')
        .annotate(
            units=Sum('quantity'),
            revenue=_line_revenue(),
            orders=Count('order_id', distinct=True),
        )
        .order_by('-units', '-revenue')[:limit]
    )
    return list(rows)


def low_stock(limit: int = 100):
    rows = (
        Inventory.objects.filter(stock_quantity__lte=F('product__low_stock_threshold'), product__is_active=True)
        .select_related('product', 'product__seller', 'product__category')
        .order_by('stock_quantity', 'product__name')[:limit]
    )
    return [
        {
            'product_id': row.product_id,
            'product': row.product.name,
            'seller': row.product.seller.store_name,
            'category': row.product.category.name,
            'stock': row.stock_quantity,
            'threshold': row.product.low_stock_threshold,
            'price': row.product.price,
        }
        for row in rows
    ]


def sales_per_category():
    rows = (
        OrderItem.objects.filter(order__status__in=REVENUE_STATUSES, product__isnull=False)
        .values('product__category__name')
        .annotate(units=Sum('quantity'), revenue=_line_revenue())
        .order_by('-revenue')
    )
    return [
        {
            'category': row['product__category__name'] or 'Uncategorised',
            'units': row['units'],
            'revenue': row['revenue'] or Decimal('0.00'),
        }
        for row in rows
    ]


def summary():
    revenue = revenue_orders().aggregate(total=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=MONEY))['total']
    return {
        'revenue': revenue,
        'paid_orders': revenue_orders().count(),
        'all_orders': Order.objects.count(),
        'customers': User.objects.filter(role='CUSTOMER').count(),
        'sellers': SellerProfile.objects.filter(is_approved=True, is_suspended=False).count(),
        'pending_sellers': SellerProfile.objects.filter(is_approved=False, is_suspended=False).count(),
        'products': Product.objects.filter(is_active=True).count(),
        'low_stock': Inventory.objects.filter(
            stock_quantity__lte=F('product__low_stock_threshold'),
            product__is_active=True,
        ).count(),
        'open_disputes': Order.objects.filter(disputes__status__in=('OPEN', 'UNDER_REVIEW')).distinct().count(),
        'pending_payments': Payment.objects.filter(status='PENDING').count(),
        'reviews': Review.objects.count(),
        'average_rating': round(
            Review.objects.aggregate(value=Avg('rating'))['value'] or 0.0,
            2,
        ),
        'unread_orders': Order.objects.filter(status='PAID').count(),
    }


def seller_summary(seller: SellerProfile):
    """Dashboard numbers for one seller."""
    items = OrderItem.objects.filter(seller=seller, order__status__in=REVENUE_STATUSES)
    revenue = items.aggregate(
        total=Coalesce(Sum(F('quantity') * F('unit_price_snapshot'), output_field=MONEY), Decimal('0.00'))
    )['total']
    return {
        'products': seller.products.filter(is_active=True).count(),
        'low_stock': Inventory.objects.filter(
            product__seller=seller,
            product__is_active=True,
            stock_quantity__lte=F('product__low_stock_threshold'),
        ).count(),
        'orders': items.values('order_id').distinct().count(),
        'units_sold': items.aggregate(total=Coalesce(Sum('quantity'), 0))['total'],
        'revenue': revenue,
        'rating': Review.objects.filter(product__seller=seller).aggregate(
            value=Avg('rating')
        )['value'] or 0.0,
    }


def recent_orders(limit: int = 8):
    return (
        Order.objects.select_related('customer')
        .prefetch_related('items')
        .order_by('-created_at')[:limit]
    )
