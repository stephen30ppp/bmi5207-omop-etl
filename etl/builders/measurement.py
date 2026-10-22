"""lab_results -> MEASUREMENT events.

visit_occurrence_id stays NULL: lab Case_No values never appear in case_visit and their encounter
type is unknown (docs/04 D2). Units are absent from the source, so unit_concept_id is NULL.
"""
from __future__ import annotations

import pandas as pd

from ..clean import lab_key, parse_result
from ..context import Context
from ..router import Event


def measurement_events(ctx: Context) -> list[Event]:
    events = []
    type_id = ctx.vocab.concept("type:measurement")
    for r in ctx.tables["lab_results"].itertuples():
        p = r.Patient_No
        key = ctx.deid.source_event_key("LAB", p, r.src_folder, r.src_row)
        code = lab_key(r.Test_Code, r.Short_Text)
        res = parse_result(r.Test_Result)
        fields = {
            "range_low": None if pd.isna(r.Minimum_Range) else float(r.Minimum_Range),
            "range_high": None if pd.isna(r.Maximum_Range) else float(r.Maximum_Range),
            "unit_concept_id": None, "unit_source_value": None,
            "value_source_value": res.text[:50],
        }
        if res.kind == "numeric":
            fields["value_as_number"] = res.value_as_number
        elif res.kind == "operator":
            fields["value_as_number"] = res.value_as_number
            fields["operator_concept_id"] = ctx.vocab.concept(f"operator:{res.operator}")
        else:
            test = code.split("|")[0]
            value = ctx.vocab.lookup("lab_value", f"{test}|{res.text}")
            # categorical result present: mapped concept, else 0 (CDM v5.4 convention)
            fields["value_as_concept_id"] = value.targets[0].concept_id if value.mapped else 0
            if not value.mapped:
                ctx.log("categorical_value_unmapped", key, value.unmapped_reason)
        if len(res.text) > 50:
            ctx.log("value_source_value_truncated", key, f"full text ({len(res.text)} chars): {res.text}")
        if pd.isna(r.Test_Code):
            ctx.log("lab_code_missing", key, f"Test_Code empty; mapped by Short_Text key {code}")
        events.append(Event(
            key=key, source_table="lab_results", default_table="measurement",
            person_id=ctx.deid.person_id(p), start=ctx.deid.shift_dt(p, r.Result_Test_Date),
            type_concept_id=type_id, source_value=code, mapping=ctx.vocab.lookup("lab", code),
            visit_occurrence_id=None, fields=fields,
        ))
    return events
