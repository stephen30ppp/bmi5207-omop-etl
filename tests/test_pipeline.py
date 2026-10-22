"""End-to-end tests on the real course data. Skipped unless BMI5207_RAW points at the folder that
holds the 'Patient N ...' sub-folders (raw data is not committed to the repository)."""
import hashlib
import os
from pathlib import Path

import pandas as pd
import pytest

from etl.run import ReviewGateError, run

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


def approved_copy(tmp_path, skip=None):
    """Copy the mapping sheets and mark every row as reviewed, except rows matching `skip`."""
    src = Path(__file__).resolve().parent.parent / "mappings"
    dst = tmp_path / "mappings"
    dst.mkdir()
    for f in src.glob("*.csv"):
        df = pd.read_csv(f, dtype=str, keep_default_na=False)
        mask = pd.Series(True, index=df.index)
        if skip and f.stem == skip[0]:
            mask &= ~((df.source_code == skip[1]) & (df.map_seq == skip[2]))
        df.loc[mask, "status"] = df.loc[mask, "status"].replace(
            {"PROPOSED": "APPROVED", "NEEDS_CLINICAL_REVIEW": "APPROVED"})
        df.loc[mask, "reviewer"] = "reviewer-b"
        df.loc[mask, "review_date"] = "2026-10-23"
        df.to_csv(dst / f.name, index=False)
    return dst


def test_final_mode_refuses_unreviewed_mappings_and_keeps_previous_output(first, tmp_path):
    out = tmp_path / "out"
    (out / "omop").mkdir(parents=True)
    (out / "omop" / "person.csv").write_text("previous version")
    with pytest.raises(ReviewGateError, match="not properly reviewed"):
        run(Path(RAW), DEMO, out, mapping_mode="final")
    assert (out / "omop" / "person.csv").read_text() == "previous version"


def test_final_mode_refuses_partially_approved_one_to_many(tmp_path):
    maps = approved_copy(tmp_path, skip=("procedure", "ZSD714H", "2"))
    with pytest.raises(ReviewGateError) as e:
        run(Path(RAW), DEMO, tmp_path / "out", mapping_mode="final", mappings_dir=maps)
    assert list(e.value.problems.source_code) == ["ZSD714H"]
    assert not (tmp_path / "out").exists()


def test_final_mode_publishes_when_everything_reviewed(tmp_path):
    maps = approved_copy(tmp_path)
    report = run(Path(RAW), DEMO, tmp_path / "out", mapping_mode="final", mappings_dir=maps)
    assert report["published"] and report["summary"]["FAIL"] == 0
    p = pd.read_csv(tmp_path / "out" / "omop" / "procedure_occurrence.csv")
    assert {4142645, 4184832} <= set(p.procedure_concept_id)


def test_failed_validation_does_not_overwrite_previous_output(tmp_path, monkeypatch):
    import etl.run as runmod
    out = tmp_path / "out"
    out.mkdir()
    (out / "marker.txt").write_text("previous")
    real = runmod.validate

    def failing(*a, **k):
        report = real(*a, **k)
        report["summary"]["FAIL"] = 1
        return report

    monkeypatch.setattr(runmod, "validate", failing)
    report = run(Path(RAW), DEMO, out)
    assert not report["published"]
    assert (out / "marker.txt").read_text() == "previous"
    assert (tmp_path / "out.failed" / "omop" / "person.csv").exists()
