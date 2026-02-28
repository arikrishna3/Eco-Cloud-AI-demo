# Eco-Cloud AI

Eco-Cloud AI is an AI-driven cloud optimization assistant that manages,
monitors, and optimizes Google Cloud infrastructure. It enables natural
language control of compute resources, predicts future usage, and
evaluates cost and carbon impact in real time.

The system solves three core problems:

1.  Over-provisioned infrastructure causing unnecessary cost.
2.  Under-provisioned workloads causing instability.
3.  Lack of carbon-awareness in infrastructure scaling decisions.

Eco-Cloud AI bridges infrastructure automation, AI forecasting, and
sustainability metrics into a unified operational system.

<img width="1911" height="982" alt="Screenshot 2026-02-26 093727" src="https://github.com/user-attachments/assets/143e896a-8132-4ec1-a708-168bd9b00d17" />

<img width="1908" height="988" alt="Screenshot 2026-02-26 093752" src="https://github.com/user-attachments/assets/c9ab650c-c6ee-4b8a-a3f1-74932776687b" />

------------------------------------------------------------------------

## Problem Statement

Modern cloud environments often suffer from:

-   Over-provisioned virtual machines kept "just in case".
-   Reactive scaling instead of predictive scaling.
-   No visibility into carbon footprint impact of scaling decisions.
-   Manual instance management with no intelligent guidance.

These inefficiencies lead to higher costs, wasted energy, and reduced
operational clarity.

Eco-Cloud AI addresses these challenges by combining live cloud control
with AI-based forecasting and optimization logic.

<img width="1920" height="1080" alt="Screenshot 2026-02-27 195810" src="https://github.com/user-attachments/assets/a863c8cd-84cd-4144-8b16-111783799d46" />

------------------------------------------------------------------------

## Core Capabilities

### 1. Instance Lifecycle Management

-   Create Compute Engine instances
-   Delete instances
-   Retrieve instance metadata
-   Apply performance policies

Natural language example: - "Create instance project-k" - "Delete the
instance test420" - "Set performance to eco"

------------------------------------------------------------------------

### 2. Performance Policy Engine

Supports multiple operational modes:

HIGH Mode: - Increased CPU utilization threshold - Higher memory
allocation - Higher network bandwidth - Designed for high-demand
workloads

ECO Mode: - Reduced resource allocation - Lower operational footprint -
Cost-optimized and sustainability-focused

Policy parameters: - Mode - Monitoring interval - Cooldown duration -
Enabled state

------------------------------------------------------------------------

### 3. Resource Monitoring

Integrated with Google Cloud Monitoring APIs to track:

-   CPU utilization
-   Memory utilization
-   Disk allocation
-   Network bandwidth

Detects: - Under-provisioned workloads - Over-provisioned workloads -
Memory pressure conditions - Optimization triggers

------------------------------------------------------------------------

### 4. Forecasting Engine

Provides short-term predictive analytics including:

-   RAM usage prediction for next 3 hours
-   Utilization trend estimation
-   Usage range projections

This enables proactive scaling instead of reactive response.

------------------------------------------------------------------------

### 5. Cost and Carbon Impact Analysis

Calculates:

-   Estimated cost savings over a time window
-   CO2 equivalent reduction estimates
-   Instance-to-instance impact comparison
-   Regional optimization impact

Metrics include:

-   Auto Cost Savings
-   Auto CO2e Reduction
-   Optimization window duration
-   Recommendation classification (scale up / scale down)

The system analyzes average CPU and memory utilization against
thresholds to determine recommended actions.

------------------------------------------------------------------------

## Architecture Overview

Eco-Cloud AI follows a modular multi-agent design:

AI Engine\
- Natural language intent classification\
- Parameter extraction\
- Command routing

Compute Agent\
- GCP VM lifecycle operations\
- Instance provisioning and deletion

Monitoring Agent\
- Cloud Monitoring API integration\
- Metric aggregation

Optimization Agent\
- Utilization threshold analysis\
- Scaling recommendations

Forecasting Module\
- Short-term predictive modeling

Impact Engine\
- Cost delta computation\
- Carbon emission estimation

Frontend\
- Streamlit-based dashboard\
- Real-time operational interface

------------------------------------------------------------------------

## Technology Stack

-   Python
-   Django (local backend layer)
-   Streamlit (dashboard interface)
-   Google Cloud Platform
    -   Compute Engine
    -   Cloud Monitoring APIs

------------------------------------------------------------------------

## Detailed System Explanation

Eco-Cloud AI is not a static reporting tool. It is a live infrastructure
intelligence system.

When a user submits a command:

1.  The AI Engine parses the request using intent classification logic.
2.  The appropriate agent (compute, monitoring, optimization) is
    invoked.
3.  Real-time infrastructure actions are executed against GCP.
4.  Monitoring metrics are pulled via Cloud Monitoring APIs.
5.  Optimization logic evaluates whether the workload is:
    -   Under-provisioned (high memory/CPU pressure)
    -   Over-provisioned (low sustained utilization)
6.  The Impact Engine computes projected cost and CO2 deltas.
7.  Results are surfaced through the Streamlit dashboard.

The system supports automated performance mode switching and can
simulate impact over defined time windows (e.g., 720 hours).

The forecasting engine estimates short-term RAM usage using historical
utilization patterns. This supports proactive scaling strategies.

The impact calculator evaluates:

-   Current instance configuration
-   Target instance configuration
-   Regional characteristics
-   Time duration window

It determines whether scaling decisions will:

-   Reduce cost
-   Increase cost
-   Reduce emissions
-   Increase emissions

This ensures scaling decisions are economically and environmentally
transparent.

------------------------------------------------------------------------

## Current Limitations

-   Forecasting currently optimized for short-term predictions
-   Impact labeling needs careful interpretation when scaling up
    increases cost
-   Instance name parsing can be improved for ambiguous language input

------------------------------------------------------------------------

## Vision

Eco-Cloud AI aims to evolve into:

-   A fully autonomous cloud optimization engine
-   A carbon-aware scaling assistant
-   A policy-driven infrastructure governance layer
-   A multi-cloud sustainability intelligence platform

The long-term objective is to integrate predictive analytics,
infrastructure automation, and environmental impact modeling into a
unified operational system.

## Business model
Eco-Cloud AI is geared for:
- B2B SaaS for Enterprises
- Subscription based Revenue Model
- Carbon Credit for companies
- One on One agent consultation

## Fesability and Scalability
- Proven Fesability with live implementation on Google Cloud Platform integration
- Easy to scale web interface
- Low resource usage due to API heavy architecture
- Google Oauth (google login) for easy decoupled account management
