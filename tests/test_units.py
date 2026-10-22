"""Unit tests that need no raw data."""
import datetime as dt

import pandas as pd
import pytest

from etl import cdm54
from etl.clean import dedup_exact, explode_diagnoses, lab_key, parse_dose, parse_result
from etl.deid import Deid
from etl.router import Event, route
from etl.vocab import MapResult, Target
from etl.write import WriteError, format_table

SECRET = b"unit-test-secret-0123456789"


def test_parse_result_numeric_and_operator():
    assert parse_result("142").value_as_number == 142.0
    assert parse_result("142.0").value_as_number == 142.0
    assert parse_result(5.8).kind == "numeric"
    r = parse_result("<2.0")
    assert (r.kind, r.operator, r.value_as_number) == ("operator", "<", 2.0)


def test_parse_result_categorical_keeps_full_text():
    long = "No common clinically significant red cell alloantibodies detected"
    r = parse_result(long)
    assert r.kind == "categorical" and r.value_as_number is None and r.text == long


def test_parse_dose_variants():
    assert parse_dose("10.0").value == 10.0
    assert parse_dose("0 - 2").status == "range"
    assert parse_dose(dt.datetime(2022, 7, 3)).status == "corrupt_datetime"
    assert parse_dose(float("nan")).status == "missing"


def test_lab_key_null_code():
    assert lab_key(float("nan"), "Sodium") == "NA|Sodium"
    assert lab_key("K", "Potassium") == "K|Potassium"


def test_dedup_and_explode_keep_repeated_codes():
    v = pd.DataFrame([{
        "Case_No": "c1", "Patient_No": "p1", "Primary_Diagnosis_Code_Mediclaim": "I214",
        "Primary_Diagnosis_Description_Mediclaim": "AMI",
        "Secondary_Diagnosis_Codes_Subvention": "Y442,Y9222,Y409,Y9222",
        "No_of_Secondary_Diagnosis_Subvention": 4, "src_folder": 1, "src_row": 2,
    }])
    kept, dropped = dedup_exact(pd.concat([v, v.assign(src_row=3)], ignore_index=True))
    assert len(kept) == 1 and len(dropped) == 1
    dx = explode_diagnoses(kept)
    assert list(dx.code) == ["I214", "Y442", "Y9222", "Y409", "Y9222"]
    assert list(dx.status) == ["PRIMARY"] + ["SECONDARY"] * 4


def test_explode_rejects_count_mismatch():
    v = pd.DataFrame([{"Case_No": "c", "Patient_No": "p", "Primary_Diagnosis_Code_Mediclaim": "I10",
                       "Primary_Diagnosis_Description_Mediclaim": "x",
                       "Secondary_Diagnosis_Codes_Subvention": "A,B",
                       "No_of_Secondary_Diagnosis_Subvention": 3, "src_folder": 1, "src_row": 2}])
    with pytest.raises(ValueError):
        explode_diagnoses(v)


def test_deid_deterministic_and_secret_sensitive():
    pts = ["a", "b", "c", "d", "e"]
    d1, d2, d3 = Deid(SECRET, pts), Deid(SECRET, pts), Deid(b"another-secret-abcdefgh", pts)
    assert [d1.person_id(p) for p in pts] == [d2.person_id(p) for p in pts]
    assert sorted(d1.person_id(p) for p in pts) == [1, 2, 3, 4, 5]
    assert all(30 <= abs(d1.shift_days(p)) <= 365 for p in pts)
    assert [d1.shift_days(p) for p in pts] != [d3.shift_days(p) for p in pts]


def test_shift_preserves_intervals_and_leap_day():
    d = Deid(SECRET, ["p"])
    a, b = pd.Timestamp("2016-02-29 15:48"), pd.Timestamp("2016-02-20 02:32")
    assert d.shift_dt("p", a) - d.shift_dt("p", b) == a - b
    assert d.shift_dt("p", a).time() == a.time()


def test_year_shift_uses_same_offset():
    d = Deid(SECRET, ["p"])
    delta = d.shift_days("p")
    assert d.shift_year("p", 2017) == (dt.date(2017, 7, 2) + dt.timedelta(days=delta)).year


def _event(mapping, default="condition_occurrence"):
    return Event(key="DX-1", source_table="case_visit", default_table=default, person_id=1,
                 start=dt.datetime(2020, 1, 1, 8), type_concept_id=32821, source_value="X",
                 mapping=mapping, visit_occurrence_id=7)


def test_router_unmapped_stays_in_default_table_with_reason():
    out = route([_event(MapResult("X", "UNMAPPABLE", unmapped_reason="AM-only code"))])
    (row,) = out["condition_occurrence"]
    assert row["condition_concept_id"] == 0 and row["_unmapped_reason"] == "AM-only code"


def test_router_domain_routing_one_to_many_and_value():
    m = MapResult("Z8643", "APPROVED", 45552123, "WIDER",
                  [Target(1340204, "Observation", "History of event", 4239381)])
    out = route([_event(m)])
    assert not out["condition_occurrence"]
    (obs,) = out["observation"]
    assert obs["observation_concept_id"] == 1340204 and obs["value_as_concept_id"] == 4239381
    assert obs["_rerouted"] is True
    two = MapResult("ZSD714H", "APPROVED", 0, "EQUAL",
                    [Target(4142645, "Procedure", "a"), Target(4184832, "Procedure", "b")])
    assert len(route([_event(two, "procedure_occurrence")])["procedure_occurrence"]) == 2


def test_writer_enforces_varchar_limit():
    df = pd.DataFrame([{"person_id": 1, "death_date": dt.date(2020, 12, 31), "cause_source_value": "x" * 51}])
    with pytest.raises(WriteError):
        format_table("death", df)


def test_cdm_spec_has_ten_tables():
    assert len(cdm54.TABLES) == 10
    assert cdm54.columns("visit_occurrence")[-1] == "preceding_visit_occurrence_id"
