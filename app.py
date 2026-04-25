import json
import os
import re

import requests
import streamlit as st
from huggingface_hub import InferenceClient


def get_secret(key: str, default: str = "") -> str:
	"""Safely read secrets without crashing when secrets.toml is missing."""
	try:
		return st.secrets.get(key, os.getenv(key, default))
	except Exception:
		return os.getenv(key, default)


HF_TOKEN = get_secret("HF_TOKEN", "")
HF_MODEL_ID = "aaditya/Llama3-OpenBioLLM-8B"
MEDPLUM_TOKEN = get_secret("MEDPLUM_TOKEN", "YOUR_MEDPLUM_BEARER_TOKEN")
MEDPLUM_SERVICE_REQUEST_URL = "https://api.medplum.com/fhir/R4/ServiceRequest"


def _extract_mrn_from_text(text: str) -> str | None:
	match = re.search(r"\b(?:MRN|Patient\s*MRN)\s*:\s*([^\s\n]+)", text, flags=re.IGNORECASE)
	return match.group(1).strip() if match else None


def _extract_dme_from_text(text: str) -> str | None:
	match = re.search(
		r"(?:Equipment\s*Ordered|DME\s*Equipment|Durable\s*Medical\s*Equipment\s*\(DME\))\s*:\s*(.+)",
		text,
		flags=re.IGNORECASE,
	)
	return match.group(1).strip() if match else None


def extract_dme_order(text: str) -> dict:
	"""Extract MRN and DME equipment from discharge text and return a FHIR ServiceRequest JSON."""
	client = InferenceClient(provider="featherless-ai", api_key=HF_TOKEN)

	prompt = (
		"You are a Clinical Data Extraction Agent. Extract the Patient MRN and the Durable Medical Equipment (DME) order. "
		"Output ONLY a valid FHIR ServiceRequest JSON object. "
		"Use this structure exactly: "
		"{\"resourceType\":\"ServiceRequest\",\"status\":\"active\",\"intent\":\"order\","
		"\"subject\":{\"identifier\":{\"system\":\"urn:mrn\",\"value\":\"<MRN>\"}},"
		"\"code\":{\"text\":\"<DME Equipment>\"}}.\n\n"
		f"Discharge Summary:\n{text}\n"
	)

	raw_content = client.text_generation(
		prompt,
		model=HF_MODEL_ID,
		max_new_tokens=350,
		temperature=0.1,
	)

	try:
		parsed = json.loads(raw_content)
	except json.JSONDecodeError:
		brace_match = re.search(r"\{", raw_content)
		end_brace_index = raw_content.rfind("}")
		if not brace_match or end_brace_index == -1 or end_brace_index <= brace_match.start():
			parsed = {}
		else:
			json_str = raw_content[brace_match.start() : end_brace_index + 1]
			try:
				parsed = json.loads(json_str)
			except json.JSONDecodeError:
				parsed = {}

	mrn = (
		parsed.get("subject", {}).get("identifier", {}).get("value")
		or parsed.get("subject", {}).get("reference", "").replace("Patient/", "")
		or parsed.get("MRN")
		or parsed.get("mrn")
		or parsed.get("patient_mrn")
	)

	dme_equipment = (
		parsed.get("code", {}).get("text")
		or parsed.get("code", {}).get("coding", [{}])[0].get("display")
		or parsed.get("DME Equipment")
		or parsed.get("dme_equipment")
		or parsed.get("equipment")
	)

	# Deterministic fallback from known discharge summary format.
	if not mrn:
		mrn = _extract_mrn_from_text(text)
	if not mrn:
		mrn = _extract_mrn_from_text(raw_content)
	if not dme_equipment:
		dme_equipment = _extract_dme_from_text(text)
	if not dme_equipment:
		dme_equipment = _extract_dme_from_text(raw_content)

	mrn = mrn or "unknown"
	dme_equipment = dme_equipment or "unknown"

	return {
		"resourceType": "ServiceRequest",
		"status": "active",
		"intent": "order",
		"subject": {
			"identifier": {
				"system": "urn:mrn",
				"value": mrn,
			}
		},
		"code": {
			"text": dme_equipment,
		},
	}


def sync_to_medplum(fhir_json: dict) -> bool:
	"""POST ServiceRequest JSON to Medplum and show success UI on HTTP 201."""
	headers = {
		"Authorization": f"Bearer {MEDPLUM_TOKEN}",
		"Content-Type": "application/fhir+json",
	}

	response = requests.post(
		MEDPLUM_SERVICE_REQUEST_URL,
		headers=headers,
		json=fhir_json,
		timeout=60,
	)

	if response.status_code == 201:
		st.success("ServiceRequest synced to Medplum.")
		st.balloons()
		return True

	st.error(f"Medplum sync failed ({response.status_code}): {response.text}")
	return False


st.set_page_config(page_title="HomeBound Discharge Portal", layout="wide")

st.title("🏥 HomeBound Discharge Portal")

uploaded_file = st.file_uploader("Upload discharge summary (.txt)", type=["txt"])

if uploaded_file is not None:
	file_text = uploaded_file.getvalue().decode("utf-8", errors="replace")
	if "extraction" not in st.session_state:
		st.session_state["extraction"] = None

	left_col, right_col = st.columns(2)

	with left_col:
		st.subheader("Uploaded Discharge Summary")
		st.text_area(
			"Summary Text",
			value=file_text,
			height=500,
		)

	with right_col:
		st.subheader("AI Extraction")
		st.info("Extraction results will appear here after processing.")

		if st.button("Process Discharge Summary"):
			if not HF_TOKEN:
				st.error("HF_TOKEN is missing. Add it to Streamlit secrets.")
			else:
				try:
					extraction = extract_dme_order(file_text)
					st.session_state["extraction"] = extraction
					st.success("Extraction completed.")
					st.json(extraction)
				except Exception as exc:
					st.error(f"Extraction failed: {exc}")

		if st.session_state.get("extraction"):
			st.json(st.session_state["extraction"])
			if st.button("Sync to Medplum"):
				if MEDPLUM_TOKEN == "YOUR_MEDPLUM_BEARER_TOKEN":
					st.error("MEDPLUM_TOKEN placeholder detected. Set a real Bearer token in Streamlit secrets.")
				else:
					sync_to_medplum(st.session_state["extraction"])
