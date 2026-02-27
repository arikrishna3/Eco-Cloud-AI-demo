from __future__ import annotations

import os
import re
from difflib import get_close_matches
from typing import Any
from concurrent.futures import TimeoutError as FuturesTimeoutError

try:
    from google.cloud import compute_v1
except ImportError:  # pragma: no cover
    compute_v1 = None


def gcp_project_id() -> str:
    return os.getenv("GOOGLE_CLOUD_PROJECT", "eco-cloudai")


def available() -> bool:
    return compute_v1 is not None


def list_running_instances() -> list[dict[str, Any]]:
    if compute_v1 is None:
        raise RuntimeError("google-cloud-compute is not installed.")
    project = gcp_project_id()
    client = compute_v1.InstancesClient()
    rows: list[dict[str, Any]] = []
    for _zone, response in client.aggregated_list(
        request=compute_v1.AggregatedListInstancesRequest(project=project)
    ):
        for inst in response.instances or []:
            if inst.status == "RUNNING":
                rows.append(
                    {
                        "name": inst.name,
                        "zone": inst.zone.split("/")[-1],
                        "machine_type": inst.machine_type.split("/")[-1],
                        "status": inst.status,
                    }
                )
    return rows


def list_instances_all() -> list[dict[str, Any]]:
    if compute_v1 is None:
        raise RuntimeError("google-cloud-compute is not installed.")
    project = gcp_project_id()
    client = compute_v1.InstancesClient()
    rows: list[dict[str, Any]] = []
    for _zone, response in client.aggregated_list(
        request=compute_v1.AggregatedListInstancesRequest(project=project)
    ):
        for inst in response.instances or []:
            rows.append(
                {
                    "name": inst.name,
                    "zone": inst.zone.split("/")[-1],
                    "machine_type": inst.machine_type.split("/")[-1],
                    "status": inst.status,
                }
            )
    return rows


def find_instance(name: str) -> dict[str, Any] | None:
    target = name.strip().lower()
    rows = list_running_instances()
    for row in rows:
        if row["name"].strip().lower() == target:
            return row
    # fuzzy fallback for small typos
    names = [r["name"] for r in rows]
    close = get_close_matches(target, names, n=1, cutoff=0.72)
    if close:
        for row in rows:
            if row["name"] == close[0]:
                return row
    return None


def find_instance_any(name: str) -> dict[str, Any] | None:
    target = name.strip().lower()
    rows = list_instances_all()
    for row in rows:
        if row["name"].strip().lower() == target:
            return row
    names = [r["name"] for r in rows]
    close = get_close_matches(target, names, n=1, cutoff=0.72)
    if close:
        for row in rows:
            if row["name"] == close[0]:
                return row
    return None


def find_instance_exact_any(name: str) -> dict[str, Any] | None:
    target = name.strip().lower()
    rows = list_instances_all()
    for row in rows:
        if row["name"].strip().lower() == target:
            return row
    return None


def create_instance(name: str, zone: str = "asia-south1-a", machine_type: str = "e2-standard-4") -> dict[str, Any]:
    if compute_v1 is None:
        raise RuntimeError("google-cloud-compute is not installed.")
    safe_name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")
    if not safe_name:
        safe_name = "ecocloud-vm"
    if not re.match(r"^[a-z]", safe_name):
        safe_name = f"vm-{safe_name}"
    safe_name = safe_name[:61]
    project = gcp_project_id()
    instances_client = compute_v1.InstancesClient()
    image_client = compute_v1.ImagesClient()
    image = image_client.get_from_family(project="debian-cloud", family="debian-12")

    instance = compute_v1.Instance()
    instance.name = safe_name
    instance.machine_type = f"zones/{zone}/machineTypes/{machine_type}"
    instance.disks = [
        compute_v1.AttachedDisk(
            boot=True,
            auto_delete=True,
            initialize_params=compute_v1.AttachedDiskInitializeParams(source_image=image.self_link, disk_size_gb=30),
        )
    ]
    instance.network_interfaces = [compute_v1.NetworkInterface(name="global/networks/default")]

    operation = instances_client.insert(project=project, zone=zone, instance_resource=instance)
    operation.result(timeout=300)
    return {"name": safe_name, "zone": zone, "machine_type": machine_type, "status": "RUNNING"}


def delete_instance(name: str) -> dict[str, Any]:
    if compute_v1 is None:
        raise RuntimeError("google-cloud-compute is not installed.")
    instance = find_instance_exact_any(name)
    if not instance:
        raise RuntimeError(f"Instance `{name}` not found.")

    project = gcp_project_id()
    zone = instance["zone"]
    instance_name = instance["name"]
    client = compute_v1.InstancesClient()
    operation = client.delete(project=project, zone=zone, instance=instance_name)
    wait_seconds = int(os.getenv("GCP_DELETE_WAIT_SECONDS", "20"))
    try:
        operation.result(timeout=wait_seconds)
    except FuturesTimeoutError:
        pass
    except Exception:
        pass

    refreshed = find_instance_exact_any(instance_name)
    if not refreshed:
        status = "DELETED"
    else:
        current_status = str(refreshed.get("status", "")).upper()
        if current_status in {"STOPPING", "PROVISIONING", "STAGING"}:
            status = "DELETE_IN_PROGRESS"
        elif current_status in {"TERMINATED"}:
            status = "DELETE_SCHEDULED"
        else:
            status = f"DELETE_REQUESTED_{current_status or 'UNKNOWN'}"

    return {
        "name": instance_name,
        "zone": zone,
        "machine_type": instance["machine_type"],
        "status": status,
    }


def machine_type_specs(zone: str, machine_type: str) -> dict[str, Any]:
    if compute_v1 is None:
        return {"vcpus": None, "memory_gb": None}
    try:
        client = compute_v1.MachineTypesClient()
        mt = client.get(project=gcp_project_id(), zone=zone, machine_type=machine_type)
        return {
            "vcpus": int(getattr(mt, "guest_cpus", 0)),
            "memory_gb": round(float(getattr(mt, "memory_mb", 0)) / 1024.0, 1),
        }
    except Exception:
        return {"vcpus": None, "memory_gb": None}
