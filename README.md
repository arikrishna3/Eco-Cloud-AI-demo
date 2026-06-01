# Eco-Cloud AI

Eco-Cloud AI is an AI-powered cloud optimization assistant that manages, monitors, and optimizes Google Cloud infrastructure. It lets you control compute resources using plain language, predict future usage before it becomes a problem, and understand the cost and carbon impact of every infrastructure decision in real time.

<img width="1911" height="982" alt="Screenshot 2026-02-26 093727" src="https://github.com/user-attachments/assets/143e896a-8132-4ec1-a708-168bd9b00d17" />

<img width="1908" height="988" alt="Screenshot 2026-02-26 093752" src="https://github.com/user-attachments/assets/c9ab650c-c6ee-4b8a-a3f1-74932776687b" />

---

## The Problem

Cloud infrastructure teams routinely deal with three costly issues:

- Virtual machines that are over-provisioned and left running "just in case," wasting money and energy.
- Workloads that are under-provisioned, causing slowdowns and instability at critical moments.
- Scaling decisions made with no visibility into their environmental impact.

On top of this, most teams respond to infrastructure problems after they occur rather than anticipating them. Eco-Cloud AI is built to fix all of this in one place.

<img width="1920" height="1080" alt="Screenshot 2026-02-27 195810" src="https://github.com/user-attachments/assets/a863c8cd-84cd-4144-8b16-111783799d46" />

---

## What It Does

### Instance Lifecycle Management

Create, delete, and manage Google Cloud Compute Engine instances using plain language. No need to navigate the GCP console or write scripts.

Example commands:
- "Create instance project-k"
- "Delete the instance test420"
- "Set performance to eco"

---

### Performance Policy Engine

Switch between two operational modes depending on your workload needs:

**High Mode** is designed for demanding workloads. It raises CPU utilization thresholds, increases memory allocation, and raises network bandwidth limits.

**Eco Mode** reduces resource allocation to lower costs and minimize environmental footprint. It is ideal for non-critical or off-peak workloads.

Each policy also configures the monitoring interval, cooldown duration, and whether the policy is actively enforced.

---

### Resource Monitoring

Eco-Cloud AI connects to Google Cloud Monitoring APIs to track CPU utilization, memory usage, disk allocation, and network bandwidth in real time. It automatically detects conditions like memory pressure, sustained underuse, and over-provisioning, and flags them for action.

---

### Forecasting Engine

Rather than waiting for problems to appear, the forecasting engine predicts resource usage over the next three hours using historical utilization patterns. This allows teams to scale proactively instead of reacting after the fact.

---

### Cost and Carbon Impact Analysis

Before any scaling action is taken, Eco-Cloud AI calculates what it will actually cost and what it will do to your carbon footprint. Given a current instance, a target instance, a region, and a time window, the system tells you:

- How much money the change will save or cost
- How much CO2 equivalent will be reduced or added
- Whether the recommendation is to scale up or scale down

This makes infrastructure decisions economically and environmentally transparent rather than purely technical.

---

## How It Works

When you submit a command or query, the system follows a clear sequence:

1. The AI Engine reads the request and identifies the intent and any relevant parameters.
2. The appropriate agent is selected: compute, monitoring, or optimization.
3. If an infrastructure action is needed, it is executed directly against Google Cloud.
4. Monitoring metrics are pulled from Cloud Monitoring APIs in real time.
5. The optimization layer checks whether the workload is under- or over-provisioned.
6. The Impact Engine calculates the projected cost and carbon delta for any recommended change.
7. All results are displayed through the Streamlit dashboard.

The system supports automated performance mode switching and can simulate impact over defined time windows, for example across a 720-hour period.

---

## Architecture

Eco-Cloud AI is built as a modular multi-agent system. Each component has a specific responsibility:

- **AI Engine** - Classifies intent from natural language input, extracts parameters, and routes commands.
- **Compute Agent** - Handles VM lifecycle operations including provisioning and deletion.
- **Monitoring Agent** - Integrates with Cloud Monitoring APIs and aggregates metrics.
- **Optimization Agent** - Analyzes utilization against thresholds and produces scaling recommendations.
- **Forecasting Module** - Generates short-term predictive models from historical usage data.
- **Impact Engine** - Computes cost deltas and carbon emission estimates for scaling actions.
- **Frontend** - A Streamlit-based dashboard that surfaces all of the above in real time.

---

## Technology Stack

- Python
- Django (local backend layer)
- Streamlit (dashboard interface)
- Google Cloud Platform
  - Compute Engine
  - Cloud Monitoring APIs

---

## Known Limitations

- Forecasting is currently optimized for short-term predictions only; longer-range projections are not yet supported.
- Impact labels require careful interpretation when a scale-up recommendation increases cost rather than reducing it.
- Instance name parsing from natural language input can be unreliable for ambiguous phrasing.

---

## Business Model

Eco-Cloud AI is built for business customers and organizations:

- B2B SaaS for enterprises on a subscription basis
- Carbon credit program for companies managing sustainability targets
- One-on-one agent consultation for teams that need hands-on guidance

---

## Feasibility and Scalability

- Live, working integration with Google Cloud Platform confirms the system is production-ready.
- The web interface scales without significant infrastructure overhead.
- An API-heavy architecture keeps resource usage low on the application side.
- Google OAuth provides straightforward, decoupled account management for users.

---

## Vision

The long-term goal for Eco-Cloud AI is to become a fully autonomous cloud optimization engine: one that enforces carbon-aware scaling policies, governs infrastructure through configurable rules, and supports multiple cloud providers. The aim is to unify predictive analytics, infrastructure automation, and environmental impact modeling into a single operational platform.
