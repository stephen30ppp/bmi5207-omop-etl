# BMI5207 Group 3d — OMOP CDM v5.4 ETL

Python ETL that merges the course's synthetic 5-patient dataset (25 XLSX files), pseudonymises it
and converts it into an **OMOP CDM v5.4-aligned subset of 10 tables**, with Athena-verified
standard concepts, row-level lineage and automated validation.

> Not a complete OMOP CDM instance: vocabulary tables are not shipped; the vocabulary version used
> is recorded in `CDM_SOURCE` and `mappings/*.csv`.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# raw data is NOT in this repo; point --raw at the folder holding "Patient 1 ...", ..., "Patient 5 ..."
python -c "import secrets; print(secrets.token_hex(32))" > secrets/etl.key   # keep private
python -m etl.run --raw "/path/to/Sample data for 5 patients_v2" --secret secrets/etl.key --out output

# tests (end-to-end tests run only when BMI5207_RAW is set)
BMI5207_RAW="/path/to/Sample data for 5 patients_v2" python -m pytest -q
```

`config/demo_secret.txt` is a public secret for reproducibility tests only; never use it for
results you share.

## Pipeline

```
Raw (25 XLSX) -> Staging (merge, contract, exact dedup, parsers, source_event_key)
  -> De-identification (HMAC person/visit registry, one day-shift per patient)
  -> Builders (person, visit/condition, measurement, drug, procedure)  -> Event objects
  -> Domain router (target Standard domain decides the table; unmapped -> concept 0 + reason)
  -> Central key allocator -> OMOP v5.4 writer -> Validation & coverage report
```

Builders never allocate primary keys, never write CSV and never invent concept IDs: every concept
comes from a row in `mappings/*.csv`.

| Path | Content |
|---|---|
| `etl/` | pipeline code (`run.py` entry point) |
| `mappings/*.csv` | mapping sheets (one per domain) with Athena concept IDs, equivalence, status, rationale |
| `mappings/athena_snapshots/` | raw Athena API lookups the sheets were built from |
| `scripts/build_mappings.py` | regenerates the mapping sheets from the snapshots |
| `output/omop/` | the 10 OMOP tables |
| `output/lineage/source_event_lineage.csv` | every source event -> CDM table/row/concept or reason |
| `output/validation_summary.csv`, `mapping_coverage.csv`, `unmapped_summary.csv`, `dq_log.csv` | results |
| `output/intermediate/drug_dose.csv` | ordered dose per drug_exposure (kept out of `sig`) |
| `docs/` | requirements, source-to-target contract, privacy, vocabulary, validation, roadmap, results |

## Current results (`--mapping-mode review`)

- 527 source events, all accounted for (494 written, 28 rerouted by domain, 1 exact duplicate, 4 unknown attributes not generated)
- Validation: **128 PASS, 1 WARN, 0 FAIL** (the WARN: 479 source events use PROPOSED mappings and 16 use NEEDS_CLINICAL_REVIEW ones; in final mode this check is a FAIL)
- Event-level mapping coverage: diagnoses 80.5%, labs 99.4%, drugs 91.8%, procedures 100%

See `docs/11-implementation-results.md` for the full breakdown and slide-ready mapping cases.

## Mapping review workflow

All mapping rows start as `PROPOSED` (concept verified in Athena: exists, Standard, Valid, right
domain) or as a proposed negative decision (`UNMAPPABLE`). Open questions are `NEEDS_CLINICAL_REVIEW`.

Rules enforced by `etl/vocab.py` (each row is judged on its own):

- A reviewed decision is `APPROVED`, `UNMAPPABLE` or `REJECTED` with `reviewer` and `review_date`
  filled and `reviewer` different from `mapper`.
- A source code with several rows (one-to-many, `Maps to value`) is used only if **every** live row
  passes; a partially approved group is not used at all.
- `NEEDS_CLINICAL_REVIEW` is never used and never treated as `UNMAPPABLE`.

`--mapping-mode final` runs a review gate before anything is written: if any row in
`mappings/*.csv` is not a reviewed decision, the run stops with exit code 2, writes the list to
`<out>.review_gate.csv` and leaves `<out>` untouched.

Every run (both modes) is built in a temporary sibling directory and replaces `<out>` only when
validation has no FAIL; otherwise the build is kept as `<out>.failed` and the previous output stays.

## Privacy

Pseudonymisation, not anonymisation. Raw `Patient_No`/`Case_No` and raw timestamps never appear in
outputs (checked by the validator). Raw data, the private secret and profiling dumps are excluded
from git (`.gitignore`). Calendar trends are not preserved by the date shift.
