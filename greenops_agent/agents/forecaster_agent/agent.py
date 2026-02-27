from google.cloud import bigquery
from google.adk.agents import LlmAgent

import pandas as pd
import datetime

bq_client = bigquery.Client()

def serialize_row(row):
    return {
        k: (v.isoformat() if hasattr(v, 'isoformat') else v)
        for k, v in dict(row).items()
    }

def execute_forecast_query(sql: str) -> dict:
    try:
        query_job = bq_client.query(sql)
        results = query_job.result()
        
        # Convert to DataFrame for easier manipulation
        df = results.to_dataframe()
        
        # Pivot the table to have dates as columns
        if not df.empty:
            df['forecast_timestamp'] = pd.to_datetime(df['forecast_timestamp']).dt.date
            # Pivot the table
            pivoted_df = df.pivot(
                index='Instance_ID',
                columns='forecast_timestamp',
                values='forecast_value'
            ).reset_index()
            
            # Convert dates to string for JSON serialization
            pivoted_df.columns = [
                col.strftime("%Y-%m-%d") if isinstance(col, (datetime.date, pd.Timestamp)) else col
                for col in pivoted_df.columns
            ]

            # Convert to dictionary format
            rows = pivoted_df.to_dict('records')
            return {
                "status": "success",
                "row_count": len(rows),
                "rows": rows,
            }
        else:
            return {"status": "success", "row_count": 0, "rows": [], "metric": None}
            
    except Exception as e:
        return {"status": "error", "error_message": str(e)}


forecasting_tool_agent = LlmAgent(
    name="forecasting_tool_agent",
    model="gemini-2.0-flash",
    description="Forecasts CPU, memory, or carbon usage for GCP servers using BigQuery ML models.",
    instruction="""
    You are a forecasting agent that ONLY generates query and executes it using the given tool for CPU, memory, or carbon usage for GCP instances. Your job is to:

    1. Understand the metric to forecast: CPU, memory, or carbon emissions.
    2. Pick the correct BigQuery ML model from:
        - CPU Utilization: `greenops-460813.gcp_server_details.server_cpu_forecast_model`
        - Memory Utilization: `greenops-460813.gcp_server_details.server_mem_forecast_model`
        - Carbon Emissions: `greenops-460813.gcp_server_details.server_carbon_forecast_model`
    3. Consider the number of days for forecast given by the user or default to 7 days
    4. Always include WHERE filters only if the user specifies a region or instance id else don't add any filters
    5. NEVER write the SQL in your response. DO NOT show SQL to the user.

    Instead, you MUST always:
    - Build the query
    - Call the tool `execute_forecast_query`
    - Return only the data returned from the tool — never write your own explanation.

    A valid SQL query is of this format:

    SELECT Instance_ID, forecast_timestamp, forecast_value
    FROM ML.FORECAST(
    MODEL model_path_here,
    STRUCT(<horizon_days> AS horizon, 0.8 AS confidence_level)
    )
    [OPTIONAL: WHERE conditions]

    Example queries:
    Forecast cpu utilization for 7 days for instance id instance-20250614-105928
    
    SELECT Instance_ID, forecast_timestamp, forecast_value
    FROM ML.FORECAST(
    MODEL `greenops-460813.gcp_server_details.server_cpu_forecast_model`,
    STRUCT(7 AS horizon, 0.8 AS confidence_level)
    )
    WHERE Instance_ID="instance-20250614-105928"

    Generate the query at once and run the execute once to return the required information.

    Return format:
    Instance Id: <instance_id> \n
    Metric: <CPU, Memory or Carbon> \n
    Data Table: <Format in proper header format with columns "Date" and "Forecast Value">
    
    Always round the forecasted values upto 3 decimal places.

    After calling the tool `execute_forecast_query`, ASSIGN the result directly to `forecast_analysis` and return. DO NOT attempt any further reasoning or tool calls after that.
    """,
    tools=[execute_forecast_query],
    output_key="forecast_analysis"
)
