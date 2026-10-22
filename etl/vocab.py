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

    def row_problem(self, r) -> str:
        """Why this single mapping row may not be used in the current mode ('' if usable).

        Every row is judged on its own: one approved row never vouches for its siblings.
        Reviewed decisions (APPROVED, UNMAPPABLE, REJECTED) need a reviewer different from the
        mapper and a review date; in final mode nothing else is acceptable.
        """
        status = r.status
        if (self.mode == "review" and status in ("UNMAPPABLE", "REJECTED")
                and not r.reviewer.strip()):
            return ""  # proposed negative decision; still blocks final mode
        if status in settings.REVIEWED_STATUSES:
            if not r.reviewer.strip():
                return f"{status} without reviewer"
            if not r.review_date.strip():
                return f"{status} without review_date"
            if r.reviewer.strip().lower() == r.mapper.strip().lower():
                return f"{status} reviewed by its own mapper ({r.mapper})"
            return ""
        if self.mode == "review" and status == "PROPOSED":
            return ""
        if status == "NEEDS_CLINICAL_REVIEW":
            return "pending clinical review (NEEDS_CLINICAL_REVIEW)"
        return f"status {status or '<empty>'} not accepted in {self.mode} mode"

    def review_problems(self) -> pd.DataFrame:
        """All rows that block a run in the current mode (used as the final-mode gate)."""
        rows = []
        for sheet, df in self.frames.items():
            for r in df.itertuples():
                problem = self.row_problem(r)
                if problem:
                    rows.append({"sheet": sheet, "source_code": r.source_code, "map_seq": r.map_seq,
                                 "relationship": r.relationship, "status": r.status,
                                 "target_concept_id": r.target_concept_id, "problem": problem})
        return pd.DataFrame(rows, columns=["sheet", "source_code", "map_seq", "relationship",
                                           "status", "target_concept_id", "problem"])

    def lookup(self, sheet: str, source_code: str) -> MapResult:
        g = self._index.get((sheet, str(source_code)))
        if g is None:
            return MapResult(str(source_code), "MISSING", unmapped_reason="no row in mapping sheet")
        first = g.iloc[0]
        statuses = sorted(set(g.status) - {"REJECTED"})
        res = MapResult(
            source_code=str(source_code), status="/".join(statuses) or "REJECTED",
            source_concept_id=int(first.source_concept_id or 0), equivalence=first.equivalence,
        )
        # A source code is used only if EVERY live row of its group passes review on its own;
        # a partially approved one-to-many mapping must not emit its approved half.
        live = [r for r in g.itertuples() if r.status != "REJECTED"]
        problems = [f"map_seq {r.map_seq} {r.relationship}: {p}"
                    for r in g.itertuples() if (p := self.row_problem(r))]
        if problems:
            res.unmapped_reason = "; ".join(problems)
            return res
        if not live:
            res.unmapped_reason = "all candidate mappings rejected by reviewer"
            return res
        if any(r.status == "UNMAPPABLE" for r in live):
            if len(live) > 1:
                res.unmapped_reason = "inconsistent group: UNMAPPABLE mixed with other rows"
            else:
                res.unmapped_reason = live[0].unmapped_reason or "reviewed as unmappable"
            return res
        values = {r.map_seq: int(r.target_concept_id) for r in live
                  if r.relationship == "Maps to value" and r.target_concept_id not in ("", "0")}
        for r in live:
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
