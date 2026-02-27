from __future__ import annotations

import json
import re
from typing import Iterable
from urllib import error, request

from appname.models import ChatMessage
from appname.services.agents import (
    apply_policy_command_from_prompt,
    run_forecast_agent,
    run_optimizer_agent,
    status_snapshot,
)
from appname.services.gcp_compute_manager import (
    available as gcp_compute_available,
    create_instance as gcp_create_instance,
    delete_instance as gcp_delete_instance,
    find_instance_exact_any,
)
from appname.services.groq_manager import get_agent_api_key
from appname.services.monitoring import metrics_history

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def _classify_intent(prompt: str) -> str:
    text = prompt.lower()
    if any(token in text for token in ["status", "health", "setting", "settings", "mode", "policy", "system", "systems"]):
        return "chat_status_agent"
    if any(token in text for token in ["forecast", "predict", "graph", "trend"]):
        return "forecast_agent"
    if any(token in text for token in ["optimize", "optimization", "right-size", "rightsizing"]):
        return "optimizer_agent"
    return "chat_agent"


def generate_ai_response(prompt: str, history: Iterable[ChatMessage]) -> str:
    update_msg = apply_policy_command_from_prompt(prompt)
    if update_msg:
        snap = status_snapshot()
        return (
            f"{update_msg}\n\n"
            f"Current policy: mode={snap['policy']['mode']}, "
            f"enabled={snap['policy']['optimization_enabled']}, "
            f"interval={snap['policy']['sample_interval_seconds']}s, "
            f"cooldown={snap['policy']['cooldown_seconds']}s."
        )

    compute_msg = _handle_compute_command(prompt)
    if compute_msg:
        return compute_msg

    memory_msg = _handle_memory_forecast_command(prompt)
    if memory_msg:
        return memory_msg

    agent_name = _classify_intent(prompt)
    if agent_name == "chat_status_agent":
        snap = status_snapshot()
        metrics = snap["latest_metrics"] or {"cpu_percent": 0, "memory_percent": 0, "disk_percent": 0}
        action = snap["latest_action"]
        action_line = "No optimization action yet."
        if action:
            action_line = (
                f"Latest action: {action['decision']} ({action['status']}) "
                f"{action['current_instance']} -> {action['target_instance']}"
            )
        return (
            "Delegating to `agent1_chatbot`.\n\n"
            f"Status: CPU {metrics['cpu_percent']}%, Memory {metrics['memory_percent']}%, Disk {metrics['disk_percent']}%.\n"
            f"Policy: mode={snap['policy']['mode']}, enabled={snap['policy']['optimization_enabled']}.\n"
            f"{action_line}"
        )

    if agent_name == "optimizer_agent":
        run = run_optimizer_agent()
        llm = run.get("llm_summary")
        fallback = (
            "Delegating to `agent2_optimizer`.\n\n"
            f"Decision: {run['impact']['decision']} ({run['action']['status']})\n"
            f"Path: {run['impact']['current_instance']} -> {run['impact']['target_instance']}\n"
            f"Savings: ${run['impact']['cost_savings_usd']} | CO2 reduction: {run['impact']['co2e_reduction_kg']} kg\n"
            f"Reason: {run['impact']['reason']}"
        )
        return llm or fallback

    if agent_name == "forecast_agent":
        forecast = run_forecast_agent()
        llm = forecast.get("llm_summary")
        fallback = (
            "Delegating to `agent3_forecast`.\n\n"
            f"Projected monthly savings: ${forecast['impact']['cost_savings_usd']}\n"
            f"Projected monthly CO2 reduction: {forecast['impact']['co2e_reduction_kg']} kg\n"
            f"Decision basis: {forecast['impact']['reason']}"
        )
        return llm or fallback

    llm_text, llm_error = _try_chat_groq(prompt=prompt, history=history)
    if llm_text and not _looks_off_topic(llm_text):
        return llm_text
    if llm_text and _looks_off_topic(llm_text):
        snap = status_snapshot()
        metrics = snap["latest_metrics"] or {"cpu_percent": 0, "memory_percent": 0, "disk_percent": 0}
        return (
            "Delegating to `agent1_chatbot`.\n\n"
            f"Cloud status: CPU {metrics['cpu_percent']}%, Memory {metrics['memory_percent']}%, Disk {metrics['disk_percent']}%.\n"
            f"Policy mode: {snap['policy']['mode']}."
        )
    if llm_error:
        return (
            "Delegating to `agent1_chatbot`.\n\n"
            f"Chat API failed ({llm_error}). "
            "Try asking for status, optimization mode updates, or forecast."
        )
    return "Delegating to `agent1_chatbot`."


def _handle_compute_command(prompt: str) -> str | None:
    text = prompt.strip()
    lower = text.lower()
    if "instance" not in lower:
        return None

    delete_match = re.search(
        r"\b(?:delete|remove|terminate)\b(?:\s+\w+){0,4}\s+\binstance\b(?:\s+(?:called|named))?\s+([a-zA-Z0-9-]+)\b",
        lower,
    )
    if delete_match:
        requested_name = delete_match.group(1)
        try:
            if not gcp_compute_available():
                return "Instance deletion failed: google-cloud-compute package is not installed."
            existing = find_instance_exact_any(requested_name)
            if not existing:
                return f"Instance `{requested_name}` not found."
            deleted = gcp_delete_instance(requested_name)
            status = str(deleted.get("status", "UNKNOWN"))
            if status == "DELETED":
                return (
                    f"Instance `{deleted['name']}` deleted successfully.\n\n"
                    f"Zone: {deleted['zone']}\n"
                    f"Machine type: {deleted['machine_type']}\n"
                    f"Status: {status}"
                )
            return (
                f"Delete request submitted for `{deleted['name']}`.\n\n"
                f"Zone: {deleted['zone']}\n"
                f"Machine type: {deleted['machine_type']}\n"
                f"Current status: {status}\n"
                "Deletion can take time; re-check instance list in a few seconds."
            )
        except Exception as exc:  # noqa: BLE001
            return f"Instance deletion failed: {exc}"

    create_match = re.search(
        r"\b(?:create|launch|provision)\b(?:\s+\w+){0,4}\s+\binstance\b(?:\s+(?:called|named))?\s+([a-zA-Z0-9-]+)\b",
        lower,
    )
    if not create_match:
        return None

    requested_name = create_match.group(1)
    zone_match = re.search(r"\bzone\s+([a-z]+-[a-z0-9]+-[a-z])\b", lower)
    machine_match = re.search(r"\b(e2|n2|c2|c3|t2d)-[a-z0-9-]+\b", lower)
    zone = zone_match.group(1) if zone_match else "asia-south1-a"
    machine_type = machine_match.group(0) if machine_match else "e2-standard-4"

    try:
        if not gcp_compute_available():
            return "Instance creation failed: google-cloud-compute package is not installed."
        existing = find_instance_exact_any(requested_name)
        if existing:
            return (
                f"Instance `{existing['name']}` already exists in zone `{existing['zone']}` "
                f"with machine type `{existing['machine_type']}` and status `{existing['status']}`."
            )
        created = gcp_create_instance(name=requested_name, zone=zone, machine_type=machine_type)
        return (
            "Instance created successfully.\n\n"
            f"Name: {created['name']}\n"
            f"Zone: {created['zone']}\n"
            f"Machine type: {created['machine_type']}\n"
            f"Status: {created['status']}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"Instance creation failed: {exc}"


def _try_chat_groq(prompt: str, history: Iterable[ChatMessage]) -> tuple[str | None, str | None]:
    api_key = get_agent_api_key("chat")
    if not api_key:
        return None, "chat key not configured"

    compact_history = []
    for msg in list(history)[-8:]:
        compact_history.append({"role": "assistant" if msg.role == "assistant" else "user", "content": msg.content})
    messages = [
        {
            "role": "system",
            "content": (
                "You are agent1_chatbot for eco-cloudai. You can report status and explain settings. "
                "For optimization and forecasts, summarize outcomes and keep answers concise."
            ),
        }
    ]
    messages.extend(compact_history)
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": messages,
        "temperature": 0.2,
    }
    req = request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "GreenOpsDjango/chat-agent",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"], None
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        return None, f"HTTP {exc.code} {exc.reason} {body[:120]}"
    except error.URLError as exc:
        return None, f"network {exc.reason}"
    except (KeyError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"parse {exc}"


def _looks_off_topic(text: str) -> bool:
    t = text.lower()
    banned = ["solar", "water recycling", "air quality", "energy storage", "panels"]
    return any(token in t for token in banned)


def _parse_forecast_hours(text: str, default_hours: float = 3.0) -> float:
    match = re.search(r"\b(?:next|in)?\s*(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", text)
    if not match:
        return default_hours
    try:
        return max(0.25, min(24.0, float(match.group(1))))
    except ValueError:
        return default_hours


def _handle_memory_forecast_command(prompt: str) -> str | None:
    text = prompt.strip().lower()
    memory_tokens = ("ram", "memory")
    forecast_tokens = ("predict", "forecast", "next", "future", "will be used", "usage")
    if not any(token in text for token in memory_tokens):
        return None
    if not any(token in text for token in forecast_tokens):
        return None

    hours = _parse_forecast_hours(text, default_hours=3.0)
    history = metrics_history(limit=60)
    if len(history) < 3:
        return "Need more telemetry to forecast RAM. Collect a few more samples and retry."

    series = [float(row.get("memory_percent", 0.0)) for row in history]
    latest = series[-1]
    slope_per_sample = (series[-1] - series[0]) / max(1, len(series) - 1)
    sample_interval_seconds = float(status_snapshot()["policy"].get("sample_interval_seconds", 10))
    steps = max(1, int((hours * 3600.0) / max(1.0, sample_interval_seconds)))
    predicted = max(0.0, min(100.0, latest + (slope_per_sample * steps)))

    deltas = [abs(series[i] - series[i - 1]) for i in range(1, len(series))]
    avg_delta = (sum(deltas) / len(deltas)) if deltas else 0.0
    band = min(20.0, avg_delta * (steps ** 0.5))
    low = max(0.0, predicted - band)
    high = min(100.0, predicted + band)

    if psutil is not None:
        try:
            total_gb = float(psutil.virtual_memory().total) / (1024.0 ** 3)
            latest_gb = total_gb * latest / 100.0
            pred_gb = total_gb * predicted / 100.0
            low_gb = total_gb * low / 100.0
            high_gb = total_gb * high / 100.0
            return (
                f"Predicted RAM usage in next {hours:g}h: ~{pred_gb:.2f} GB "
                f"({predicted:.1f}% of {total_gb:.2f} GB).\n\n"
                f"Current: {latest_gb:.2f} GB ({latest:.1f}%). "
                f"Range estimate: {low_gb:.2f}-{high_gb:.2f} GB."
            )
        except Exception:
            pass

    return (
        f"Predicted RAM usage in next {hours:g}h: ~{predicted:.1f}%.\n\n"
        f"Current: {latest:.1f}%. Range estimate: {low:.1f}-{high:.1f}%."
    )
