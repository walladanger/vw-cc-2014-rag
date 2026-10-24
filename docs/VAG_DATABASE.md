# Manual database bundle

Export the processed manual corpus to Qdrant with deterministic IDs and resumable uploads.
Factory manuals and community guides remain in separate collections.

```powershell
python build_vag_database.py --corpus .\out --output .\manual-export
python verify_vag_bundle.py --bundle .\manual-export
python -m vag_pipeline.uploader --bundle .\manual-export --url http://localhost:6333
```

Use `--no-embeddings` to build the source ledger without running Ollama.
Use a fresh output directory when replacing a bundle made by an older version.
The exporter processes manuals and guides only.
