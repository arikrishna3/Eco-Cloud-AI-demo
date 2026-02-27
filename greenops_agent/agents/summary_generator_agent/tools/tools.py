"""
summary_agent_tools.py
────────────────────────────────────────────────────────────────────────────
Tools used exclusively by summary_generator_agent.

Key change vs original:
  • get_weekly_data() now calls Cloud Monitoring for real per-instance
    utilisation instead of returning synthetic/hardcoded data.
  • get_forecast_information() queries all BQ ML models (cpu, mem, carbon)
    for a 7-day horizon across all instances.
  • create_google_doc() is unchanged.
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

from greenops_agent.agents.forecaster_agent.agent import execute_forecast_query

# ── GCP monitoring (real utilisation) ────────────────────────────────────────
try:
    from greenops_agent.gcloud_monitoring import get_all_instances_utilization, list_running_instances
    _HAS_GCP_MONITORING = True
except ImportError:
    _HAS_GCP_MONITORING = False

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "greenops-460813")


# ─────────────────────────────────────────────────────────────────────────────
# get_weekly_data  (was a stub — now real Cloud Monitoring data)
# ─────────────────────────────────────────────────────────────────────────────

def get_weekly_data() -> dict:
    """
    Returns a structured summary of the past 7 days:
    - All running instances grouped by region
    - Per-instance 7-day average CPU and memory utilisation (Cloud Monitoring)
    - Underutilised instance counts per region (cpu < 20% threshold)

    Shape:
    {
      "week_start": "YYYY-MM-DD",
      "week_end":   "YYYY-MM-DD",
      "regions": ["us-central1", …],
      "instances": [
        {
          "name", "zone", "region", "machine_type",
          "avg_cpu_percent", "avg_memory_percent",
          "is_underutilized"
        }, …
      ],
      "region_summary": {
        "us-central1": {
          "total": int,
          "underutilized": int,
          "avg_cpu": float,
          "avg_memory": float
        }, …
      },
      "total_instances": int,
      "total_underutilized": int,
      "source": "gcp_monitoring" | "compute_only"
    }
    """
    now        = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week_end   = now.strftime("%Y-%m-%d")

    if _HAS_GCP_MONITORING:
        try:
            rows   = get_all_instances_utilization(hours=168)   # 7 days
            source = "gcp_monitoring"
        except Exception:
            rows   = _compute_only_instances()
            source = "compute_only"
    else:
        rows   = _compute_only_instances()
        source = "compute_only"

    CPU_UNDERUTIL_THRESHOLD = 20.0   # %

    # Derive region from zone  (e.g. us-central1-a → us-central1)
    for r in rows:
        zone = r.get("zone", "")
        r["region"] = "-".join(zone.split("-")[:-1]) if zone else "unknown"
        r["is_underutilized"] = r.get("avg_cpu_percent", 100) < CPU_UNDERUTIL_THRESHOLD

    regions = sorted({r["region"] for r in rows})

    region_summary: dict[str, dict] = {}
    for region in regions:
        subset = [r for r in rows if r["region"] == region]
        cpu_vals = [r["avg_cpu_percent"]    for r in subset if r.get("avg_cpu_percent") is not None]
        mem_vals = [r["avg_memory_percent"] for r in subset if r.get("avg_memory_percent") is not None]
        region_summary[region] = {
            "total":         len(subset),
            "underutilized": sum(1 for r in subset if r["is_underutilized"]),
            "avg_cpu":       round(sum(cpu_vals) / len(cpu_vals), 2) if cpu_vals else 0.0,
            "avg_memory":    round(sum(mem_vals) / len(mem_vals), 2) if mem_vals else 0.0,
        }

    return {
        "week_start":          week_start,
        "week_end":            week_end,
        "regions":             regions,
        "instances":           rows,
        "region_summary":      region_summary,
        "total_instances":     len(rows),
        "total_underutilized": sum(1 for r in rows if r["is_underutilized"]),
        "source":              source,
    }


def _compute_only_instances() -> list[dict]:
    """Fallback: return instance list with zero utilisation stats."""
    try:
        from greenops_agent.gcloud_monitoring import list_running_instances
        return [
            {**i, "avg_cpu_percent": 0.0, "avg_memory_percent": 0.0, "samples": 0}
            for i in list_running_instances()
        ]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# get_forecast_information  (summary variant — all instances, 7 days)
# ─────────────────────────────────────────────────────────────────────────────

def get_forecast_information() -> dict:
    """
    Returns 7-day BQ ML forecasts for CPU, Memory, and Carbon across ALL
    instances (no WHERE filter).  Used by the summary agent to build the
    Overall Carbon Forecast section.
    """
    def _run(model_suffix: str) -> dict:
        sql = f"""
            SELECT Instance_ID, forecast_timestamp, forecast_value
            FROM ML.FORECAST(
                MODEL `{PROJECT_ID}.gcp_server_details.server_{model_suffix}_forecast_model`,
                STRUCT(7 AS horizon, 0.8 AS confidence_level)
            )
        """
        return execute_forecast_query(sql)

    cpu_result    = _run("cpu")
    mem_result    = _run("mem")
    carbon_result = _run("carbon")

    return {
        "cpu_forecast":    cpu_result.get("rows", []),
        "memory_forecast": mem_result.get("rows", []),
        "carbon_forecast": carbon_result.get("rows", []),
        "row_counts": {
            "cpu":    cpu_result.get("row_count", 0),
            "memory": mem_result.get("row_count", 0),
            "carbon": carbon_result.get("row_count", 0),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# create_google_doc  (unchanged from original)
# ─────────────────────────────────────────────────────────────────────────────

def create_google_doc(title: str, body_content: str) -> dict:
    """
    Creates a Google Doc with the given markdown content and returns a
    shareable link.
    """
    SCOPES = [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
    ]

    sa_raw = os.environ.get("SERVICE_ACCOUNT_KEY", "")
    if not sa_raw:
        from greenops_agent.secrets_access_manager import access_secret
        sa_raw = access_secret(secret_id="SERVICE_ACCOUNT_KEY")

    creds = service_account.Credentials.from_service_account_info(
        json.loads(sa_raw), scopes=SCOPES
    )

    docs_service  = build("docs",  "v1", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)

    # Create empty doc
    doc = docs_service.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    # Insert content
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": 1},
                        "text":     body_content,
                    }
                }
            ]
        },
    ).execute()

    # Make it readable by anyone with the link
    drive_service.permissions().create(
        fileId=doc_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    link = f"https://docs.google.com/document/d/{doc_id}/edit"
    return {"doc_id": doc_id, "link": link, "title": title}
