# VAG database bundle

This pipeline converts the existing page-cited corpus and decoded diagnostic
reports into two complementary data products:

- Qdrant collections for semantic retrieval.
- CSV/Parquet/Postgres-ready tables for HEX dashboards and analysis.

It never transmits ECU write commands and never exports a raw VIN.

## Build

```powershell
$corpus = "C:\Users\Desktop\OneDrive\Documents\Projects\vw_rag_phase2b\out"
$diagnostics = "C:\Users\Desktop\OneDrive\BACK UP FOLDER\AUDI A4 And VW CC\CAR SOFTWARE\iCarsoft OBD2\iCaresoft_DECODED"

python build_vag_database.py `
  --corpus $corpus `
  --diagnostics $diagnostics `
  --output .\data-export
```

The build is deterministic: point IDs derive from source hashes and content.
Re-running the uploader safely upserts the same IDs, and its progress file lets
an interrupted upload resume.

For a quick schema/analytics build without embeddings:

```powershell
python build_vag_database.py --corpus $corpus --diagnostics $diagnostics `
  --output .\data-export --no-embeddings
```

## Upload to local Qdrant

```powershell
python -m vag_pipeline.uploader `
  --bundle .\data-export `
  --url http://localhost:6333
```

Use `--recreate` only when intentionally replacing collections. The collections
are:

- `vag_manual_chunks` — authoritative manual evidence.
- `vag_community_guides` — community procedures that cannot override manuals.
- `vag_diagnostic_catalog` — observed DTC/catalog records.

Verify a completed bundle before importing it:

```powershell
python verify_vag_bundle.py --bundle .\data-export
```

## HEX

The `analytics` directory contains seven CSV and Parquet tables,
`postgres_schema.sql`, and `hex_semantic_model.json`. HEX can later query these
through Postgres or uploaded dataframes. No HEX account is needed during build.

## Adding future live data

Append records using the column contract in the generated CSV files. Live values
belong in `measurement_samples`; long coding and adaptation values belong in
their snapshot tables. Both are read-only records. Preserve:

- session and privacy-safe vehicle IDs;
- ECU address and module name;
- timestamps, raw values, numeric values, normalized values, and units;
- sampling rate and source provenance.
