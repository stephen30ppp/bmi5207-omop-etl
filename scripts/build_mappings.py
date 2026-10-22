#!/usr/bin/env python3
"""Generate mappings/*.csv from the Athena lookup snapshots plus the mapper's documented choices.

Every concept ID below was returned by the Athena API (athena.ohdsi.org/api/v1, browser session,
2026-10-22) and checked to be Standard + Valid in the stated domain; see mappings/athena_snapshots/.
All rows are written with status=PROPOSED: a second human reviewer must set status=APPROVED and
fill reviewer/review_date before the ETL is run in --mapping-mode final.

Usage: python scripts/build_mappings.py [--raw DIR]   (DIR adds source frequencies)
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from etl import clean  # noqa: E402
from etl.vocab import MAPPING_COLUMNS  # noqa: E402

SNAP = ROOT / "mappings" / "athena_snapshots"
OUT = ROOT / "mappings"
VOCAB_VERSION = "Athena 2026-10-22 (SNOMED 2026-02-01 Intl)"
MAPPER = "athena-api lookup"


def row(sheet_rows, **kw):
    base = {c: "" for c in MAPPING_COLUMNS}
    base.update({"map_seq": "1", "relationship": "Maps to", "status": "PROPOSED",
                 "mapper": MAPPER, "vocab_version": VOCAB_VERSION, "source_concept_id": "0"})
    base.update({k: ("" if v is None else str(v)) for k, v in kw.items()})
    sheet_rows.append(base)


def unmapped(sheet_rows, reason, **kw):
    row(sheet_rows, target_concept_id="0", equivalence="UNMATCHED", status="UNMAPPABLE",
        unmapped_reason=reason, **kw)


# ---------------------------------------------------------------- diagnoses
# Codes whose ICD10 (WHO) candidate is known to differ in meaning from the ICD-10-AM source.
DX_REVIEW = {
    "S7211": "WHO S72.11 means OPEN pertrochanteric fracture but source says intertrochanteric (no "
             "'open'); identical-code match rejected, parent S72.1 used",
    "E1472": "WHO E14.7 = unspecified DM with multiple complications; ICD-10-AM E14.72 differs "
             "(DM with features of insulin resistance) - clinical review required",
    "Z8643": "WHO Z86.4 = history of psychoactive substance abuse; ICD-10-AM Z86.43 is tobacco-specific",
}


DX_RESOLVED = {"S7211"}  # mismatch already handled by falling back to the parent code


def build_diagnosis(freq: Counter, desc: dict, names: dict) -> list[dict]:
    rows = []
    for line in (SNAP / "diagnosis_icd10_lookup.txt").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("~")
        code = parts[0]
        common = dict(source_table="case_visit", source_field="Primary/Secondary diagnosis",
                      source_code=code, source_description=desc.get(code, ""),
                      source_vocab_hint="ICD-10-AM (presumed; not in Athena)",
                      frequency=freq.get(code, ""), mapping_group_id=f"DX-{code}")
        if parts[1] == "NONE":
            unmapped(rows, "ICD-10-AM-specific code; no WHO ICD10 code or parent exists in Athena "
                           "(Athena has no ICD10AM vocabulary)", mapping_method="vocab_api",
                     rationale="AM-only category (e.g. U73 activity, Y92.x2 place codes, E09)",
                     **common)
            continue
        level, src_id, icd = parts[1], parts[2], parts[3]
        exact = level == "EXACT"
        rationale = (f"Identical code {icd} exists in WHO ICD10; cross-version match "
                     "(ICD-10-AM -> ICD10) - reviewer must confirm meaning is unchanged"
                     if exact else
                     f"Code absent from WHO ICD10; parent {icd} used (WIDER). Candidate only")
        status = "PROPOSED"
        if code in DX_REVIEW:
            rationale = f"{rationale}. {DX_REVIEW[code]}"
            status = "PROPOSED" if code in DX_RESOLVED else "NEEDS_CLINICAL_REVIEW"
        seq = 0
        for t in parts[4].split("#"):
            rel, tid, dom, std, valid, voc, ccode = t.split("^")[:7]
            if rel == "M":
                seq += 1
            row(rows, **common, map_seq=str(max(seq, 1)),
                relationship="Maps to" if rel == "M" else "Maps to value",
                target_concept_id=tid, target_concept_name=names.get(tid, ""),
                target_vocabulary_id=voc, target_domain_id=dom,
                standard_concept="S" if std == "Standard" else std,
                invalid_reason="" if valid == "Valid" else valid,
                source_concept_id=src_id, equivalence="EQUAL" if exact else "WIDER", status=status,
                mapping_method="vocab_api: ICD10 'Maps to'", rationale=rationale)
    return rows


# ---------------------------------------------------------------- labs
LAB_NOTES = {
    "GHB": "Value 5.8 implies % (NGSP); no unit in source - reviewer to confirm",
    "GHB2": "Value 40 implies mmol/mol (IFCC); no unit in source - reviewer to confirm",
    "CRE": "Moles/volume chosen from value range (umol/L); unit inferred, not in source",
    "25OHD": "Unit unknown (nmol/L vs ng/mL); mass/volume concept chosen - review",
    "NRBC": "Value 0.1 could be #/volume or /100 WBC - review",
}


def build_lab(freq: Counter, names_by_key: dict) -> list[dict]:
    rows = []
    loinc = {}
    for line in (SNAP / "lab_loinc_lookup.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            code, lc, cid, name = line.split("^", 3)
            loinc[code] = (lc, cid, name)
    for key, desc in sorted(names_by_key.items()):
        test_code = key.split("|")[0]
        common = dict(source_table="lab_results", source_field="Test_Code|Short_Text",
                      source_code=key, source_description=desc, source_vocab_hint="local lab code",
                      frequency=freq.get(key, ""), mapping_group_id=f"LAB-{test_code}")
        if test_code == "CHSCL":
            row(rows, **common, target_concept_id="3003150",
                target_concept_name="Sample lipemic [Presence] of Serum or Plasma",
                target_vocabulary_id="LOINC", target_domain_id="Measurement", standard_concept="S",
                equivalence="EQUAL", mapping_method="athena_web search",
                rationale="Lipaemic index reported as category ('Mild Lipaemia')")
        elif test_code == "SLIDE":
            unmapped(rows, "Workflow flag ('Reviewed'), not a clinical measurement result",
                     mapping_method="manual", **common)
        elif test_code in loinc:
            lc, cid, name = loinc[test_code]
            row(rows, **common, target_concept_id=cid, target_concept_name=name,
                target_vocabulary_id="LOINC", target_domain_id="Measurement", standard_concept="S",
                equivalence="EQUAL", mapping_method=f"LOINC code lookup {lc}",
                rationale=LAB_NOTES.get(test_code, "Short_Text + chapter + reference range"))
        else:
            unmapped(rows, "no LOINC proposal", **common)
    return rows


LAB_VALUES = [
    # (Test_Code, verbatim result, concept_id, name, rationale or unmapped reason)
    ("BSAG", "Non-Reactive", "4305306", "Non-Reactive", ""),
    ("RH", "Positive", "9191", "Positive", ""),
    ("ABO", "B", "4009006", "Blood group B", ""),
    ("ABS", "No common clinically significant red cell alloantibodies detected", "9189", "Negative",
     "Antibody screen sentence = negative screen"),
    ("CHSCL", "Mild Lipaemia", "0", "", "No Standard Meas Value concept for 'mild lipaemia' verified"),
    ("SLIDE", "Reviewed", "0", "", "Workflow flag, not a categorical result"),
]


def build_lab_value() -> list[dict]:
    rows = []
    for test, text, cid, name, note in LAB_VALUES:
        common = dict(source_table="lab_results", source_field="Test_Result",
                      source_code=f"{test}|{text}", source_description=text,
                      source_vocab_hint="free text", mapping_group_id=f"LABV-{test}")
        if cid == "0":
            unmapped(rows, note, mapping_method="manual", **common)
        else:
            row(rows, **common, target_concept_id=cid, target_concept_name=name,
                target_domain_id="Meas Value" if cid in ("4305306", "9191", "9189") else "Condition",
                target_vocabulary_id="SNOMED" if cid not in ("9191", "9189") else "Meas Value",
                standard_concept="S", equivalence="EQUAL", mapping_method="athena_web search",
                rationale=note or "verbatim categorical result")
    return rows


# ---------------------------------------------------------------- drugs
ING = "Ingredient"
CDF = "Clinical Drug Form"
DRUG_MAP = {
    # cluster code: (concept_id, name, vocabulary, class, equivalence, note)
    "P00660": ("1332418", "amlodipine", "RxNorm", ING, "WIDER", ""),
    "P00710027": ("42480682", "Amoxicillin / Clavulanate Injection", "RxNorm Extension", CDF, "WIDER", ""),
    "P00750": ("40105046", "amoxicillin / clavulanate Oral Tablet", "RxNorm", CDF, "WIDER", ""),
    "P01090": ("1112807", "aspirin", "RxNorm", ING, "WIDER", ""),
    "P01160": ("1545958", "atorvastatin", "RxNorm", ING, "WIDER", ""),
    "P012300270389": ("1734104", "azithromycin", "RxNorm", ING, "WIDER", ""),
    "P01490": ("19019620", "benzydamine", "RxNorm", ING, "WIDER", ""),
    "P01780": ("924939", "bisacodyl", "RxNorm", ING, "WIDER", ""),
    "P01830": ("1338005", "bisoprolol", "RxNorm", ING, "WIDER", ""),
    "P02070": ("902616", "calamine", "RxNorm", ING, "WIDER", ""),
    "P02230": ("1351557", "candesartan", "RxNorm", ING, "WIDER", ""),
    "P024300270194": ("1771162", "cefazolin", "RxNorm", ING, "WIDER", ""),
    "P024800270194": ("1776684", "ceftazidime", "RxNorm", ING, "WIDER", ""),
    "P02650": ("1790812", "chlorhexidine", "RxNorm", ING, "WIDER", ""),
    "P02730": ("1192710", "chlorpheniramine", "RxNorm", ING, "WIDER", "chlorphenamine = chlorpheniramine"),
    "P03380027": ("40166953", "calcium chloride / lactate / potassium chloride / sodium chloride Injectable Solution",
                  "RxNorm", CDF, "EQUAL", "Compound sodium lactate (Hartmann's)"),
    "P04070024": ("40044592", "glucose / sodium chloride Injectable Solution", "RxNorm", CDF, "WIDER", "dextrose = glucose"),
    "P04190": ("1326303", "digoxin", "RxNorm", ING, "WIDER", ""),
    "P04300": ("40031530", "diosmin / hesperidin Oral Tablet", "RxNorm", CDF, "WIDER", ""),
    "P04810": ("1341927", "enalapril", "RxNorm", ING, "WIDER", ""),
    "P05460": None,  # see DRUG_UNMAPPED
    "P054700270110": ("1154029", "fentanyl", "RxNorm", ING, "WIDER", ""),
    "P05490": ("1396012", "ferrous gluconate", "RxNorm", ING, "WIDER", "'Compound' product; other components unknown"),
    "P05500": ("1153428", "fexofenadine", "RxNorm", ING, "WIDER", ""),
    "P05920": ("956874", "furosemide", "RxNorm", ING, "WIDER", ""),
    "P06300": ("1361711", "nitroglycerin", "RxNorm", ING, "WIDER", "glyceryl trinitrate = nitroglycerin"),
    "P06650": ("974166", "hydrochlorothiazide", "RxNorm", ING, "WIDER", ""),
    "P06850": ("777221", "hydroxyzine", "RxNorm", ING, "WIDER", ""),
    "P071800270103": ("1596977", "insulin, regular, human", "RxNorm", ING, "WIDER", "Actrapid = soluble human insulin"),
    "P07590": ("1185922", "ketoprofen", "RxNorm", ING, "WIDER", ""),
    "P07690": ("987245", "lactulose", "RxNorm", ING, "WIDER", ""),
    "P08250": ("1107830", "loratadine", "RxNorm", ING, "WIDER", ""),
    "P08730": ("1503297", "metformin", "RxNorm", ING, "WIDER", ""),
    "P08890": ("906780", "metoclopramide", "RxNorm", ING, "WIDER", ""),
    "P088900270133": ("906780", "metoclopramide", "RxNorm", ING, "WIDER", ""),
    "P09110": ("905233", "mometasone", "RxNorm", ING, "WIDER", ""),
    "P09170": ("1110410", "morphine", "RxNorm", ING, "WIDER", ""),
    "P096600270371": ("1321341", "norepinephrine", "RxNorm", ING, "WIDER", ""),
    "P09830": ("923645", "omeprazole", "RxNorm", ING, "WIDER", ""),
    "P098300270357": ("923645", "omeprazole", "RxNorm", ING, "WIDER", ""),
    "P10080": ("1125315", "acetaminophen", "RxNorm", ING, "WIDER", "paracetamol = acetaminophen"),
    "P103500270412": ("1102527", "meperidine", "RxNorm", ING, "WIDER", "pethidine = meperidine"),
    "P10500": ("43262564", "Bromhexine / pholcodine Oral Solution", "RxNorm Extension", CDF, "WIDER", ""),
    "P10530": ("19044727", "vitamin K1", "RxNorm", ING, "WIDER", "phytomenadione = vitamin K1"),
    "P10610027": ("46275426", "piperacillin / tazobactam Injection", "RxNorm", CDF, "WIDER", ""),
    "P108100270248": ("19049105", "potassium chloride", "RxNorm", ING, "WIDER", ""),
    "P10820": ("19049105", "potassium chloride", "RxNorm", ING, "WIDER", ""),
    "P10830": ("976545", "potassium citrate", "RxNorm", ING, "WIDER", ""),
    "P11150": ("40029854", "codeine / promethazine Oral Solution", "RxNorm", CDF, "WIDER", ""),
    "P112000270232": ("753626", "propofol", "RxNorm", ING, "WIDER", ""),
    "P11840": ("40144024", "fluticasone / salmeterol Metered Dose Inhaler", "RxNorm", CDF, "WIDER", "Evohaler = MDI"),
    "P11860": ("40144024", "fluticasone / salmeterol Metered Dose Inhaler", "RxNorm", CDF, "WIDER", "Evohaler = MDI"),
    "P11950": ("938268", "sennosides, USP", "RxNorm", ING, "WIDER", ""),
    "P12050": ("1539403", "simvastatin", "RxNorm", ING, "WIDER", ""),
    "P12160": ("40080069", "sodium chloride Injectable Solution", "RxNorm", CDF, "WIDER", "diluent"),
    "P12160024": ("40080069", "sodium chloride Injectable Solution", "RxNorm", CDF, "WIDER", ""),
    "P12540": ("970250", "spironolactone", "RxNorm", ING, "WIDER", ""),
    "P13670": ("1103314", "tramadol", "RxNorm", ING, "WIDER", ""),
    "P136700270412": ("1103314", "tramadol", "RxNorm", ING, "WIDER", ""),
    "P14290": ("1310149", "warfarin", "RxNorm", ING, "WIDER", ""),
    "P16440": ("40822308", "Calcium / Cholecalciferol Oral Tablet", "RxNorm Extension", CDF, "WIDER", ""),
    "P22380": ("924566", "tamsulosin", "RxNorm", ING, "WIDER", ""),
    "P23140": ("40163718", "prasugrel", "RxNorm", ING, "WIDER", ""),
    "P23620024": ("19093848", "magnesium sulfate", "RxNorm", ING, "WIDER", "premix in NaCl 0.9%"),
}
DRUG_UNMAPPED = {
    "P05460": "No Standard metered-dose-inhaler form for fenoterol/ipratropium; Athena forms "
              "(powder, solution) do not match source 'Inhaler, puff'",
    "P06240": "Enteral nutrition product (Glucerna); no Standard Drug concept verified",
    "P09310": "Composition of 'Mylocaine' suspension not verified",
    "P14830024": "Blood product (fresh frozen plasma); no Standard Drug concept verified",
    "P14970": "Emollient (QV Cream); no Standard Drug concept verified",
    "P15020": "Emollient (Cetaphil); no Standard Drug concept verified",
    "P21780": "Oral nutrition supplement (Resource Plus); no Standard Drug concept verified",
    "P24970": "Oral nutrition supplement (Resource Fruit Beverage); no Standard Drug concept verified",
    "P25030": "Skin cleanser (QV Gentle Wash); no Standard Drug concept verified",
    "P26320": "Oral nutrition supplement (Fresubin); no Standard Drug concept verified",
}


def build_drug(freq: Counter, desc: dict) -> list[dict]:
    rows = []
    for code in sorted(desc):
        common = dict(source_table="medication_order", source_field="Cluster_Preferred_Name_Code",
                      source_code=code, source_description=desc[code], source_vocab_hint="local drug cluster",
                      frequency=freq.get(code, ""), mapping_group_id=f"DRUG-{code}")
        if code in DRUG_UNMAPPED:
            unmapped(rows, DRUG_UNMAPPED[code], mapping_method="athena_web search", **common)
            continue
        if DRUG_MAP.get(code) is None:
            unmapped(rows, "no proposal", **common)
            continue
        cid, name, voc, cls, eq, note = DRUG_MAP[code]
        rationale = note or ("Ingredient level: strength/form not encoded (Clinical Drug mapping is a "
                             "review TODO)" if cls == ING else "Clinical Drug Form; strength not encoded")
        row(rows, **common, target_concept_id=cid, target_concept_name=name, target_vocabulary_id=voc,
            target_domain_id="Drug", target_concept_class_id=cls, standard_concept="S",
            equivalence=eq, mapping_method="athena_web search (RxNorm exact name)", rationale=rationale)
    return rows


# ---------------------------------------------------------------- procedures
PROC_MAP = {
    "ESF701I": [("4294382", "Esophagogastroduodenoscopy", "EQUAL", "Upper GI endoscopy +/- biopsy")],
    "XSC718T": [("4308384", "Biopsy of thorax", "WIDER", "Percutaneous/IR approach not encoded")],
    "ZSD714H": [("4142645", "Angiography of coronary artery", "EQUAL", "one-to-many: angiography"),
                ("4184832", "Imaging guided percutaneous transluminal angioplasty of coronary artery", "EQUAL",
                 "one-to-many: angioplasty (official 'Maps to' target of SNOMED 11101003 PTCA)")],
    "DSIC004": [("4337799", "Dilation of cervical canal", "EQUAL", "")],
    "CSM700N": [("37153412", "Nasendoscopy", "EQUAL", "")],
    "SSB705F": [("4231432", "Intramedullary nailing of femur", "WIDER", "multifragmentary fracture context not encoded")],
}


def build_procedure(freq: Counter, desc: dict) -> list[dict]:
    rows = []
    for code in sorted(desc):
        common = dict(source_table="surgical", source_field="Surgical_Code", source_code=code,
                      source_description=desc[code], source_vocab_hint="TOSP (presumed; not in Athena)",
                      frequency=freq.get(code, ""), mapping_group_id=f"PX-{code}")
        for seq, (cid, name, eq, note) in enumerate(PROC_MAP[code], start=1):
            row(rows, **common, map_seq=str(seq), target_concept_id=cid, target_concept_name=name,
                target_vocabulary_id="SNOMED", target_domain_id="Procedure", standard_concept="S",
                equivalence=eq, mapping_method="athena_web search (SNOMED Procedure)", rationale=note)
    return rows


# ---------------------------------------------------------------- demographics / visit / fixed
def build_demographics() -> list[dict]:
    rows = []
    for code, cid, name, dom, voc in [
        ("Gender|Male", "8507", "MALE", "Gender", "Gender"),
        ("Gender|Female", "8532", "FEMALE", "Gender", "Gender"),
        ("Race|Chinese", "38003579", "Chinese", "Race", "Race"),
    ]:
        row(rows, source_table="patient_demo", source_field=code.split("|")[0], source_code=code,
            source_description=code.split("|")[1], target_concept_id=cid, target_concept_name=name,
            target_vocabulary_id=voc, target_domain_id=dom, standard_concept="S", equivalence="EQUAL",
            mapping_method="athena_web search", mapping_group_id=f"DEMO-{code}")
    for code, attr, attr_name, val, val_name in [
        ("Religion|Buddhism", "4052017", "Religious affiliation", "4143324", "Buddhism"),
        ("Marital_Status|Marr'd", "4053609", "Marital status", "4338692", "Married"),
    ]:
        common = dict(source_table="patient_demo", source_field=code.split("|")[0], source_code=code,
                      source_description=code.split("|")[1], mapping_group_id=f"DEMO-{code}",
                      mapping_method="athena_web search", equivalence="EQUAL")
        row(rows, **common, target_concept_id=attr, target_concept_name=attr_name,
            target_vocabulary_id="SNOMED", target_domain_id="Observation", standard_concept="S")
        row(rows, **common, relationship="Maps to value", target_concept_id=val,
            target_concept_name=val_name, target_vocabulary_id="SNOMED", target_domain_id="Observation",
            standard_concept="S")
    for code in ("Religion|No Mapping", "Marital_Status|No Mapping"):
        unmapped(rows, "Source value 'No Mapping' means unknown; no OBSERVATION is generated",
                 source_table="patient_demo", source_field=code.split("|")[0], source_code=code,
                 source_description="No Mapping", mapping_method="manual", mapping_group_id=f"DEMO-{code}")
    return rows


def build_visit() -> list[dict]:
    rows = []
    for code, cid, name, note in [
        ("Emergency|Intra-Hosp A&E", "9201", "Inpatient Visit",
         "Admitted via A&E; ER+Inpatient (262) is the alternative - group decision U4"),
        ("Emergency|Intra-Hosp SOC", "9201", "Inpatient Visit", "Emergency admission referred from SOC"),
        ("Day Surgery|Intra-Hosp SOC", "9202", "Outpatient Visit", "Same-day day-surgery case"),
    ]:
        row(rows, source_table="case_visit", source_field="Adm_Type_Desc|Referral_Type_From",
            source_code=code, target_concept_id=cid, target_concept_name=name,
            target_vocabulary_id="Visit", target_domain_id="Visit", standard_concept="S",
            equivalence="EQUAL", mapping_method="rule table", rationale=note, mapping_group_id=f"VISIT-{code}")
    return rows


FIXED = [
    ("type:visit", "32827", "EHR encounter record", "Type Concept"),
    ("type:condition", "32821", "EHR billing record", "Type Concept"),
    ("type:drug", "32833", "EHR order", "Type Concept"),
    ("type:measurement", "32856", "Lab", "Type Concept"),
    ("type:procedure", "32817", "EHR", "Type Concept"),
    ("type:observation", "32817", "EHR", "Type Concept"),
    ("type:death", "32817", "EHR", "Type Concept"),
    ("type:period", "32882", "Standard algorithm from EHR", "Type Concept"),
    ("status:PRIMARY", "32902", "Primary diagnosis", "Condition Status"),
    ("status:SECONDARY", "32908", "Secondary diagnosis", "Condition Status"),
    ("operator:<", "4171756", "<", "Meas Value Operator"),
    ("cdm:v5.4", "756265", "OMOP CDM Version 5.4.0", "Metadata"),
]
FIXED_NOTES = {
    "type:condition": "Diagnoses come from Mediclaim/Subvention (billing) fields",
    "type:drug": "Medication ORDERS, not administrations",
    "type:period": "Observation period inferred from earliest/latest event",
}


def build_fixed() -> list[dict]:
    rows = []
    for key, cid, name, dom in FIXED:
        row(rows, source_table="(fixed)", source_field="convention", source_code=key,
            target_concept_id=cid, target_concept_name=name, target_domain_id=dom,
            target_vocabulary_id=dom, standard_concept="S", equivalence="EQUAL",
            mapping_method="athena_web search", rationale=FIXED_NOTES.get(key, ""), mapping_group_id=key)
    return rows


def load_target_names() -> dict:
    path = SNAP / "concept_names.txt"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            cid, name = line.split("^", 1)
            out[cid] = name
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, required=True, help="folder with the 25 course workbooks")
    args = ap.parse_args()
    from etl.load import load_all
    tables, _ = load_all(args.raw)
    visits, _ = clean.dedup_exact(tables["case_visit"])
    dx = clean.explode_diagnoses(visits)
    dx_freq = Counter(dx.code)
    dx_desc = {r.code: r.description for r in dx.itertuples() if pd.notna(r.description)}
    lab = tables["lab_results"]
    lab_keys = [clean.lab_key(a, b) for a, b in zip(lab.Test_Code, lab.Short_Text)]
    lab_desc = {k: k.split("|")[1] for k in lab_keys}
    med = tables["medication_order"]
    drug_desc = dict(zip(med.Cluster_Preferred_Name_Code, med.Cluster_Preferred_Name_Description))
    sx = tables["surgical"]
    sx_desc = dict(zip(sx.Surgical_Code, sx.Surgical_Desc))

    names = load_target_names()
    sheets = {
        "diagnosis": build_diagnosis(dx_freq, dx_desc, names),
        "lab": build_lab(Counter(lab_keys), lab_desc),
        "lab_value": build_lab_value(),
        "drug": build_drug(Counter(med.Cluster_Preferred_Name_Code), drug_desc),
        "procedure": build_procedure(Counter(sx.Surgical_Code), sx_desc),
        "demographics": build_demographics(),
        "visit": build_visit(),
        "fixed": build_fixed(),
    }
    for name, rows in sheets.items():
        pd.DataFrame(rows, columns=MAPPING_COLUMNS).to_csv(OUT / f"{name}.csv", index=False)
        print(f"{name}.csv: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
