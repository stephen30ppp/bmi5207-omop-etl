"""OMOP v5.4 writer: official column order, typed formatting, empty string for NULL."""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pandas as pd

from . import cdm54


class WriteError(RuntimeError):
    pass


def _fmt(value, dtype: str) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT:
        return ""
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if dtype == "integer":
        return str(int(value))
    if dtype == "float":
        f = float(value)
        return str(int(f)) if f.is_integer() else repr(f)
    if dtype == "date":
        return (value.date() if isinstance(value, dt.datetime) else value).isoformat()
    if dtype == "datetime":
        if not isinstance(value, dt.datetime):
            value = dt.datetime.combine(value, dt.time())
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def format_table(table: str, df: pd.DataFrame) -> pd.DataFrame:
    spec = cdm54.TABLES[table]
    limits = cdm54.varchar_limits(table)
    out = pd.DataFrame(index=range(len(df)))
    for col, _, dtype in spec:
        values = df[col].tolist() if col in df.columns else [None] * len(df)
        out[col] = [_fmt(v, dtype) for v in values]
        if col in limits:
            too_long = [v for v in out[col] if len(v) > limits[col]]
            if too_long:
                raise WriteError(f"{table}.{col}: {len(too_long)} value(s) exceed varchar({limits[col]})")
    return out


def write_table(table: str, df: pd.DataFrame, out_dir: Path) -> pd.DataFrame:
    formatted = format_table(table, df)
    out_dir.mkdir(parents=True, exist_ok=True)
    formatted.to_csv(out_dir / f"{table}.csv", index=False, lineterminator="\n")
    return formatted


def write_plain(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n")
