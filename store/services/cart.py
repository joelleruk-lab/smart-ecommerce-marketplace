"""Cart operations shared by the HTML storefront and the JSON API."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from ..models import Cart, CartItem


MAX_LINE_QUANTITY = 99
MAX_DISTINCT_ITEMS = 50
MIN_LINE_QUANTITY = 1


class CartError(Exception):
    """A user-correctable cart problem (bad quantity, stock, limits)."""

    def __init__(self, message: str, code: str = 'cart_error'):
        super().__init__(message)
        self.message = message
        self.code = code


def get_cart(request, *, create: bool = False) -> Cart | None:
    """Return the active cart, optionally creating it.

    Signed-in users always use their database cart.  Guests use a cart keyed to
    their Django session, which is merged on login (see ``merge_carts``).
    """
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if cart is None and create:
            cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart

    session_key = request.session.session_key
    if not session_key:
        if not create:
            return None
        request.session.create()
        session_key = request.session.session_key
    cart = Cart.objects.filter(session_key=session_key).first()
    if cart is None and create:
        cart, _ = Cart.objects.get_or_create(session_key=session_key)
    return cart


def cart_items(cart: Cart | None):
    if cart is None:
        return []
    return list(
        cart.items.select_related('product', 'product__seller', 'product__category', 'product__inventory')
        .order_by('product__name')
    )


def cart_total(cart: Cart | None):
    from decimal import Decimal

    total = Decimal('0.00')
    for item in cart_items(cart):
        total += item.line_total
    return total


def _validate_quantity(product, quantity: int) -> int:
    if not isinstance(quantity, int):
        raise CartError('Quantity must be a whole number.', 'invalid_quantity')
    if quantity < MIN_LINE_QUANTITY:
        raise CartError('Quantity must be at least 1.', 'invalid_quantity')
    if quantity > MAX_LINE_QUANTITY:
        raise CartError(f'You can order at most {MAX_LINE_QUANTITY} units per item.', 'quantity_limit')
    stock = getattr(getattr(product, 'inventory', None), 'stock_quantity', 0)
    if quantity > stock:
        raise CartError(f'Only {stock} unit(s) of {product.name} are available.', 'insufficient_stock')
    return quantity


def add_item(cart: Cart, product, quantity: int = 1) -> CartItem:
    quantity = _validate_quantity(product, quantity)
    with transaction.atomic():
        cart = Cart.objects.select_for_update().get(pk=cart.pk)
        item = CartItem.objects.filter(cart=cart, product=product).first()
        new_quantity = quantity + (item.quantity if item else 0)
        if new_quantity > MAX_LINE_QUANTITY:
            raise CartError(f'You can order at most {MAX_LINE_QUANTITY} units per item.', 'quantity_limit')
        # Re-check stock against the combined quantity.
        _validate_quantity(product, new_quantity)
        if item is None:
            if cart.items.count() >= MAX_DISTINCT_ITEMS:
                raise CartError(f'A cart can hold at most {MAX_DISTINCT_ITEMS} different products.', 'cart_limit')
            item = CartItem.objects.create(cart=cart, product=product, quantity=new_quantity)
        else:
            item.quantity = new_quantity
            item.save(update_fields=['quantity', 'updated_at'])
    return item


def update_item(cart: Cart, product, quantity: int) -> CartItem | None:
    with transaction.atomic():
        item = CartItem.objects.filter(cart=cart, product=product).first()
        if item is None:
            raise CartError('That product is not in your cart.', 'not_in_cart')
        if quantity <= 0:
            item.delete()
            return None
        _validate_quantity(product, quantity)
        item.quantity = quantity
        item.save(update_fields=['quantity', 'updated_at'])
    return item


def remove_item(cart: Cart, product) -> bool:
    deleted, _ = CartItem.objects.filter(cart=cart, product=product).delete()
    return bool(deleted)


def clear(cart: Cart) -> None:
    cart.items.all().delete()


def merge_carts(source: Cart | None, target: Cart) -> None:
    """Merge a guest cart into a user cart after login.

    Quantities are combined and then clamped to available stock and the
    per-line limit, so a merge can never create an invalid cart.
    """
    if source is None or source.pk == target.pk:
        return
    with transaction.atomic():
        target = Cart.objects.select_for_update().get(pk=target.pk)
        for source_item in source.items.select_related('product', 'product__inventory'):
            product = source_item.product
            stock = getattr(getattr(product, 'inventory', None), 'stock_quantity', 0)
            existing = CartItem.objects.filter(cart=target, product=product).first()
            combined = source_item.quantity + (existing.quantity if existing else 0)
            allowed = min(combined, stock, MAX_LINE_QUANTITY)
            if allowed <= 0:
                continue
            if existing:
                CartItem.objects.filter(pk=existing.pk).update(quantity=allowed, updated_at=timezone.now())
            else:
                if target.items.count() >= MAX_DISTINCT_ITEMS:
                    break
                CartItem.objects.create(cart=target, product=product, quantity=allowed)
        source.delete()


def merge_session_cart_into_user(request, user) -> None:
    """Called by the login/registration views before the session is cycled."""
    session_key = request.session.session_key
    if not session_key:
        return
    guest_cart = Cart.objects.filter(session_key=session_key).first()
    if guest_cart is None:
        return
    user_cart, _ = Cart.objects.get_or_create(user=user)
    merge_carts(guest_cart, user_cart)
