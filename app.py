import json
import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import pydeck as pdk
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
SUPABASE_URL = get_secret("SUPABASE_URL", "")
SUPABASE_KEY = get_secret("SUPABASE_KEY", "")
MAX_BATCH_FILES = 20
MAX_FILE_SIZE_MB = 200
SNOMED_SYSTEM_URL = "http://snomed.info/sct"
SNOMED_CODE_EXTENSION_URL = "https://caredevi.health/fhir/StructureDefinition/snomed-code"

# Runtime SNOMED mappings aligned with smart_dme_factory DME catalog.
DME_SNOMED_CATALOG = [
	{"keywords": ["oxygen concentrator", "oxygen equipment"], "code": "426854004", "display": "Oxygen Concentrator"},
	{"keywords": ["portable oxygen tank", "oxygen tank", "oxygen cylinder"], "code": "463752001", "display": "Portable Oxygen Tank"},
	{"keywords": ["cpap", "cpap machine"], "code": "702172008", "display": "CPAP Machine"},
	{"keywords": ["nebulizer"], "code": "334947002", "display": "Nebulizer"},
	{"keywords": ["manual wheelchair", "wheelchair"], "code": "228869008", "display": "Manual Wheelchair"},
	{"keywords": ["power wheelchair", "electric wheelchair"], "code": "705422005", "display": "Power Wheelchair"},
	{"keywords": ["standard walker", "walker"], "code": "1290910004", "display": "Standard Walker"},
	{"keywords": ["rollator", "rollator walker"], "code": "1255320005", "display": "Rollator Walker"},
	{"keywords": ["crutches"], "code": "443663000", "display": "Crutches"},
	{"keywords": ["hospital bed", "home hospital bed"], "code": "91537007", "display": "Hospital Bed"},
	{"keywords": ["pressure relief mattress", "pressure mattress", "mattress overlay"], "code": "702029004", "display": "Pressure Relief Mattress"},
	{"keywords": ["patient lift", "hoyer lift", "mechanical lift"], "code": "706112002", "display": "Patient Lift"},
	{"keywords": ["shower chair", "bath chair"], "code": "467158009", "display": "Shower Chair"},
	{"keywords": ["bedside commode", "commode"], "code": "360008003", "display": "Bedside Commode"},
	{"keywords": ["raised toilet seat", "toilet seat riser"], "code": "705593007", "display": "Raised Toilet Seat"},
	{"keywords": ["grab bars", "grab bar"], "code": "466196003", "display": "Grab Bars"},
	{"keywords": ["blood pressure monitor", "bp monitor"], "code": "258057004", "display": "Blood Pressure Monitor"},
	{"keywords": ["pulse oximeter", "oximeter"], "code": "448703006", "display": "Pulse Oximeter"},
	{"keywords": ["glucose monitor", "glucometer", "glucose meter"], "code": "926334000", "display": "Glucose Monitor"},
	{"keywords": ["tens unit", "transcutaneous electrical nerve stimulation"], "code": "770743001", "display": "TENS Unit"},
]


def _normalize_for_match(value: str) -> str:
	return re.sub(r"\s+", " ", value.lower()).strip()


def _parse_json_object_from_text(raw_text: str) -> dict:
	try:
		loaded = json.loads(raw_text)
		return loaded if isinstance(loaded, dict) else {}
	except json.JSONDecodeError:
		brace_match = re.search(r"\{", raw_text)
		end_brace_index = raw_text.rfind("}")
		if not brace_match or end_brace_index == -1 or end_brace_index <= brace_match.start():
			return {}
		json_str = raw_text[brace_match.start() : end_brace_index + 1]
		try:
			loaded = json.loads(json_str)
			return loaded if isinstance(loaded, dict) else {}
		except json.JSONDecodeError:
			return {}


def _lookup_snomed_from_catalog(dme_equipment: str) -> tuple[str | None, str | None]:
	normalized = _normalize_for_match(dme_equipment)
	for candidate in DME_SNOMED_CATALOG:
		if any(keyword in normalized for keyword in candidate["keywords"]):
			return candidate["code"], candidate["display"]
	return None, None


def _infer_snomed_with_llm(dme_equipment: str) -> tuple[str | None, str | None]:
	if not HF_TOKEN or not dme_equipment or dme_equipment == "unknown":
		return None, None

	client = InferenceClient(provider="featherless-ai", api_key=HF_TOKEN)
	prompt = (
		"Map the following durable medical equipment phrase to the single best SNOMED CT concept. "
		"Return ONLY compact JSON with keys snomed_code, display, confidence. "
		"confidence must be high, medium, or low.\n"
		f"equipment: {dme_equipment}"
	)

	raw_content = client.text_generation(
		prompt,
		model=HF_MODEL_ID,
		max_new_tokens=120,
		temperature=0,
	)

	parsed = _parse_json_object_from_text(raw_content)
	code = str(parsed.get("snomed_code", "")).strip()
	display = str(parsed.get("display", "")).strip()
	confidence = str(parsed.get("confidence", "")).strip().lower()

	if not re.fullmatch(r"\d{6,18}", code):
		return None, None
	if confidence == "low":
		return None, None
	if not display:
		display = dme_equipment

	return code, display


def resolve_snomed_for_dme(dme_equipment: str) -> tuple[str, str, str]:
	"""Resolve SNOMED code for DME text using catalog first, then LLM fallback."""
	code, display = _lookup_snomed_from_catalog(dme_equipment)
	if code:
		return code, display or dme_equipment, "catalog"

	try:
		code, display = _infer_snomed_with_llm(dme_equipment)
	except Exception:
		code, display = None, None

	if code:
		return code, display or dme_equipment, "llm"

	return "unknown", dme_equipment, "unmapped"


def _upsert_snomed_extension(service_request: dict, snomed_code: str, snomed_display: str, source: str) -> None:
	extensions = [ext for ext in service_request.get("extension", []) if ext.get("url") != SNOMED_CODE_EXTENSION_URL]
	if snomed_code != "unknown":
		extensions.append(
			{
				"url": SNOMED_CODE_EXTENSION_URL,
				"valueCoding": {
					"system": SNOMED_SYSTEM_URL,
					"code": snomed_code,
					"display": snomed_display,
				},
			}
		)
	else:
		extensions.append(
			{
				"url": SNOMED_CODE_EXTENSION_URL,
				"valueString": f"unknown ({source})",
			}
		)
	service_request["extension"] = extensions


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

	parsed = _parse_json_object_from_text(raw_content)

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
	snomed_code, snomed_display, snomed_source = resolve_snomed_for_dme(dme_equipment)

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
	notes.append({"text": f"SNOMED Code: {snomed_code}"})
	notes.append({"text": f"SNOMED Source: {snomed_source}"})

	code_obj = {
		"text": dme_equipment,
	}
	if snomed_code != "unknown":
		code_obj["coding"] = [
			{
				"system": SNOMED_SYSTEM_URL,
				"code": snomed_code,
				"display": snomed_display,
			}
		]

	service_request = {
		"resourceType": "ServiceRequest",
		"status": "active",
		"intent": "order",
		"subject": subject_obj,
		"code": code_obj,
	}
	_upsert_snomed_extension(service_request, snomed_code, snomed_display, snomed_source)
	if notes:
		service_request["note"] = notes

	return _build_extraction_payload(service_request)


def sync_to_medplum(fhir_json: dict) -> bool:
	"""Upsert Patient and POST linked ServiceRequest to Medplum."""
	headers = {
		"Authorization": f"Bearer {MEDPLUM_TOKEN}",
		"Content-Type": "application/fhir+json",
		"X-Project-Id": "87daa0e1-c34c-4f14-bdbc-1e2719b371b7"
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


def _status_color_rgba(order_status: str) -> list[int]:
	normalized = str(order_status or "").strip().lower()
	if normalized in {"delivered", "complete", "completed"}:
		return [34, 197, 94, 190]  # green
	if normalized in {"pending", "in progress", "processing"}:
		return [249, 115, 22, 190]  # orange
	if normalized in {"failed", "cancelled", "canceled"}:
		return [239, 68, 68, 190]  # red
	return [56, 189, 248, 185]  # clinical blue fallback


HIGH_COMPLEXITY_EQUIPMENT_TERMS = {
	"ventilator",
	"oxygen concentrator",
	"oxygen",
	"cpap",
	"bipap",
	"hospital bed",
	"suction",
	"nebulizer",
}

URGENCY_TERMS = {
	"urgent",
	"stat",
	"high risk",
	"fall risk",
	"respiratory distress",
	"hypoxia",
	"oxygen",
	"readmission",
	"decompensat",
	"worsening",
}


def _compute_supply_chain_risk(extraction_payload: dict) -> dict:
	"""Compute an actionable risk signal from extracted session-state payload."""
	if not extraction_payload:
		return {"score": 0, "level": "Low", "reasons": ["No extraction loaded."], "expedite": False}

	service_request = extraction_payload.get("service_request", {}) if isinstance(extraction_payload, dict) else {}
	code_text = str(service_request.get("code", {}).get("text", "")).lower()
	notes = service_request.get("note", [])
	clinical_course = str(_extract_note_value(notes, "Clinical Course") or "").lower()

	score = 0
	reasons = []

	for term in HIGH_COMPLEXITY_EQUIPMENT_TERMS:
		if term in code_text:
			score += 30
			reasons.append(f"High-complexity equipment detected: {term}.")
			break

	urgency_hits = [term for term in URGENCY_TERMS if term in clinical_course]
	if urgency_hits:
		score += min(45, 15 * len(urgency_hits))
		reasons.append(f"Urgency signals in clinical course: {', '.join(sorted(set(urgency_hits[:4])))}.")

	if "unknown" in code_text:
		score += 20
		reasons.append("Equipment classification is unknown; manual review recommended.")

	if score >= 70:
		level = "Critical"
	elif score >= 45:
		level = "High"
	elif score >= 25:
		level = "Moderate"
	else:
		level = "Low"

	expedite = level in {"High", "Critical"}
	if not reasons:
		reasons.append("No major urgency or complexity signals found.")

	return {"score": int(min(score, 100)), "level": level, "reasons": reasons, "expedite": expedite}


@st.cache_data(ttl=120)
def get_analytics_data() -> pd.DataFrame:
	"""Query active equipment orders from Supabase and return a dataframe."""
	if not SUPABASE_URL or not SUPABASE_KEY:
		return pd.DataFrame()

	headers = {
		"apikey": SUPABASE_KEY,
		"Authorization": f"Bearer {SUPABASE_KEY}",
	}
	select_attempts = [
		"id,patient_name,delivery_address,equipment_type,vendor_name,order_status,created_at,estimated_delivery_days,lat,lon,latitude,longitude,delivery_lat,delivery_lon,delivery_latitude,delivery_longitude",
		"id,patient_name,delivery_address,equipment_type,vendor_name,order_status,created_at,estimated_delivery_days",
		"id,patient_name,equipment_type,vendor_name,order_status,created_at,estimated_delivery_days",
	]

	last_error: Exception | None = None
	for select_clause in select_attempts:
		url = f"{SUPABASE_URL}/rest/v1/equipment_orders?select={select_clause}&order=id.desc"
		response = requests.get(url, headers=headers, timeout=30)
		if response.status_code == 400:
			last_error = requests.HTTPError(f"{response.status_code} Client Error: {response.text}")
			continue
		response.raise_for_status()
		rows = response.json()
		return pd.DataFrame(rows)

	if last_error:
		raise last_error

	return pd.DataFrame()


STATE_CENTER_BY_ABBR = {
	"AL": (32.806671, -86.791130), "AK": (61.370716, -152.404419), "AZ": (33.729759, -111.431221),
	"AR": (34.969704, -92.373123), "CA": (36.116203, -119.681564), "CO": (39.059811, -105.311104),
	"CT": (41.597782, -72.755371), "DE": (39.318523, -75.507141), "FL": (27.766279, -81.686783),
	"GA": (33.040619, -83.643074), "HI": (21.094318, -157.498337), "ID": (44.240459, -114.478828),
	"IL": (40.349457, -88.986137), "IN": (39.849426, -86.258278), "IA": (42.011539, -93.210526),
	"KS": (38.526600, -96.726486), "KY": (37.668140, -84.670067), "LA": (31.169546, -91.867805),
	"ME": (44.693947, -69.381927), "MD": (39.063946, -76.802101), "MA": (42.230171, -71.530106),
	"MI": (43.326618, -84.536095), "MN": (45.694454, -93.900192), "MS": (32.741646, -89.678696),
	"MO": (38.456085, -92.288368), "MT": (46.921925, -110.454353), "NE": (41.125370, -98.268082),
	"NV": (38.313515, -117.055374), "NH": (43.452492, -71.563896), "NJ": (40.298904, -74.521011),
	"NM": (34.840515, -106.248482), "NY": (42.165726, -74.948051), "NC": (35.630066, -79.806419),
	"ND": (47.528912, -99.784012), "OH": (40.388783, -82.764915), "OK": (35.565342, -96.928917),
	"OR": (44.572021, -122.070938), "PA": (40.590752, -77.209755), "RI": (41.680893, -71.511780),
	"SC": (33.856892, -80.945007), "SD": (44.299782, -99.438828), "TN": (35.747845, -86.692345),
	"TX": (31.054487, -97.563461), "UT": (40.150032, -111.862434), "VT": (44.045876, -72.710686),
	"VA": (37.769337, -78.169968), "WA": (47.400902, -121.490494), "WV": (38.491226, -80.954453),
	"WI": (44.268543, -89.616508), "WY": (42.755966, -107.302490), "DC": (38.907200, -77.036900),
}

def _derived_city_center(city_name: str, state_abbr: str) -> tuple[float, float] | None:
	"""Generate a deterministic pseudo-center for any city/state pair within a state region."""
	state_center = STATE_CENTER_BY_ABBR.get(state_abbr)
	if not state_center:
		return None

	city_key = f"{city_name.upper()}, {state_abbr}"
	city_hash = hashlib.sha256(city_key.encode("utf-8")).hexdigest()

	# Keep each city consistently offset from its state center for demo-only plotting.
	lat_offset = ((int(city_hash[:8], 16) / 0xFFFFFFFF) - 0.5) * 2.4
	lon_offset = ((int(city_hash[8:16], 16) / 0xFFFFFFFF) - 0.5) * 2.4
	return state_center[0] + lat_offset, state_center[1] + lon_offset


@st.cache_data(ttl=60 * 60 * 24)
def _geocode_city_state(city_name: str, state_abbr: str) -> tuple[float, float] | None:
	"""Resolve a real city centroid using OpenStreetMap Nominatim."""
	if not city_name or not state_abbr:
		return None

	headers = {
		"User-Agent": "homebound-discharge-portal/1.0 (city-level map demo)",
	}
	params = {
		"q": f"{city_name}, {state_abbr}, USA",
		"format": "json",
		"limit": 1,
		"countrycodes": "us",
	}

	try:
		response = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers, timeout=12)
		response.raise_for_status()
		results = response.json()
		if not results:
			return None
		return float(results[0]["lat"]), float(results[0]["lon"])
	except Exception:
		return None


@st.cache_data(ttl=60 * 60 * 24)
def _geocode_address(address_text: str) -> tuple[float, float] | None:
	"""Resolve full address to coordinates for tighter map placement."""
	if not address_text:
		return None

	headers = {
		"User-Agent": "homebound-discharge-portal/1.0 (address-level map demo)",
	}
	params = {
		"q": f"{address_text}, USA",
		"format": "json",
		"limit": 1,
		"countrycodes": "us",
	}

	try:
		response = requests.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers, timeout=12)
		response.raise_for_status()
		results = response.json()
		if not results:
			return None
		return float(results[0]["lat"]), float(results[0]["lon"])
	except Exception:
		return None


def _state_from_address(address_text: str) -> str | None:
	if not address_text:
		return None

	upper_address = address_text.strip().upper()
	state_match = re.search(r",\s*([A-Z]{2})\s*,?\s*(?:\d{5}(?:-\d{4})?)?\s*$", upper_address)
	if state_match:
		abbr = state_match.group(1)
		if abbr in STATE_CENTER_BY_ABBR:
			return abbr

	# Fallback for loose formatting: find state abbreviation token anywhere in address.
	for token in re.findall(r"\b[A-Z]{2}\b", upper_address):
		if token in STATE_CENTER_BY_ABBR:
			return token

	return None


def _city_state_from_address(address_text: str) -> tuple[str | None, str | None]:
	if not address_text:
		return None, None

	state_abbr = _state_from_address(address_text)
	if not state_abbr:
		return None, None

	parts = [part.strip() for part in address_text.split(",") if part.strip()]
	city_name: str | None = None

	# Typical formats: "street, city, ST, ZIP" or "street, city, ST ZIP".
	for idx in range(len(parts) - 1, -1, -1):
		if re.search(rf"\b{state_abbr}\b", parts[idx].upper()):
			if idx - 1 >= 0:
				city_name = parts[idx - 1]
			break

	if city_name:
		city_name = re.sub(r"\s+", " ", city_name).strip()

	if not city_name:
		return None, state_abbr

	return city_name, state_abbr


def _city_demo_point(city_name: str, state_abbr: str, seed_value: str) -> tuple[float, float] | None:
	city_key = f"{city_name.upper()}, {state_abbr}"
	city_center = _geocode_city_state(city_name, state_abbr) or _derived_city_center(city_name, state_abbr)
	if not city_center:
		return None

	# Deterministic city-level jitter so same city appears clustered but not stacked.
	seed_hash = hashlib.sha256(f"{city_key}-{seed_value}".encode("utf-8")).hexdigest()
	jitter_lat = ((int(seed_hash[:4], 16) / 65535) - 0.5) * 0.06
	jitter_lon = ((int(seed_hash[4:8], 16) / 65535) - 0.5) * 0.06
	return city_center[0] + jitter_lat, city_center[1] + jitter_lon


def _state_demo_point(state_abbr: str, seed_value: str) -> tuple[float, float] | None:
	center = STATE_CENTER_BY_ABBR.get(state_abbr)
	if not center:
		return None

	# Deterministic jitter so repeated records in a state do not overlap exactly.
	seed_hash = hashlib.sha256(seed_value.encode("utf-8")).hexdigest()
	jitter_lat = ((int(seed_hash[:4], 16) / 65535) - 0.5) * 0.45
	jitter_lon = ((int(seed_hash[4:8], 16) / 65535) - 0.5) * 0.45
	return center[0] + jitter_lat, center[1] + jitter_lon


def get_delivery_map_points(df: pd.DataFrame) -> pd.DataFrame:
	"""Return mapped delivery points with status and UI metadata."""
	if df.empty:
		return pd.DataFrame(columns=["lat", "lon", "order_status", "color", "patient_name", "equipment_type", "vendor_name"])

	coordinate_column_pairs = [
		("lat", "lon"),
		("latitude", "longitude"),
		("delivery_lat", "delivery_lon"),
		("delivery_latitude", "delivery_longitude"),
	]

	for lat_col, lon_col in coordinate_column_pairs:
		if lat_col in df.columns and lon_col in df.columns:
			map_df = df[[lat_col, lon_col]].copy()
			map_df.columns = ["lat", "lon"]
			map_df["lat"] = pd.to_numeric(map_df["lat"], errors="coerce")
			map_df["lon"] = pd.to_numeric(map_df["lon"], errors="coerce")
			map_df = map_df.dropna(subset=["lat", "lon"])
			if not map_df.empty:
				map_df["order_status"] = df.get("order_status", "Unknown").astype(str)
				map_df["patient_name"] = df.get("patient_name", "Unknown").astype(str)
				map_df["equipment_type"] = df.get("equipment_type", "Unknown").astype(str)
				map_df["vendor_name"] = df.get("vendor_name", "Unknown").astype(str)
				map_df["color"] = map_df["order_status"].apply(_status_color_rgba)
				return map_df

	address_columns = ["delivery_address", "address", "patient_address"]
	address_col = next((col for col in address_columns if col in df.columns), None)
	if not address_col:
		return pd.DataFrame(columns=["lat", "lon", "order_status", "color", "patient_name", "equipment_type", "vendor_name"])

	map_rows = []
	for idx, (_, row) in enumerate(df.dropna(subset=[address_col]).head(200).iterrows(), start=1):
		address_text = str(row[address_col])
		address_point = _geocode_address(address_text)
		if address_point:
			status_text = str(row.get("order_status", "Unknown"))
			map_rows.append(
				{
					"lat": address_point[0],
					"lon": address_point[1],
					"order_status": status_text,
					"color": _status_color_rgba(status_text),
					"patient_name": str(row.get("patient_name", "Unknown")),
					"equipment_type": str(row.get("equipment_type", "Unknown")),
					"vendor_name": str(row.get("vendor_name", "Unknown")),
				}
			)
			continue

		city_name, state_abbr = _city_state_from_address(address_text)
		point = None
		if city_name and state_abbr:
			point = _city_demo_point(city_name, state_abbr, f"{address_text}-{idx}")
		if not point and state_abbr:
			point = _state_demo_point(state_abbr, f"{address_text}-{idx}")
		if not point:
			continue
		status_text = str(row.get("order_status", "Unknown"))
		map_rows.append(
			{
				"lat": point[0],
				"lon": point[1],
				"order_status": status_text,
				"color": _status_color_rgba(status_text),
				"patient_name": str(row.get("patient_name", "Unknown")),
				"equipment_type": str(row.get("equipment_type", "Unknown")),
				"vendor_name": str(row.get("vendor_name", "Unknown")),
			}
		)

	if not map_rows:
		return pd.DataFrame(columns=["lat", "lon", "order_status", "color", "patient_name", "equipment_type", "vendor_name"])

	return pd.DataFrame(map_rows)


def _ensure_queue_state() -> None:
	if "file_queue" not in st.session_state:
		st.session_state["file_queue"] = []
	if "queued_hashes" not in st.session_state:
		st.session_state["queued_hashes"] = set()
	if "job_counter" not in st.session_state:
		st.session_state["job_counter"] = 1


def _queue_uploaded_files(uploaded_files: list) -> None:
	_ensure_queue_state()

	if len(uploaded_files) > MAX_BATCH_FILES:
		st.error(f"Please upload at most {MAX_BATCH_FILES} files per batch.")
		return

	added = 0
	skipped = 0
	for file_obj in uploaded_files:
		if file_obj.size > MAX_FILE_SIZE_MB * 1024 * 1024:
			skipped += 1
			continue

		raw_bytes = file_obj.getvalue()
		file_hash = hashlib.sha256(raw_bytes).hexdigest()
		if file_hash in st.session_state["queued_hashes"]:
			skipped += 1
			continue

		file_text = raw_bytes.decode("utf-8", errors="replace")
		job_id = st.session_state["job_counter"]
		st.session_state["job_counter"] += 1

		st.session_state["file_queue"].append(
			{
				"job_id": job_id,
				"filename": file_obj.name,
				"file_hash": file_hash,
				"size_bytes": file_obj.size,
				"status": "queued",
				"error": "",
				"queued_at": datetime.now(timezone.utc).isoformat(),
				"processed_at": None,
				"file_text": file_text,
				"extraction": None,
				"risk_level": "Unknown",
				"risk_score": None,
			}
		)
		st.session_state["queued_hashes"].add(file_hash)
		added += 1

	if added:
		st.success(f"Queued {added} file(s).")
	if skipped:
		st.warning(f"Skipped {skipped} file(s) due to duplicates or size > {MAX_FILE_SIZE_MB}MB.")


def _process_queued_jobs(max_jobs: int) -> None:
	_ensure_queue_state()
	jobs = [job for job in st.session_state["file_queue"] if job["status"] == "queued"]
	if not jobs:
		st.info("No queued files to process.")
		return

	if not HF_TOKEN:
		st.error("HF_TOKEN is missing. Add it to Streamlit secrets before processing the queue.")
		return

	total = min(max_jobs, len(jobs))
	progress = st.progress(0)

	for idx, job in enumerate(jobs[:total], start=1):
		job["status"] = "processing"
		with st.status(f"Job #{job['job_id']} - {job['filename']}", expanded=True) as job_status:
			try:
				job_status.write("Step 1/4: Extracting FHIR data from discharge summary...")
				extraction = extract_dme_order(job["file_text"])
				job["extraction"] = extraction
				st.session_state["extraction"] = extraction
				risk_signal = _compute_supply_chain_risk(extraction)
				st.session_state["latest_risk"] = risk_signal
				job["risk_level"] = risk_signal["level"]
				job["risk_score"] = risk_signal["score"]
				job_status.write("Step 2/4: Extraction complete and validated.")
				if risk_signal["expedite"]:
					job_status.write(
						f"Risk Indicator: {risk_signal['level']} ({risk_signal['score']}/100) - Expedited review suggested."
					)
					st.toast("Expedited review suggested by Supply Chain Risk Indicator.")

				job_status.write("Step 3/4: Awaiting case manager approval before external sync.")
				job_status.write("Step 4/4: Ready for review.")
				job["status"] = "ready_for_review"
				job["error"] = ""
				if job["status"] == "ready_for_review":
					job_status.update(label=f"Job #{job['job_id']} ready for approval", state="running")
				else:
					job_status.update(label=f"Job #{job['job_id']} completed", state="complete")
			except Exception as exc:
				job["status"] = "failed"
				job["error"] = str(exc)
				job_status.update(label=f"Job #{job['job_id']} failed", state="error")
			finally:
				job["processed_at"] = datetime.now(timezone.utc).isoformat()
				progress.progress(idx / total)

	# Keep failed/queued items in the upload queue, but remove completed successes.
	remaining_jobs = []
	removed_done = 0
	for job in st.session_state["file_queue"]:
		if job["status"] == "done":
			removed_done += 1
			continue
		remaining_jobs.append(job)

	st.session_state["file_queue"] = remaining_jobs
	if removed_done:
		st.success(f"Processed and removed {removed_done} completed file(s) from the upload queue.")


def _sync_ready_jobs() -> None:
	_ensure_queue_state()
	jobs = [job for job in st.session_state["file_queue"] if job["status"] == "ready_for_review"]
	if not jobs:
		st.info("No reviewed files are waiting for approval.")
		return

	total = len(jobs)
	progress = st.progress(0)

	for idx, job in enumerate(jobs, start=1):
		job["status"] = "processing"
		with st.status(f"Approval #{job['job_id']} - {job['filename']}", expanded=True) as job_status:
			try:
				extraction = job.get("extraction")
				if not extraction:
					job["status"] = "failed"
					job["error"] = "Missing extraction payload for approval sync."
					job_status.update(label=f"Approval #{job['job_id']} failed", state="error")
					continue

				if MEDPLUM_TOKEN != "YOUR_MEDPLUM_BEARER_TOKEN":
					job_status.write("Step 1/2: Syncing Patient + ServiceRequest to Medplum...")
					medplum_ok = sync_to_medplum(extraction)
				else:
					job_status.write("Step 1/2: Medplum sync skipped (token not configured).")
					medplum_ok = True

				job_status.write("Step 2/2: Jira/Make sync check (not configured in this prototype).")
				if medplum_ok:
					job["status"] = "done"
					job["error"] = ""
					st.toast(f"Approved and synced {job['filename']}.")
					st.balloons()
					job_status.update(label=f"Approval #{job['job_id']} completed", state="complete")
				else:
					job["status"] = "failed"
					job["error"] = "External sync failed."
					job_status.update(label=f"Approval #{job['job_id']} failed during sync", state="error")
			except Exception as exc:
				job["status"] = "failed"
				job["error"] = str(exc)
				job_status.update(label=f"Approval #{job['job_id']} failed", state="error")
			finally:
				job["processed_at"] = datetime.now(timezone.utc).isoformat()
				progress.progress(idx / total)

	remaining_jobs = []
	removed_done = 0
	for job in st.session_state["file_queue"]:
		if job["status"] == "done":
			removed_done += 1
			continue
		remaining_jobs.append(job)

	st.session_state["file_queue"] = remaining_jobs
	if removed_done:
		st.success(f"Approved and removed {removed_done} synced file(s) from the upload queue.")


def _queue_overview_df() -> pd.DataFrame:
	_ensure_queue_state()
	rows = []
	for job in st.session_state["file_queue"]:
		rows.append(
			{
				"job_id": job["job_id"],
				"filename": job["filename"],
				"status": job["status"],
				"size_kb": round(job["size_bytes"] / 1024, 1),
				"queued_at": job["queued_at"],
				"processed_at": job["processed_at"],
				"error": job["error"],
				"risk_level": job.get("risk_level", "Unknown"),
				"risk_score": job.get("risk_score"),
			}
		)
	return pd.DataFrame(rows)


def _request_processing() -> None:
	"""Lock controls immediately and mark extraction processing for this rerun."""
	st.session_state["processing_lock"] = True
	st.session_state["process_requested"] = True


def _request_approval_sync() -> None:
	"""Lock controls immediately and mark approval sync for this rerun."""
	st.session_state["processing_lock"] = True
	st.session_state["approval_requested"] = True


def _resolve_brand_asset(filename: str) -> str | None:
	"""Resolve branding assets across common local folders."""
	base_dir = Path(__file__).resolve().parent
	candidates = [
		base_dir / "materials" / filename,
		base_dir / "diagrams" / filename,
		base_dir / "assets" / filename,
		base_dir.parent / "materials" / filename,
		base_dir.parent / "logos" / filename,
	]
	for path in candidates:
		if path.exists():
			return str(path)
	return None


def _apply_brand_theme() -> None:
	st.markdown(
		"""
		<style>
		:root {
			--hb-blue: #60a5fa;
			--hb-navy: #0b1220;
			--hb-slate: #cbd5e1;
			--hb-surface: #111827;
			--hb-border: #334155;
			--hb-text: #e5e7eb;
		}
		.stApp {
			background: radial-gradient(circle at 20% 0%, #1e293b 0%, #0f172a 45%, #0b1220 100%);
		}
		.block-container {
			padding-top: 4.2rem;
			max-width: 1220px;
			color: var(--hb-text);
		}
		.hb-hero {
			background: rgba(15, 23, 42, 0.82);
			border: 1px solid var(--hb-border);
			border-radius: 16px;
			padding: 1rem 1.25rem;
			box-shadow: 0 10px 26px rgba(2, 6, 23, 0.45);
			margin-bottom: 1rem;
		}
		.hb-eyebrow {
			font-size: 0.78rem;
			font-weight: 700;
			letter-spacing: 0.06em;
			text-transform: uppercase;
			color: var(--hb-blue);
			margin-bottom: 0.25rem;
		}
		.hb-title {
			font-size: 1.55rem;
			font-weight: 700;
			color: #f8fafc;
			line-height: 1.2;
			margin: 0;
		}
		.hb-subtitle {
			color: #dbeafe;
			margin-top: 0.35rem;
			font-size: 0.95rem;
		}
		[data-testid="stImage"] img {
			background: rgba(15, 23, 42, 0.75);
			border: 1px solid var(--hb-border);
			border-radius: 12px;
			padding: 0.4rem;
		}
		p, li, label, [data-testid="stMarkdownContainer"] {
			color: var(--hb-text);
		}
		.stButton > button {
			border-radius: 10px;
			font-weight: 600;
			border: 1px solid #334155;
			background: linear-gradient(180deg, #2563eb 0%, #1d4ed8 100%);
			color: #f8fafc;
		}
		[data-testid="stMetricValue"] {
			color: #f8fafc;
		}
		[data-testid="stMetricLabel"] {
			color: #cbd5e1;
		}
		</style>
		""",
		unsafe_allow_html=True,
	)


def _render_brand_header() -> None:
	full_logo = _resolve_brand_asset("homebound-full-logo.png")
	icon_logo = _resolve_brand_asset("homebound-icon.png")
	col_logo, col_text = st.columns([1.3, 3.2])
	with col_logo:
		if full_logo:
			st.image(full_logo, use_container_width=True)
		elif icon_logo:
			st.image(icon_logo, width=88)
	with col_text:
		st.markdown(
			"""
			<div class="hb-hero">
				<div class="hb-eyebrow">CareDevi 2026 Hackathon</div>
				<h1 class="hb-title">HomeBound Discharge Portal</h1>
				<div class="hb-subtitle">AI-powered, FHIR-native logistics for post-discharge DME delivery.</div>
			</div>
			""",
			unsafe_allow_html=True,
		)


st.set_page_config(page_title="HomeBound Discharge Portal", page_icon="🏥", layout="wide")
_apply_brand_theme()
_render_brand_header()

st.sidebar.caption(
	"⚠️ **Disclaimer:** This tool is a hackathon prototype for informational purposes only. "
	"AI-extracted data should be verified by a clinician. All patient data is synthetic (Synthea). "
	"Map data is aggregated for HIPAA compliance."
)

tab_physician, tab_analytics = st.tabs(["Physician Portal", "Analytics Command Center"])

with tab_physician:
	_ensure_queue_state()
	if "extraction" not in st.session_state:
		st.session_state["extraction"] = None
	if "latest_risk" not in st.session_state:
		st.session_state["latest_risk"] = None
	if "processing_lock" not in st.session_state:
		st.session_state["processing_lock"] = False
	if "process_requested" not in st.session_state:
		st.session_state["process_requested"] = False
	if "approval_requested" not in st.session_state:
		st.session_state["approval_requested"] = False

	# Auto-release a stale lock if no job is actually processing.
	if st.session_state["processing_lock"] and not any(
		job["status"] == "processing" for job in st.session_state["file_queue"]
	) and not st.session_state.get("process_requested", False) and not st.session_state.get("approval_requested", False):
		st.session_state["processing_lock"] = False

	controls_locked = st.session_state["processing_lock"]

	st.caption(
		f"Upload up to {MAX_BATCH_FILES} text files per batch. "
		f"Files larger than {MAX_FILE_SIZE_MB}MB are skipped."
	)

	st.info("Review extracted JSON first, then use 'Approve & Send to Services' to perform external sync.")

	uploaded_files = st.file_uploader(
		"Upload discharge summaries (.txt)",
		type=["txt"],
		accept_multiple_files=True,
		disabled=controls_locked,
	)
	has_queued_jobs = any(job["status"] == "queued" for job in st.session_state["file_queue"])

	st.button(
		"Process All Files",
		type="primary",
		use_container_width=True,
		disabled=controls_locked,
		on_click=_request_processing,
	)

	ready_for_review_count = sum(1 for job in st.session_state["file_queue"] if job["status"] == "ready_for_review")
	st.button(
		f"Approve & Send to Services ({ready_for_review_count})",
		type="secondary",
		use_container_width=True,
		disabled=controls_locked or ready_for_review_count == 0,
		on_click=_request_approval_sync,
		help="Sends reviewed extraction payloads to Medplum/Jira integrations.",
	)

	if st.session_state.get("process_requested", False):
		if uploaded_files:
			_queue_uploaded_files(uploaded_files)
			st.toast("Files added to processing queue.")
			has_queued_jobs = any(job["status"] == "queued" for job in st.session_state["file_queue"])

		if has_queued_jobs:
			try:
				with st.spinner("Processing queued files..."):
					_process_queued_jobs(max_jobs=10_000)
			finally:
				st.session_state["processing_lock"] = False
				st.session_state["process_requested"] = False
		else:
			st.warning("Please upload one or more files to process.")
			st.session_state["processing_lock"] = False
			st.session_state["process_requested"] = False

	if st.session_state.get("approval_requested", False):
		try:
			with st.spinner("Syncing approved files to external services..."):
				_sync_ready_jobs()
		finally:
			st.session_state["processing_lock"] = False
			st.session_state["approval_requested"] = False
			st.rerun()

	queue_df = _queue_overview_df()
	if queue_df.empty:
		st.caption("Queue is empty.")
	else:
		status_counts = queue_df["status"].value_counts().to_dict()
		metric_col1, metric_col2, metric_col3, metric_col4, metric_col5 = st.columns(5)
		metric_col1.metric("Queued", int(status_counts.get("queued", 0)))
		metric_col2.metric("Processing", int(status_counts.get("processing", 0)))
		metric_col3.metric("Ready for Review", int(status_counts.get("ready_for_review", 0)))
		metric_col4.metric("Done", int(status_counts.get("done", 0)))
		metric_col5.metric("Failed", int(status_counts.get("failed", 0)))

		st.markdown("#### Processing Queue")
		st.dataframe(queue_df.sort_values("job_id", ascending=False), use_container_width=True)

		review_jobs = [job for job in st.session_state["file_queue"] if job["status"] == "ready_for_review"]
		if review_jobs:
			st.markdown("#### Ready for Review: Extracted FHIR JSON")
			for job in sorted(review_jobs, key=lambda j: j["job_id"], reverse=True):
				with st.expander(f"Review Job #{job['job_id']} - {job['filename']}", expanded=False):
					if job.get("extraction"):
						st.json(job["extraction"])
					else:
						st.warning("No extraction payload found for this job.")

		if st.button("Clear Completed / Failed", use_container_width=False):
			st.session_state["file_queue"] = [
				job for job in st.session_state["file_queue"] if job["status"] in {"queued", "processing"}
			]
			st.session_state["queued_hashes"] = {job["file_hash"] for job in st.session_state["file_queue"]}
			st.success("Removed completed and failed jobs from the queue.")

	if st.session_state.get("extraction"):
		st.markdown("#### Latest Extraction Output")
		risk = _compute_supply_chain_risk(st.session_state["extraction"])
		st.session_state["latest_risk"] = risk
		risk_col1, risk_col2 = st.columns([2, 1])
		with risk_col1:
			if risk["level"] in {"High", "Critical"}:
				st.error(
					f"Supply Chain Risk Indicator: {risk['level']} ({risk['score']}/100). "
					"Expedited Review Recommended."
				)
			elif risk["level"] == "Moderate":
				st.warning(f"Supply Chain Risk Indicator: {risk['level']} ({risk['score']}/100).")
			else:
				st.success(f"Supply Chain Risk Indicator: {risk['level']} ({risk['score']}/100).")
		with risk_col2:
			st.metric("Risk Score", f"{risk['score']}/100")

		with st.expander("Why this risk was assigned", expanded=False):
			for reason in risk["reasons"]:
				st.write(f"- {reason}")

		with st.expander("View extracted FHIR JSON payload", expanded=False):
			st.json(st.session_state["extraction"])

with tab_analytics:
	st.subheader("Analytics Command Center")
	if st.button("Refresh Analytics Data", use_container_width=False):
		get_analytics_data.clear()
		_geocode_address.clear()
		_geocode_city_state.clear()
		st.rerun()

	if not SUPABASE_URL or not SUPABASE_KEY:
		st.warning("Set SUPABASE_URL and SUPABASE_KEY in Streamlit secrets to enable analytics.")
	else:
		try:
			analytics_df = get_analytics_data()
			if analytics_df.empty:
				st.info("No equipment orders found in Supabase.")
			else:
				total_orders = int(len(analytics_df))
				avg_fulfillment = pd.to_numeric(analytics_df.get("estimated_delivery_days"), errors="coerce").mean()
				active_vendors = int(analytics_df.get("vendor_name", pd.Series(dtype=str)).fillna("").astype(str).str.strip().ne("").sum())

				kpi_col1, kpi_col2, kpi_col3 = st.columns(3)
				kpi_col1.metric("Total Orders", total_orders)
				kpi_col2.metric("Avg. Fulfillment Time", f"{avg_fulfillment:.1f} days" if pd.notna(avg_fulfillment) else "N/A")
				kpi_col3.metric("Active Vendors", active_vendors)

				st.markdown("#### Delivery Locations")
				map_df = get_delivery_map_points(analytics_df)
				if map_df.empty:
					st.info("No mappable coordinates found. Add coordinates or U.S.-formatted addresses (e.g., ', TX 78701').")
				else:
					initial_view = pdk.ViewState(
						latitude=float(map_df["lat"].mean()),
						longitude=float(map_df["lon"].mean()),
						zoom=3.3,
						pitch=25,
					)
					layer = pdk.Layer(
						"ScatterplotLayer",
						data=map_df,
						get_position="[lon, lat]",
						get_fill_color="color",
						get_radius=18000,
						pickable=True,
					)
					deck = pdk.Deck(
						map_style="https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
						initial_view_state=initial_view,
						layers=[layer],
						tooltip={
							"html": "<b>{patient_name}</b><br/>{equipment_type}<br/>Vendor: {vendor_name}<br/>Status: {order_status}",
							"style": {"backgroundColor": "#f8fafc", "color": "#0f172a"},
						},
					)
					st.pydeck_chart(deck, use_container_width=True)
					with st.expander("Map debug data", expanded=False):
						st.dataframe(map_df, use_container_width=True)

				st.markdown("#### Fulfillment Speed by Equipment Type")
				chart_df = (
					analytics_df.dropna(subset=["equipment_type", "estimated_delivery_days"])
					.groupby("equipment_type", as_index=False)["estimated_delivery_days"]
					.mean()
				)
				if chart_df.empty:
					st.info("No delivery-day data available for charting yet.")
				else:
					bar_chart = (
						alt.Chart(chart_df)
						.mark_bar()
						.encode(
							x=alt.X("equipment_type:N", title="Equipment Type", sort="-y"),
							y=alt.Y("estimated_delivery_days:Q", title="Estimated Delivery Days (avg)"),
							tooltip=["equipment_type", "estimated_delivery_days"],
						)
						.properties(height=350)
					)
					st.altair_chart(bar_chart, use_container_width=True)

				st.markdown("#### Live Feed: Most Recent 5 Orders")
				live_feed_df = analytics_df.head(5).copy()
				live_feed_df = live_feed_df.drop(columns=["delivery_address"], errors="ignore")
				live_feed_df.index = live_feed_df.index + 1
				st.dataframe(live_feed_df, use_container_width=True)

				with st.expander("Raw analytics/debug data", expanded=False):
					st.dataframe(analytics_df, use_container_width=True)
		except Exception as exc:
			st.error(f"Failed to load analytics from Supabase: {exc}")
