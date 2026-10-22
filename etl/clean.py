"""Staging layer: exact de-duplication, diagnosis explosion and value parsers.

Pure functions only; no identifiers are replaced here (that is etl.deid).
"""
from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass

import pandas as pd

SOURCE_COLS = lambda df: [c for c in df.columns if not c.startswith("src_")]  # noqa: E731


def dedup_exact(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop rows whose source columns are identical to an earlier row. Returns (kept, dropped)."""
    dup = df.duplicated(subset=SOURCE_COLS(df), keep="first")
    return df[~dup].reset_index(drop=True), df[dup].reset_index(drop=True)


def explode_diagnoses(visits: pd.DataFrame) -> pd.DataFrame:
    """One row per diagnosis: the primary code, then every element of the secondary list in order.

    Repeated codes inside one list are kept (e.g. ICD-10-AM place-of-occurrence Y9222 after each
    external cause), because CONDITION_OCCURRENCE records conditions as they exist in the source.
    """
    rows = []
    for _, v in visits.iterrows():
        rows.append({
            "Case_No": v.Case_No, "Patient_No": v.Patient_No, "seq": 0,
            "code": str(v.Primary_Diagnosis_Code_Mediclaim).strip(), "status": "PRIMARY",
            "description": v.Primary_Diagnosis_Description_Mediclaim,
            "src_folder": v.src_folder, "src_row": v.src_row,
        })
        raw = v.Secondary_Diagnosis_Codes_Subvention
        codes = [] if pd.isna(raw) else [c.strip() for c in str(raw).split(",") if c.strip()]
        if len(codes) != int(v.No_of_Secondary_Diagnosis_Subvention):
            raise ValueError(f"secondary diagnosis count mismatch at source row {v.src_row}")
        for i, code in enumerate(codes, start=1):
            rows.append({
                "Case_No": v.Case_No, "Patient_No": v.Patient_No, "seq": i, "code": code,
                "status": "SECONDARY", "description": None, "src_folder": v.src_folder, "src_row": v.src_row,
            })
    return pd.DataFrame(rows)


def lab_key(test_code, short_text) -> str:
    code = "NA" if test_code is None or (isinstance(test_code, float) and math.isnan(test_code)) \
        else str(test_code).strip()
    return f"{code}|{str(short_text).strip()}"


@dataclass(frozen=True)
class ParsedResult:
    kind: str                    # numeric | operator | categorical
    value_as_number: float | None
    operator: str | None         # '<', '<=', '>', '>=' or None
    text: str                    # verbatim source value (full length)


_NUM = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")
_OP = re.compile(r"^(<=|>=|<|>)\s*([+-]?(\d+(\.\d*)?|\.\d+))$")


def parse_result(value) -> ParsedResult:
    text = "" if value is None else str(value).strip()
    if isinstance(value, (int, float)) and not (isinstance(value, float) and math.isnan(value)):
        return ParsedResult("numeric", float(value), None, text)
    if _NUM.match(text):
        return ParsedResult("numeric", float(text), None, text)
    m = _OP.match(text)
    if m:
        return ParsedResult("operator", float(m.group(2)), m.group(1), text)
    return ParsedResult("categorical", None, None, text)


@dataclass(frozen=True)
class ParsedDose:
    status: str                  # ok | range | corrupt_datetime | missing
    value: float | None
    raw: str | None


def parse_dose(cell) -> ParsedDose:
    """Dosage_Ordered can be a number, a range string ('0 - 2') or an Excel-mangled datetime."""
    if cell is None or (isinstance(cell, float) and math.isnan(cell)):
        return ParsedDose("missing", None, None)
    if isinstance(cell, (dt.datetime, dt.date, pd.Timestamp)):
        return ParsedDose("corrupt_datetime", None, str(cell))
    text = str(cell).strip()
    if _NUM.match(text):
        return ParsedDose("ok", float(text), text)
    if re.match(r"^\d+(\.\d+)?\s*-\s*\d+(\.\d+)?$", text):
        return ParsedDose("range", None, text)
    return ParsedDose("corrupt_datetime" if re.match(r"^\d{4}-\d{2}-\d{2}", text) else "range",
                      None, text)
