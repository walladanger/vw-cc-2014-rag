# CC Workshop

CC Workshop turns the original VW CC 2014 manual-backed RAG project into:

- a native Windows desktop program;
- a responsive browser application;
- one shared, safety-gated Python backend for both.

The indexed factory manuals remain local and are not included in the repository or
application binary.

## What you need

1. Python 3.11 for development/building.
2. [Ollama](https://ollama.com/) running locally.
3. The generation and embedding models:

   ```powershell
   ollama pull qwen3.6:latest
   ollama pull nomic-embed-text
   ```

4. A previously generated `out` folder, or factory-manual PDFs to process with the
   included ingestion scripts.

## Run the web app on Windows

```powershell
.\run_web.ps1
```

Then open [http://localhost:5000](http://localhost:5000).

Configuration can be placed in `.env`:

```dotenv
VW_RAG_OUT=C:\path\to\your\out
OLLAMA_BASE=http://localhost:11434
OLLAMA_MODEL=qwen3.6:latest
OLLAMA_EMBED_MODEL=nomic-embed-text
EMBEDDER=ollama
```

## Run with Docker

Place the processed `out` directory beside `docker-compose.yml`, then run:

```powershell
docker compose up --build
```

The application is available at [http://localhost:5000](http://localhost:5000).
The compose file connects to Ollama on the Windows host through
`host.docker.internal`.

## Build the Windows program

```powershell
.\build_windows.ps1
```

The executable is written to `dist\CCWorkshop.exe`.

On first launch, the desktop program creates:

```text
%LOCALAPPDATA%\CC Workshop\out
```

Copy the contents of your processed `out` folder there. Use the **Open data folder**
button in the app to open the exact location. Restart the program after adding or
replacing an index.

## Development

Install the ingestion and local MiniLM extras only when needed:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ingest.txt
```

Run safety checks:

```powershell
.\.venv\Scripts\python.exe specverify.py selftest
.\.venv\Scripts\python.exe retrieve.py --selftest --embedder ollama
```

## Build the Qdrant and HEX analytics database

The restartable database exporter creates three safety-separated Qdrant
collections plus CSV, Parquet, Postgres DDL, and a HEX semantic model. It also
imports decoded iCarsoft reports while hashing VINs and keeping all coding,
adaptation, security-access, and ECU write capabilities disabled.

See [docs/VAG_DATABASE.md](docs/VAG_DATABASE.md) for build and upload commands.

## Review original and processed manuals side by side

The local integrity reviewer finds official/original copies by VW document code,
compares page-level text counts, flags likely losses, renders both PDFs beside
each other, and saves manual corrections separately from the indexed corpus.

```powershell
python manual_review.py --rebuild-index
```

Open [http://127.0.0.1:5074](http://127.0.0.1:5074). Nothing is uploaded.

## Data and deployment warning

Factory service PDFs and derivative indexes may be copyrighted. Keep deployments
private or access-controlled, do not bake manuals into public images or installers,
and retain the source PDFs as the canonical citation targets.
