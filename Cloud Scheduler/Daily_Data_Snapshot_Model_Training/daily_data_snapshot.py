"""Cloud Function to append daily snapshots and retrain BQML forecast models."""

import logging

import functions_framework
from google.cloud import bigquery

PROJECT_ID = "greenops-460813"
DATASET_ID = "gcp_server_details"
SOURCE_TABLE = f"`{PROJECT_ID}.{DATASET_ID}.server_metrics`"
TIMESERIES_TABLE = f"`{PROJECT_ID}.{DATASET_ID}.server_metrics_timeseries`"

MODEL_SPECS = (
    ("server_cpu_forecast_model", "cpu_util"),
    ("server_mem_forecast_model", "memory_util"),
    ("server_carbon_forecast_model", "total_carbon"),
)

INSERT_DAILY_SNAPSHOT_QUERY = f"""
INSERT INTO {TIMESERIES_TABLE} (
    date,
    instance_id,
    instance_type,
    region,
    cpu_util,
    memory_util,
    disk_iops,
    network_iops,
    total_carbon
)
SELECT
    TIMESTAMP_TRUNC(CURRENT_TIMESTAMP(), DAY) AS date,
    Instance_ID AS instance_id,
    Instance_Type AS instance_type,
    Region AS region,
    ROUND(
        CASE MOD(FARM_FINGERPRINT(Instance_ID), 4)
            WHEN 0 THEN Average_CPU_Utilization * (1 + RAND() * 0.1)
            WHEN 1 THEN Average_CPU_Utilization * (1 - RAND() * 0.1)
            WHEN 2 THEN Average_CPU_Utilization + RAND() * 5
            ELSE Average_CPU_Utilization - RAND() * 5
        END,
        2
    ) AS cpu_util,
    ROUND(
        CASE MOD(FARM_FINGERPRINT(Instance_ID), 3)
            WHEN 0 THEN Memory_Utilization * (1 + RAND() * 0.2)
            WHEN 1 THEN Memory_Utilization * (1 - RAND() * 0.15)
            ELSE Memory_Utilization + RAND() * 10
        END,
        2
    ) AS memory_util,
    CAST(
        GREATEST(
            CASE MOD(FARM_FINGERPRINT(Instance_ID), 3)
                WHEN 0 THEN Disk_IOPS + CAST(FLOOR(RAND() * 50) AS INT64)
                WHEN 1 THEN Disk_IOPS - CAST(FLOOR(RAND() * 30) AS INT64)
                ELSE Disk_IOPS
            END,
            0
        ) AS INT64
    ) AS disk_iops,
    CAST(
        GREATEST(
            CASE MOD(FARM_FINGERPRINT(Instance_ID), 3)
                WHEN 0 THEN Network_IOPS + CAST(FLOOR(RAND() * 40) AS INT64)
                WHEN 1 THEN Network_IOPS - CAST(FLOOR(RAND() * 20) AS INT64)
                ELSE Network_IOPS
            END,
            0
        ) AS INT64
    ) AS network_iops,
    ROUND(
        CASE MOD(FARM_FINGERPRINT(Instance_ID), 4)
            WHEN 0 THEN Total_Carbon_Emission_in_kg * (1 + RAND() * 0.2)
            WHEN 1 THEN Total_Carbon_Emission_in_kg * (1 - RAND() * 0.1)
            WHEN 2 THEN Total_Carbon_Emission_in_kg + RAND() * 0.5
            ELSE Total_Carbon_Emission_in_kg
        END,
        3
    ) AS total_carbon
FROM {SOURCE_TABLE}
"""


def _build_model_query(model_name: str, metric_column: str) -> str:
    """Build a CREATE OR REPLACE MODEL query for a single metric column."""
    return f"""
CREATE OR REPLACE MODEL `{PROJECT_ID}.{DATASET_ID}.{model_name}`
OPTIONS(
    MODEL_TYPE='ARIMA_PLUS',
    TIME_SERIES_TIMESTAMP_COL='date',
    TIME_SERIES_ID_COL='instance_id',
    TIME_SERIES_DATA_COL='{metric_column}',
    DATA_FREQUENCY='AUTO_FREQUENCY'
) AS
SELECT
    date,
    instance_id,
    {metric_column}
FROM {TIMESERIES_TABLE}
WHERE {metric_column} IS NOT NULL
"""


@functions_framework.http
def run_daily_snapshot_model_retrain(request):
    """
    Scheduled HTTP function entrypoint.

    Steps:
    1. Append one daily data point per instance in the time-series table.
    2. Retrain all forecast models used by GreenOps agents.
    """
    del request  # Request content is not used for scheduled runs.

    try:
        client = bigquery.Client(project=PROJECT_ID)

        logging.info("Running daily snapshot insert query.")
        client.query(INSERT_DAILY_SNAPSHOT_QUERY).result()

        for model_name, metric_column in MODEL_SPECS:
            logging.info("Retraining model=%s metric=%s", model_name, metric_column)
            client.query(_build_model_query(model_name, metric_column)).result()

        return "Success: daily snapshot inserted and models retrained.", 200
    except Exception as exc:
        logging.exception("Daily snapshot/model retraining failed.")
        return f"Error occurred during retraining: {exc}", 500
