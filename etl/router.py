"""Domain router: turns source events into CDM rows according to the mapped Standard domain.

Builders produce `Event`s; only this module decides which table a row lands in. Unmapped events
keep concept_id 0 in the source's default table (DRUG_EXPOSURE convention, docs/04 D3) and carry
an explicit unmapped_reason into the lineage - nothing is dropped silently.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import cdm54, settings
from .vocab import MapResult

# table -> (concept, date, datetime, type, source_value, source_concept)
TABLE_FIELDS = {
    "condition_occurrence": ("condition_concept_id", "condition_start_date", "condition_start_datetime",
                             "condition_type_concept_id", "condition_source_value",
                             "condition_source_concept_id"),
    "observation": ("observation_concept_id", "observation_date", "observation_datetime",
                    "observation_type_concept_id", "observation_source_value",
                    "observation_source_concept_id"),
    "procedure_occurrence": ("procedure_concept_id", "procedure_date", "procedure_datetime",
                             "procedure_type_concept_id", "procedure_source_value",
                             "procedure_source_concept_id"),
    "measurement": ("measurement_concept_id", "measurement_date", "measurement_datetime",
                    "measurement_type_concept_id", "measurement_source_value",
                    "measurement_source_concept_id"),
    "drug_exposure": ("drug_concept_id", "drug_exposure_start_date", "drug_exposure_start_datetime",
                      "drug_type_concept_id", "drug_source_value", "drug_source_concept_id"),
}


@dataclass
class Event:
    key: str                       # stable source_event_key (no raw identifiers)
    source_table: str
    default_table: str
    person_id: int
    start: dt.datetime             # already date-shifted
    type_concept_id: int
    source_value: str
    mapping: MapResult
    visit_occurrence_id: int | None = None
    keep_datetime: bool = True     # False -> only the date part is trustworthy
    fields: dict = field(default_factory=dict)   # extra CDM columns (applied if the table has them)


def route(events: list[Event]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {t: [] for t in TABLE_FIELDS}
    for ev in events:
        targets = ev.mapping.targets or [None]
        for seq, tgt in enumerate(targets, start=1):
            table = settings.DOMAIN_TABLE.get(tgt.domain, ev.default_table) if tgt else ev.default_table
            concept, date_col, dt_col, type_col, sv_col, sc_col = TABLE_FIELDS[table]
            cols = set(cdm54.columns(table))
            row = {
                "person_id": ev.person_id,
                concept: tgt.concept_id if tgt else 0,
                date_col: ev.start.date(),
                dt_col: ev.start if ev.keep_datetime else None,
                type_col: ev.type_concept_id,
                sv_col: ev.source_value[:50],
                sc_col: ev.mapping.source_concept_id,
            }
            if "visit_occurrence_id" in cols:
                row["visit_occurrence_id"] = ev.visit_occurrence_id
            for k, v in ev.fields.items():
                if k in cols:
                    row[k] = v
            if tgt and tgt.value_concept_id:
                row["value_as_concept_id"] = tgt.value_concept_id
            if table == "drug_exposure":
                row.setdefault("drug_exposure_end_date", ev.start.date())
            row.update({
                "_key": ev.key, "_seq": seq, "_source_table": ev.source_table,
                "_status": ev.mapping.status, "_equivalence": ev.mapping.equivalence,
                "_unmapped_reason": "" if tgt else (ev.mapping.unmapped_reason or "unmapped"),
                "_rerouted": table != ev.default_table,
            })
            out[table].append(row)
    return out
