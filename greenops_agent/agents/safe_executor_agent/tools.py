"""
tools.py  (safe_executor_agent)
────────────────────────────────────────────────────────────────────────────
Replaces the old tools.py.  Key change:
  • `get_forecast_information` now ALSO pulls the last 24 h of REAL Cloud
    Monitoring utilization alongside the BigQuery ML forecast so
    `is_safe_to_migrate` has richer, real data to work with.
  • Everything else (change_machine_type, zone lookup, wait_for_status) is
    identical to the original.
────────────────────────────────────────────────────────────────────────────
"""

import os
import time

from google.cloud import compute_v1
from greenops_agent.agents.forecaster_agent.agent import execute_forecast_query

# ── optional: pull real metrics alongside BQ forecast ────────────────────────
try:
    from greenops_agent.gcloud_monitoring import get_instance_utilization_summary as _gcp_util
    _HAS_GCP_MONITORING = True
except ImportError:
    _HAS_GCP_MONITORING = False

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "eco-cloudai")

# ─────────────────────────────────────────────────────────────────────────────
# Safety check
# ─────────────────────────────────────────────────────────────────────────────

def is_safe_to_migrate(cpu_forecast: list[float], mem_forecast: list[float]) -> bool:
    """
    Returns True only when both the 7-day average CPU < 30 % and memory < 40 %.
    Accepts the lists returned by get_forecast_information.
    """
    if not cpu_forecast or not mem_forecast:
        return False
    cpu_avg = sum(cpu_forecast) / len(cpu_forecast)
    mem_avg = sum(mem_forecast) / len(mem_forecast)
    return cpu_avg < 30 and mem_avg < 40


# ─────────────────────────────────────────────────────────────────────────────
# Zone lookup
# ─────────────────────────────────────────────────────────────────────────────

def get_instance_zone(instance_id: str) -> str:
    compute = compute_v1.InstancesClient()
    for _zone, response in compute.aggregated_list(
        request=compute_v1.AggregatedListInstancesRequest(project=PROJECT_ID)
    ):
        for instance in response.instances or []:
            if instance.name == instance_id:
                return instance.zone.split("/")[-1]
    raise Exception(f"Zone not found for instance: {instance_id}")


# ─────────────────────────────────────────────────────────────────────────────
# Wait helper
# ─────────────────────────────────────────────────────────────────────────────

def wait_for_status(
    instance_client,
    project: str,
    zone: str,
    instance_name: str,
    expected_status: str,
    timeout_sec: int = 300,
) -> bool:
    elapsed = 0
    while elapsed < timeout_sec:
        instance       = instance_client.get(project=project, zone=zone, instance=instance_name)
        current_status = instance.status
        print(f"[wait_for_status] {instance_name} → {current_status}")
        if current_status == expected_status:
            return True
        time.sleep(5)
        elapsed += 5
    raise TimeoutError(
        f"Instance {instance_name!r} did not reach {expected_status!r} in {timeout_sec}s."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Machine-type migration
# ─────────────────────────────────────────────────────────────────────────────

def change_machine_type(instance_id: str, new_machine_type: str) -> dict:
    """
    Stop → change machine type → start.
    Returns a status dict so the LLM agent can report results cleanly.
    """
    zone            = get_instance_zone(instance_id)
    instance_client = compute_v1.InstancesClient()

    print(f"[change_machine_type] Stopping {instance_id} in {zone}…")
    stop_op = instance_client.stop(project=PROJECT_ID, zone=zone, instance=instance_id)
    stop_op.result()
    wait_for_status(instance_client, PROJECT_ID, zone, instance_id, "TERMINATED")
    print("[change_machine_type] Stopped ✓")

    machine_type_uri = f"projects/{PROJECT_ID}/zones/{zone}/machineTypes/{new_machine_type}"
    req = compute_v1.InstancesSetMachineTypeRequest(machine_type=machine_type_uri)
    print(f"[change_machine_type] Updating machine type → {new_machine_type}…")
    op = instance_client.set_machine_type(
        project=PROJECT_ID,
        zone=zone,
        instance=instance_id,
        instances_set_machine_type_request_resource=req,
    )
    op.result()
    print("[change_machine_type] Machine type updated ✓")

    print(f"[change_machine_type] Starting {instance_id}…")
    start_op = instance_client.start(project=PROJECT_ID, zone=zone, instance=instance_id)
    start_op.result()
    wait_for_status(instance_client, PROJECT_ID, zone, instance_id, "RUNNING")
    print("[change_machine_type] Running ✓")

    return {
        "status":       "success",
        "instance_id":  instance_id,
        "new_type":     new_machine_type,
        "zone":         zone,
        "message":      f"Instance {instance_id} migrated to {new_machine_type} successfully.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Forecast + real utilisation combined
# ─────────────────────────────────────────────────────────────────────────────

def get_forecast_information(instance_id: str) -> dict:
    """
    Returns 7-day BigQuery ML forecasts for CPU and memory PLUS (if available)
    the last 24 h of real Cloud Monitoring utilisation.

    Output shape
    ────────────
    {
      "CPU Forecast":    [ {row dict}, … ],   # BQ ML rows
      "Memory Forecast": [ {row dict}, … ],   # BQ ML rows
      "cpu_values":      [float, …],          # flat list for is_safe_to_migrate
      "mem_values":      [float, …],          # flat list for is_safe_to_migrate
      "real_utilization": {                   # live data (may be absent)
          "avg_cpu_percent": float,
          "avg_memory_percent": float,
          "samples": int,
      }
    }
    """
    cpu_sql = f"""
        SELECT Instance_ID, forecast_timestamp, forecast_value
        FROM ML.FORECAST(
            MODEL `{PROJECT_ID}.gcp_server_details.server_cpu_forecast_model`,
            STRUCT(7 AS horizon, 0.8 AS confidence_level)
        )
        WHERE Instance_ID = "{instance_id}"
    """
    mem_sql = f"""
        SELECT Instance_ID, forecast_timestamp, forecast_value
        FROM ML.FORECAST(
            MODEL `{PROJECT_ID}.gcp_server_details.server_mem_forecast_model`,
            STRUCT(7 AS horizon, 0.8 AS confidence_level)
        )
        WHERE Instance_ID = "{instance_id}"
    """

    cpu_result = execute_forecast_query(cpu_sql)
    mem_result = execute_forecast_query(mem_sql)

    cpu_rows = cpu_result.get("rows", [])
    mem_rows = mem_result.get("rows", [])

    # Flatten forecast_value lists for is_safe_to_migrate
    def _extract_values(rows: list[dict]) -> list[float]:
        values = []
        for row in rows:
            for k, v in row.items():
                if k != "Instance_ID" and v is not None:
                    try:
                        values.append(float(v))
                    except (TypeError, ValueError):
                        pass
        return values

    cpu_values = _extract_values(cpu_rows)
    mem_values = _extract_values(mem_rows)

    result = {
        "CPU Forecast":    cpu_rows,
        "Memory Forecast": mem_rows,
        "cpu_values":      cpu_values,
        "mem_values":      mem_values,
    }

    # Enrich with real Cloud Monitoring data when available
    if _HAS_GCP_MONITORING:
        try:
            zone = get_instance_zone(instance_id)
            util = _gcp_util(instance_id, zone=zone, hours=24)
            result["real_utilization"] = {
                "avg_cpu_percent":    util["avg_cpu_percent"],
                "avg_memory_percent": util["avg_memory_percent"],
                "samples":            util["samples"],
            }
        except Exception as e:
            result["real_utilization_error"] = str(e)

    return result
