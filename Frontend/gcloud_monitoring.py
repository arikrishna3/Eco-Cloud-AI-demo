"""
gcloud_monitoring.py  (fixed)
Key fixes:
  1. Wider time windows (10 min) for ingestion lag
  2. No instance filter in query — get all data, works reliably
  3. CPU 0-1 → 0-100 conversion fixed
  4. debug_query() to test from terminal
"""

from __future__ import annotations
import os
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from google.cloud import monitoring_v3
from google.api_core.exceptions import GoogleAPIError

PROJECT_ID   = os.environ.get("GOOGLE_CLOUD_PROJECT", "eco-cloudai")
PROJECT_NAME = f"projects/{PROJECT_ID}"

_HISTORY_MAX = 120
_metric_history: deque = deque(maxlen=_HISTORY_MAX)
_client: Optional[monitoring_v3.MetricServiceClient] = None


def _get_client() -> monitoring_v3.MetricServiceClient:
    global _client
    if _client is None:
        _client = monitoring_v3.MetricServiceClient()
    return _client


def _query_metric(
    metric_type: str,
    instance_id: Optional[str] = None,
    zone: Optional[str] = None,
    minutes_back: int = 10,
    aligner=monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
    reducer=monitoring_v3.Aggregation.Reducer.REDUCE_NONE,
    alignment_period_seconds: int = 60,
    extra_filter: str = "",
) -> list[dict]:
    now = time.time()
    interval = monitoring_v3.TimeInterval({
        "end_time":   {"seconds": int(now)},
        "start_time": {"seconds": int(now) - minutes_back * 60},
    })
    aggregation = monitoring_v3.Aggregation(
        {
            "alignment_period": {"seconds": alignment_period_seconds},
            "per_series_aligner": aligner,
        }
    )
    filter_str = (
        f'metric.type="{metric_type}" AND '
        'resource.type="gce_instance"'
    )
    if instance_id:
        filter_str += f' AND resource.labels.instance_id="{instance_id}"'
    if zone:
        filter_str += f' AND resource.labels.zone="{zone}"'
    if extra_filter:
        filter_str += f" AND {extra_filter}"

    request = monitoring_v3.ListTimeSeriesRequest(
        name=PROJECT_NAME,
        filter=filter_str,
        interval=interval,
        view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        aggregation=aggregation,
    )
    results = []
    try:
        for ts in _get_client().list_time_series(request=request):
            inst = ts.resource.labels.get("instance_id", "unknown")
            for point in ts.points:
                if point.value.double_value is not None:
                    val = point.value.double_value
                elif point.value.int64_value is not None:
                    val = float(point.value.int64_value)
                elif point.value.distribution_value is not None:
                    val = float(point.value.distribution_value.mean)
                else:
                    val = 0.0
                results.append({
                    "instance_id": inst,
                    "value":       val,
                    "timestamp":   point.interval.end_time.isoformat(),
                })
    except GoogleAPIError as e:
        results.append({"error": str(e)})
    return results


def debug_query():
    """
    Run from terminal to verify metrics are flowing:
        python -c "from gcloud_monitoring import debug_query; debug_query()"
    """
    print(f"\n{'='*60}")
    print(f"Project: {PROJECT_ID}")
    print(f"{'='*60}\n")
    tests = [
        ("CPU utilization", "compute.googleapis.com/instance/cpu/utilization"),
        ("Memory % (agent)", "agent.googleapis.com/memory/percent_used"),
        ("Disk read", "compute.googleapis.com/instance/disk/read_bytes_count"),
        ("Net sent", "compute.googleapis.com/instance/network/sent_bytes_count"),
    ]
    for label, metric in tests:
        results = _query_metric(metric, minutes_back=15)
        valid = [r for r in results if "value" in r]
        if valid:
            latest = valid[-1]
            print(f"FOUND {label}: {latest['value']:.6f}  instance={latest['instance_id']}")
        elif results and "error" in results[0]:
            print(f"ERROR {label}: {results[0]['error']}")
        else:
            print(f"EMPTY {label}: No data (metric not yet ingested)")
    print()
def get_current_metrics(instance_id: Optional[str] = None, zone: Optional[str] = None) -> dict:
    cpu_series = _query_metric(
        "compute.googleapis.com/instance/cpu/utilization",
        instance_id=instance_id,
        zone=zone,
        minutes_back=10,
    )
    mem_series = _query_metric(
        "agent.googleapis.com/memory/percent_used",
        instance_id=instance_id,
        zone=zone,
        minutes_back=10,
    )
    dr_series = _query_metric(
        "compute.googleapis.com/instance/disk/read_bytes_count",
        instance_id=instance_id,
        zone=zone,
        minutes_back=10,
        aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
    )
    dw_series = _query_metric(
        "compute.googleapis.com/instance/disk/write_bytes_count",
        instance_id=instance_id,
        zone=zone,
        minutes_back=10,
        aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
    )
    ns_series = _query_metric(
        "compute.googleapis.com/instance/network/sent_bytes_count",
        instance_id=instance_id,
        zone=zone,
        minutes_back=10,
        aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
    )
    nr_series = _query_metric(
        "compute.googleapis.com/instance/network/received_bytes_count",
        instance_id=instance_id,
        zone=zone,
        minutes_back=10,
        aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
    )

    def _latest(series):
        valid = [p for p in series if "value" in p and "error" not in p]
        return valid[-1]["value"] if valid else 0.0

    cpu_raw = _latest(cpu_series)
    cpu_pct = round(cpu_raw * 100 if cpu_raw <= 1.0 else cpu_raw, 2)
    mem_pct = round(_latest(mem_series), 2)
    disk_read  = _latest(dr_series)
    disk_write = _latest(dw_series)
    disk_pct   = min(round((disk_read + disk_write) / (50 * 1024 * 1024) * 100, 2), 100.0)

    snapshot = {
        "cpu_percent":    cpu_pct,
        "memory_percent": mem_pct,
        "disk_percent":   disk_pct,
        "bytes_sent":     int(_latest(ns_series)),
        "bytes_recv":     int(_latest(nr_series)),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    }
    _metric_history.append(snapshot)
    return {"metrics": snapshot, "source": "gcp_monitoring", "instance_id": instance_id or "all", "timestamp": snapshot["timestamp"]}


def get_metric_history(limit: int = 30) -> dict:
    if not _metric_history:
        _backfill_history()
    return {"history": list(_metric_history)[-limit:], "count": len(_metric_history), "source": "gcp_monitoring"}


def _backfill_history(minutes: int = 30) -> None:
    cpu_s = _query_metric(
        "compute.googleapis.com/instance/cpu/utilization",
        minutes_back=minutes,
        alignment_period_seconds=60,
    )
    mem_s = _query_metric(
        "agent.googleapis.com/memory/percent_used",
        minutes_back=minutes,
        alignment_period_seconds=60,
    )
    cpu_by_ts = {p["timestamp"]: p["value"] for p in cpu_s if "value" in p}
    mem_by_ts = {p["timestamp"]: p["value"] for p in mem_s if "value" in p}
    for ts in sorted(set(cpu_by_ts) | set(mem_by_ts)):
        raw = cpu_by_ts.get(ts, 0.0)
        _metric_history.append({
            "cpu_percent":    round(raw * 100 if raw <= 1.0 else raw, 2),
            "memory_percent": round(mem_by_ts.get(ts, 0.0), 2),
            "disk_percent":   0.0,
            "bytes_sent":     0,
            "bytes_recv":     0,
            "timestamp":      ts,
        })


def list_running_instances() -> list[dict]:
    from google.cloud import compute_v1
    client  = compute_v1.InstancesClient()
    results = []
    for _zone, response in client.aggregated_list(
        request=compute_v1.AggregatedListInstancesRequest(project=PROJECT_ID)
    ):
        for inst in response.instances or []:
            if inst.status == "RUNNING":
                results.append({
                    "instance_id":  inst.name,
                    "name":         inst.name,
                    "zone":         inst.zone.split("/")[-1],
                    "machine_type": inst.machine_type.split("/")[-1],
                    "status":       inst.status,
                })
    return results


def get_instance_utilization_summary(instance_id: str, zone: Optional[str] = None, hours: int = 1) -> dict:
    minutes   = hours * 60
    cpu_s = _query_metric(
        "compute.googleapis.com/instance/cpu/utilization",
        instance_id=instance_id,
        zone=zone,
        minutes_back=minutes,
        alignment_period_seconds=300,
    )
    mem_s = _query_metric(
        "agent.googleapis.com/memory/percent_used",
        instance_id=instance_id,
        zone=zone,
        minutes_back=minutes,
        alignment_period_seconds=300,
    )
    cpu_vals = [(p["value"]*100 if p["value"] <= 1.0 else p["value"]) for p in cpu_s if "value" in p]
    mem_vals = [p["value"] for p in mem_s if "value" in p]
    return {
        "instance_id":        instance_id,
        "avg_cpu_percent":    round(sum(cpu_vals)/len(cpu_vals), 2) if cpu_vals else 0.0,
        "avg_memory_percent": round(sum(mem_vals)/len(mem_vals), 2) if mem_vals else 0.0,
        "samples":            len(cpu_vals),
        "hours":              hours,
    }


def get_all_instances_utilization(hours: int = 1) -> list[dict]:
    return [{**i, **get_instance_utilization_summary(i["instance_id"], i["zone"], hours)} for i in list_running_instances()]

