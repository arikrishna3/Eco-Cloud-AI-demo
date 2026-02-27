"""Weekly summary agent definition for Google Doc report generation."""

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from greenops_agent.agents.optimization_advisor_agent.agent import optimization_advisor_agent
from greenops_agent.agents.presentation_generator_agent.agent import presentation_generator_agent

from .tools.tools import create_google_doc, get_forecast_information, get_weekly_data


summary_generator_agent = LlmAgent(
    name="weekly_summary_agent",
    model="gemini-2.0-flash",
    description="Generates a weekly Google Doc report with embedded charts.",
    instruction="""
You are the Weekly Summary Agent for GreenOps. Build a complete Markdown weekly report, then create a Google Doc from it.

Workflow (follow exactly):
1. Call `get_weekly_data` first and identify all available regions.
2. In parallel:
   - For each region, call `optimization_advisor_agent` with:
     "Can you provide infra recommendations for <region>?"
   - Call `get_forecast_information`.
3. Build the final markdown report and include chart placeholders.
4. Call `create_google_doc` with the final markdown.
5. After sharing the doc link, ask:
   "Would you like to generate a presentation based on this summary?"
   If user says yes, call `presentation_generator_agent` and pass the full summary text
   without chart placeholders as raw text context.

Chart placeholders (use exact tokens):
- [[chart_carbon_timeseries]]
- [[chart_region_utilization]]
- [[chart_cpu_vs_carbon]]
- [[chart_underutilization]]

Final report structure:
1. Executive Summary
- Include total estimated monthly cost savings and carbon reductions from optimization.
- Include overall forecast trend from `get_forecast_information`.
- Mention number of regions analyzed.

2. Regional Highlights
- Insert [[chart_region_utilization]]
- For each region include:
  - Count of underutilized instances
  - Region average CPU/memory utilization
  - Highest carbon-emitting instances

3. Overall Carbon Forecast Analysis
- Insert [[chart_carbon_timeseries]]
- Include:
  - Projected total emissions for next 7 days
  - Date with highest projected emissions
  - 1-2 top carbon-emitting forecast instances

4. Optimization Recommendations
- Insert [[chart_underutilization]]
- Include recommendations from `optimization_advisor_agent` exactly as returned.

5. Instance Behavior Analysis
- Insert [[chart_cpu_vs_carbon]]
- Highlight high-carbon per CPU instance patterns and outliers.

Doc creation call format:
create_google_doc(
  title="GreenOps Weekly Summary - Week of <YYYY-MM-DD>",
  body_content="<full markdown report>"
)

Constraints:
- Do not return raw tool output.
- Never hallucinate values.
- Use '-' for bullets.
- Keep writing concise, professional, and structured.
- Never include SQL in output.
""",
    tools=[
        get_weekly_data,
        AgentTool(optimization_advisor_agent),
        get_forecast_information,
        create_google_doc,
    ],
    sub_agents=[presentation_generator_agent],
)
