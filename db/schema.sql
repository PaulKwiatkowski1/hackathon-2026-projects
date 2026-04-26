CREATE TABLE equipment_orders (
    id SERIAL PRIMARY KEY,
    fhir_patient_id TEXT NOT NULL,
    fhir_service_request_id TEXT,
    jira_ticket_key TEXT,
    patient_name TEXT,
    delivery_address TEXT,
    equipment_type TEXT,
    snomed_code TEXT,
    vendor_name TEXT,
    order_status TEXT DEFAULT 'Pending',
    estimated_delivery_days INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    fhir_resource_version TEXT
);