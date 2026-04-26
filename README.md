# Project HomeBound

**From Discharge Note to Delivered Equipment, Without the Fax Chaos.**
HomeBound bridges the gap between messy, unstructured clinical documentation and real-world home-care logistics. We use AI to transform discharge summaries into structured, interoperable DME orders that can be routed, tracked, and actioned automatically.

---

## **Architecture Diagram**

<img width="6040" height="4846" alt="HomeBound Architecture V2" src="https://github.com/user-attachments/assets/e92e352a-28a5-4559-8955-6d357b925fb7" />

---

## **The Tech Stack**

- **Frontend:** Streamlit (Physician Portal)
- **Clinical Engine:** Medplum (FHIR R4 Server)
- **AI Agent:** OpenBioLLM-Llama3-8B (Hugging Face)
- **Logistics Layer:** Jira Service Management
- **Data/Insights:** Supabase

---

## **Codebase Navigation**

Use this section as the fastest path to understanding the demo flow and engineering decisions.

- [app.py](app.py): Main Streamlit application, LLM extraction logic, and Medplum sync workflow.
- [smart_dme_factory.py](smart_dme_factory.py): Synthetic clinical note generator used for the 50-case demo set.
- [discharge_summaries](discharge_summaries): 50 synthetically generated high-fidelity discharge records used to validate extraction and routing.

```text
caredevi-hackathon-2026-homebound/
├── app.py
├── smart_dme_factory.py 
├── discharge_summaries/
│   ├── ... 50 synthetic discharge notes ...
├── db/
│   └── schema.sql
├── workflow/
├── README.md
└── ResponsibleAI.md
```

---

## **Quick Start**

### 1. Install dependencies

Use the `python -m pip` pattern

```bash
python -m pip install --upgrade pip
python -m pip install streamlit requests huggingface_hub
```

### 2. Configure secrets

Create `.streamlit/secrets.toml` with your keys:

```toml
HF_TOKEN = "your_huggingface_token"
MEDPLUM_TOKEN = "your_medplum_bearer_token"
```

### 3. Launch the portal

```bash
python -m streamlit run app.py
```

### 4. Demo flow

1. Upload a discharge summary in the Streamlit portal.
2. Run AI extraction to produce structured clinical output.
3. Sync to Medplum to store longitudinal patient/order context.
4. Route logistics actions through Jira Service Management.

---

## **The Why**

### **Why FHIR R4?**

FHIR R4 gives HomeBound a common clinical language that is interoperable across systems. Rather than creating one-off payloads, we model core data as standards-based resources so patient context and order intent remain portable, auditable, and integration-ready.

### **Why a Biomedical LLM instead of a generalist model?**

Discharge notes are clinically dense and abbreviation-heavy. A specialized biomedical model (OpenBioLLM-Llama3-8B) improves extraction reliability for clinical entities such as MRN-linked context, care-course narrative, and DME order intent compared with general-purpose models not tuned for healthcare language.

---

## **Mission Alignment**

Project HomeBound is built for the CareDevi 2026 Hackathon to reduce discharge friction and improve continuity of care by converting unstructured clinical documents into actionable home-care logistics.
