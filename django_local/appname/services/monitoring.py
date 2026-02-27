from __future__ import annotations

from typing import Any, Dict, List

from appname.models import MetricSnapshot

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def sample_metrics() -> Dict[str, Any]:
    if psutil is None:
        raise RuntimeError("psutil is not installed. Install with: pip install psutil")

    cpu_percent = float(psutil.cpu_percent(interval=0.2))
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    net = psutil.net_io_counters()

    snapshot = MetricSnapshot.objects.create(
        cpu_percent=cpu_percent,
        memory_percent=float(vm.percent),
        disk_percent=float(du.percent),
        bytes_sent=int(net.bytes_sent),
        bytes_recv=int(net.bytes_recv),
    )

    return {
        "cpu_percent": snapshot.cpu_percent,
        "memory_percent": snapshot.memory_percent,
        "disk_percent": snapshot.disk_percent,
        "bytes_sent": snapshot.bytes_sent,
        "bytes_recv": snapshot.bytes_recv,
        "created_at": snapshot.created_at.isoformat(),
    }


def metrics_history(limit: int = 30) -> List[Dict[str, Any]]:
    rows = list(MetricSnapshot.objects.all()[:limit])
    rows.reverse()
    return [
        {
            "cpu_percent": row.cpu_percent,
            "memory_percent": row.memory_percent,
            "disk_percent": row.disk_percent,
            "bytes_sent": row.bytes_sent,
            "bytes_recv": row.bytes_recv,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
