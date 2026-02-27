"""
appname/auth_views.py
────────────────────────────────────────────────────────────────────────────
Google OAuth login/logout views + python-social-auth pipeline step that
auto-enables GCP APIs on first login.

Fits exactly into the existing project layout:
  appname/
  ├── models.py           (ChatSession, MetricSnapshot, etc.)
  ├── views.py            (existing API endpoints)
  ├── urls.py             (will be updated)
  ├── middleware.py       (existing RequestLoggingMiddleware)
  ├── auth_views.py       ← THIS FILE
  ├── auth_middleware.py
  └── services/
      ├── agents.py
      ├── ai_engine.py
      ├── monitoring.py
      ├── gcloud_monitoring.py
      └── groq_manager.py
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import os
from typing import Any

from django.contrib import messages
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

# GCP project — same env var already used in gcloud_monitoring.py
GCP_PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "eco-cloudai")

# All APIs your app already calls (compute + monitoring + secret manager)
REQUIRED_GCP_SERVICES: list[str] = [
    "compute.googleapis.com",            # gcp_compute_manager.py
    "monitoring.googleapis.com",         # gcloud_monitoring.py
    "secretmanager.googleapis.com",      # secrets_access_manager.py
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "logging.googleapis.com",
    "iam.googleapis.com",
]


# ── Login / logout views ──────────────────────────────────────────────────────

def login_view(request: HttpRequest) -> HttpResponse:
    """GET /login — renders login.html template. Logged-in users go straight to dashboard."""
    if request.user.is_authenticated:
        return redirect("index")
    return render(request, "appname/login.html")


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    """POST /logout"""
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("login")


# ── python-social-auth pipeline step ─────────────────────────────────────────

def enable_gcp_services_pipeline(
    backend,
    user,
    response,
    is_new: bool = False,
    *args: Any,
    **kwargs: Any,
) -> dict:
    """
    social-auth pipeline step — insert after 'social_core.pipeline.user.create_user'
    in settings.SOCIAL_AUTH_PIPELINE.

    - Runs on every login (to reset the monitoring client singleton).
    - Calls the GCP Service Usage API ONLY on the very first login (is_new=True)
      to enable all APIs the app needs.
    """
    if backend.name != "google-oauth2":
        return {}

    email = getattr(user, "email", "unknown")

    # Always reset the gcloud_monitoring lazy client so it re-auths cleanly
    _reset_monitoring_client()

    if is_new:
        logger.info("First login for %s — enabling GCP services", email)
        try:
            results = enable_required_gcp_services()
            _log_results(results, email)
        except Exception as exc:
            # Never break the login flow — log and continue
            logger.error("GCP service-enable failed for %s: %s", email, exc)

    return {}


# ── GCP Service Usage helper ──────────────────────────────────────────────────

def enable_required_gcp_services(project_id: str | None = None) -> list[dict]:
    """
    Enable every service in REQUIRED_GCP_SERVICES via the Service Usage API.
    Returns [{ "service": str, "status": "enabled"|"already_enabled"|"error", "message": str }].

    Can be called standalone for debugging:
        python manage.py shell -c "
        from appname.auth_views import enable_required_gcp_services
        import json; print(json.dumps(enable_required_gcp_services(), indent=2))
        "
    """
    from google.cloud import service_usage_v1
    from google.api_core.exceptions import GoogleAPIError

    project = project_id or GCP_PROJECT_ID
    client = service_usage_v1.ServiceUsageClient()
    results: list[dict] = []

    for svc in REQUIRED_GCP_SERVICES:
        name = f"projects/{project}/services/{svc}"
        try:
            op = client.enable_service(
                request=service_usage_v1.EnableServiceRequest(name=name)
            )
            op.result(timeout=60)
            results.append({"service": svc, "status": "enabled", "message": "OK"})
            logger.info("Enabled GCP service: %s", svc)
        except GoogleAPIError as exc:
            status = "already_enabled" if "already" in str(exc).lower() else "error"
            results.append({"service": svc, "status": status, "message": str(exc)[:200]})
        except Exception as exc:
            results.append({"service": svc, "status": "error", "message": str(exc)[:200]})
            logger.error("Unexpected error enabling %s: %s", svc, exc)

    return results


def _reset_monitoring_client() -> None:
    """
    Reset the lazy singleton in appname/services/gcloud_monitoring.py.
    That module uses:  _client: Optional[monitoring_v3.MetricServiceClient] = None
    Setting it to None forces re-authentication on the next call.
    """
    try:
        from appname.services import gcloud_monitoring
        gcloud_monitoring._client = None
        logger.debug("gcloud_monitoring._client reset")
    except ImportError:
        pass


def _log_results(results: list[dict], email: str) -> None:
    enabled  = [r["service"] for r in results if r["status"] == "enabled"]
    already  = [r["service"] for r in results if r["status"] == "already_enabled"]
    errors   = [r for r in results if r["status"] == "error"]
    if enabled:
        logger.info("User %s — newly enabled: %s", email, enabled)
    if already:
        logger.debug("Already enabled: %s", already)
    if errors:
        logger.warning("Enable errors for %s: %s", email, errors)