from .models import Category
from .permissions import is_admin
from .services.cart import get_cart


def marketplace_context(request):
    try:
        cart = get_cart(request)
        cart_count = cart.item_count if cart else 0
    except Exception:  # pragma: no cover - templates should never 500 on nav
        cart_count = 0
    return {
        'nav_categories': Category.objects.filter(is_active=True).order_by('name')[:7],
        'cart_count': cart_count,
        'is_admin_user': is_admin(getattr(request, 'user', None)),
        'current_seller': getattr(getattr(request, 'user', None), 'seller_profile', None),
    }
