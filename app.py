import json
import os
import random
import re
import hashlib
from datetime import datetime, timezone

import altair as alt
import pandas as pd
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
MAX_FILE_SIZE_MB = 2


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


@st.cache_data(ttl=120)
def get_analytics_data() -> pd.DataFrame:
	"""Query active equipment orders from Supabase and return a dataframe."""
	if not SUPABASE_URL or not SUPABASE_KEY:
		return pd.DataFrame()

	headers = {
		"apikey": SUPABASE_KEY,
		"Authorization": f"Bearer {SUPABASE_KEY}",
	}
	url = (
		f"{SUPABASE_URL}/rest/v1/equipment_orders"
		"?select=id,patient_name,equipment_type,vendor_name,order_status,created_at,estimated_delivery_days"
		"&order=id.desc"
	)

	response = requests.get(url, headers=headers, timeout=30)
	response.raise_for_status()
	rows = response.json()
	return pd.DataFrame(rows)


def add_mock_delivery_coordinates(df: pd.DataFrame) -> pd.DataFrame:
	"""Generate demo coordinates around Austin and San Marcos for map rendering."""
	if df.empty:
		return df

	points = []
	for _, row in df.iterrows():
		seed_value = int(row.get("id", 0)) if pd.notna(row.get("id")) else 0
		rng = random.Random(seed_value)
		if rng.random() < 0.5:
			# Austin city center with a small random radius
			lat = 30.2672 + rng.uniform(-0.08, 0.08)
			lon = -97.7431 + rng.uniform(-0.08, 0.08)
		else:
			# San Marcos city center with a small random radius
			lat = 29.8833 + rng.uniform(-0.06, 0.06)
			lon = -97.9414 + rng.uniform(-0.06, 0.06)
		points.append((lat, lon))

	map_df = df.copy()
	map_df["lat"] = [p[0] for p in points]
	map_df["lon"] = [p[1] for p in points]
	return map_df


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
		try:
			extraction = extract_dme_order(job["file_text"])
			job["extraction"] = extraction
			st.session_state["extraction"] = extraction

			if MEDPLUM_TOKEN != "YOUR_MEDPLUM_BEARER_TOKEN":
				sync_to_medplum(extraction)

			job["status"] = "done"
			job["error"] = ""
		except Exception as exc:
			job["status"] = "failed"
			job["error"] = str(exc)
		finally:
			job["processed_at"] = datetime.now(timezone.utc).isoformat()
			progress.progress(idx / total)


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
			}
		)
	return pd.DataFrame(rows)


st.set_page_config(page_title="HomeBound Discharge Portal", layout="wide")

st.title("🏥 HomeBound Discharge Portal")

tab_physician, tab_analytics = st.tabs(["Physician Portal", "Analytics Command Center"])

with tab_physician:
	_ensure_queue_state()
	if "extraction" not in st.session_state:
		st.session_state["extraction"] = None

	st.caption(
		f"Upload up to {MAX_BATCH_FILES} text files per batch. "
		f"Files larger than {MAX_FILE_SIZE_MB}MB are skipped."
	)

	uploaded_files = st.file_uploader(
		"Upload discharge summaries (.txt)",
		type=["txt"],
		accept_multiple_files=True,
	)

	controls_col1, controls_col2, controls_col3 = st.columns(3)
	with controls_col1:
		if st.button("Queue Uploaded Files", type="primary", use_container_width=True):
			if uploaded_files:
				_queue_uploaded_files(uploaded_files)
			else:
				st.info("Please choose one or more files first.")
	with controls_col2:
		if st.button("Process Next File", use_container_width=True):
			with st.spinner("Processing next queued file..."):
				_process_queued_jobs(max_jobs=1)
	with controls_col3:
		if st.button("Process All Queued Files", use_container_width=True):
			with st.spinner("Processing queued files..."):
				_process_queued_jobs(max_jobs=10_000)

	queue_df = _queue_overview_df()
	if queue_df.empty:
		st.info("No files queued yet.")
	else:
		status_counts = queue_df["status"].value_counts().to_dict()
		metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
		metric_col1.metric("Queued", int(status_counts.get("queued", 0)))
		metric_col2.metric("Processing", int(status_counts.get("processing", 0)))
		metric_col3.metric("Done", int(status_counts.get("done", 0)))
		metric_col4.metric("Failed", int(status_counts.get("failed", 0)))

		st.markdown("#### Processing Queue")
		st.dataframe(queue_df.sort_values("job_id", ascending=False), use_container_width=True)

		if st.button("Clear Completed / Failed", use_container_width=False):
			st.session_state["file_queue"] = [
				job for job in st.session_state["file_queue"] if job["status"] in {"queued", "processing"}
			]
			st.session_state["queued_hashes"] = {job["file_hash"] for job in st.session_state["file_queue"]}
			st.success("Removed completed and failed jobs from the queue.")

	if st.session_state.get("extraction"):
		st.markdown("#### Latest Extraction Output")
		st.json(st.session_state["extraction"])

with tab_analytics:
	st.subheader("Analytics Command Center")

	if not SUPABASE_URL or not SUPABASE_KEY:
		st.warning("Set SUPABASE_URL and SUPABASE_KEY in Streamlit secrets to enable analytics.")
	else:
		try:
			analytics_df = get_analytics_data()
			if analytics_df.empty:
				st.info("No equipment orders found in Supabase.")
			else:
				st.metric("Total Orders In Flight", int(len(analytics_df)))

				st.markdown("#### Delivery Locations")
				map_df = add_mock_delivery_coordinates(analytics_df)
				st.map(map_df[["lat", "lon"]])

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
				st.dataframe(analytics_df.head(5), use_container_width=True)
		except Exception as exc:
			st.error(f"Failed to load analytics from Supabase: {exc}")
