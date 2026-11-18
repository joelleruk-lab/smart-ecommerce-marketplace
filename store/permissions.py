"""Role-based access helpers for the server-rendered views."""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import render


def is_admin(user) -> bool:
    return bool(user.is_authenticated and (user.role == 'ADMIN' or user.is_staff or user.is_superuser))


def is_seller(user) -> bool:
    return bool(user.is_authenticated and user.role == 'SELLER')


def role_required(*roles):
    """Allow only the given roles.

    Unauthenticated users are sent to the login page; authenticated users
    without the role receive a 403 page (least privilege, no information leak).
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            allowed = set(roles)
            if 'ADMIN' in allowed and is_admin(request.user):
                return view(request, *args, **kwargs)
            if request.user.role in allowed:
                return view(request, *args, **kwargs)
            return render(request, 'store/403.html', {'required_roles': roles}, status=403)

        return wrapper

    return decorator


def customer_required(view):
    return role_required('CUSTOMER')(view)


def seller_required(view):
    return role_required('SELLER')(view)


def admin_required(view):
    return role_required('ADMIN')(view)


def get_seller_or_403(request):
    seller = getattr(request.user, 'seller_profile', None)
    if seller is None:
        raise PermissionDenied('Only seller accounts have a store.')
    return seller
