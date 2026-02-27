"""
gcloud_monitoring.py
─────────────────────────────────────────────────────────────────────────────
Replaces every local-psutil call in the original app.py / Django backend with
real Google Cloud Monitoring (formerly Stackdriver) API calls.

Drop this file next to your Django views and import from it.
All functions return plain dicts so they slot in identically where
psutil-backed endpoints used to.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional

from google.cloud import monitoring_v3
from google.api_core.exceptions import GoogleAPIError

# ── Project config ────────────────────────────────────────────────────────────
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "greenops-460813")
PROJECT_NAME = f"projects/{PROJECT_ID}"

# ── In-memory rolling history (replaces the psutil deque in Django views) ────
_HISTORY_MAX = 120           # keep last 120 samples ≈ 20 min at 10-sec refresh
_metric_history: deque = deque(maxlen=_HISTORY_MAX)

# ── Monitoring client (lazy singleton) ───────────────────────────────────────
_client: Optional[monitoring_v3.MetricServiceClient] = None


def _get_client() -> monitoring_v3.MetricServiceClient:
    global _client
    if _client is None:
        _client = monitoring_v3.MetricServiceClient()
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# Low-level helper
# ─────────────────────────────────────────────────────────────────────────────

def _query_metric(
    metric_type: str,
    instance_id: Optional[str] = None,
    zone: Optional[str] = None,
    minutes_back: int = 5,
    aligner: monitoring_v3.Aggregation.Aligner = monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
    reducer: monitoring_v3.Aggregation.Reducer = monitoring_v3.Aggregation.Reducer.REDUCE_MEAN,
    group_by_fields: Optional[list[str]] = None,
    alignment_period_seconds: int = 60,
) -> list[dict]:
    """
    Query a single Cloud Monitoring metric and return a list of
    { "instance_id": str, "value": float, "timestamp": str } dicts.
    """
    client = _get_client()

    now = time.time()
    interval = monitoring_v3.TimeInterval(
        {
            "end_time": {"seconds": int(now)},
            "start_time": {"seconds": int(now) - minutes_back * 60},
        }
    )

    aggregation = monitoring_v3.Aggregation(
        {
            "alignment_period": {"seconds": alignment_period_seconds},
            "per_series_aligner": aligner,
            "cross_series_reducer": reducer,
            "group_by_fields": group_by_fields or ["resource.labels.instance_id"],
        }
    )

    filters = [f'metric.type="{metric_type}"']
    if instance_id:
        filters.append(f'resource.labels.instance_id="{instance_id}"')
    if zone:
        filters.append(f'resource.labels.zone="{zone}"')

    request = monitoring_v3.ListTimeSeriesRequest(
        name=PROJECT_NAME,
        filter=" AND ".join(filters),
        interval=interval,
        view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        aggregation=aggregation,
    )

    results = []
    try:
        for ts in client.list_time_series(request=request):
            inst = ts.resource.labels.get("instance_id", "unknown")
            for point in ts.points:
                val = (
                    point.value.double_value
                    or point.value.int64_value
                    or point.value.distribution_value.mean
                )
                ts_str = point.interval.end_time.isoformat()
                results.append({"instance_id": inst, "value": val, "timestamp": ts_str})
    except GoogleAPIError as e:
        results.append({"error": str(e)})

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Public API – mirrors exactly what the old psutil Django endpoints returned
# ─────────────────────────────────────────────────────────────────────────────

def get_current_metrics(instance_id: Optional[str] = None, zone: Optional[str] = None) -> dict:
    """
    Replacement for /metrics/current  (was: psutil.cpu_percent, virtual_memory …)

    Returns:
        {
          "metrics": {
            "cpu_percent":    float,   # 0-100
            "memory_percent": float,   # 0-100
            "disk_percent":   float,   # 0-100  (from disk I/O ratio, best-effort)
            "bytes_sent":     int,
            "bytes_recv":     int,
          },
          "source": "gcp_monitoring",
          "instance_id": str,
          "timestamp": str,
        }
    """
    cpu_series = _query_metric(
        "compute.googleapis.com/instance/cpu/utilization",
        instance_id=instance_id,
        zone=zone,
        minutes_back=3,
    )
    mem_series = _query_metric(
        "agent.googleapis.com/memory/percent_used",
        instance_id=instance_id,
        zone=zone,
        minutes_back=3,
    )
    # Disk I/O bytes – closest proxy for "disk busy" without OS agent disk %
    disk_read_series = _query_metric(
        "compute.googleapis.com/instance/disk/read_bytes_count",
        instance_id=instance_id,
        zone=zone,
        minutes_back=3,
        aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
    )
    disk_write_series = _query_metric(
        "compute.googleapis.com/instance/disk/write_bytes_count",
        instance_id=instance_id,
        zone=zone,
        minutes_back=3,
        aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
    )
    net_sent_series = _query_metric(
        "compute.googleapis.com/instance/network/sent_bytes_count",
        instance_id=instance_id,
        zone=zone,
        minutes_back=3,
        aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
    )
    net_recv_series = _query_metric(
        "compute.googleapis.com/instance/network/received_bytes_count",
        instance_id=instance_id,
        zone=zone,
        minutes_back=3,
        aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
    )

    def _latest(series: list[dict]) -> float:
        """Pick the most-recent non-error point."""
        valid = [p for p in series if "value" in p]
        if not valid:
            return 0.0
        return valid[-1]["value"]

    cpu_pct   = round(_latest(cpu_series) * 100, 2)   # utilization is 0-1
    mem_pct   = round(_latest(mem_series), 2)          # already 0-100
    disk_read  = round(_latest(disk_read_series), 0)
    disk_write = round(_latest(disk_write_series), 0)
    net_sent  = round(_latest(net_sent_series), 0)
    net_recv  = round(_latest(net_recv_series), 0)

    # Proxy disk_percent: read+write throughput normalised to 100 MB/s ceiling
    disk_pct = min(round((disk_read + disk_write) / (100 * 1024 * 1024) * 100, 2), 100.0)

    snapshot = {
        "cpu_percent":    cpu_pct,
        "memory_percent": mem_pct,
        "disk_percent":   disk_pct,
        "bytes_sent":     int(net_sent),
        "bytes_recv":     int(net_recv),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }
    _metric_history.append(snapshot)

    return {
        "metrics":     snapshot,
        "source":      "gcp_monitoring",
        "instance_id": instance_id or "all",
        "timestamp":   snapshot["timestamp"],
    }


def get_metric_history(limit: int = 30) -> dict:
    """
    Replacement for /metrics/history  (was: in-memory psutil deque)

    Returns the rolling window of snapshots collected by get_current_metrics().
    If history is empty (cold start), back-fills from Cloud Monitoring.
    """
    if not _metric_history:
        _backfill_history()

    items = list(_metric_history)[-limit:]
    return {"history": items, "count": len(items), "source": "gcp_monitoring"}


def _backfill_history(minutes: int = 30) -> None:
    """Pull the last `minutes` of data from Cloud Monitoring into the local cache."""
    cpu_series = _query_metric(
        "compute.googleapis.com/instance/cpu/utilization",
        minutes_back=minutes,
        alignment_period_seconds=60,
        reducer=monitoring_v3.Aggregation.Reducer.REDUCE_MEAN,
    )
    mem_series = _query_metric(
        "agent.googleapis.com/memory/percent_used",
        minutes_back=minutes,
        alignment_period_seconds=60,
        reducer=monitoring_v3.Aggregation.Reducer.REDUCE_MEAN,
    )

    # Zip by timestamp (best-effort)
    cpu_by_ts = {p["timestamp"]: p["value"] for p in cpu_series if "value" in p}
    mem_by_ts = {p["timestamp"]: p["value"] for p in mem_series if "value" in p}

    all_ts = sorted(set(cpu_by_ts) | set(mem_by_ts))
    for ts in all_ts:
        cpu_val = round(cpu_by_ts.get(ts, 0.0) * 100, 2)
        mem_val = round(mem_by_ts.get(ts, 0.0), 2)
        _metric_history.append(
            {
                "cpu_percent":    cpu_val,
                "memory_percent": mem_val,
                "disk_percent":   0.0,
                "bytes_sent":     0,
                "bytes_recv":     0,
                "timestamp":      ts,
            }
        )


# ─────────────────────────────────────────────────────────────────────────────
# Instance inventory helpers (used by recommender + impact calculator)
# ─────────────────────────────────────────────────────────────────────────────

def list_running_instances() -> list[dict]:
    """
    Returns a list of all running GCE instances in the project:
        [{ "instance_id", "name", "zone", "machine_type", "status" }, …]

    Uses the Compute Engine aggregated list API (not Monitoring) so no
    VM agent is required.
    """
    from google.cloud import compute_v1  # lazy import – not needed by all callers

    client = compute_v1.InstancesClient()
    results = []
    for _zone, response in client.aggregated_list(
        request=compute_v1.AggregatedListInstancesRequest(project=PROJECT_ID)
    ):
        for inst in response.instances or []:
            if inst.status == "RUNNING":
                zone_name = inst.zone.split("/")[-1]
                mt = inst.machine_type.split("/")[-1]
                results.append(
                    {
                        "instance_id":   inst.name,
                        "name":          inst.name,
                        "zone":          zone_name,
                        "machine_type":  mt,
                        "status":        inst.status,
                    }
                )
    return results


def get_instance_utilization_summary(
    instance_id: str,
    zone: Optional[str] = None,
    hours: int = 1,
) -> dict:
    """
    Return average CPU + memory for a specific instance over the last `hours` hours.
    Matches the shape that the old /impact/auto endpoint produced.
    """
    minutes = hours * 60
    cpu_series = _query_metric(
        "compute.googleapis.com/instance/cpu/utilization",
        instance_id=instance_id,
        zone=zone,
        minutes_back=minutes,
        alignment_period_seconds=300,
    )
    mem_series = _query_metric(
        "agent.googleapis.com/memory/percent_used",
        instance_id=instance_id,
        zone=zone,
        minutes_back=minutes,
        alignment_period_seconds=300,
    )

    cpu_vals = [p["value"] * 100 for p in cpu_series if "value" in p]
    mem_vals = [p["value"] for p in mem_series if "value" in p]

    avg_cpu = round(sum(cpu_vals) / len(cpu_vals), 2) if cpu_vals else 0.0
    avg_mem = round(sum(mem_vals) / len(mem_vals), 2) if mem_vals else 0.0

    return {
        "instance_id":  instance_id,
        "avg_cpu_percent":    avg_cpu,
        "avg_memory_percent": avg_mem,
        "samples":      len(cpu_vals),
        "hours":        hours,
    }


def get_all_instances_utilization(hours: int = 1) -> list[dict]:
    """
    Fetch utilization summary for ALL running instances in the project.
    Used by the Weekly Summary Agent's get_weekly_data tool.
    """
    instances = list_running_instances()
    summaries = []
    for inst in instances:
        util = get_instance_utilization_summary(
            instance_id=inst["instance_id"],
            zone=inst["zone"],
            hours=hours,
        )
        summaries.append({**inst, **util})
    return summaries
