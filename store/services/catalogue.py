"""Product search and catalogue filtering.

Filters map to the indexes declared on ``Product``:

* ``category`` + ``price`` -> ``product_cat_price_idx``
* ``price``               -> ``product_price_idx``
* ``seller`` + active     -> ``product_seller_active_idx``
* keyword on name         -> ``product_name_idx`` (prefix search)

Keyword matching uses ``icontains`` for portability across SQLite/PostgreSQL;
on PostgreSQL the same code path works, and a GIN/trigram index can be added
later without changing callers.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.db.models import Avg, Count, DecimalField, IntegerField, Max, Min, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce

from ..models import Category, Inventory, Product


SORT_OPTIONS = {
    'newest': ('-created_at', 'name'),
    'oldest': ('created_at', 'name'),
    'price_asc': ('price', 'name'),
    'price_desc': ('-price', 'name'),
    'name': ('name',),
}


def available_products():
    stock = Inventory.objects.filter(product_id=OuterRef('pk')).values('stock_quantity')[:1]
    return (
        Product.objects.filter(
            is_active=True,
            category__is_active=True,
            seller__is_approved=True,
            seller__is_suspended=False,
        )
        .select_related('category', 'seller')
        .annotate(
            stock_quantity=Coalesce(
                Subquery(stock, output_field=IntegerField()),
                Value(0),
                output_field=IntegerField(),
            ),
            rating_average=Avg('reviews__rating'),
            reviews_total=Count('reviews', distinct=True),
        )
    )


def parse_price(value) -> Decimal | None:
    if value in (None, ''):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def filter_products(
    *,
    q: str = '',
    category: str = '',
    min_price=None,
    max_price=None,
    seller: str = '',
    sort: str = 'newest',
    in_stock_only: bool = False,
):
    products = available_products()
    keyword = (q or '').strip()
    if keyword:
        products = products.filter(
            Q(name__icontains=keyword)
            | Q(description__icontains=keyword)
            | Q(category__name__icontains=keyword)
            | Q(seller__store_name__icontains=keyword)
        )

    category_value = (category or '').strip()
    if category_value:
        if category_value.isdigit():
            products = products.filter(category_id=int(category_value))
        else:
            products = products.filter(category__slug=category_value)

    minimum = parse_price(min_price)
    maximum = parse_price(max_price)
    if minimum is not None:
        products = products.filter(price__gte=minimum)
    if maximum is not None:
        products = products.filter(price__lte=maximum)
    if minimum is not None and maximum is not None and minimum > maximum:
        products = products.none()

    seller_value = (seller or '').strip()
    if seller_value:
        if seller_value.isdigit():
            products = products.filter(seller_id=int(seller_value))
        else:
            products = products.filter(seller__slug=seller_value)

    if in_stock_only:
        products = products.filter(stock_quantity__gt=0)

    if sort == 'rating':
        products = products.order_by('-rating_average', 'name')
    elif sort == 'popular':
        products = products.annotate(sold_count=Count('order_items', distinct=True)).order_by('-sold_count', 'name')
    else:
        products = products.order_by(*SORT_OPTIONS.get(sort, SORT_OPTIONS['newest']))
    return products


def categories_for_nav():
    return Category.objects.filter(is_active=True).order_by('name')


def price_summary(category: str = ''):
    products = filter_products(category=category)
    return products.aggregate(
        minimum=Coalesce(
            Min('price'),
            Value(Decimal('0.00')),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        ),
        maximum=Max('price'),
    )
