"""Central primary-key allocator: every table is numbered from 1 in a deterministic order."""
from __future__ import annotations

import pandas as pd

from .deid import Deid

PK = {
    "person": "person_id",
    "observation_period": "observation_period_id",
    "visit_occurrence": "visit_occurrence_id",
    "condition_occurrence": "condition_occurrence_id",
    "drug_exposure": "drug_exposure_id",
    "procedure_occurrence": "procedure_occurrence_id",
    "measurement": "measurement_id",
    "observation": "observation_id",
}

DATE_COL = {
    "condition_occurrence": "condition_start_date",
    "drug_exposure": "drug_exposure_start_date",
    "procedure_occurrence": "procedure_date",
    "measurement": "measurement_date",
    "observation": "observation_date",
}


def assign_visit_ids(visits: pd.DataFrame, deid: Deid) -> dict[str, int]:
    """visit_occurrence_id ordered by (person_id, shifted admission, HMAC(Case_No))."""
    keys = sorted(
        (deid.person_id(v.Patient_No), deid.shift_dt(v.Patient_No, v.Adm_DateTime),
         deid.h("visit", v.Case_No), v.Case_No)
        for v in visits.itertuples()
    )
    return {k[3]: i for i, k in enumerate(keys, start=1)}


def allocate(table: str, rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    order = ["person_id", DATE_COL[table], "_key", "_seq"]
    df = df.sort_values(order, kind="mergesort").reset_index(drop=True)
    df.insert(0, PK[table], range(1, len(df) + 1))
    return df
