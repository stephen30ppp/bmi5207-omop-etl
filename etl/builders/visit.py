"""case_visit -> VISIT_OCCURRENCE (one row per de-duplicated Case_No) and diagnosis events."""
from __future__ import annotations

from ..clean import explode_diagnoses
from ..context import Context
from ..router import Event


def build_visits(ctx: Context) -> list[dict]:
    rows = []
    type_id = ctx.vocab.concept("type:visit")
    for v in ctx.visits.itertuples():
        p = v.Patient_No
        rule = ctx.vocab.lookup("visit", f"{v.Adm_Type_Desc}|{v.Referral_Type_From}")
        start, end = ctx.deid.shift_dt(p, v.Adm_DateTime), ctx.deid.shift_dt(p, v.Dis_DateTime)
        rows.append({
            "visit_occurrence_id": ctx.visit_ids[v.Case_No],
            "person_id": ctx.deid.person_id(p),
            "visit_concept_id": rule.targets[0].concept_id if rule.mapped else 0,
            "visit_start_date": start.date(), "visit_start_datetime": start,
            "visit_end_date": end.date(), "visit_end_datetime": end,
            "visit_type_concept_id": type_id,
            "visit_source_value": v.Adm_Type_Desc,
            "visit_source_concept_id": 0,
            "admitted_from_concept_id": 0,
            "admitted_from_source_value": v.Referral_Type_From,
            "discharged_to_concept_id": 0,
            "discharged_to_source_value": v.Discharge_Type_Desc,
            "_key": ctx.deid.source_event_key("VIS", p, v.src_folder, v.src_row),
            "_status": rule.status,
            "_unmapped_reason": "" if rule.mapped else rule.unmapped_reason,
        })
    return rows


def condition_events(ctx: Context) -> list[Event]:
    events = []
    type_id = ctx.vocab.concept("type:condition")
    status_id = {s: ctx.vocab.concept(f"status:{s}") for s in ("PRIMARY", "SECONDARY")}
    for d in explode_diagnoses(ctx.visits).itertuples():
        p = d.Patient_No
        visit_start = ctx.deid.shift_dt(p, ctx.visits.loc[ctx.visits.Case_No == d.Case_No,
                                                           "Adm_DateTime"].iloc[0])
        events.append(Event(
            key=ctx.deid.source_event_key("DX", p, d.src_folder, d.src_row, d.seq),
            source_table="case_visit", default_table="condition_occurrence",
            person_id=ctx.deid.person_id(p), start=visit_start, type_concept_id=type_id,
            source_value=d.code, mapping=ctx.vocab.lookup("diagnosis", d.code),
            visit_occurrence_id=ctx.visit_ids[d.Case_No],
            fields={"condition_status_concept_id": status_id[d.status],
                    "condition_status_source_value": d.status},
        ))
    return events
