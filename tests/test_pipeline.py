"""End-to-end tests on the real course data. Skipped unless BMI5207_RAW points at the folder that
holds the 'Patient N ...' sub-folders (raw data is not committed to the repository)."""
import hashlib
import os
from pathlib import Path

import pandas as pd
import pytest

from etl.run import run

RAW = os.environ.get("BMI5207_RAW")
pytestmark = pytest.mark.skipif(not RAW or not Path(RAW).is_dir(), reason="set BMI5207_RAW")
DEMO = (Path(__file__).resolve().parent.parent / "config" / "demo_secret.txt").read_bytes().strip()


def digests(out: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((out / "omop").glob("*.csv")) if p.name != "cdm_source.csv"}


@pytest.fixture(scope="module")
def first(tmp_path_factory):
    out = tmp_path_factory.mktemp("run1")
    return out, run(Path(RAW), DEMO, out)


def test_no_failed_checks(first):
    _, report = first
    failed = report["checks"][report["checks"].status == "FAIL"]
    assert failed.empty, failed.to_string()


def test_idempotent_rerun(first, tmp_path):
    out, _ = first
    run(Path(RAW), DEMO, tmp_path)
    assert digests(out) == digests(tmp_path)


def test_other_secret_changes_ids_and_dates(first, tmp_path):
    out, _ = first
    run(Path(RAW), b"a-completely-different-secret-xyz", tmp_path)
    assert digests(out)["visit_occurrence.csv"] != digests(tmp_path)["visit_occurrence.csv"]


def test_row_counts_and_reconciliation(first):
    out, _ = first
    count = lambda t: len(pd.read_csv(out / "omop" / f"{t}.csv"))  # noqa: E731
    assert (count("person"), count("death"), count("visit_occurrence"), count("drug_exposure"),
            count("measurement")) == (5, 2, 21, 170, 162)
    lineage = pd.read_csv(out / "lineage" / "source_event_lineage.csv", keep_default_na=False)
    assert lineage.source_event_key.nunique() == 5 + 2 + 10 + 22 + 149 + 162 + 170 + 7


def test_final_mode_refuses_unreviewed_mappings(tmp_path):
    # Nothing is APPROVED yet, so final mode must stop instead of emitting unreviewed concepts.
    with pytest.raises(KeyError, match="not accepted in final mode"):
        run(Path(RAW), DEMO, tmp_path, mapping_mode="final")
