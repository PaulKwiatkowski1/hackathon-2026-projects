import json
import os
import random
import sys
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
        
        return patient_id, patient_name, patient_entry
    except (IndexError, KeyError, TypeError) as e:
        raise ValueError(f"Could not extract patient info: {e}")


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


def create_demo_bundle(synthea_bundle: dict, equipment: dict) -> dict:
    """Create a compact demo bundle with patient + DME order."""
    patient_id, patient_name, patient_entry = extract_patient_info(synthea_bundle)
    dme_request = create_dme_service_request(patient_id, equipment)
    
    return {
        "resourceType": "Bundle",
        "type": "batch",
        "entry": [patient_entry, dme_request]
    }


def main():
    """Main factory function."""
    synthea_folder = Path("Synthea_files")
    output_folder = Path("demo_ready")
    
    if not synthea_folder.exists():
        print(f"❌ Synthea_files folder not found. Please ensure it exists in the current directory.")
        sys.exit(1)
    
    output_folder.mkdir(exist_ok=True)
    
    json_files = sorted(list(synthea_folder.glob("*.json")))
    if not json_files:
        print(f"❌ No JSON files found in {synthea_folder}")
        sys.exit(1)
    
    print(f"🏭 Smart DME Factory initializing...")
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
            
            # Random equipment selection for this patient
            equipment = random.choice(DME_CATALOG)
            equipment_distribution[equipment["display"]] = equipment_distribution.get(equipment["display"], 0) + 1
            
            # Create compact demo bundle
            demo_bundle = create_demo_bundle(synthea_bundle, equipment)
            
            # Write output
            output_file = output_folder / f"demo_{input_file.name}"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(demo_bundle, f, indent=2, ensure_ascii=False)
            
            success_count += 1
            category_icon = "🫁" if equipment["category"] == "Respiratory" else \
                           "🚶" if equipment["category"] == "Mobility" else \
                           "🛏️" if equipment["category"] == "Bed & Transfer" else \
                           "🚿" if equipment["category"] == "Bathroom" else \
                           "🛡️" if equipment["category"] == "Safety" else \
                           "📊" if equipment["category"] == "Monitoring" else "💊"
            
            print(f"  {category_icon} {input_file.stem[:40]:40} → {equipment['display']:30} ({equipment['vendor_type']})")
            
        except Exception as e:
            error_count += 1
            print(f"  ❌ {input_file.name}: {e}")


if __name__ == "__main__":
    main()
