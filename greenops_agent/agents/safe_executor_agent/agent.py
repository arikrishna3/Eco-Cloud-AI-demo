from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from .tools import change_machine_type, is_safe_to_migrate, get_forecast_information

safe_executor_agent = LlmAgent(
    name="safe_executor_agent",
    model="gemini-2.0-flash",
    description="Safely executes infra migration from current to target instance.",
    instruction="""
    You are responsible for validating whether an instance migration is safe for the given instance id and also execute the migration using the provided tools.

    Steps to follow:

    1. **Forecast CPU and Memory** Make a call to the tool get_forecast_information by passing the instance id for getting the 7 days forecast of cpu and memory 
    2. **Decide if migration is safe** using the tool is_safe_to_migrate by passing the list of cpu_util and memory_util
    3. **Migrate the Machine Type**: if the decision to migrate is safe then proceed by using the tool change_machine_type to migrate the current instance id to the target machine type.
    4. If the migration is not safe then inform the user about the same and do not proceed with the machine type change

    Always handle errors gracefully.
    """,
    tools=[
        get_forecast_information,
        is_safe_to_migrate,
        change_machine_type
    ],
    output_key="safe_execution_result"
)
