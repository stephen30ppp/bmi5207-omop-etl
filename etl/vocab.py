"""Vocabulary layer: read the reviewed mapping sheets (mappings/*.csv) and answer lookups.

Builders never invent concept IDs; every non-zero concept comes from a mapping sheet row whose
status is accepted for the current run mode (settings.ACCEPTED_STATUSES).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import settings

MAPPING_COLUMNS = [
    "mapping_group_id", "source_table", "source_field", "source_code", "source_description",
    "source_vocab_hint", "frequency", "map_seq", "relationship", "target_concept_id",
    "target_concept_name", "target_vocabulary_id", "target_domain_id", "target_concept_class_id",
    "standard_concept", "invalid_reason", "source_concept_id", "equivalence", "status",
    "mapping_method", "mapper", "reviewer", "review_date", "vocab_version", "rationale",
    "unmapped_reason",
]

# One file per domain workstream (docs/07-vocabulary-mapping-plan.md).
SHEETS = ["diagnosis", "lab", "lab_value", "drug", "procedure", "demographics", "visit", "fixed"]


@dataclass(frozen=True)
class Target:
    concept_id: int
    domain: str
    name: str
    value_concept_id: int | None = None


@dataclass
class MapResult:
    source_code: str
    status: str
    source_concept_id: int = 0
    equivalence: str = ""
    targets: list[Target] = field(default_factory=list)
    unmapped_reason: str = ""

    @property
    def mapped(self) -> bool:
        return bool(self.targets)


class VocabIndex:
    def __init__(self, frames: dict[str, pd.DataFrame], mode: str = "review"):
        if mode not in settings.ACCEPTED_STATUSES:
            raise ValueError(f"unknown mapping mode {mode}")
        self.mode = mode
        self.accepted = settings.ACCEPTED_STATUSES[mode]
        self.frames = frames
        self._index: dict[tuple[str, str], pd.DataFrame] = {}
        for sheet, df in frames.items():
            for code, g in df.groupby("source_code", sort=False):
                self._index[(sheet, str(code))] = g

    @classmethod
    def load(cls, directory: Path = settings.MAPPINGS_DIR, mode: str = "review") -> "VocabIndex":
        frames = {}
        for sheet in SHEETS:
            path = Path(directory) / f"{sheet}.csv"
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
            missing = set(MAPPING_COLUMNS) - set(df.columns)
            if missing:
                raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
            frames[sheet] = df
        return cls(frames, mode)

    def lookup(self, sheet: str, source_code: str) -> MapResult:
        g = self._index.get((sheet, str(source_code)))
        if g is None:
            return MapResult(str(source_code), "MISSING", unmapped_reason="no row in mapping sheet")
        first = g.iloc[0]
        res = MapResult(
            source_code=str(source_code), status=first.status,
            source_concept_id=int(first.source_concept_id or 0), equivalence=first.equivalence,
        )
        if first.status not in self.accepted:
            res.unmapped_reason = first.unmapped_reason or (
                f"mapping status {first.status} not accepted in {self.mode} mode")
            return res
        values = {r.map_seq: int(r.target_concept_id) for r in g.itertuples()
                  if r.relationship == "Maps to value" and r.target_concept_id not in ("", "0")}
        for r in g.itertuples():
            if r.relationship == "Maps to value":
                continue
            cid = int(r.target_concept_id or 0)
            if cid == 0:
                continue
            res.targets.append(Target(cid, r.target_domain_id, r.target_concept_name,
                                      values.get(r.map_seq)))
        if not res.targets:
            res.unmapped_reason = first.unmapped_reason or "no standard target concept"
        return res

    def concept(self, key: str) -> int:
        """Fixed concepts (type concepts, gender, visit rules...) from fixed.csv by source_code."""
        res = self.lookup("fixed", key)
        if not res.targets:
            raise KeyError(f"fixed concept {key!r} unavailable: {res.unmapped_reason}")
        return res.targets[0].concept_id

    def vocabulary_version(self) -> str:
        versions = {v for df in self.frames.values() for v in df["vocab_version"] if v}
        return sorted(versions)[-1] if versions else "unknown"
