import json
import os
import re
from datetime import datetime, timezone

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
MEDPLUM_BASE_URL = "https://api.medplum.com/fhir/R4"
MEDPLUM_SERVICE_REQUEST_URL = "https://api.medplum.com/fhir/R4/ServiceRequest"
MEDPLUM_PATIENT_URL = "https://api.medplum.com/fhir/R4/Patient"


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


def _extract_name_from_text(text: str) -> str | None:
	match = re.search(r"\bName\s*:\s*(.+)", text, flags=re.IGNORECASE)
	return match.group(1).strip() if match else None


def _extract_dob_from_text(text: str) -> str | None:
	match = re.search(r"\bDate\s+of\s+Birth\s*:\s*(.+)", text, flags=re.IGNORECASE)
	return match.group(1).strip() if match else None


def _extract_sex_from_text(text: str) -> str | None:
	match = re.search(r"\bSex\s*:\s*(.+)", text, flags=re.IGNORECASE)
	return match.group(1).strip() if match else None


def _extract_address_from_text(text: str) -> str | None:
	match = re.search(r"\bAddress\s*:\s*(.+)", text, flags=re.IGNORECASE)
	return match.group(1).strip() if match else None


def _extract_clinical_course_from_text(text: str) -> str | None:
	match = re.search(
		r"CLINICAL\s+COURSE:\s*(.+?)(?:\n\s*=\s*=\s*=|\n\s*DISCHARGE\s+PLAN:|$)",
		text,
		flags=re.IGNORECASE | re.DOTALL,
	)
	if not match:
		return None
	course = re.sub(r"\s+", " ", match.group(1)).strip()
	return course or None


def _clean_dme_text(value: str | None) -> str | None:
	if not value:
		return value
	cleaned = re.sub(
		r"^(?:Equipment\s*Ordered|DME\s*Equipment|Durable\s*Medical\s*Equipment\s*\(DME\))\s*:\s*",
		"",
		value,
		flags=re.IGNORECASE,
	)
	cleaned = re.sub(r"\s+", " ", cleaned).strip()
	return cleaned or None


def _extract_note_value(notes: list[dict], prefix: str) -> str | None:
	for note in notes:
		text = note.get("text", "")
		if text.lower().startswith(prefix.lower()):
			return text.split(":", 1)[1].strip() if ":" in text else None
	return None


def _split_name(full_name: str) -> tuple[str, str]:
	parts = full_name.split()
	if not parts:
		return "Unknown", "Patient"
	if len(parts) == 1:
		return parts[0], "Patient"
	return " ".join(parts[:-1]), parts[-1]


def _parse_fhir_address(address_text: str) -> dict:
	parts = [part.strip() for part in address_text.split(",") if part.strip()]
	if len(parts) >= 4:
		return {
			"line": [parts[0]],
			"city": parts[1],
			"state": parts[2],
			"postalCode": parts[3],
		}
	return {"text": address_text}


def _build_patient_resource(service_request: dict) -> dict:
	subject = service_request.get("subject", {})
	notes = service_request.get("note", [])

	mrn = subject.get("identifier", {}).get("value", "unknown")
	full_name = subject.get("display") or "Unknown Patient"
	given, family = _split_name(full_name)

	dob = _extract_note_value(notes, "DOB")
	sex = _extract_note_value(notes, "Sex")
	address_text = _extract_note_value(notes, "Address")

	patient = {
		"resourceType": "Patient",
		"identifier": [
			{
				"system": "urn:mrn",
				"value": mrn,
			}
		],
		"name": [
			{
				"family": family,
				"given": [given],
				"text": full_name,
			}
		],
	}

	if dob:
		patient["birthDate"] = dob
	if sex:
		patient["gender"] = sex.lower()
	if address_text:
		patient["address"] = [_parse_fhir_address(address_text)]

	return patient


def _build_extraction_payload(service_request: dict) -> dict:
	"""Build a professional extraction payload for UI and downstream integrations."""
	patient_resource = _build_patient_resource(service_request)
	return {
		"resourceType": "Bundle",
		"type": "collection",
		"patient_profile": patient_resource,
		"service_request": service_request,
	}


def _find_or_create_patient(patient_resource: dict, headers: dict) -> str:
	mrn = patient_resource["identifier"][0]["value"]
	search_url = f"{MEDPLUM_PATIENT_URL}?identifier=urn:mrn|{mrn}"
	search_response = requests.get(search_url, headers=headers, timeout=60)
	search_response.raise_for_status()
	bundle = search_response.json()

	entries = bundle.get("entry", []) if isinstance(bundle, dict) else []
	if entries:
		patient_id = entries[0].get("resource", {}).get("id")
		if patient_id:
			return patient_id

	create_response = requests.post(
		MEDPLUM_PATIENT_URL,
		headers=headers,
		json=patient_resource,
		timeout=60,
	)
	create_response.raise_for_status()
	created = create_response.json()
	return created.get("id", "")


def extract_dme_order(text: str) -> dict:
	"""Extract MRN/DME and return a professional payload with Patient + ServiceRequest."""
	client = InferenceClient(provider="featherless-ai", api_key=HF_TOKEN)

	prompt = (
		"You are a Clinical Data Extraction Agent. Extract the Patient MRN, Durable Medical Equipment (DME) order, and Clinical Course narrative. "
		"Output ONLY a valid FHIR ServiceRequest JSON object. "
		"Use this structure exactly: "
		"{\"resourceType\":\"ServiceRequest\",\"status\":\"active\",\"intent\":\"order\","
		"\"subject\":{\"identifier\":{\"system\":\"urn:mrn\",\"value\":\"<MRN>\"}},"
		"\"code\":{\"text\":\"<DME Equipment>\"},"
		"\"note\":[{\"text\":\"Clinical Course: <clinical course summary>\"}]}.\n\n"
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

	patient_name = _extract_name_from_text(text)
	patient_dob = _extract_dob_from_text(text)
	patient_sex = _extract_sex_from_text(text)
	patient_address = _extract_address_from_text(text)
	clinical_course = (
		_extract_note_value(parsed.get("note", []), "Clinical Course")
		or parsed.get("clinical_course")
		or _extract_clinical_course_from_text(text)
	)

	mrn = mrn or "unknown"
	dme_equipment = _clean_dme_text(dme_equipment) or "unknown"

	subject_obj = {
		"identifier": {
			"system": "urn:mrn",
			"value": mrn,
		}
	}
	if patient_name:
		subject_obj["display"] = patient_name

	notes = []
	if patient_dob:
		notes.append({"text": f"DOB: {patient_dob}"})
	if patient_sex:
		notes.append({"text": f"Sex: {patient_sex}"})
	if patient_address:
		notes.append({"text": f"Address: {patient_address}"})
	if clinical_course:
		notes.append({"text": f"Clinical Course: {clinical_course}"})

	service_request = {
		"resourceType": "ServiceRequest",
		"status": "active",
		"intent": "order",
		"subject": subject_obj,
		"code": {
			"text": dme_equipment,
		},
	}
	if notes:
		service_request["note"] = notes

	return _build_extraction_payload(service_request)


def sync_to_medplum(fhir_json: dict) -> bool:
	"""Upsert Patient and POST linked ServiceRequest to Medplum."""
	headers = {
		"Authorization": f"Bearer {MEDPLUM_TOKEN}",
		"Content-Type": "application/fhir+json",
	}

	try:
		if fhir_json.get("resourceType") == "Bundle":
			service_request_input = fhir_json.get("service_request", {})
			patient_resource = fhir_json.get("patient_profile") or _build_patient_resource(service_request_input)
		else:
			service_request_input = fhir_json
			patient_resource = _build_patient_resource(service_request_input)

		if not service_request_input or service_request_input.get("resourceType") != "ServiceRequest":
			st.error("Extraction payload is missing a valid ServiceRequest.")
			return False

		patient_id = _find_or_create_patient(patient_resource, headers)
		if not patient_id:
			st.error("Could not determine Patient ID for Medplum sync.")
			return False

		service_request = dict(service_request_input)
		service_request["subject"] = {
			"reference": f"Patient/{patient_id}",
			"display": patient_resource.get("name", [{}])[0].get("text", "Unknown Patient"),
		}
		service_request["authoredOn"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

		response = requests.post(
			MEDPLUM_SERVICE_REQUEST_URL,
			headers=headers,
			json=service_request,
			timeout=60,
		)

		if response.status_code == 201:
			created_sr = response.json()
			st.success(
				f"Patient and ServiceRequest synced to Medplum. "
				f"Patient/{patient_id}, ServiceRequest/{created_sr.get('id', 'created')}"
			)
			st.balloons()
			return True

		st.error(f"Medplum sync failed ({response.status_code}): {response.text}")
		return False
	except Exception as exc:
		st.error(f"Medplum sync failed: {exc}")
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
				except Exception as exc:
					st.error(f"Extraction failed: {exc}")

		if st.session_state.get("extraction"):
			st.json(st.session_state["extraction"])
			if st.button("Sync to Medplum"):
				if MEDPLUM_TOKEN == "YOUR_MEDPLUM_BEARER_TOKEN":
					st.error("MEDPLUM_TOKEN placeholder detected. Set a real Bearer token in Streamlit secrets.")
				else:
					sync_to_medplum(st.session_state["extraction"])
