"""Bearer-token authentication and JSON helpers for the REST API.

The API uses opaque, hashed bearer tokens rather than JWTs: they can be revoked
individually, they carry no claims that can be tampered with, and no signing key
has to be rotated.  Tokens are stored as SHA-256 hashes, so even a database
dump cannot be replayed against the API.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from .models import ApiToken


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def issue_token(user, label: str = 'api') -> str:
    raw = secrets.token_urlsafe(32)
    ApiToken.objects.create(user=user, token_hash=hash_token(raw), label=label[:100])
    return raw


def revoke_token(raw_token: str) -> bool:
    return ApiToken.objects.filter(token_hash=hash_token(raw_token)).update(revoked=True) > 0


def _extract_token(request) -> str:
    header = request.META.get('HTTP_AUTHORIZATION', '')
    if header.lower().startswith('bearer '):
        return header[7:].strip()
    return request.META.get('HTTP_X_API_TOKEN', '').strip()


def authenticate_request(request):
    """Return ``(user, token)`` for a valid bearer token, else ``(None, None)``."""
    raw = _extract_token(request)
    if not raw:
        return None, None
    token = (
        ApiToken.objects.select_related('user')
        .filter(token_hash=hash_token(raw), revoked=False, user__is_active=True)
        .first()
    )
    if token is None:
        return None, None
    if token.user.is_blocked:
        return None, None
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
    return token.user, token


def json_body(request) -> dict:
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Request body must be valid JSON.') from exc
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')
    return payload


def error_response(message: str, code: str = 'error', status: int = 400, details=None) -> JsonResponse:
    return JsonResponse(
        {'error': {'code': code, 'message': message, 'details': details or {}}},
        status=status,
    )


def ok(data=None, *, status: int = 200, **extra) -> JsonResponse:
    payload = {'data': data} if data is not None else {}
    payload.update(extra)
    return JsonResponse(payload, status=status, safe=False)


def api_login_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user, token = authenticate_request(request)
        if user is None:
            return error_response('Authentication required. Send "Authorization: Bearer <token>".', 'unauthorized', 401)
        request.api_user = user
        request.api_token = token
        return view(request, *args, **kwargs)

    return wrapper


def api_role_required(*roles):
    def decorator(view):
        @wraps(view)
        @api_login_required
        def wrapper(request, *args, **kwargs):
            user = request.api_user
            allowed = set(roles)
            if 'ADMIN' in allowed and (user.role == 'ADMIN' or user.is_staff):
                return view(request, *args, **kwargs)
            if user.role in allowed:
                return view(request, *args, **kwargs)
            return error_response('You do not have permission to perform this action.', 'forbidden', 403)

        return wrapper

    return decorator


def verify_webhook_signature(request) -> bool:
    """Verify the mock gateway callback signature.

    ``X-Mock-Signature`` must equal HMAC-SHA256(secret, raw_body) in hex.  This
    mirrors how Stripe/Paystack webhooks are verified, without sending real
    money.
    """
    secret = getattr(settings, 'MOCK_GATEWAY_SECRET', '')
    if not secret:
        return False
    provided = request.META.get('HTTP_X_MOCK_SIGNATURE', '')
    expected = hmac.new(secret.encode('utf-8'), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)
