## Demo Video
https://www.youtube.com/watch?v=6XkgrZ84ico

# HomeBound: The AI-Powered Logistics Hub

**From discharge note to delivered DME with full clinical visibility, operational accountability, and real-time status intelligence.**

HomeBound is a CareDevi 2026 hackathon solution that closes the post-discharge coordination gap by connecting AI extraction, FHIR-native clinical systems, logistics execution, and live analytics into one interoperable loop.

---

## Architecture Diagram

<img width="6040" height="4846" alt="HomeBound Architecture V2" src="https://github.com/user-attachments/assets/e92e352a-28a5-4559-8955-6d357b925fb7" />

---

## 1) Problem Statement (Real-World Impact)

### The DME Black Hole
In many discharge workflows, case managers submit a DME request and then lose visibility once the note leaves the hospital workflow. This creates the "DME Black Hole":

- Providers cannot reliably track whether equipment was ordered, accepted, dispatched, or delivered.
- Care teams spend time on manual calls, fax follow-ups, and status chasing.
- Delays in home equipment create avoidable risk during the high-vulnerability post-discharge period.

HomeBound directly addresses this care-delivery failure mode by maintaining an end-to-end, auditable status loop from **clinical intent** to **vendor execution** to **delivery confirmation**.

---

## 2) The Solution (Technical Innovation)

### Three-Link Closed-Loop Architecture
HomeBound is built on a Three-Link architecture that synchronizes:

1. **Clinical Records (Medplum / FHIR R4)**  
   AI-extracted discharge intent is normalized into `Patient` + `ServiceRequest` resources and written to Medplum.

2. **Vendor Tasks (Jira Service Management)**  
   Equipment orders are routed into operational work queues as structured Jira issues for vendor fulfillment.

3. **Real-Time Analytics (Supabase)**  
   Order lifecycle data is captured for command-center monitoring, fulfillment KPIs, and delivery status visibility.

Together, these links create a bidirectional operational fabric instead of a one-way handoff.

---

## 3) Key Features

### AI Clinical Extraction
- Uses **Llama 3.3** in Make.com workflow automation (`llama-3.3-70b-versatile` via Groq/OpenRouter) to transform webhook payloads into structured order JSON.
- Uses **`aaditya/Llama3-OpenBioLLM-8B`** in the Streamlit app path for clinical extraction and SNOMED fallback mapping.
- Applies deterministic-first logic (catalog + regex fallback) before LLM fallback for safer clinical normalization.

### FHIR R4 Interoperability
- Native Medplum integration using FHIR R4 endpoints.
- Core resources: **`Patient`** and **`ServiceRequest`**.
- Upsert behavior:
  - Search/create `Patient` by MRN.
  - Post linked `ServiceRequest` with traceable authored timestamp.
- Standards-based payload design keeps data portable and audit-ready across systems.

### Closed-Loop Sync
- Make.com webhooks orchestrate real-time synchronization:
  - Inbound order flow: webhook -> AI parse -> Supabase create -> Jira issue create -> Supabase upsert with Jira key.
  - Delivery update flow: Jira webhook -> Medplum `ServiceRequest` status patch (`completed`) -> Supabase `order_status` update (`Delivered`).
- This creates continuous visibility for both clinical and operations teams.

### Human-in-the-Loop Safety Controls
- External sync is blocked unless **Human-in-the-Loop Verification Complete** is confirmed in the Streamlit UI.
- Low-confidence/invalid SNOMED responses are rejected and marked `unknown`/`unmapped` for manual follow-up.
- Advisory-only design: no autonomous diagnosis or treatment actions.

---

## 4) Overview

### Real-World Impact
- Targets a high-friction, high-consequence transition-of-care gap ("DME Black Hole").
- Improves time-to-visibility and care-team coordination during post-discharge risk windows.
- Produces actionable operational traceability from order creation through delivery confirmation.

### Feasibility
- Working prototype implemented with production-grade platforms: Streamlit, Medplum, Jira, Supabase, Make.com.
- Concrete processing controls are implemented (`MAX_BATCH_FILES = 20`, max file size `2MB`, duplicate hash prevention).
- Demonstrated synthetic test corpus included (`Synthea_files` and `discharge_summaries`) for repeatable demo execution.

### Innovation
- Combines clinical AI extraction + standards-based interoperability + logistics orchestration into a true closed loop.
- Uses multi-model strategy by context (OpenBioLLM in app, Llama 3.3 in workflow automation).
- Includes risk signaling and explicit human verification gates as first-class workflow primitives.

### Interoperability
- Native FHIR R4 integration with Medplum (`Patient`, `ServiceRequest`).
- Event-driven cross-platform sync across Medplum, Jira, Supabase through Make webhooks.
- Structured data contracts reduce point-to-point custom integration debt.

---

## 5) Tech Stack

- **Language:** Python
- **UI / App Layer:** Streamlit
- **Clinical Interoperability:** Medplum (FHIR R4)
- **Task Orchestration:** Jira Service Management
- **Analytics / Data Layer:** Supabase
- **Automation / Integration:** Make.com (webhooks, routers, API modules)
- **AI Models:**
  - `aaditya/Llama3-OpenBioLLM-8B` (Hugging Face InferenceClient path)
  - `llama-3.3-70b-versatile` (Groq endpoint in Make.com workflow)

---

## 6) Repository Map

- `app.py`: Streamlit physician portal, extraction logic, Medplum sync, risk indicator, queue processing.
- `smart_dme_factory.py`: Synthetic discharge-summary generator from Synthea bundles.
- `workflow/Integration Webhooks, Supabase.blueprint.json`: inbound order automation (webhook -> AI -> Supabase -> Jira -> Supabase).
- `workflow/Jira DME Delivered Update.blueprint.json`: delivery confirmation automation (Jira webhook -> Medplum patch -> Supabase update).
- `db/schema.sql`: Supabase table schema for equipment order analytics.
- `ResponsibleAI.md`: Responsible AI controls and safety governance.

---

## 7) Setup Instructions (Local Development)

### Prerequisites
- Python 3.10+
- Access tokens/credentials for:
  - Hugging Face (or configured model provider in app path)
  - Medplum
  - Supabase
  - Jira + Make.com (for workflow orchestration outside the local app)

### Install dependencies
```bash
python -m pip install --upgrade pip
python -m pip install streamlit requests huggingface_hub pandas altair pydeck
```

### Configure environment/secrets
Create `.streamlit/secrets.toml` (or set equivalent environment variables):

```toml
HF_TOKEN = "your_hf_or_provider_token"
MEDPLUM_TOKEN = "your_medplum_bearer_token"
SUPABASE_URL = "your_supabase_project_url"
SUPABASE_KEY = "your_supabase_service_or_anon_key"
```

### Run the app
```bash
python -m streamlit run app.py
```

### Local demo flow
1. Upload one or more `.txt` discharge summaries.
2. Enable **Human-in-the-Loop Verification Complete**
3. Process queue and review extracted FHIR payload.
4. Sync to Medplum and monitor analytics panel.
5. Use Make.com scenarios to demonstrate Jira/Supabase closed-loop updates.

---

## 8) Patient Safety

- Development/testing is performed with synthetic data (Synthea-derived records).
- Human verification is required before external sync.
- Low-confidence extraction/mapping is surfaced for manual review.
- The system is a care-coordination support tool, not a diagnostic or autonomous clinical decision engine.

For full details, see `ResponsibleAI.md`.
