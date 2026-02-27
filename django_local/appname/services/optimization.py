from __future__ import annotations

from typing import Any, Dict, List


def build_recommendations(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    cpu = metrics["cpu_percent"]
    memory = metrics["memory_percent"]
    disk = metrics["disk_percent"]
    recs: List[Dict[str, Any]] = []

    if cpu < 25 and memory < 40:
        recs.append(
            {
                "title": "Downsize underutilized compute",
                "priority": "high",
                "estimated_monthly_cost_savings_usd": 180,
                "estimated_monthly_co2e_reduction_kg": 32,
                "reason": f"Low sustained load: CPU {cpu:.1f}% / Memory {memory:.1f}%.",
            }
        )
    if cpu > 85:
        recs.append(
            {
                "title": "Scale out to avoid saturation",
                "priority": "high",
                "estimated_monthly_cost_savings_usd": 0,
                "estimated_monthly_co2e_reduction_kg": 0,
                "reason": f"CPU saturation risk at {cpu:.1f}%. Avoid latency/SLA incidents.",
            }
        )
    if memory > 85:
        recs.append(
            {
                "title": "Increase memory class or optimize memory footprint",
                "priority": "medium",
                "estimated_monthly_cost_savings_usd": 45,
                "estimated_monthly_co2e_reduction_kg": 8,
                "reason": f"Memory pressure is {memory:.1f}%.",
            }
        )
    if disk > 80:
        recs.append(
            {
                "title": "Archive cold data and shrink active volume",
                "priority": "medium",
                "estimated_monthly_cost_savings_usd": 35,
                "estimated_monthly_co2e_reduction_kg": 6,
                "reason": f"Disk utilization is {disk:.1f}%.",
            }
        )

    if not recs:
        recs.append(
            {
                "title": "No urgent optimization required",
                "priority": "low",
                "estimated_monthly_cost_savings_usd": 20,
                "estimated_monthly_co2e_reduction_kg": 3,
                "reason": "Utilization is balanced. Continue periodic monitoring.",
            }
        )
    return recs
