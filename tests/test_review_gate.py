"""Review-gate rules: every mapping row is judged on its own, and final mode only consumes
properly reviewed decisions (reviewer + review_date, reviewer != mapper)."""
import pandas as pd
import pytest

from etl.vocab import MAPPING_COLUMNS, SHEETS, VocabIndex


def mrow(code, seq, cid, status, reviewer="", date="", mapper="athena-api lookup",
         relationship="Maps to", domain="Procedure", reason=""):
    r = {c: "" for c in MAPPING_COLUMNS}
    r.update(source_code=code, map_seq=str(seq), relationship=relationship,
             target_concept_id=str(cid), target_domain_id=domain, target_concept_name=f"c{cid}",
             standard_concept="S", status=status, reviewer=reviewer, review_date=date,
             mapper=mapper, source_concept_id="0", unmapped_reason=reason)
    return r


def index(rows, mode):
    frames = {s: pd.DataFrame(columns=MAPPING_COLUMNS) for s in SHEETS}
    frames["procedure"] = pd.DataFrame(rows, columns=MAPPING_COLUMNS)
    return VocabIndex(frames, mode)


OK = dict(reviewer="reviewer-b", date="2026-10-23")


def test_partially_approved_one_to_many_is_not_used_in_final_mode():
    v = index([mrow("ZSD714H", 1, 4142645, "APPROVED", **OK),
               mrow("ZSD714H", 2, 4184832, "PROPOSED")], "final")
    res = v.lookup("procedure", "ZSD714H")
    assert res.targets == []  # the approved half must not be emitted on its own
    assert "map_seq 2" in res.unmapped_reason
    problems = v.review_problems()
    assert list(problems.map_seq) == ["2"]


def test_partially_approved_one_to_many_order_does_not_matter():
    v = index([mrow("ZSD714H", 1, 4142645, "PROPOSED"),
               mrow("ZSD714H", 2, 4184832, "APPROVED", **OK)], "final")
    assert v.lookup("procedure", "ZSD714H").targets == []


def test_fully_approved_one_to_many_emits_both_targets():
    v = index([mrow("ZSD714H", 1, 4142645, "APPROVED", **OK),
               mrow("ZSD714H", 2, 4184832, "APPROVED", **OK)], "final")
    assert [t.concept_id for t in v.lookup("procedure", "ZSD714H").targets] == [4142645, 4184832]
    assert v.review_problems().empty


@pytest.mark.parametrize("kw, problem", [
    (dict(reviewer="", date="2026-10-23"), "without reviewer"),
    (dict(reviewer="reviewer-b", date=""), "without review_date"),
    (dict(reviewer="athena-api lookup", date="2026-10-23"), "own mapper"),
])
def test_approved_row_needs_valid_review_metadata(kw, problem):
    v = index([mrow("X1", 1, 4294382, "APPROVED", **kw)], "final")
    assert v.lookup("procedure", "X1").targets == []
    assert problem in v.review_problems().problem.iloc[0]


def test_approved_row_needs_valid_review_metadata_in_review_mode_too():
    v = index([mrow("X1", 1, 4294382, "APPROVED", reviewer="athena-api lookup", date="2026-10-23")],
              "review")
    assert v.lookup("procedure", "X1").targets == []


def test_needs_clinical_review_is_not_treated_as_unmappable():
    for mode in ("review", "final"):
        v = index([mrow("E1472", 1, 442793, "NEEDS_CLINICAL_REVIEW", domain="Condition")], mode)
        res = v.lookup("procedure", "E1472")
        assert res.targets == [] and res.status == "NEEDS_CLINICAL_REVIEW"
        assert "pending clinical review" in res.unmapped_reason
        assert "unmappable" not in res.unmapped_reason.lower()
        assert not v.review_problems().empty  # it blocks final mode instead of silently becoming 0


def test_unmappable_needs_review_in_final_mode_but_not_in_review_mode():
    rows = [mrow("P06240", 1, 0, "UNMAPPABLE", reason="nutrition product")]
    assert index(rows, "review").lookup("procedure", "P06240").unmapped_reason == "nutrition product"
    assert "without reviewer" in index(rows, "final").review_problems().problem.iloc[0]
    reviewed = [mrow("P06240", 1, 0, "UNMAPPABLE", reason="nutrition product", **OK)]
    v = index(reviewed, "final")
    assert v.review_problems().empty
    assert v.lookup("procedure", "P06240").unmapped_reason == "nutrition product"


def test_review_mode_still_accepts_proposed():
    v = index([mrow("X1", 1, 4294382, "PROPOSED")], "review")
    assert [t.concept_id for t in v.lookup("procedure", "X1").targets] == [4294382]
