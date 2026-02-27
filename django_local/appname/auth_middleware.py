"""
appname/auth_middleware.py
────────────────────────────────────────────────────────────────────────────
API key middleware for the Django JSON backend.

Architecture reality:
  - Streamlit (app.py) is the UI — it talks to Django via requests.get/post
  - Django is a pure JSON API — it must NEVER redirect to /login/
  - The login page lives in Streamlit (app.py), not Django

This middleware checks for an API key on every non-public request.
The Streamlit app sends it as a header: X-API-Key: <value>

Set the key via environment variable:
    GREENOPS_API_KEY=your-secret-key

If GREENOPS_API_KEY is not set, middleware is disabled (dev mode).
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import os
from django.http import JsonResponse

_PUBLIC_EXACT = frozenset([
    "/",
    "/health",
    "/health/",
    "/login/",
    "/login",
    "/logout/",
    "/logout",
])

_PUBLIC_PREFIX = (
    "/auth/",
    "/static/",
    "/admin/",
)

_API_KEY = os.environ.get("GREENOPS_API_KEY", "")


class ApiKeyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # No key configured → dev mode, no auth enforced
        if not _API_KEY:
            return self.get_response(request)

        path = request.path_info

        if path in _PUBLIC_EXACT or path.startswith(_PUBLIC_PREFIX):
            return self.get_response(request)

        provided = request.headers.get("X-API-Key", "")
        if provided != _API_KEY:
            return JsonResponse(
                {"error": "Unauthorized. Provide a valid X-API-Key header."},
                status=401,
            )

        return self.get_response(request)


# Backward compatibility for older settings paths.
LoginRequiredMiddleware = ApiKeyMiddleware
