from google.adk.agents import LlmAgent

infra_recommender_agent = LlmAgent(
    name="infra_recommender",
    model="gemini-2.0-flash",
    description="Providing well crafted professional recommendations",
    instruction="""
    Your main goal is delivering final recommendations based on the found analysis: 
    
    Analysis:
    {analysis_results}
    
    Final output format:
    # Infrastructure Recommendations for [Region]
    ## Summary
    - [Short summary about what was found]
    
    ## Detailed Recommendations:
    - [Instance ID]
    - [Issue Identified]
    - [Current Instance Type]
    - [Recommmendation also mentioning which instance type to replace with]
    - [Potential savings based on current and target instance]
    -----------------------------------

    Format the recommendations in a professional format seperated by horizontal bars.

    """,
    output_key="final_recommendations"
)