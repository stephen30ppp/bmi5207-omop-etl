"""Pipeline entry point.

    python -m etl.run --raw "<folder with Patient N ... sub-folders>" --secret secrets/etl.key --out output

Stages: raw -> staging -> de-identification -> builders -> domain router -> central keys ->
OMOP writer -> validation. Exit code 1 if any ERROR-level validation check fails.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from . import cdm54, ids, settings
from .builders import drug, measurement, person, procedure, visit
from .clean import dedup_exact
from .context import Context
from .deid import Deid
from .load import docprops_modified, load_all
from .router import TABLE_FIELDS, route
from .validate import validate
from .vocab import VocabIndex
from .write import write_plain, write_table

LINEAGE_COLUMNS = ["source_event_key", "source_table", "outcome", "cdm_table", "cdm_id", "concept_id",
                   "mapping_status", "equivalence", "unmapped_reason"]
CONCEPT_COL = {t: f[0] for t, f in TABLE_FIELDS.items()}


def event_span(tables: dict, visits: pd.DataFrame, deid: Deid) -> dict[int, tuple[dt.date, dt.date]]:
    """Earliest / latest shifted clinical event per person (visits, labs, orders, procedures)."""
    stamps: dict[int, list] = {}
    sources = [(visits, "Adm_DateTime"), (visits, "Dis_DateTime"),
               (tables["lab_results"], "Result_Test_Date"),
               (tables["medication_order"], "Order_Creation_Date"),
               (tables["surgical"], "operation_date")]
    for df, col in sources:
        for p, t in zip(df.Patient_No, df[col]):
            stamps.setdefault(deid.person_id(p), []).append(deid.shift_dt(p, t).date())
    return {pid: (min(v), max(v)) for pid, v in stamps.items()}


def run(raw: Path, secret: bytes, out: Path, mapping_mode: str = "review") -> dict:
    tables, manifest = load_all(raw)
    visits, dropped = dedup_exact(tables["case_visit"])
    deid = Deid(secret, list(tables["patient_demo"].Patient_No))
    vocab = VocabIndex.load(settings.MAPPINGS_DIR, mapping_mode)
    ctx = Context(deid, vocab, tables, visits, ids.assign_visit_ids(visits, deid))

    for r in dropped.itertuples():
        key = deid.source_event_key("VIS", r.Patient_No, r.src_folder, r.src_row)
        ctx.outcome(key, "case_visit", "deduplicated", "exact duplicate of an earlier case_visit row")
        ctx.log("visit_exact_duplicate", key, "row identical in all 40 columns; dropped", "WARN")

    span = event_span(tables, visits, deid)
    ctx.period_start = {pid: s for pid, (s, _) in span.items()}
    period_type = vocab.concept("type:period")
    periods = [{"observation_period_id": i, "person_id": pid, "observation_period_start_date": s,
                "observation_period_end_date": e, "period_type_concept_id": period_type}
               for i, (pid, (s, e)) in enumerate(sorted(span.items()), start=1)]

    direct = {
        "person": person.build_person(ctx),
        "death": person.build_death(ctx),
        "visit_occurrence": visit.build_visits(ctx),
    }
    drug_ev, doses = drug.drug_events(ctx)
    events = (person.demographic_events(ctx) + visit.condition_events(ctx)
              + measurement.measurement_events(ctx) + drug_ev + procedure.procedure_events(ctx))
    routed = {t: ids.allocate(t, rows) for t, rows in route(events).items()}

    lineage = list(ctx.lineage)
    pk_of = {"person": "person_id", "death": "person_id", "visit_occurrence": "visit_occurrence_id"}
    concept_of = {"person": "gender_concept_id", "death": "death_type_concept_id",
                  "visit_occurrence": "visit_concept_id"}
    for t, rows in direct.items():
        for r in rows:
            source = "case_visit" if t == "visit_occurrence" else "patient_demo"
            lineage.append({"source_event_key": r["_key"], "source_table": source,
                            "outcome": "written", "cdm_table": t, "cdm_id": r[pk_of[t]],
                            "concept_id": r[concept_of[t]], "mapping_status": r.get("_status", ""),
                            "equivalence": "", "unmapped_reason": r.get("_unmapped_reason", "")})
    for t, df in routed.items():
        for r in df.to_dict("records"):
            lineage.append({"source_event_key": r["_key"], "source_table": r["_source_table"],
                            "outcome": "written_rerouted" if r["_rerouted"] else "written",
                            "cdm_table": t, "cdm_id": r[ids.PK[t]],
                            "concept_id": r[CONCEPT_COL[t]], "mapping_status": r["_status"],
                            "equivalence": r["_equivalence"], "unmapped_reason": r["_unmapped_reason"]})
    lineage_df = pd.DataFrame(lineage, columns=LINEAGE_COLUMNS).sort_values(
        ["source_table", "source_event_key", "cdm_table", "cdm_id"], kind="mergesort")

    modified = docprops_modified(raw)
    cdm_source = [{
        "cdm_source_name": settings.CDM_SOURCE_NAME,
        "cdm_source_abbreviation": settings.CDM_SOURCE_ABBREVIATION,
        "cdm_holder": settings.CDM_HOLDER,
        "source_description": settings.SOURCE_DESCRIPTION,
        "cdm_etl_reference": settings.CDM_ETL_REFERENCE,
        "source_release_date": dt.date.fromisoformat(settings.SOURCE_RELEASE_DATE_PROXY),
        "cdm_release_date": dt.date.today(),
        "cdm_version": settings.CDM_VERSION,
        "cdm_version_concept_id": vocab.concept("cdm:v5.4"),
        "vocabulary_version": vocab.vocabulary_version()[:20],
    }]
    if modified != {settings.SOURCE_RELEASE_DATE_PROXY}:
        ctx.log("source_release_date_proxy", "", f"docProps modified dates {sorted(modified)}", "WARN")

    for t, pk in (("person", "person_id"), ("death", "person_id"), ("visit_occurrence", "visit_occurrence_id")):
        direct[t] = sorted(direct[t], key=lambda r: r[pk])
    final = {
        "person": pd.DataFrame(direct["person"]),
        "observation_period": pd.DataFrame(periods),
        "visit_occurrence": pd.DataFrame(direct["visit_occurrence"]),
        "condition_occurrence": routed["condition_occurrence"],
        "drug_exposure": routed["drug_exposure"],
        "procedure_occurrence": routed["procedure_occurrence"],
        "measurement": routed["measurement"],
        "observation": routed["observation"],
        "death": pd.DataFrame(direct["death"]),
        "cdm_source": pd.DataFrame(cdm_source),
    }
    omop_dir = out / "omop"
    written = {t: write_table(t, df, omop_dir) for t, df in final.items()}

    drug_ids = routed["drug_exposure"][["_key", "drug_exposure_id"]].rename(columns={"_key": "source_event_key"})
    dose_df = pd.DataFrame(doses).merge(drug_ids, on="source_event_key", how="left")
    write_plain(dose_df[["drug_exposure_id", "source_event_key", "component_type", "dose_value",
                         "dose_unit", "dose_raw", "dose_parse_status", "dosage_form"]],
                out / "intermediate" / "drug_dose.csv")
    write_plain(lineage_df, out / "lineage" / "source_event_lineage.csv")
    write_plain(pd.DataFrame(ctx.dq, columns=["level", "check", "source_event_key", "detail"]),
                out / "dq_log.csv")
    unmapped = lineage_df[lineage_df.unmapped_reason.astype(str) != ""]
    write_plain(unmapped.groupby(["source_table", "cdm_table", "unmapped_reason"], dropna=False)
                .size().reset_index(name="rows"), out / "unmapped_summary.csv")

    report = validate(raw, tables, visits, final, written, lineage_df, vocab, deid, out)
    write_plain(report["checks"], out / "validation_summary.csv")
    write_plain(report["coverage"], out / "mapping_coverage.csv")

    hashes = {f"omop/{t}.csv": hashlib.sha256((omop_dir / f"{t}.csv").read_bytes()).hexdigest()
              for t in final}
    (out / "manifest.json").write_text(json.dumps({
        "cdm_version": settings.CDM_VERSION, "mapping_mode": mapping_mode,
        "vocabulary_version": vocab.vocabulary_version(),
        "inputs": manifest, "outputs": hashes,
        "row_counts": {t: len(df) for t, df in final.items()},
        "validation": report["summary"],
    }, indent=2, default=str) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BMI5207 Group 3d OMOP CDM v5.4 ETL")
    ap.add_argument("--raw", type=Path, required=True, help="folder holding the 'Patient N ...' folders")
    ap.add_argument("--secret", type=Path, required=True, help="file with the HMAC secret (>=16 bytes)")
    ap.add_argument("--out", type=Path, default=settings.ROOT / "output")
    ap.add_argument("--mapping-mode", choices=sorted(settings.ACCEPTED_STATUSES), default="review",
                    help="review = APPROVED+PROPOSED mappings; final = APPROVED only")
    args = ap.parse_args(argv)
    report = run(args.raw, args.secret.read_bytes().strip(), args.out, args.mapping_mode)
    s = report["summary"]
    print(f"validation: {s['PASS']} pass, {s['WARN']} warn, {s['FAIL']} fail -> {args.out}")
    return 1 if s["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
