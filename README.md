# HomeBound

AI-Powered Care Coordination for Durable Medical Equipment (DME) workflows.

HomeBound helps case managers reduce delays in post-acute care coordination by replacing fragmented fax-first processes with an AI-assisted orchestration layer. Our goal is to improve discharge continuity and reduce preventable 30-day readmissions.

## Problem

Case managers and care coordinators often rely on manual, fax-based DME workflows that create bottlenecks at discharge:

- DME requests are sent through disconnected channels with limited status visibility.
- Follow-ups with vendors are manual and time-consuming.
- Documentation is spread across systems, increasing handoff risk.
- Delays in equipment delivery can compromise post-discharge safety and increase 30-day readmission risk.

In short, teams spend too much time chasing updates and too little time on patient-centered transitions.

## Approach

HomeBound uses AI-driven workflow orchestration to coordinate DME requests from intake to delivery:

- Capture and normalize DME order details.
- Use AI to interpret request context and route tasks.
- Automate status tracking and escalation logic.
- Keep care teams informed through a centralized operational view.
- Structure clinical context in FHIR-compatible resources for interoperability.

By reducing coordination lag and improving visibility, HomeBound supports earlier interventions that help prevent avoidable readmissions within 30 days of discharge.

## Architecture

HomeBound is built as an integrated orchestration stack:

- Make.com: Workflow automation, event routing, and notifications.
- Supabase: Backend database and operational state management.
- Hugging Face OpenBioLLM-70B: Clinical language understanding for request interpretation and coordination support.
- Medplum FHIR: Interoperable clinical data modeling and FHIR resource alignment.

High-level flow:

1. DME request is created and stored in Supabase.
2. Make.com triggers orchestration scenarios.
3. OpenBioLLM-70B assists with request interpretation and triage signals.
4. Medplum FHIR structures patient and care-context data.
5. Status updates are persisted and surfaced to case managers.

## Data Sources

We use Synthea synthetic data for development and demonstration:

- Realistic but non-identifiable patient records.
- Representative care transitions and chronic-condition scenarios.
- Safe environment for testing DME coordination workflows and readmission-focused interventions.

No real patient PHI is required for this prototype.

## Limitations

This project is a prototype and has important constraints:

- Not a production clinical decision support system.
- Readmission impact is directional and not yet validated in live deployments.
- Limited external vendor integration depth in current scope.
- FHIR mappings are prototype-level and require implementation hardening.
- Regulatory, privacy, and security controls would need full enterprise review before real-world use.

## Setup Instructions

### 1. Clone the repository

- Clone this project locally.
- Move into the project directory.

### 2. Configure Supabase

- Create a Supabase project.
- Open the SQL editor and run [db/schema.sql](db/schema.sql) to create the core DME tracking table.
- Confirm that the equipment_orders table is created successfully.

### 3. Configure Medplum

- Create a Medplum project and obtain API credentials.
- Define or map the FHIR resources used by your workflow.

### 4. Configure Hugging Face model access

- Create a Hugging Face access token with permissions for OpenBioLLM-70B usage.
- Store token securely in your workflow environment variables.

### 5. Build Make.com scenarios

- Create scenarios for:
  - New DME order intake.
  - AI enrichment/triage step.
  - Status synchronization and notification.
  - Escalation for pending or delayed orders.
- Connect Supabase, Hugging Face, and Medplum modules with required credentials.

### 6. Run a test flow

- Seed one or more synthetic patient/DME requests.
- Execute scenarios end-to-end.
- Validate status transitions and escalation behavior.

## Team AI Avengers

- Ace Brown
- Paul Kwiatkowski

---

Built for the AI-Powered Care Coordination track at CareDevi Hackathon 2026, with a focus on safer transitions of care and lower 30-day readmissions.