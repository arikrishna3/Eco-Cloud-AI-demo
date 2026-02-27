from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import google_search
import requests
from bs4 import BeautifulSoup
import re


def normalize_to_gcp_region(region: str) -> str:
    """
    Converts formats like 'us_east_1' or 'us-east-1' to standard GCP format like 'us-east1'.

    Examples:
    - 'us_east_1' -> 'us-east1'
    - 'us-east-1' -> 'us-east1'
    """
    if not region:
        return ""

    region = region.lower().replace("_", "-")
    match = re.match(r"([a-z]+)-([a-z]+)-(\d+)", region)
    if match:
        return f"{match.group(1)}-{match.group(2)}{match.group(3)}"
    return region


def get_on_demand_price(instance_type: str, region: str) -> dict:
    print("Inside on demand region: ", region, " Instance type: ", instance_type)
    region = normalize_to_gcp_region(region)

    url = f"https://sparecores.com/server/gcp/{instance_type}?showDetails=true"
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.select_one("#availability > table")

        if not table:
            return {"error": "Could not find the pricing table on the page."}

        rows = table.find_all("tr")

        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 3:
                region_cell = cols[0].text.strip()
                if region in region_cell:
                    on_demand_price = cols[2].text.strip()
                    return {
                        "instance_type": instance_type,
                        "region": region,
                        "on_demand_price": on_demand_price,
                    }

        return {"error": f"No matching region '{region}' found for instance type '{instance_type}'."}

    except Exception as e:
        return {"error": str(e)}


_FAMILY_EFFICIENCY_FACTOR = {
    "e2": 0.85,
    "n2": 0.95,
    "n1": 1.00,
    "c2": 1.10,
    "c3": 1.00,
    "t2d": 0.90,
    "a2": 1.40,
}

_REGION_GRID_INTENSITY = {
    "us-west": 0.20,
    "us-central": 0.36,
    "us-east": 0.39,
    "europe-west": 0.22,
    "europe-north": 0.08,
    "asia-south": 0.55,
    "asia-east": 0.46,
    "asia-southeast": 0.50,
    "australia-southeast": 0.63,
    "southamerica-east": 0.10,
}


def _parse_machine_type(instance_type: str) -> dict:
    t = (instance_type or "").lower().strip()
    family = t.split("-")[0] if "-" in t else t

    vcpus = 2
    mem_gb = 8.0
    gpus = 0

    cpu_match = re.search(r"-(\d+)$", t)
    if cpu_match:
        vcpus = max(int(cpu_match.group(1)), 1)

    if "highcpu" in t:
        mem_gb = float(vcpus)
    elif "highmem" in t:
        mem_gb = float(vcpus) * 8.0
    elif "standard" in t:
        mem_gb = float(vcpus) * 4.0

    gpu_match = re.search(r"-(\d+)g$", t)
    if gpu_match:
        gpus = max(int(gpu_match.group(1)), 1)

    return {"family": family, "vcpus": vcpus, "mem_gb": mem_gb, "gpus": gpus}


def _region_grid_intensity(region: str) -> float:
    r = normalize_to_gcp_region(region)
    for prefix, intensity in _REGION_GRID_INTENSITY.items():
        if r.startswith(prefix):
            return intensity
    return 0.40


def _estimate_co2e_kg_per_hour(instance_type: str, region: str) -> dict:
    parsed = _parse_machine_type(instance_type)
    family = parsed["family"]
    vcpus = parsed["vcpus"]
    mem_gb = parsed["mem_gb"]
    gpus = parsed["gpus"]

    cpu_kwh = vcpus * 0.04
    mem_kwh = mem_gb * 0.003
    gpu_kwh = gpus * 0.15

    efficiency = _FAMILY_EFFICIENCY_FACTOR.get(family, 1.0)
    adjusted_kwh = (cpu_kwh + mem_kwh + gpu_kwh) * efficiency
    grid_intensity = _region_grid_intensity(region)
    total_co2e_kg_per_hour = adjusted_kwh * grid_intensity

    return {
        "cpu_estimate": round(cpu_kwh * grid_intensity, 6),
        "memory_estimate": round(mem_kwh * grid_intensity, 6),
        "embodied_cpu_estimate": round(gpu_kwh * grid_intensity, 6),
        "total_emissions": round(total_co2e_kg_per_hour, 6),
    }


def get_carbon_emissions_per_hour(
    current_instance_type: str,
    current_region: str,
    target_instance_type: str,
    target_region: str,
    duration_hours: float = 24.0,
):
    """
    Returns estimated carbon emissions without external APIs.
    `duration_hours` scales the returned values linearly.
    """
    current = _estimate_co2e_kg_per_hour(current_instance_type, current_region)
    target = _estimate_co2e_kg_per_hour(target_instance_type, target_region)

    emissions_data = {}
    for label, result in ((current_instance_type, current), (target_instance_type, target)):
        emissions_data[label] = {
            "cpu_estimate": round(result["cpu_estimate"] * duration_hours, 6),
            "memory_estimate": round(result["memory_estimate"] * duration_hours, 6),
            "embodied_cpu_estimate": round(result["embodied_cpu_estimate"] * duration_hours, 6),
            "total_emissions": round(result["total_emissions"] * duration_hours, 6),
        }

    return emissions_data


impact_calculator_agent = Agent(
    name="impact_calculator_agent",
    model="gemini-2.0-flash",
    description="Agent that compares cost and carbon impact of changing GCP VM instance types.",
    instruction="""
    You are a Green Cloud Optimization Assistant that helps users understand the environmental and financial impact of changing their GCP VM instance type.

    Your responsibilities include:
    1. Estimating the hourly and daily cost difference between a current and target instance.
    2. Estimating the hourly and daily carbon footprint difference between the two instances.
    3. Concluding whether the change has a positive or negative impact.

    To accomplish this, follow this logic:

    PRICE ESTIMATION

    Use the tool `get_on_demand_price` to get the hourly on-demand price for each instance (current and target).
    If this fails, fall back to the `google_search` tool by querying:

    "GCP pricing [INSTANCE_TYPE] [REGION] on-demand site:sparecores.com"

    Only use sparecores.com results, and always return exact prices (not approximations).

    Then compute:
    price_change_per_day = (target_price - current_price) * 24

    CARBON IMPACT ESTIMATION (LOCAL ESTIMATE)

    Use the tool `get_carbon_emissions_per_hour` with:
    - current_instance_type
    - current_region (if no region provided ask from user)
    - target_instance_type
    - target_region (if no target region given use the current region)

    This returns an estimated carbon result (no external API required):
    - total_emissions
    - cpu_estimate
    - memory_estimate
    - embodied_cpu_estimate

    Compute:
    carbon_change_per_day = (target_total - current_total) * 24

    FINAL RESPONSE

    Return a clear and structured message that includes:
    - Daily cost for both instances
    - Daily carbon emissions for both instances
    - Whether the impact is positive or negative (in both cost and carbon)
    - Mention if any fallback (search-based pricing) was used

    Do not guess or hallucinate. Only respond when data from tools is available.
    If either tool fails, return a partial answer or suggest user visit official pricing page: https://cloud.google.com/compute/vm-instance-pricing

    Examples of valid queries:
    - "I want to move from `n1-standard-4` in `us-central1` to `e2-standard-2` in `asia-south1`. What will I save?"
    - "Is it better (carbon-wise) to use `a2-highgpu-1g` or `n2-standard-8`?"

    """,
    tools=[get_on_demand_price, get_carbon_emissions_per_hour, AgentTool(google_search)],
)
