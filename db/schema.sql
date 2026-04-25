-- HomeBound Central Tracking Schema
CREATE TABLE equipment_orders (
    id SERIAL PRIMARY KEY,
    patient_name TEXT,
    equipment_type TEXT,
    snomed_code TEXT,
    vendor_name TEXT,
    order_status TEXT DEFAULT 'Pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);