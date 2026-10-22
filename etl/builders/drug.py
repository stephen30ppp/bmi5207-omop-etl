"""medication_order -> DRUG_EXPOSURE events (orders, not administrations).

quantity, route and sig stay NULL: the source has no total amount, no route and no verbatim
prescriber instruction. The ordered dose is kept in the intermediate dose table instead.
"""
from __future__ import annotations

from ..clean import parse_dose
from ..context import Context
from ..router import Event


def drug_events(ctx: Context) -> tuple[list[Event], list[dict]]:
    events, doses = [], []
    type_id = ctx.vocab.concept("type:drug")
    visit_start = {v.Case_No: v.Adm_DateTime for v in ctx.visits.itertuples()}
    for r in ctx.tables["medication_order"].itertuples():
        p = r.Patient_No
        key = ctx.deid.source_event_key("DRG", p, r.src_folder, r.src_row)
        dose = parse_dose(r.Dosage_Ordered)
        doses.append({
            "source_event_key": key, "component_type": r.Component_Type_Code,
            "dose_value": dose.value, "dose_unit": r.Dosage_Ordered_Unit,
            "dose_raw": dose.raw if dose.status != "corrupt_datetime" else None,
            "dose_parse_status": dose.status, "dosage_form": r.Dosage_Form,
        })
        if dose.status == "corrupt_datetime":
            ctx.log("dose_corrupt", key, "Dosage_Ordered is an Excel datetime; dose unknown, order kept",
                    "WARN")
        elif dose.status == "range":
            ctx.log("dose_range", key, f"Dosage_Ordered is a range '{dose.raw}' {r.Dosage_Ordered_Unit}")
        if r.Order_Creation_Date < visit_start[r.Case_No]:
            hours = (visit_start[r.Case_No] - r.Order_Creation_Date).total_seconds() / 3600
            ctx.log("order_before_admission", key, f"order placed {hours:.1f} h before admission", "WARN")
        events.append(Event(
            key=key, source_table="medication_order", default_table="drug_exposure",
            person_id=ctx.deid.person_id(p), start=ctx.deid.shift_dt(p, r.Order_Creation_Date),
            type_concept_id=type_id, source_value=str(r.Cluster_Preferred_Name_Code),
            mapping=ctx.vocab.lookup("drug", str(r.Cluster_Preferred_Name_Code)),
            visit_occurrence_id=ctx.visit_ids[r.Case_No],
            fields={"dose_unit_source_value": str(r.Dosage_Ordered_Unit)[:50],
                    "sig": None, "quantity": None, "route_concept_id": None,
                    "route_source_value": None},
        ))
    return events, doses
