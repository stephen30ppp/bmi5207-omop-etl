"""De-identification layer: HMAC registry for persons/visits and one day shift per patient.

This is pseudonymisation, not anonymisation: whoever holds the secret and the raw files can
re-link records (docs/06-data-privacy-design.md).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac

import pandas as pd

from . import settings


class Deid:
    def __init__(self, secret: bytes, patient_nos: list[str]):
        if len(secret) < 16:
            raise ValueError("secret must be at least 16 bytes")
        self._secret = secret
        ranked = sorted(set(patient_nos), key=lambda p: self.h("person", p))
        self._person = {p: i for i, p in enumerate(ranked, start=1)}
        span = settings.SHIFT_MAX_DAYS - settings.SHIFT_MIN_DAYS + 1
        self._shift = {}
        for p in ranked:
            n = int(self.h("shift", p), 16)
            sign = -1 if n & 1 else 1
            self._shift[p] = sign * (settings.SHIFT_MIN_DAYS + (n >> 1) % span)

    def h(self, namespace: str, value: str) -> str:
        msg = f"{namespace}:{value}".encode("utf-8")
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def person_id(self, patient_no: str) -> int:
        return self._person[patient_no]

    def shift_days(self, patient_no: str) -> int:
        return self._shift[patient_no]

    def shift_dt(self, patient_no: str, value):
        if value is None or pd.isna(value):
            return None
        return pd.Timestamp(value).to_pydatetime() + dt.timedelta(days=self._shift[patient_no])

    def shift_year(self, patient_no: str, year: int) -> int:
        m, d = settings.YEAR_ANCHOR
        return (dt.date(int(year), m, d) + dt.timedelta(days=self._shift[patient_no])).year

    def token(self, namespace: str, value: str, n: int = 10) -> str:
        """Short pseudonymous token for shareable lineage (not reversible without the secret)."""
        return self.h(namespace, value)[:n]

    def source_event_key(self, prefix: str, patient_no: str, folder: int, row: int, seq: int = 0) -> str:
        return f"{prefix}-{self.token('event', f'{prefix}|{patient_no}|{folder}|{row}|{seq}', 12)}"
