# Responsible AI Statement: HomeBound

This document describes the Responsible AI controls for the CareDevi HomeBound hackathon prototype. The system supports DME care coordination, not diagnosis or autonomous treatment decisions. All outputs are advisory and require qualified human validation before external action.

## 1) Data Sources

HomeBound is developed and validated using **Synthea-generated synthetic patient records** and synthetic discharge summaries derived from those records.

- Synthea provides realistic, clinically structured, de-identified test data for FHIR-based workflows.
- No live production PHI is required for model development, prompt tuning, or UI testing.
- Synthetic data use supports HIPAA-safe prototyping by reducing direct exposure to identifiable patient data during hackathon development.
- In the application, extracted data is represented as a FHIR `Bundle` containing a `Patient` profile and a `ServiceRequest` for DME coordination, and the Medplum sync path writes `Patient` and `ServiceRequest` resources to FHIR R4 endpoints.

## 2) Model Choices

HomeBound uses a **multi-model implementation** aligned to task context:

- In the Streamlit extraction app, we use **`aaditya/Llama3-OpenBioLLM-8B`** via the Hugging Face `InferenceClient` (configured with the Featherless provider in this prototype).
- In the Make.com integration workflow, we also use **Llama 3.3 (70B)** served through **Groq/OpenRouter** for structured workflow extraction and JSON transformation in automation steps.

Within the Streamlit app path, the OpenBioLLM model supports two constrained tasks:

1. Clinical entity extraction from discharge summaries into a FHIR `ServiceRequest` structure (MRN, DME, and clinical course).
2. SNOMED-CT mapping assistance for DME terminology when deterministic catalog matching is insufficient.

Why this model pattern was selected:

- OpenBioLLM is clinically oriented and performs well on structured extraction prompts.
- The implementation uses **temperature-controlled, schema-constrained prompting** to reduce output variability.
- A deterministic-first strategy is applied: curated DME-to-SNOMED mappings are attempted first; LLM inference is used as fallback for unmapped equipment terms.
- The architecture remains provider-portable and can be switched to equivalent hosted runtimes without changing the human-safety workflow.

## 3) Bias Considerations

- Synthetic populations may not fully preserve real-world demographic, linguistic, or socioeconomic complexity.
- Clinical phrasing diversity in generated summaries may underrepresent edge cases, regional language, or atypical charting styles.
- Model extraction confidence can differ across documentation styles, which may indirectly affect prioritization in care workflows.

Mitigations implemented in this prototype:

- Human review is required before external synchronization is allowed.
- Extraction includes deterministic fallbacks (regex and catalog matching) to reduce overreliance on model-only behavior.
- Unknown or weakly mapped DME terms are explicitly labeled as `unknown`/`unmapped` rather than silently forced into a code.
- Risk signaling surfaces uncertainty and prompts expedited review for potentially high-impact cases.

## 4) Failure Cases and Manual Review

HomeBound includes explicit safeguards for low-confidence or uncertain outputs:

- In SNOMED mapping, if the LLM returns **low confidence** or an invalid code format, the system rejects that mapping and falls back to `unknown`/`unmapped`.
- Uncertain extractions are carried forward transparently in the FHIR payload (including SNOMED source metadata and extension annotations).
- The Streamlit workflow enforces a **Human-in-the-Loop verification gate**: external Medplum/Jira sync is blocked unless the user confirms "Human-in-the-Loop Verification Complete."
- If verification is not completed, queued jobs are marked failed with a verification-required message, creating a clear **manual review fallback** before any external write.
- Clinicians/care coordinators can inspect the extracted FHIR JSON in the UI before deciding to proceed.

These controls are designed to prioritize patient safety, traceability, and clinician accountability over automation speed.
