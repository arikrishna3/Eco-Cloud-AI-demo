from google.adk.agents import LlmAgent
from google.cloud import bigquery
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Instantiate BigQuery client
bq_client = bigquery.Client()

def execute_server_query(sql: str) -> dict:
    """Executes a BigQuery SQL query"""
    try:
        print(f"Executing SQL: {sql}")
        query_job = bq_client.query(sql)
        results = query_job.result()
        data = [dict(row) for row in results]

        if not data:
            return {"status": "error", "error_message": "No matching records found"}

        return {
            "status": "success",
            "row_count": len(data),
            "rows": data
        }
    except Exception as e:
        logger.error(f"Query execution error: {e}")
        return {"status": "error", "error_message": str(e)}

# Define the ADK agent
infra_scout_agent = LlmAgent(
    name="gcp_server_analyst",
    model="gemini-2.0-flash",
    description="Fetches GCP server metrics from BigQuery for use in downstream analysis.",
    instruction="""
    You are responsible for retrieving server data from the BigQuery table:
    `greenops-460813.gcp_server_details.server_metrics`.

    You must:
    1. Extract only the **filters** (such as Region, Instance_Type) from the user query.
    2. Ignore any intent like "optimize", "recommend", or "analyze". You do **not** provide interpretations or recommendations.
    3. Generate a SQL query that returns all rows matching those filters (e.g., Region = 'us_west_1').
    4. Call the `execute_server_query` tool with the generated SQL.
    5. Assign the tool result directly to `infra_data` and RETURN that as the final answer.

    Important rules:
    - If the user query mentions a region (e.g., "us_west_1"), filter the SQL by Region.
    - If the user doesn't provide filters, return all rows.

    Example:
    User: "Give me server data for us_west_1"
    → You generate:
    SELECT Instance_ID, Average_CPU_Utilization, Instance_Type, Memory_Utilization, Region, Total_Carbon_Emission_in_kg 
    FROM `greenops-460813.gcp_server_details.server_metrics` 
    WHERE Region = 'us_west_1'

    - Don't just return the query — execute the query using the `execute_server_query` tool
    - Wrap the final output like this:

    {
        "infra_data": {
            "status": "success",
            "row_count": X,
            "rows": [ ... ]
        }
    }
    """,
    tools=[execute_server_query],
    output_key="infra_data"
)

