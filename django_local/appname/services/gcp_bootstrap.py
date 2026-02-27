from __future__ import annotations

import json
from typing import Any
from urllib import error, request

import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest

DEFAULT_REQUIRED_SERVICES = [
    "compute.googleapis.com",
    "monitoring.googleapis.com",
    "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com",
]


def _credentials_and_project() -> tuple[Any, str | None]:
    creds, project_id = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(GoogleAuthRequest())
    return creds, project_id


def _authorized_get_json(url: str, token: str) -> dict[str, Any]:
    req = request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "EcoCloudAI/bootstrap",
        },
        method="GET",
    )
    with request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _authorized_post_json(url: str, token: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = json.dumps(body or {}).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "EcoCloudAI/bootstrap",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def bootstrap_status(project_id: str | None = None, services: list[str] | None = None) -> dict[str, Any]:
    try:
        creds, default_project = _credentials_and_project()
    except Exception as exc:  # noqa: BLE001
        return {
            "connected": False,
            "error": str(exc),
            "default_project_id": None,
            "project_id": project_id or None,
            "required_services": services or DEFAULT_REQUIRED_SERVICES,
            "service_states": [],
        }

    token = creds.token
    effective_project = (project_id or default_project or "").strip()
    if not effective_project:
        return {
            "connected": True,
            "error": "No project id provided and no default project found in ADC.",
            "default_project_id": default_project,
            "project_id": None,
            "required_services": services or DEFAULT_REQUIRED_SERVICES,
            "service_states": [],
        }

    required = services or DEFAULT_REQUIRED_SERVICES
    states: list[dict[str, str]] = []
    for svc in required:
        url = f"https://serviceusage.googleapis.com/v1/projects/{effective_project}/services/{svc}"
        state = "UNKNOWN"
        try:
            payload = _authorized_get_json(url=url, token=token)
            state = str(payload.get("state", "UNKNOWN"))
        except error.HTTPError as exc:
            if exc.code == 404:
                state = "NOT_ENABLED"
            else:
                state = f"ERROR_HTTP_{exc.code}"
        except Exception:
            state = "ERROR"
        states.append({"service": svc, "state": state})

    principal_hint = getattr(creds, "service_account_email", None) or getattr(creds, "quota_project_id", None) or "user-oauth"
    return {
        "connected": True,
        "default_project_id": default_project,
        "project_id": effective_project,
        "principal_hint": principal_hint,
        "required_services": required,
        "service_states": states,
    }


def enable_required_services(project_id: str, services: list[str] | None = None) -> dict[str, Any]:
    creds, default_project = _credentials_and_project()
    token = creds.token
    effective_project = (project_id or default_project or "").strip()
    if not effective_project:
        raise RuntimeError("Project id is required.")

    required = services or DEFAULT_REQUIRED_SERVICES
    results: list[dict[str, str]] = []
    for svc in required:
        url = f"https://serviceusage.googleapis.com/v1/projects/{effective_project}/services/{svc}:enable"
        try:
            payload = _authorized_post_json(url=url, token=token, body={})
            operation = str(payload.get("name", ""))
            results.append({"service": svc, "status": "ENABLE_REQUESTED", "operation": operation})
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            # Service Usage may return 400/409 when already enabled.
            if "already enabled" in body.lower() or "alreadyenable" in body.lower():
                results.append({"service": svc, "status": "ALREADY_ENABLED", "operation": ""})
            else:
                results.append({"service": svc, "status": f"ERROR_HTTP_{exc.code}", "operation": ""})
        except Exception:
            results.append({"service": svc, "status": "ERROR", "operation": ""})

    return {
        "project_id": effective_project,
        "default_project_id": default_project,
        "results": results,
    }
