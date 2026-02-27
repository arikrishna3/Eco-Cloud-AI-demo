"""
find_metrics.py
Run this to discover exactly what metric types your VM is sending:
    python find_metrics.py
"""

import os
import time

from google.cloud import monitoring_v3


PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "eco-cloudai")
PROJECT_NAME = f"projects/{PROJECT_ID}"

client = monitoring_v3.MetricServiceClient()

# Try these metric type prefixes — OTel agent uses different names
CANDIDATES = [
    "compute.googleapis.com/instance/cpu/utilization",
    "compute.googleapis.com/instance/cpu/usage_time",
    "agent.googleapis.com/cpu/utilization",
    "agent.googleapis.com/cpu/load_1m",
    "agent.googleapis.com/memory/percent_used",
    "agent.googleapis.com/memory/bytes_used",
    "agent.googleapis.com/disk/read_bytes_count",
    "agent.googleapis.com/network/tcp_connections",
    "workload.googleapis.com/system.cpu.utilization",
    "workload.googleapis.com/system.memory.utilization",
    "workload.googleapis.com/system.disk.io",
    "workload.googleapis.com/system.network.io",
]

now = time.time()
interval = monitoring_v3.TimeInterval(
    {
        "end_time": {"seconds": int(now)},
        "start_time": {"seconds": int(now) - 20 * 60},  # last 20 min
    }
)

print(f"\nSearching project: {PROJECT_ID}")
print("=" * 60)

found = []
for metric_type in CANDIDATES:
    try:
        request = monitoring_v3.ListTimeSeriesRequest(
            name=PROJECT_NAME,
            filter=f'metric.type="{metric_type}"',
            interval=interval,
            view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.HEADERS,
        )
        results = list(client.list_time_series(request=request))
        if results:
            latest_val = "n/a"
            # Try to get a value
            try:
                req2 = monitoring_v3.ListTimeSeriesRequest(
                    name=PROJECT_NAME,
                    filter=f'metric.type="{metric_type}"',
                    interval=interval,
                    view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
                )
                for ts in client.list_time_series(request=req2):
                    if ts.points:
                        p = ts.points[-1]
                        latest_val = p.value.double_value or float(p.value.int64_value) or 0.0
                        break
            except Exception:
                pass
            print(f"FOUND: {metric_type}")
            print(f"   Series count: {len(results)}  |  Latest value: {latest_val}")
            found.append(metric_type)
        else:
            print(f"empty: {metric_type}")
    except Exception as e:  # noqa: BLE001
        print(f"error: {metric_type} -> {e}")

print("\n" + "=" * 60)
print(f"Found {len(found)} active metric types:")
for f in found:
    print(f"  -> {f}")

# Also list ALL metric descriptors that have recent data
print("\n" + "=" * 60)
print("Scanning ALL metrics with recent data in this project...")
print("(This finds metrics we didn't know to look for)")
try:
    desc_request = monitoring_v3.ListMetricDescriptorsRequest(
        name=PROJECT_NAME,
        filter='metric.type = starts_with("agent.googleapis.com")',
        page_size=50,
    )
    for desc in client.list_metric_descriptors(request=desc_request):
        print(f"  descriptor: {desc.type}")
except Exception as e:  # noqa: BLE001
    print(f"  Error listing descriptors: {e}")
