"""Shared state handed to every builder. Builders read from it; they never allocate primary keys."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .deid import Deid
from .vocab import VocabIndex


@dataclass
class Context:
    deid: Deid
    vocab: VocabIndex
    tables: dict[str, pd.DataFrame]       # raw merged source tables
    visits: pd.DataFrame                  # case_visit after exact de-duplication
    visit_ids: dict[str, int]             # raw Case_No -> visit_occurrence_id (central allocator)
    period_start: dict[int, object] = field(default_factory=dict)  # person_id -> shifted date
    lineage: list[dict] = field(default_factory=list)  # outcomes that never reach the router
    dq: list[dict] = field(default_factory=list)       # data-quality log

    def log(self, check: str, key: str, detail: str, level: str = "INFO") -> None:
        self.dq.append({"level": level, "check": check, "source_event_key": key, "detail": detail})

    def outcome(self, key: str, source_table: str, outcome: str, reason: str) -> None:
        self.lineage.append({"source_event_key": key, "source_table": source_table,
                             "outcome": outcome, "cdm_table": "", "cdm_id": "", "concept_id": "",
                             "mapping_status": "", "equivalence": "", "unmapped_reason": reason})
