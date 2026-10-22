"""Raw layer: discover the 25 workbooks, enforce the source contract and merge each type into one table."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import settings


class ContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceFile:
    source_type: str
    folder_index: int  # the "Patient N" number of the course folder, never the raw Patient_No
    path: Path
    sha256: str


FOLDER_RE = re.compile(r"^Patient (\d+)\b")


def discover(raw_dir: Path) -> list[SourceFile]:
    files = []
    for path in sorted(raw_dir.glob("*/*.xlsx")):
        m = FOLDER_RE.match(path.parent.name)
        if not m:
            continue
        stype = next(
            (k for k, prefix in settings.SOURCE_TYPES.items() if path.name.startswith(prefix + "_")),
            None,
        )
        if stype is None:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files.append(SourceFile(stype, int(m.group(1)), path, digest))
    return files


def load_all(raw_dir: Path) -> tuple[dict[str, pd.DataFrame], list[dict]]:
    """Return one merged DataFrame per source type plus an input manifest.

    Each row keeps `src_folder` and `src_row` (1-based worksheet row) so lineage can point back to the
    exact source cell without exposing raw identifiers.
    """
    files = discover(Path(raw_dir))
    by_type: dict[str, list[SourceFile]] = {k: [] for k in settings.SOURCE_TYPES}
    for f in files:
        by_type[f.source_type].append(f)

    tables, manifest = {}, []
    for stype, group in by_type.items():
        if len(group) != 5:
            raise ContractError(f"{stype}: expected 5 files, found {len(group)}")
        frames = []
        for f in group:
            book = pd.ExcelFile(f.path)
            if book.sheet_names != ["Sheet1"]:
                raise ContractError(f"{stype} folder {f.folder_index}: sheets {book.sheet_names}")
            df = book.parse("Sheet1")
            if list(df.columns) != settings.EXPECTED_COLUMNS[stype]:
                raise ContractError(f"{stype} folder {f.folder_index}: unexpected columns")
            df["src_folder"] = f.folder_index
            df["src_row"] = range(2, len(df) + 2)
            frames.append(df)
            manifest.append({
                "source_type": stype, "folder_index": f.folder_index,
                "sha256": f.sha256, "rows": len(df), "sheet": "Sheet1",
            })
        merged = pd.concat(frames, ignore_index=True)
        if len(merged) != settings.EXPECTED_ROWS[stype]:
            raise ContractError(
                f"{stype}: expected {settings.EXPECTED_ROWS[stype]} rows, found {len(merged)}")
        tables[stype] = merged
    return tables, manifest


def docprops_modified(raw_dir: Path) -> set[str]:
    """Distinct docProps/core.xml modified dates (YYYY-MM-DD) across the workbooks."""
    import zipfile
    dates = set()
    for f in discover(Path(raw_dir)):
        with zipfile.ZipFile(f.path) as z:
            core = z.read("docProps/core.xml").decode("utf-8")
        m = re.search(r"<dcterms:modified[^>]*>(\d{4}-\d{2}-\d{2})", core)
        if m:
            dates.add(m.group(1))
    return dates
