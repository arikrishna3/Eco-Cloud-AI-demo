from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any
from urllib import error, request

from django.utils import timezone

from appname.models import ForecastSnapshot, OptimizationAction, OptimizationPolicy
from appname.services.impact import auto_impact_from_averages, average_utilization, demo_non_zero_impact
from appname.services.monitoring import metrics_history, sample_metrics
from appname.services.groq_manager import get_agent_api_key


def get_policy() -> OptimizationPolicy:
    policy, _ = OptimizationPolicy.objects.get_or_create(id=1)
    return policy


def update_policy_from_payload(payload: dict[str, Any]) -> OptimizationPolicy:
    policy = get_policy()
    mode = payload.get("mode")
    enabled = payload.get("optimization_enabled")
    sample_interval = payload.get("sample_interval_seconds")
    cooldown = payload.get("cooldown_seconds")

    if mode in {"low", "balanced", "high", "eco"}:
        policy.mode = "low" if mode == "eco" else mode
    if isinstance(enabled, bool):
        policy.optimization_enabled = enabled
    if isinstance(sample_interval, int):
        policy.sample_interval_seconds = max(5, min(120, sample_interval))
    if isinstance(cooldown, int):
        policy.cooldown_seconds = max(10, min(3600, cooldown))

    policy.save()
    return policy


def apply_policy_command_from_prompt(prompt: str) -> str | None:
    text = prompt.strip().lower()
    policy = get_policy()
    changed = False
    updates: list[str] = []

    mode_match = re.search(
        r"\b(?:set|switch|change).{0,20}\b(?:optimization|performance|mode)\b.{0,20}\b(low|balanced|high|eco)\b",
        text,
    )
    if mode_match:
        parsed_mode = mode_match.group(1)
        policy.mode = "low" if parsed_mode == "eco" else parsed_mode
        changed = True
        updates.append(f"mode={'eco' if policy.mode == 'low' else policy.mode}")

    if "disable optimization" in text or "turn optimization off" in text:
        policy.optimization_enabled = False
        changed = True
        updates.append("optimization_enabled=false")
    if "enable optimization" in text or "turn optimization on" in text:
        policy.optimization_enabled = True
        changed = True
        updates.append("optimization_enabled=true")

    sample_match = re.search(r"\b(?:every|interval)\s+(\d+)\s*(?:sec|second|seconds)\b", text)
    if sample_match:
        policy.sample_interval_seconds = max(5, min(120, int(sample_match.group(1))))
        changed = True
        updates.append(f"sample_interval_seconds={policy.sample_interval_seconds}")

    cooldown_match = re.search(r"\bcooldown\s+(\d+)\s*(?:sec|second|seconds)\b", text)
    if cooldown_match:
        policy.cooldown_seconds = max(10, min(3600, int(cooldown_match.group(1))))
        changed = True
        updates.append(f"cooldown_seconds={policy.cooldown_seconds}")

    if changed:
        policy.save()
        return f"Policy updated: {', '.join(updates)}."
    return None


def status_snapshot() -> dict[str, Any]:
    policy = get_policy()
    latest_action = OptimizationAction.objects.first()
    history = metrics_history(limit=30)
    averages = average_utilization(history)
    latest_metrics = history[-1] if history else None
    return {
        "policy": _policy_json(policy),
        "latest_metrics": latest_metrics,
        "averages": averages,
        "latest_action": _action_json(latest_action) if latest_action else None,
    }


def run_optimizer_agent(
    current_instance: str = "n2-standard-4",
    current_region: str = "us-central1",
    target_region: str = "us-central1",
    hours: float = 24 * 30,
) -> dict[str, Any]:
    policy = get_policy()
    sampled = sample_metrics()
    history = metrics_history(limit=60)
    averages = average_utilization(history)
    thresholds = _thresholds_for_mode(policy.mode)

    impact = auto_impact_from_averages(
        avg_cpu=averages["avg_cpu"],
        avg_memory=averages["avg_memory"],
        current_instance=current_instance,
        current_region=current_region,
        target_region=target_region,
        hours=hours,
        threshold_cpu_down=thresholds["cpu_down"],
        threshold_memory_down=thresholds["memory_down"],
        threshold_cpu_up=thresholds["cpu_up"],
        threshold_memory_up=thresholds["memory_up"],
    )

    status = "recommended"
    executed = False
    if not policy.optimization_enabled:
        status = "cooldown_skipped"
    else:
        last_action = OptimizationAction.objects.first()
        if last_action and last_action.created_at >= timezone.now() - timedelta(seconds=policy.cooldown_seconds):
            status = "cooldown_skipped"
        elif impact["decision"] in {"scale_down", "scale_up"} and impact["target_instance"] != impact["current_instance"]:
            status = "simulated_applied"
            executed = True

    action = OptimizationAction.objects.create(
        decision=impact["decision"],
        status=status,
        current_instance=impact["current_instance"],
        target_instance=impact["target_instance"],
        reason=impact["reason"],
        cost_savings_usd=float(impact["cost_savings_usd"]),
        co2e_reduction_kg=float(impact["co2e_reduction_kg"]),
        meta={
            "avg_cpu": averages["avg_cpu"],
            "avg_memory": averages["avg_memory"],
            "thresholds": thresholds,
            "policy_mode": policy.mode,
            "optimization_enabled": policy.optimization_enabled,
        },
    )
    llm_summary = _optimizer_llm_summary(impact=impact, policy=policy)
    return {
        "metrics": sampled,
        "averages": averages,
        "impact": impact,
        "policy": _policy_json(policy),
        "action": _action_json(action),
        "executed": executed,
        "llm_summary": llm_summary,
    }


def run_forecast_agent(current_instance: str = "n2-standard-4", hours: int = 720) -> dict[str, Any]:
    policy = get_policy()
    history = metrics_history(limit=120)
    averages = average_utilization(history)
    thresholds = _thresholds_for_mode(policy.mode)
    impact = auto_impact_from_averages(
        avg_cpu=averages["avg_cpu"],
        avg_memory=averages["avg_memory"],
        current_instance=current_instance,
        current_region="us-central1",
        target_region="us-central1",
        hours=float(hours),
        threshold_cpu_down=thresholds["cpu_down"],
        threshold_memory_down=thresholds["memory_down"],
        threshold_cpu_up=thresholds["cpu_up"],
        threshold_memory_up=thresholds["memory_up"],
    )
    days = list(range(1, 31))
    current_monthly = float(impact.get("current_cost_usd", 0))
    target_monthly = float(impact.get("target_cost_usd", 0))
    current_co2_monthly = float(impact.get("current_co2e_kg", 0))
    target_co2_monthly = float(impact.get("target_co2e_kg", 0))
    graph = {
        "days": days,
        "cost_without": [round((current_monthly / 30.0) * d, 2) for d in days],
        "cost_with": [round((target_monthly / 30.0) * d, 2) for d in days],
        "co2_without": [round((current_co2_monthly / 30.0) * d, 2) for d in days],
        "co2_with": [round((target_co2_monthly / 30.0) * d, 2) for d in days],
    }
    payload = {
        "averages": averages,
        "impact": impact,
        "graph": graph,
        "policy": _policy_json(policy),
        "data_source": "live",
    }
    fallback = _latest_non_zero_forecast_payload()
    current_cost_delta = float(impact.get("cost_savings_usd", 0.0))
    current_co2_delta = float(impact.get("co2e_reduction_kg", 0.0))
    if fallback and (current_cost_delta == 0.0 and current_co2_delta == 0.0):
        payload["impact"] = fallback.get("impact", payload["impact"])
        payload["graph"] = fallback.get("graph", payload["graph"])
        payload["data_source"] = "fallback_previous"
        payload["fallback_from"] = fallback.get("created_at")
    elif current_cost_delta == 0.0 and current_co2_delta == 0.0:
        synthetic_impact = demo_non_zero_impact(
            current_instance=current_instance,
            current_region="us-central1",
            target_region="us-central1",
            hours=float(hours),
        )
        synthetic_current_monthly = float(synthetic_impact.get("current_cost_usd", 0))
        synthetic_target_monthly = float(synthetic_impact.get("target_cost_usd", 0))
        synthetic_current_co2 = float(synthetic_impact.get("current_co2e_kg", 0))
        synthetic_target_co2 = float(synthetic_impact.get("target_co2e_kg", 0))
        payload["impact"] = synthetic_impact
        payload["graph"] = {
            "days": days,
            "cost_without": [round((synthetic_current_monthly / 30.0) * d, 2) for d in days],
            "cost_with": [round((synthetic_target_monthly / 30.0) * d, 2) for d in days],
            "co2_without": [round((synthetic_current_co2 / 30.0) * d, 2) for d in days],
            "co2_with": [round((synthetic_target_co2 / 30.0) * d, 2) for d in days],
        }
        payload["data_source"] = "synthetic_demo"

    ForecastSnapshot.objects.create(
        current_instance=impact["current_instance"],
        target_instance=impact["target_instance"],
        hours=hours,
        payload=payload,
    )
    payload["llm_summary"] = _forecast_llm_summary(payload)
    return payload


def _optimizer_llm_summary(impact: dict[str, Any], policy: OptimizationPolicy) -> str | None:
    key = get_agent_api_key("optimizer")
    if not key:
        return None
    prompt = (
        f"Mode: {policy.mode}. Decision: {impact['decision']}. "
        f"Current: {impact['current_instance']} Target: {impact['target_instance']}. "
        f"Savings: ${impact['cost_savings_usd']} CO2: {impact['co2e_reduction_kg']} kg. "
        f"Reason: {impact['reason']}. Provide a one-line optimizer rationale."
    )
    return _call_groq(key=key, prompt=prompt, model="llama-3.1-8b-instant")


def _forecast_llm_summary(payload: dict[str, Any]) -> str | None:
    key = get_agent_api_key("forecast")
    if not key:
        return None
    impact = payload["impact"]
    prompt = (
        f"Forecast summary for 30-day graph. Decision {impact['decision']}, "
        f"monthly savings ${impact['cost_savings_usd']}, CO2 reduction {impact['co2e_reduction_kg']} kg. "
        "Write 2 short sentences for dashboard users."
    )
    return _call_groq(key=key, prompt=prompt, model="llama-3.1-8b-instant")


def _call_groq(key: str, prompt: str, model: str) -> str | None:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a concise cloud optimization assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    req = request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "GreenOpsDjango/optimizer-forecast",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except (error.HTTPError, error.URLError, KeyError, TimeoutError, json.JSONDecodeError):
        return None


def _thresholds_for_mode(mode: str) -> dict[str, float]:
    mapping = {
        "low": {"cpu_down": 25.0, "memory_down": 30.0, "cpu_up": 85.0, "memory_up": 90.0},
        "balanced": {"cpu_down": 35.0, "memory_down": 40.0, "cpu_up": 75.0, "memory_up": 80.0},
        "high": {"cpu_down": 45.0, "memory_down": 50.0, "cpu_up": 65.0, "memory_up": 70.0},
    }
    return mapping.get(mode, mapping["balanced"])


def _latest_non_zero_forecast_payload() -> dict[str, Any] | None:
    rows = ForecastSnapshot.objects.all()[:50]
    for row in rows:
        payload = row.payload or {}
        impact = payload.get("impact", {})
        if float(impact.get("cost_savings_usd", 0.0)) != 0.0 or float(impact.get("co2e_reduction_kg", 0.0)) != 0.0:
            payload = dict(payload)
            payload["created_at"] = row.created_at.isoformat()
            return payload
    return None


def _policy_json(policy: OptimizationPolicy) -> dict[str, Any]:
    return {
        "mode": "eco" if policy.mode == "low" else policy.mode,
        "optimization_enabled": policy.optimization_enabled,
        "sample_interval_seconds": policy.sample_interval_seconds,
        "cooldown_seconds": policy.cooldown_seconds,
        "updated_at": policy.updated_at.isoformat(),
    }


def _action_json(action: OptimizationAction) -> dict[str, Any]:
    return {
        "decision": action.decision,
        "status": action.status,
        "current_instance": action.current_instance,
        "target_instance": action.target_instance,
        "reason": action.reason,
        "cost_savings_usd": action.cost_savings_usd,
        "co2e_reduction_kg": action.co2e_reduction_kg,
        "meta": action.meta,
        "created_at": action.created_at.isoformat(),
    }
