import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

DME_CATALOG = [
    {
        "display": "Oxygen Concentrator",
        "code": "426854004",
        "category": "Respiratory",
        "note": "Stationary oxygen concentrator (5L/min) for COPD and chronic respiratory disease management.",
        "vendor_type": "Clinical Respiratory"
    },
    {
        "display": "Portable Oxygen Tank",
        "code": "24882003",
        "category": "Respiratory",
        "note": "Portable oxygen cylinder (E-tank) with regulator for patient mobility.",
        "vendor_type": "Clinical Respiratory"
    },
    {
        "display": "CPAP Machine",
        "code": "426371004",
        "category": "Respiratory",
        "note": "Continuous positive airway pressure device for obstructive sleep apnea treatment.",
        "vendor_type": "Clinical Respiratory"
    },
    {
        "display": "Nebulizer",
        "code": "468158002",
        "category": "Respiratory",
        "note": "Aerosol delivery device for respiratory medications (albuterol, etc.).",
        "vendor_type": "Clinical Respiratory"
    },
    {
        "display": "Manual Wheelchair",
        "code": "469315003",
        "category": "Mobility",
        "note": "Standard folding wheelchair with brakes for post-op and post-stroke mobility.",
        "vendor_type": "Mobility & Rehabilitation"
    },
    {
        "display": "Power Wheelchair",
        "code": "14586004",
        "category": "Mobility",
        "note": "Electric wheelchair with joystick control for patients with upper limb weakness.",
        "vendor_type": "Mobility & Rehabilitation"
    },
    {
        "display": "Standard Walker",
        "code": "469143003",
        "category": "Mobility",
        "note": "Four-legged walker with front wheels for gait stability and balance support.",
        "vendor_type": "Mobility & Rehabilitation"
    },
    {
        "display": "Rollator Walker",
        "code": "26637000",
        "category": "Mobility",
        "note": "Wheeled walker with seat and hand brakes for elderly patients with limited endurance.",
        "vendor_type": "Mobility & Rehabilitation"
    },
    {
        "display": "Crutches",
        "code": "74139003",
        "category": "Mobility",
        "note": "Underarm crutches for non-weight-bearing gait after fracture or surgery.",
        "vendor_type": "Mobility & Rehabilitation"
    },
    {
        "display": "Hospital Bed",
        "code": "430533005",
        "category": "Bed & Transfer",
        "note": "Adjustable electric bed with side rails, Trendelenburg capability for post-op care.",
        "vendor_type": "Furniture & Logistics"
    },
    {
        "display": "Pressure Relief Mattress",
        "code": "469168000",
        "category": "Bed & Transfer",
        "note": "Air or gel mattress overlay for pressure ulcer prevention in immobile patients.",
        "vendor_type": "Furniture & Logistics"
    },
    {
        "display": "Patient Lift",
        "code": "706664007",
        "category": "Bed & Transfer",
        "note": "Mechanical or electric lift device for safe patient transfer from bed to wheelchair.",
        "vendor_type": "Furniture & Logistics"
    },
    {
        "display": "Shower Chair",
        "code": "303734007",
        "category": "Bathroom",
        "note": "Waterproof chair with back support and armrests for safe bathing.",
        "vendor_type": "Home Care Accessories"
    },
    {
        "display": "Bedside Commode",
        "code": "464871007",
        "category": "Bathroom",
        "note": "Portable toilet seat for patients unable to reach standard bathroom safely.",
        "vendor_type": "Home Care Accessories"
    },
    {
        "display": "Raised Toilet Seat",
        "code": "464872000",
        "category": "Bathroom",
        "note": "Elevated toilet seat riser to reduce hip flexion stress in post-op patients.",
        "vendor_type": "Home Care Accessories"
    },
    {
        "display": "Grab Bars",
        "code": "448737008",
        "category": "Safety",
        "note": "Wall-mounted safety rails for bathroom and hallways to prevent falls.",
        "vendor_type": "Home Care Accessories"
    },
    {
        "display": "Blood Pressure Monitor",
        "code": "258057007",
        "category": "Monitoring",
        "note": "Automated home blood pressure cuff for hypertension monitoring and Telehealth reporting.",
        "vendor_type": "Remote Monitoring"
    },
    {
        "display": "Pulse Oximeter",
        "code": "59408008",
        "category": "Monitoring",
        "note": "Finger-based oxygen saturation monitor for respiratory disease and post-operative monitoring.",
        "vendor_type": "Remote Monitoring"
    },
    {
        "display": "Glucose Monitor",
        "code": "20947000",
        "category": "Monitoring",
        "note": "Continuous glucose meter for diabetic patients in home care programs.",
        "vendor_type": "Remote Monitoring"
    },
    {
        "display": "TENS Unit",
        "code": "303357003",
        "category": "Pain Management",
        "note": "Transcutaneous electrical nerve stimulation device for chronic pain relief.",
        "vendor_type": "Physical Therapy"
    }
]


def extract_patient_info(bundle_data: dict) -> tuple:
    """Extract patient ID, name, DOB, gender, and address from FHIR bundle."""
    try:
        patient_entry = bundle_data.get("entry", [{}])[0]
        patient_resource = patient_entry.get("resource", {})
        patient_id = patient_resource.get("id", "unknown")
        
        names = patient_resource.get("name", [{}])
        if names and isinstance(names[0], dict):
            family = names[0].get("family", "Patient")
            given_list = names[0].get("given", [""])
            given = given_list[0] if given_list else ""
            patient_name = f"{given} {family}".strip()
        else:
            patient_name = "Patient"
        
        birthdate = patient_resource.get("birthDate", "Unknown")
        gender = patient_resource.get("gender", "Unknown").capitalize()

        # Build a single-line patient address if present.
        address = "Unknown"
        addresses = patient_resource.get("address", [])
        if addresses and isinstance(addresses[0], dict):
            addr = addresses[0]
            line_parts = addr.get("line", [])
            city = addr.get("city", "")
            state = addr.get("state", "")
            postal_code = addr.get("postalCode", "")
            address_parts = [part for part in [", ".join(line_parts), city, state, postal_code] if part]
            if address_parts:
                address = ", ".join(address_parts)
        
        return patient_id, patient_name, birthdate, gender, address, patient_entry
    except (IndexError, KeyError, TypeError) as e:
        raise ValueError(f"Could not extract patient info: {e}")


def extract_name_from_filename(input_file: Path) -> str:
    """Extract a display name from source file and preserve numeric suffixes."""
    parts = input_file.stem.split("_")
    # Synthea filename pattern: Given[_Middle...]_Family_<uuid>
    if len(parts) >= 3:
        given = parts[0]
        family = parts[-2]
        return f"{given} {family}".strip()
    return ""



# Clinical Course Templates for Variety
CLINICAL_COURSE_TEMPLATES = [
    "Patient admitted for {condition} and was stabilized with {intervention}. Hospital course was uncomplicated. Vital signs stabilized by hospital day 2. Patient discharged in stable condition.",
    "Presented with {condition}. Managed conservatively with {intervention} over {days} days. Patient improved significantly and is ready for home-based care.",
    "{condition} required immediate hospitalization. After {intervention} and close monitoring, patient achieved clinical improvement. {comorbidity} was also managed. Discharged to home with outpatient follow-up.",
    "Patient experienced {condition} and underwent {intervention}. Recovery was steady without complications. Patient tolerating diet well by discharge. Now appropriate for discharge with home care support.",
    "Admitted for management of {condition}. {intervention} was initiated, resulting in symptomatic relief. Patient remained stable throughout {days}-day admission. Discharged after clinical goals met.",
    "Patient presented with {condition} complicated by {comorbidity}. Multi-disciplinary team managed with {intervention}. Achieved adequate pain control (VAS {pain_score}). Ready for discharge.",
    "{condition} management required {intervention} and careful monitoring. Patient demonstrated good compliance with therapy. Labs normalized by hospital day {days}. Appropriate for home discharge.",
    "Acute {condition} successfully managed with {intervention}. Physical and occupational therapy consulted. Patient progressed well and met all discharge criteria.",
    "Patient hospitalized for {condition}. Started on {intervention} protocol immediately upon admission. Clinical status improved daily. Discharged after {days} days of therapy.",
    "Initial presentation of {condition} responded well to {intervention}. Vitals stable (BP {bp_systolic}/{bp_diastolic}, HR {hr}). Patient educated on follow-up. Safe for discharge.",
    "{condition} required admission for {intervention} and optimization of {comorbidity} management. Patient discharged after stable period.",
    "Complex case of {condition} with {comorbidity} managed successfully with {intervention}. Multidisciplinary coordination ensured smooth discharge planning.",
    "Patient with {condition} admitted for {intervention}. Nursing staff provided extensive education on self-care. Patient demonstrated understanding of discharge instructions.",
    "{condition} resolved with {intervention} after {days} days of hospitalization. No complications noted. Patient ambulatory at discharge.",
    "Managed {condition} with {intervention}. Patient's functional status improved significantly. {comorbidity} well-controlled on current regimen. Ready for home recovery.",
]

CONDITIONS = [
    "acute exacerbation of COPD",
    "post-operative recovery from hip replacement",
    "acute respiratory infection",
    "fall with fractured femur",
    "acute decompensated heart failure",
    "post-stroke rehabilitation",
    "post-surgical wound infection management",
    "acute atrial fibrillation with rate control",
    "severe pneumonia requiring hospitalization",
    "acute diabetic ketoacidosis",
    "post-operative pain management",
    "sepsis from urinary tract infection",
    "acute coronary syndrome",
    "bowel obstruction requiring surgical intervention",
    "compound fracture with open reduction",
    "acute pancreatitis",
]

INTERVENTIONS = [
    "oxygen therapy and nebulized bronchodilators",
    "pain management with opioid and non-opioid analgesics",
    "broad-spectrum IV antibiotic therapy",
    "bed rest with physical therapy consultation",
    "intensive rehabilitation protocols",
    "medication optimization and titration",
    "continuous cardiac monitoring",
    "IV hydration and electrolyte management",
    "surgical intervention and post-operative wound care",
    "blood glucose management with sliding scale insulin",
    "anticoagulation therapy initiation",
    "transfusion and blood product management",
]

COMORBIDITIES = [
    "uncontrolled hypertension",
    "type 2 diabetes mellitus",
    "chronic kidney disease stage 3",
    "coronary artery disease",
    "atrial fibrillation",
    "obesity",
    "anemia",
    "depression",
    "chronic obstructive pulmonary disease",
]

DAYS = ["1", "2", "3", "4", "5", "6", "7"]


def generate_clinical_course() -> str:
    """Generate a varied clinical course summary."""
    template = random.choice(CLINICAL_COURSE_TEMPLATES)
    condition = random.choice(CONDITIONS)
    intervention = random.choice(INTERVENTIONS)
    days = random.choice(DAYS)
    comorbidity = random.choice(COMORBIDITIES)
    pain_score = str(random.randint(2, 6))
    bp_systolic = str(random.randint(110, 160))
    bp_diastolic = str(random.randint(65, 95))
    hr = str(random.randint(55, 95))
    return template.format(
        condition=condition,
        intervention=intervention,
        days=days,
        comorbidity=comorbidity,
        pain_score=pain_score,
        bp_systolic=bp_systolic,
        bp_diastolic=bp_diastolic,
        hr=hr
    )


def generate_discharge_summary(patient_id: str, patient_name: str, birthdate: str,
                               gender: str, address: str, equipment: dict) -> str:
    """Generate a Heidi-style discharge summary with DME ordering."""
    
    # Calculate admission and discharge dates
    discharge_date = datetime(2026, 4, 25)
    admission_date = discharge_date - timedelta(days=random.randint(1, 5))
    
    clinical_course = generate_clinical_course()
    
    # Randomly select disposition and follow-up timeline
    dispositions = ["home", "skilled nursing facility", "assisted living", "home with home health services"]
    disposition = random.choice(dispositions)
    followup_days = random.randint(5, 21)
    
    # Randomly select number of medications
    num_meds = random.randint(3, 8)
    med_list = "\n    ".join([f"• Medication {i+1}: Continue as prescribed" for i in range(num_meds)])
    
    summary = f"""DISCHARGE SUMMARY

{'='*80}

PATIENT IDENTIFICATION:
    Name:                {patient_name}
    Date of Birth:       {birthdate}
    Sex:                 {gender}
    Address:             {address}
    MRN:                 {patient_id}

ADMISSION/DISCHARGE INFORMATION:
    Admission Date:      {admission_date.strftime("%B %d, %Y")}
    Discharge Date:      {discharge_date.strftime("%B %d, %Y")}
    Length of Stay:      {(discharge_date - admission_date).days} days
    Attending Physician: Dr. {random.choice(['Martinez', 'Chen', 'Patel', 'Williams', 'Johnson', 'Garcia'])}

{'='*80}

CLINICAL COURSE:
    {clinical_course}

{'='*80}

DISCHARGE PLAN:

Medications:
    {med_list}
    All prescriptions filled at discharge pharmacy.

Follow-up Appointments:
    • Primary Care: {followup_days}-{followup_days+7} days
    • Specialty: {random.choice(["Cardiology", "Pulmonology", "Orthopedics", "Infectious Disease", "Endocrinology"])} - 1-2 weeks
    • Lab work: As ordered by primary care physician

Durable Medical Equipment (DME):
    Equipment Ordered:   {equipment['display']}
    Description:         {equipment['note']}
    Vendor Type:         {equipment['vendor_type']}
    Category:            {equipment['category']}
    Expected Delivery:   3-5 business days

Patient Disposition:
    Patient discharged to {disposition}.
    Home care services arranged: {random.choice(['Yes', 'No', 'As needed'])}
    Visiting nurse evaluation: {random.choice(['Scheduled', 'Pending', 'Not needed'])}

{'='*80}

ADDITIONAL NOTES:
    • Comprehensive discharge education provided regarding medications, diet, activity
    • Patient and caregiver demonstrated understanding of discharge instructions
    • Activity restrictions and weight-bearing status clearly communicated
    • Warning signs reviewed: seek emergency care if experiencing chest pain, shortness of breath, severe fever
    • Follow-up immunizations status reviewed
    • Completed advance directive documentation

______________________________________________________________________________
MRN: {patient_id}
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
______________________________________________________________________________
"""
    return summary


def create_dme_service_request(patient_id: str, equipment: dict) -> dict:
    """Create a FHIR ServiceRequest for DME ordering."""
    return {
        "fullUrl": f"urn:uuid:dme-order-{patient_id[:8]}-{random.randint(1000, 9999)}",
        "resource": {
            "resourceType": "ServiceRequest",
            "id": f"dme-{patient_id[:8]}-{random.randint(1000, 9999)}",
            "status": "active",
            "intent": "order",
            "authoredOn": "2026-04-25T14:00:00Z",
            "code": {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": equipment["code"],
                        "display": equipment["display"]
                    }
                ],
                "text": f"{equipment['display']} - {equipment['note']}"
            },
            "subject": {
                "reference": f"Patient/{patient_id}",
                "display": f"DME Order for Patient {patient_id[:8]}"
            },
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://snomed.info/sct",
                            "code": "386053000",
                            "display": "Evaluation procedure"
                        }
                    ],
                    "text": equipment["category"]
                }
            ],
            "priority": "routine"
        }
    }



def main():
    """Main discharge summary factory function."""
    synthea_folder = Path("Synthea_files")
    output_folder = Path("discharge_summaries")
    
    if not synthea_folder.exists():
        print(f"❌ Synthea_files folder not found. Please ensure it exists in the current directory.")
        sys.exit(1)
    
    output_folder.mkdir(exist_ok=True)
    
    json_files = sorted(list(synthea_folder.glob("*.json")))
    if not json_files:
        print(f"❌ No JSON files found in {synthea_folder}")
        sys.exit(1)
    
    print(f"📋 Discharge Summary Generator initializing...")
    print(f"📁 Found {len(json_files)} Synthea patient files")
    print(f"📦 DME Catalog: {len(DME_CATALOG)} equipment types across 6 categories")
    print()
    
    success_count = 0
    error_count = 0
    equipment_distribution = {}
    
    for input_file in json_files:
        try:
            with open(input_file, "r", encoding="utf-8") as f:
                synthea_bundle = json.load(f)
            
            # Extract patient info
            patient_id, patient_name, birthdate, gender, address, _ = extract_patient_info(synthea_bundle)

            # Prefer filename-derived name so numeric suffixes are preserved for anonymity.
            filename_name = extract_name_from_filename(input_file)
            if filename_name:
                patient_name = filename_name
            
            # Random equipment selection for this patient
            equipment = random.choice(DME_CATALOG)
            equipment_distribution[equipment["display"]] = equipment_distribution.get(equipment["display"], 0) + 1
            
            # Generate discharge summary
            summary = generate_discharge_summary(patient_id, patient_name, birthdate, gender, address, equipment)
            
            # Write output
            output_file = output_folder / f"{patient_name.replace(' ', '_')}_{patient_id[:8]}.txt"
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(summary)
            
            success_count += 1
            category_icon = "🫁" if equipment["category"] == "Respiratory" else \
                           "🚶" if equipment["category"] == "Mobility" else \
                           "🛏️" if equipment["category"] == "Bed & Transfer" else \
                           "🚿" if equipment["category"] == "Bathroom" else \
                           "🛡️" if equipment["category"] == "Safety" else \
                           "📊" if equipment["category"] == "Monitoring" else "💊"
            
            print(f"  {category_icon} {patient_name:30} → {equipment['display']:30}")
            
        except Exception as e:
            error_count += 1
            print(f"  ❌ {input_file.name}: {e}")

if __name__ == "__main__":
    main()
