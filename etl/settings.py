"""Project-wide constants. Every value here is a decision recorded in docs/04-decisions-and-tradeoffs.md."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPPINGS_DIR = ROOT / "mappings"

CDM_VERSION = "v5.4"

# Source file types: key -> file-name prefix used in the course data folders.
SOURCE_TYPES = {
    "patient_demo": "patient demo",
    "case_visit": "case visit",
    "lab_results": "lab results",
    "medication_order": "medication order",
    "surgical": "surgical",
}

# Verified by profiling (docs/01-requirements.md section 2).
EXPECTED_ROWS = {
    "patient_demo": 5,
    "case_visit": 22,
    "lab_results": 162,
    "medication_order": 170,
    "surgical": 7,
}

EXPECTED_COLUMNS = {
    "patient_demo": [
        "Patient_No", "Patient_DOB", "Religion", "Race", "Gender", "Marital_Status",
        "Deceased_Ind", "Death_Date",
    ],
    "case_visit": [
        "Case_No", "Referral_Type_From", "No_of_Subspecialities", "No_of_Secondary_Diagnosis_ICD9",
        "Adm_DateTime", "Adm_Dept_Description", "Adm_Type_Desc", "Adm_Reason", "Adm_Trt_Cat_Desc",
        "Adm_Physical_Class_Desc", "Adm_Subspecialty_Desc", "Dis_DateTime", "Dis_Dept_Description",
        "Dis_Reason", "Dis_Physical_Class_Desc", "Case_Specialty_Desc", "Discharge_Type_Desc",
        "Primary_Diagnosis_Code_Mediclaim", "Primary_Diagnosis_Description_Mediclaim",
        "Secondary_Diagnosis_Codes_Subvention", "MDC_Code", "MDC_Description", "Dis_DateTime_Planned",
        "CCI_Score", "DS_Turn_Inpatient_Ind", "Outpatient_Turn_DS_Ind", "Unplanned_Surgery_Ind",
        "ReAdm_Ind", "Planned_Adm_Ind", "Lodger_Ind", "Surgical_Emergency_Ind", "LOS_Days",
        "Last_Day_LOS_Hours", "Acute_LOS_Days", "HD_LOS_Days", "ICU_LOS_Days", "Rehab_LOS_Days",
        "No_of_Surgical_Operations", "No_of_Secondary_Diagnosis_Subvention", "Patient_No",
    ],
    "lab_results": [
        "Case_No", "Test_Code", "Test_Result", "Result_Test_Date", "Minimum_Range", "Maximum_Range",
        "Short_Text", "Panel_Test_Code", "Test_Order", "Chapter_Description", "Number_of_Tests",
        "Patient_No",
    ],
    "medication_order": [
        "Case_No", "Order_Text", "Order_Creation_Date", "Dosage_Ordered_Unit", "Dosage_Ordered",
        "Dosage_Form", "Strength_Unit", "Component_Type_Code", "Component_Type_Description",
        "Medication_Order_Component_Text", "Cluster_Preferred_Name_Code",
        "Cluster_Preferred_Name_Description", "Patient_No",
    ],
    "surgical": [
        "Surgical_Code", "Surgical_Desc", "Operation_Table_Code", "Case_No", "Patient_No",
        "operation_date",
    ],
}

# De-identification (docs/06-data-privacy-design.md): per-patient day shift d in +/-[MIN, MAX].
SHIFT_MIN_DAYS = 30
SHIFT_MAX_DAYS = 365
YEAR_ANCHOR = (7, 2)  # year-only fields are shifted via YYYY-07-02 + d

# Mapping statuses.
#   PROPOSED  = target concept verified in Athena (exists, Standard, Valid, right domain) but not yet
#               reviewed by a second person. Usable in "review" mode only.
#   NEEDS_CLINICAL_REVIEW = open question; never usable, and never treated as UNMAPPABLE.
#   APPROVED / UNMAPPABLE / REJECTED = reviewed decisions; each row needs reviewer + review_date,
#               reviewer != mapper. "final" mode accepts nothing else and refuses to run otherwise.
REVIEWED_STATUSES = {"APPROVED", "UNMAPPABLE", "REJECTED"}
ACCEPTED_STATUSES = {
    "review": {"APPROVED", "PROPOSED"},
    "final": {"APPROVED"},
}

# Target table for each Standard domain; anything else falls back to the source's default table.
DOMAIN_TABLE = {
    "Condition": "condition_occurrence",
    "Observation": "observation",
    "Procedure": "procedure_occurrence",
    "Measurement": "measurement",
    "Drug": "drug_exposure",
}

# CDM_SOURCE metadata (docs/04 D11 as amended by the audit: release date is a labelled proxy).
CDM_SOURCE_NAME = "BMI5207 Group 3d synthetic 5-patient dataset"
CDM_SOURCE_ABBREVIATION = "BMI5207G3D"
CDM_HOLDER = "NUS BMI5207 Group 3d"
SOURCE_RELEASE_DATE_PROXY = "2022-11-07"
SOURCE_DESCRIPTION = (
    "Synthetic EHR extract of 5 patients (25 XLSX files) converted to an OMOP CDM v5.4-aligned "
    "subset of 10 tables. Pseudonymised: integer IDs via HMAC registry, per-patient day shift. "
    "source_release_date is a PROXY taken from the XLSX docProps modified timestamp (2022-11-07); "
    "the true extraction date is unknown."
)
CDM_ETL_REFERENCE = "https://github.com/stephen30ppp/bmi5207-omop-etl"
