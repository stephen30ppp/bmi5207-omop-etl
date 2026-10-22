"""Validation layer (docs/09-validation-plan.md): structure, linkage, time, privacy, semantics,
row-level reconciliation of every source event and vocabulary coverage.

Each check yields PASS / WARN / FAIL. FAIL = ERROR level (pipeline exit code 1).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import cdm54, settings
from .clean import explode_diagnoses
from .deid import Deid
from .ids import PK
from .router import TABLE_FIELDS
from .vocab import VocabIndex

EXPECTED_EVENTS = {"PER": 5, "DTH": 2, "OBS": 10, "VIS": 22, "DX": None, "LAB": 162, "DRG": 170, "PRC": 7}
DOMAIN_OF_TABLE = {"condition_occurrence": "Condition", "drug_exposure": "Drug",
                   "procedure_occurrence": "Procedure", "measurement": "Measurement",
                   "observation": "Observation"}


class Checks:
    def __init__(self):
        self.rows = []

    def add(self, group: str, check: str, ok: bool, detail: str = "", warn_only: bool = False):
        status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
        self.rows.append({"group": group, "check": check, "status": status, "detail": detail})

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=["group", "check", "status", "detail"])


def validate(raw: Path, tables: dict, visits: pd.DataFrame, final: dict, written: dict,
             lineage: pd.DataFrame, vocab: VocabIndex, deid: Deid, out: Path) -> dict:
    c = Checks()

    # --- source contract (load.py already raised on violations; recorded here for the report)
    for t, n in settings.EXPECTED_ROWS.items():
        c.add("source", f"{t} rows == {n}", len(tables[t]) == n, str(len(tables[t])))
    c.add("source", "case_visit exact duplicates == 1", len(tables["case_visit"]) - len(visits) == 1,
          str(len(tables["case_visit"]) - len(visits)))

    # --- deterministic row counts
    for t, n in {"person": 5, "death": 2, "visit_occurrence": 21, "observation_period": 5,
                 "cdm_source": 1}.items():
        c.add("rows", f"{t} == {n}", len(final[t]) == n, str(len(final[t])))

    # --- row-level reconciliation: every source event has an outcome, every CDM row has a source
    n_dx = len(explode_diagnoses(visits))
    expected = dict(EXPECTED_EVENTS, DX=n_dx)
    prefix = lineage.source_event_key.str.split("-").str[0]
    for p, n in expected.items():
        got = lineage.loc[prefix == p, "source_event_key"].nunique()
        c.add("reconciliation", f"{p} source events with an outcome == {n}", got == n, str(got))
    c.add("reconciliation", "diagnosis source events (after visit dedup) == 149", n_dx == 149, str(n_dx))
    for t, df in final.items():
        if "_key" in df.columns:
            missing = df._key.isna().sum()
            c.add("reconciliation", f"{t}: every row traces to a source event", missing == 0, str(missing))
    silent = lineage[(lineage.concept_id.astype(str) == "0") & (lineage.unmapped_reason.astype(str) == "")]
    c.add("reconciliation", "every concept_id=0 row has an unmapped_reason", silent.empty, str(len(silent)))
    outcomes = lineage.groupby("outcome").source_event_key.nunique().to_dict()
    c.add("reconciliation", "outcomes", True, str(outcomes))

    # --- structure: required fields, primary keys
    for t, df in written.items():
        for col in cdm54.required(t):
            blank = (df[col] == "").sum()
            c.add("structure", f"{t}.{col} required non-null", blank == 0, str(blank))
        if t in PK:
            c.add("structure", f"{t}.{PK[t]} unique", df[PK[t]].is_unique)

    # --- referential integrity
    persons = set(final["person"].person_id)
    visit_person = dict(zip(final["visit_occurrence"].visit_occurrence_id, final["visit_occurrence"].person_id))
    for t, df in final.items():
        if "person_id" in df.columns and t != "person":
            bad = (~df.person_id.isin(persons)).sum()
            c.add("linkage", f"{t}.person_id in PERSON", bad == 0, str(bad))
        if "visit_occurrence_id" in df.columns and t != "visit_occurrence":
            v = df.dropna(subset=["visit_occurrence_id"])
            bad = sum(visit_person.get(int(a)) != b for a, b in zip(v.visit_occurrence_id, v.person_id))
            c.add("linkage", f"{t}.visit_occurrence_id exists and belongs to same person", bad == 0, str(bad))
    meas_visits = final["measurement"].visit_occurrence_id.notna().sum()
    c.add("linkage", "MEASUREMENT.visit_occurrence_id all NULL (lab episode not a confirmed visit)",
          meas_visits == 0, str(meas_visits))

    # --- vocabulary: every non-zero concept is a reviewed Standard target in the right domain
    targets = pd.concat(vocab.frames.values(), ignore_index=True)
    std = targets[(targets.target_concept_id != "") & (targets.target_concept_id != "0")]
    info = {int(r.target_concept_id): (r.standard_concept, r.invalid_reason, r.target_domain_id)
            for r in std.itertuples()}
    for t, cols in TABLE_FIELDS.items():
        df = final[t]
        ids_ = [int(x) for x in df[cols[0]] if int(x) != 0]
        not_std = [i for i in ids_ if info.get(i, ("", "", ""))[0] != "S" or info[i][1] != ""]
        c.add("vocabulary", f"{t}.{cols[0]} non-zero concepts Standard & valid", not not_std,
              str(sorted(set(not_std))[:5]))
        wrong = [i for i in ids_ if info.get(i, ("", "", ""))[2] != DOMAIN_OF_TABLE[t]]
        c.add("vocabulary", f"{t}.{cols[0]} domain == {DOMAIN_OF_TABLE[t]}", not wrong,
              str(sorted(set(wrong))[:5]))
    proposed = lineage[lineage.mapping_status == "PROPOSED"].source_event_key.nunique()
    c.add("vocabulary", "rows relying on mappings not yet second-reviewed (status PROPOSED)",
          proposed == 0, f"{proposed} source events - set status=APPROVED after review", warn_only=True)

    # --- semantics
    m, d = final["measurement"], final["drug_exposure"]
    c.add("semantics", "MEASUREMENT.unit_concept_id all NULL (no units in source)",
          m.get("unit_concept_id", pd.Series(dtype=object)).isna().all())
    cat = m[m.value_source_value.notna() & m.value_as_number.isna()]
    c.add("semantics", "categorical results not stored in value_as_number", cat.value_as_number.isna().all())
    c.add("semantics", "operator '<' result parsed (B-HCG '<2.0')",
          (m.operator_concept_id.notna()).sum() == 1, str(m.operator_concept_id.notna().sum()))
    c.add("semantics", "DRUG_EXPOSURE quantity/route/sig all NULL",
          all(d[col].isna().all() for col in ("quantity", "route_concept_id", "sig")))
    c.add("semantics", "drug_type_concept_id = EHR order (not administration)",
          (d.drug_type_concept_id == vocab.concept("type:drug")).all())
    women = set(final["person"].loc[final["person"].gender_concept_id == 8532, "person_id"])
    female_only = {3018171, 3026725, 3009214, 4337799, 4199599}  # B-HCG, E2, LH, cervix dilation, IVF
    hits = [(t, int(r.person_id)) for t in ("measurement", "procedure_occurrence")
            for r in final[t].itertuples()
            if int(getattr(r, TABLE_FIELDS[t][0])) in female_only and r.person_id not in women]
    c.add("semantics", "sex-specific concepts only in female persons", not hits, str(hits[:3]), warn_only=True)

    # --- time
    vo = final["visit_occurrence"]
    c.add("time", "visit start <= end", (vo.visit_start_datetime <= vo.visit_end_datetime).all())
    overlap = 0
    for _, g in vo.sort_values("visit_start_datetime").groupby("person_id"):
        s, e = g.visit_start_datetime.tolist(), g.visit_end_datetime.tolist()
        overlap += sum(s[i + 1] < e[i] for i in range(len(s) - 1))
    c.add("time", "no overlapping visits per person", overlap == 0, str(overlap))
    dates = []
    for t, cols in TABLE_FIELDS.items():
        dates.append(final[t][["person_id", cols[1]]].rename(columns={cols[1]: "d"}))
    ev = pd.concat(dates + [vo[["person_id", "visit_end_date"]].rename(columns={"visit_end_date": "d"})])
    ev["d"] = pd.to_datetime(ev.d)
    last = ev.groupby("person_id").d.max()
    first = ev.groupby("person_id").d.min()
    death = final["death"].set_index("person_id").death_date
    bad = [p for p, dd in death.items() if pd.Timestamp(dd) < last[p]]
    c.add("time", "death_date >= last event", not bad, str(bad))
    yob = final["person"].set_index("person_id").year_of_birth
    c.add("time", "year_of_birth <= first event year", all(yob[p] <= first[p].year for p in first.index))
    op = final["observation_period"].set_index("person_id")
    cover = all(pd.Timestamp(op.loc[p, "observation_period_start_date"]) <= first[p]
                and pd.Timestamp(op.loc[p, "observation_period_end_date"]) >= last[p] for p in first.index)
    c.add("time", "observation period covers all events", cover)
    pr = final["procedure_occurrence"].merge(vo[["visit_occurrence_id", "visit_start_date", "visit_end_date"]],
                                              on="visit_occurrence_id")
    c.add("time", "procedure_date within its visit",
          ((pr.procedure_date >= pr.visit_start_date) & (pr.procedure_date <= pr.visit_end_date)).all())
    dv = d.merge(vo[["visit_occurrence_id", "visit_start_datetime"]], on="visit_occurrence_id")
    pre = (dv.drug_exposure_start_datetime < dv.visit_start_datetime).sum()
    c.add("time", "orders before admission == 20 (A&E orders, kept on their visit)", pre == 20, str(pre),
          warn_only=True)
    shifts = {deid.shift_days(p) for p in tables["patient_demo"].Patient_No}
    c.add("privacy", f"|shift| in [{settings.SHIFT_MIN_DAYS}, {settings.SHIFT_MAX_DAYS}] days",
          all(settings.SHIFT_MIN_DAYS <= abs(s) <= settings.SHIFT_MAX_DAYS for s in shifts))

    # --- privacy: raw identifiers and raw timestamps must not appear in any output file
    needles = set(tables["patient_demo"].Patient_No)
    for t in ("case_visit", "lab_results", "medication_order", "surgical"):
        needles |= set(tables[t].Case_No.astype(str))
    raw_times = set()
    for t, col in (("case_visit", "Adm_DateTime"), ("case_visit", "Dis_DateTime"),
                   ("lab_results", "Result_Test_Date"), ("medication_order", "Order_Creation_Date")):
        raw_times |= {pd.Timestamp(x).strftime("%Y-%m-%d %H:%M:%S") for x in tables[t][col]}
    leaks = []
    for f in sorted(out.rglob("*.csv")):
        text = f.read_text(encoding="utf-8")
        leaks += [f"{f.name}:{n}" for n in needles if n in text]
        leaks += [f"{f.name}:time" for tm in raw_times if tm in text][:1]
    c.add("privacy", "no raw Patient_No / Case_No / raw timestamp in outputs", not leaks, str(leaks[:5]))

    checks = c.frame()
    summary = {s: int((checks.status == s).sum()) for s in ("PASS", "WARN", "FAIL")}
    return {"checks": checks, "coverage": coverage(lineage, vocab), "summary": summary}


def coverage(lineage: pd.DataFrame, vocab: VocabIndex) -> pd.DataFrame:
    """Per domain: distinct source codes mapped and source rows mapped (concept != 0)."""
    rows = []
    for sheet in ("diagnosis", "lab", "drug", "procedure"):
        df = vocab.frames[sheet]
        codes = df.groupby("source_code").apply(
            lambda g: (g.status.iloc[0] in vocab.accepted)
            and any(x not in ("", "0") for x in g.target_concept_id), include_groups=False)
        rows.append({"domain": sheet, "distinct_codes": len(codes), "codes_mapped": int(codes.sum()),
                     "code_coverage_pct": round(100 * codes.mean(), 1)})
    events = lineage[lineage.cdm_table.isin(list(TABLE_FIELDS))]
    src = {"case_visit": "diagnosis", "lab_results": "lab", "medication_order": "drug",
           "surgical": "procedure"}
    out = pd.DataFrame(rows).set_index("domain")
    for s, dom in src.items():
        e = events[events.source_table == s]
        mapped = e.groupby("source_event_key").concept_id.apply(lambda x: any(str(v) != "0" for v in x))
        out.loc[dom, "source_events"] = len(mapped)
        out.loc[dom, "events_mapped"] = int(mapped.sum())
        out.loc[dom, "event_coverage_pct"] = round(100 * mapped.mean(), 1)
    return out.reset_index()
