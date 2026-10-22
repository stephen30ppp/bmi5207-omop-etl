"""surgical -> PROCEDURE_OCCURRENCE events.

operation_date equals Adm_DateTime in 7/7 rows, so only the date is trusted (procedure_datetime NULL).
"""
from __future__ import annotations

from ..context import Context
from ..router import Event


def procedure_events(ctx: Context) -> list[Event]:
    events = []
    type_id = ctx.vocab.concept("type:procedure")
    adm = {v.Case_No: v.Adm_DateTime for v in ctx.visits.itertuples()}
    for r in ctx.tables["surgical"].itertuples():
        p = r.Patient_No
        key = ctx.deid.source_event_key("PRC", p, r.src_folder, r.src_row)
        if r.operation_date == adm.get(r.Case_No):
            ctx.log("procedure_time_equals_admission", key, "procedure_datetime left NULL")
        events.append(Event(
            key=key, source_table="surgical", default_table="procedure_occurrence",
            person_id=ctx.deid.person_id(p), start=ctx.deid.shift_dt(p, r.operation_date),
            type_concept_id=type_id, source_value=str(r.Surgical_Code),
            mapping=ctx.vocab.lookup("procedure", str(r.Surgical_Code)),
            visit_occurrence_id=ctx.visit_ids[r.Case_No], keep_datetime=False,
            fields={"quantity": 1},
        ))
    return events
