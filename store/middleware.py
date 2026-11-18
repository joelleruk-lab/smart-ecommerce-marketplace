"""Middleware that keeps API errors JSON instead of HTML."""

from __future__ import annotations

import logging

from django.conf import settings
from django.http import JsonResponse


logger = logging.getLogger(__name__)

JSON_ERRORS = {
    403: ('forbidden', 'You do not have permission to perform this action.'),
    404: ('not_found', 'The requested resource was not found.'),
    405: ('method_not_allowed', 'This HTTP method is not allowed for this endpoint.'),
    409: ('conflict', 'The request conflicts with the current state.'),
}


class ApiJSONMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/api/'):
            return self.get_response(request)
        try:
            response = self.get_response(request)
        except Exception:
            logger.exception('Unhandled API error on %s', request.path)
            if settings.DEBUG:
                raise
            return JsonResponse(
                {'error': {'code': 'server_error', 'message': 'An unexpected error occurred.'}},
                status=500,
            )
        if response.status_code in JSON_ERRORS and response.get('Content-Type', '').startswith('text/html'):
            code, message = JSON_ERRORS[response.status_code]
            return JsonResponse({'error': {'code': code, 'message': message}}, status=response.status_code)
        return response
