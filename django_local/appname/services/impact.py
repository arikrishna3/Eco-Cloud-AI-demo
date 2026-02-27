from __future__ import annotations

import math
from typing import Dict, Iterable

INSTANCE_CATALOG = {
    "e2-micro": {"vcpus": 2, "memory_gb": 1.0, "usd_per_hour": 0.008, "co2e_kg_per_hour": 0.015},
    "e2-small": {"vcpus": 2, "memory_gb": 2.0, "usd_per_hour": 0.017, "co2e_kg_per_hour": 0.024},
    "e2-medium": {"vcpus": 2, "memory_gb": 4.0, "usd_per_hour": 0.033, "co2e_kg_per_hour": 0.040},
    "e2-standard-2": {"vcpus": 2, "memory_gb": 8.0, "usd_per_hour": 0.067, "co2e_kg_per_hour": 0.067},
    "n2-standard-2": {"vcpus": 2, "memory_gb": 8.0, "usd_per_hour": 0.097, "co2e_kg_per_hour": 0.088},
    "n2-standard-4": {"vcpus": 4, "memory_gb": 16.0, "usd_per_hour": 0.194, "co2e_kg_per_hour": 0.176},
    "n2-standard-8": {"vcpus": 8, "memory_gb": 32.0, "usd_per_hour": 0.388, "co2e_kg_per_hour": 0.352},
}

CPU_HEADROOM = 1.25
MEMORY_HEADROOM = 1.20

REGION_MULTIPLIER = {
    "us-central1": 1.00,
    "us-east1": 1.03,
    "us-west1": 0.98,
    "asia-south1": 1.08,
    "europe-west1": 1.01,
}


def _profile(instance_type: str, region: str) -> Dict[str, float]:
    base = INSTANCE_CATALOG.get(instance_type, INSTANCE_CATALOG["n2-standard-2"])
    multiplier = REGION_MULTIPLIER.get(region, 1.00)
    return {
        "vcpus": base["vcpus"],
        "memory_gb": base["memory_gb"],
        "usd_per_hour": base["usd_per_hour"] * multiplier,
        "co2e_kg_per_hour": base["co2e_kg_per_hour"] * multiplier,
    }


def calculate_impact(
    current_instance: str,
    target_instance: str,
    current_region: str = "us-central1",
    target_region: str = "us-central1",
    hours: float = 24 * 30,
) -> Dict[str, float]:
    current = _profile(current_instance, current_region)
    target = _profile(target_instance, target_region)

    current_cost = current["usd_per_hour"] * hours
    target_cost = target["usd_per_hour"] * hours
    current_co2e = current["co2e_kg_per_hour"] * hours
    target_co2e = target["co2e_kg_per_hour"] * hours

    return {
        "hours": float(hours),
        "current_cost_usd": round(current_cost, 2),
        "target_cost_usd": round(target_cost, 2),
        "cost_savings_usd": round(current_cost - target_cost, 2),
        "current_co2e_kg": round(current_co2e, 2),
        "target_co2e_kg": round(target_co2e, 2),
        "co2e_reduction_kg": round(current_co2e - target_co2e, 2),
    }


def auto_impact_from_metrics(metrics: Dict[str, float], hours: float = 24 * 30) -> Dict[str, float | str]:
    return auto_impact_from_averages(
        avg_cpu=float(metrics.get("cpu_percent", 0)),
        avg_memory=float(metrics.get("memory_percent", 0)),
        hours=hours,
    )


def demo_non_zero_impact(
    current_instance: str = "n2-standard-4",
    current_region: str = "us-central1",
    target_region: str = "us-central1",
    hours: float = 24 * 30,
) -> Dict[str, float | str]:
    current = _profile(current_instance, current_region)
    cheaper = [
        (name, spec)
        for name, spec in INSTANCE_CATALOG.items()
        if spec["usd_per_hour"] < INSTANCE_CATALOG.get(current_instance, INSTANCE_CATALOG["n2-standard-4"])["usd_per_hour"]
    ]
    cheaper.sort(key=lambda item: item[1]["usd_per_hour"])
    target_instance = cheaper[0][0] if cheaper else "e2-standard-2"

    impact = calculate_impact(
        current_instance=current_instance,
        target_instance=target_instance,
        current_region=current_region,
        target_region=target_region,
        hours=hours,
    )
    current_cost = float(impact["current_cost_usd"])
    current_co2 = float(impact["current_co2e_kg"])

    if float(impact["cost_savings_usd"]) <= 0:
        target_cost = round(current_cost * 0.88, 2)
        impact["target_cost_usd"] = target_cost
        impact["cost_savings_usd"] = round(current_cost - target_cost, 2)
    if float(impact["co2e_reduction_kg"]) <= 0:
        target_co2 = round(current_co2 * 0.86, 2)
        impact["target_co2e_kg"] = target_co2
        impact["co2e_reduction_kg"] = round(current_co2 - target_co2, 2)

    current_specs = _profile(current_instance, current_region)
    target_specs = _profile(target_instance, target_region)
    impact["current_instance"] = current_instance
    impact["target_instance"] = target_instance
    impact["decision"] = "demo_projection"
    impact["reason"] = "Hackathon demo projection based on nearest lower-cost cloud shape."
    impact["avg_cpu_percent"] = 52.0
    impact["avg_memory_percent"] = 68.0
    impact["required_vcpus"] = max(1, min(int(current_specs["vcpus"]), int(target_specs["vcpus"]) + 1))
    impact["required_memory_gb"] = max(1, min(int(current_specs["memory_gb"]), int(target_specs["memory_gb"]) + 2))
    impact["current_vcpus"] = current_specs["vcpus"]
    impact["current_memory_gb"] = current_specs["memory_gb"]
    impact["target_vcpus"] = target_specs["vcpus"]
    impact["target_memory_gb"] = target_specs["memory_gb"]
    impact["is_demo_projection"] = True
    return impact


def average_utilization(history: Iterable[dict]) -> Dict[str, float]:
    points = list(history)
    if not points:
        return {"avg_cpu": 0.0, "avg_memory": 0.0, "samples": 0}
    avg_cpu = sum(float(p.get("cpu_percent", 0.0)) for p in points) / len(points)
    avg_memory = sum(float(p.get("memory_percent", 0.0)) for p in points) / len(points)
    return {"avg_cpu": round(avg_cpu, 2), "avg_memory": round(avg_memory, 2), "samples": len(points)}


def auto_impact_from_averages(
    avg_cpu: float,
    avg_memory: float,
    current_instance: str = "n2-standard-4",
    current_region: str = "us-central1",
    target_region: str = "us-central1",
    hours: float = 24 * 30,
    threshold_cpu_down: float = 35.0,
    threshold_memory_down: float = 40.0,
    threshold_cpu_up: float = 75.0,
    threshold_memory_up: float = 80.0,
) -> Dict[str, float | str]:
    direction = "keep"
    reason = "Utilization is balanced."
    if avg_cpu < threshold_cpu_down and avg_memory < threshold_memory_down:
        direction = "scale_down"
        reason = (
            f"Over-provisioned: avg CPU {avg_cpu:.1f}% < {threshold_cpu_down:.1f}% and "
            f"avg memory {avg_memory:.1f}% < {threshold_memory_down:.1f}%."
        )
    elif avg_cpu > threshold_cpu_up or avg_memory > threshold_memory_up:
        direction = "scale_up"
        reason = (
            f"Under-provisioned: avg CPU {avg_cpu:.1f}% > {threshold_cpu_up:.1f}% or "
            f"avg memory {avg_memory:.1f}% > {threshold_memory_up:.1f}%."
        )

    current_specs = _profile(current_instance, current_region)
    used_vcpus = max(1.0, current_specs["vcpus"] * (avg_cpu / 100.0))
    used_memory = max(0.5, current_specs["memory_gb"] * (avg_memory / 100.0))
    required_vcpus = math.ceil(used_vcpus * CPU_HEADROOM)
    required_memory = math.ceil(used_memory * MEMORY_HEADROOM)
    target_instance = _pick_target_instance(
        current_instance=current_instance,
        required_vcpus=required_vcpus,
        required_memory_gb=required_memory,
        direction=direction,
    )

    impact = calculate_impact(
        current_instance=current_instance,
        target_instance=target_instance,
        current_region=current_region,
        target_region=target_region,
        hours=hours,
    )
    target_specs = _profile(target_instance, target_region)
    impact["current_instance"] = current_instance
    impact["target_instance"] = target_instance
    impact["decision"] = direction
    impact["reason"] = reason
    impact["avg_cpu_percent"] = round(avg_cpu, 2)
    impact["avg_memory_percent"] = round(avg_memory, 2)
    impact["threshold_cpu_down"] = float(threshold_cpu_down)
    impact["threshold_memory_down"] = float(threshold_memory_down)
    impact["threshold_cpu_up"] = float(threshold_cpu_up)
    impact["threshold_memory_up"] = float(threshold_memory_up)
    impact["required_vcpus"] = required_vcpus
    impact["required_memory_gb"] = required_memory
    impact["current_vcpus"] = current_specs["vcpus"]
    impact["current_memory_gb"] = current_specs["memory_gb"]
    impact["target_vcpus"] = target_specs["vcpus"]
    impact["target_memory_gb"] = target_specs["memory_gb"]
    return impact


def _pick_target_instance(
    current_instance: str,
    required_vcpus: int,
    required_memory_gb: int,
    direction: str,
) -> str:
    current = INSTANCE_CATALOG.get(current_instance, INSTANCE_CATALOG["n2-standard-4"])
    candidates = []
    for name, spec in INSTANCE_CATALOG.items():
        if spec["vcpus"] >= required_vcpus and spec["memory_gb"] >= required_memory_gb:
            candidates.append((name, spec))
    if not candidates:
        return current_instance

    candidates.sort(key=lambda item: (item[1]["usd_per_hour"], item[1]["vcpus"], item[1]["memory_gb"]))
    if direction == "scale_down":
        for name, spec in candidates:
            if spec["vcpus"] < current["vcpus"] or spec["memory_gb"] < current["memory_gb"]:
                return name
    if direction == "scale_up":
        for name, spec in candidates:
            if spec["vcpus"] > current["vcpus"] or spec["memory_gb"] > current["memory_gb"]:
                return name
        return current_instance
    return current_instance
