"""patient_demo -> PERSON, DEATH and OBSERVATION events (Religion, Marital_Status)."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from ..context import Context
from ..router import Event


def build_person(ctx: Context) -> list[dict]:
    rows = []
    for r in ctx.tables["patient_demo"].itertuples():
        pid = ctx.deid.person_id(r.Patient_No)
        key = ctx.deid.source_event_key("PER", r.Patient_No, r.src_folder, r.src_row)
        gender = ctx.vocab.lookup("demographics", f"Gender|{r.Gender}")
        race = ctx.vocab.lookup("demographics", f"Race|{r.Race}")
        rows.append({
            "person_id": pid,
            "gender_concept_id": gender.targets[0].concept_id if gender.mapped else 0,
            "year_of_birth": ctx.deid.shift_year(r.Patient_No, int(r.Patient_DOB)),
            "race_concept_id": race.targets[0].concept_id if race.mapped else 0,
            "ethnicity_concept_id": 0,  # US OMB ethnicity; not applicable to this data (docs/05)
            "person_source_value": f"P{pid:02d}",
            "gender_source_value": r.Gender,
            "gender_source_concept_id": 0,
            "race_source_value": r.Race,
            "race_source_concept_id": 0,
            "_key": key,
            "_status": gender.status,
        })
    return rows


def build_death(ctx: Context) -> list[dict]:
    rows = []
    type_id = ctx.vocab.concept("type:death")
    for r in ctx.tables["patient_demo"].itertuples():
        if not bool(r.Deceased_Ind):
            continue
        key = ctx.deid.source_event_key("DTH", r.Patient_No, r.src_folder, r.src_row)
        if pd.isna(r.Death_Date):
            ctx.log("death_without_year", key, "Deceased_Ind=True but Death_Date empty", "WARN")
            ctx.outcome(key, "patient_demo", "not_generated", "death year missing")
            continue
        year = ctx.deid.shift_year(r.Patient_No, int(r.Death_Date))
        rows.append({
            "person_id": ctx.deid.person_id(r.Patient_No),
            "death_date": dt.date(year, 12, 31),  # CDM convention for year-only death dates
            "death_type_concept_id": type_id,
            "_key": key,
            "_status": "PROPOSED",
        })
    return rows


def demographic_events(ctx: Context) -> list[Event]:
    """Religion / Marital_Status as OBSERVATION; 'No Mapping' (unknown) produces no record."""
    events = []
    type_id = ctx.vocab.concept("type:observation")
    for r in ctx.tables["patient_demo"].itertuples():
        pid = ctx.deid.person_id(r.Patient_No)
        for seq, field in enumerate(("Religion", "Marital_Status"), start=1):
            value = str(getattr(r, field))
            key = ctx.deid.source_event_key("OBS", r.Patient_No, r.src_folder, r.src_row, seq)
            mapping = ctx.vocab.lookup("demographics", f"{field}|{value}")
            if value == "No Mapping":
                ctx.outcome(key, "patient_demo", "not_generated", mapping.unmapped_reason)
                continue
            start = ctx.period_start[pid]
            events.append(Event(
                key=key, source_table="patient_demo", default_table="observation", person_id=pid,
                start=dt.datetime.combine(start, dt.time()), type_concept_id=type_id,
                source_value=field, mapping=mapping, keep_datetime=False,
                fields={"value_source_value": value[:50]},
            ))
            ctx.log("derived_observation_date", key,
                    "observation_date = observation period start (collection date not in source)")
    return events
