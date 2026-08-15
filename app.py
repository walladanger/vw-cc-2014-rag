#!/usr/bin/env python3
"""
VW CC 2014 Mechanic Assistant — Phase 3 Flask App

Pipeline: query → hybrid retrieval → grounding gate → Ollama generation
          → specverify numeric gate → cited answer + PDF viewer links
"""
import glob
import json
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

# Load .env from project root before reading any env vars
def _resource_path(*parts):
    root = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *parts)


def _load_dotenv():
    _ef = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_ef):
        with open(_ef, encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
_load_dotenv()

BASE_DIR        = _resource_path()
OUT_DIR         = os.path.abspath(os.environ.get("VW_RAG_OUT", os.path.join(BASE_DIR, "out")))
OLLAMA_BASE     = os.environ.get("OLLAMA_BASE",     "http://localhost:11434")
OLLAMA_MODEL    = os.environ.get("OLLAMA_MODEL",    "qwen3.6:latest")
EMBEDDER        = os.environ.get("EMBEDDER",        "ollama")
GOOGLE_API_KEY  = os.environ.get("GOOGLE_API_KEY",  "")

# ── VW jargon → factory-manual synonym expansion ──────────────────────────────
# Appended to the retrieval query (not the display query) so embedding aligns
# with how the factory manuals actually phrase things.
_JARGON = [
    (r"\bDSG\b",    "dual clutch transmission gearbox"),
    (r"\bDQ250\b",  "dual clutch transmission 02E"),
    (r"\b02E\b",    "dual clutch transmission gearbox"),
    (r"\bDQ500\b",  "dual clutch transmission 0CW"),
    (r"\bTSI\b",    "turbocharged stratified injection petrol engine"),
    (r"\bTDI\b",    "turbocharged direct injection diesel"),
    (r"\bEA888\b",  "1.8 2.0 turbo engine"),
    (r"\bHPFP\b",   "high pressure fuel pump"),
    (r"\bPCV\b",    "positive crankcase ventilation"),
    (r"\bEGR\b",    "exhaust gas recirculation"),
    (r"\bTCU\b",    "transmission control unit"),
    (r"\bECU\b",    "engine control unit module"),
    (r"\bMAF\b",    "mass air flow sensor"),
    (r"\bIAT\b",    "intake air temperature sensor"),
    (r"\bDTC\b",    "fault code diagnostic trouble code"),
    (r"\bN80\b",    "activated charcoal filter valve solenoid"),
    (r"\bJ17\b",    "fuel pump relay"),
    (r"\bfluid\b",  "oil ATF fluid"),
    (r"\blitres?\b","liters capacity quantity fill"),
    (r"\bhow many\b","capacity quantity specification"),
]

def _expand(q: str) -> str:
    """Append factory-manual synonyms for VW jargon. Preserves the original query."""
    extra = []
    for pattern, expansion in _JARGON:
        if re.search(pattern, q, re.IGNORECASE):
            extra.append(expansion)
    return (q + " " + " ".join(extra)).strip() if extra else q

app = Flask(
    __name__,
    template_folder=_resource_path("templates"),
    static_folder=_resource_path("static"),
)

# This page reads private local PDFs, so cloud builds do not enable it unless
# explicitly configured. Windows desktop/local installs enable it by default.
MANUAL_REVIEW_ENABLED = os.environ.get(
    "ENABLE_MANUAL_REVIEW", "1" if os.name == "nt" else "0"
).lower() in {"1", "true", "yes", "on"}
if MANUAL_REVIEW_ENABLED:
    from manual_review import register_manual_review

    register_manual_review(
        app,
        Path(OUT_DIR),
        Path(
            os.environ.get(
                "VW_MANUAL_SEARCH_ROOT",
                str(Path.home() / "OneDrive"),
            )
        ),
    )

# ── lazy singletons ────────────────────────────────────────────────────────────
_library      = None
_chunks_by_id = {}
_manifests    = {}   # manual_id -> manifest dict (has source_path, etc.)


def get_library():
    global _library, _chunks_by_id, _manifests
    if _library is not None:
        return _library
    sys.path.insert(0, BASE_DIR)
    from retrieve import ChromaLibrary, Library, DualLibrary, make_embedder, LocalEmbedder

    chroma_path = os.path.join(OUT_DIR, "chroma_db")
    if os.path.isdir(chroma_path):
        # Preferred path: persistent ChromaDB — no in-memory vectors, fast startup
        emb      = LocalEmbedder()
        _library = ChromaLibrary(OUT_DIR, emb)
        print(f"[vw-rag] Vector DB : ChromaDB ({_library._col.count()} docs)", flush=True)
    elif EMBEDDER == "dual":
        if not GOOGLE_API_KEY:
            sys.exit("EMBEDDER=dual requires GOOGLE_API_KEY env var")
        from retrieve import GeminiEmbedder
        emb_local  = LocalEmbedder()
        emb_gemini = GeminiEmbedder(api_key=GOOGLE_API_KEY)
        _library   = DualLibrary(OUT_DIR, emb_local, emb_gemini)
    else:
        emb      = make_embedder(EMBEDDER)
        _library = Library(OUT_DIR, emb)

    _chunks_by_id = {c["chunk_id"]: c for c in _library.chunks}
    for path in glob.glob(os.path.join(OUT_DIR, "*", "manifest.json")):
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        _manifests[m["manual_id"]] = m
    return _library


def _library_files():
    return glob.glob(os.path.join(OUT_DIR, "*", "chunks.jsonl"))


def _library_unavailable():
    if not os.path.isdir(OUT_DIR):
        return f"Data folder does not exist: {OUT_DIR}"
    if not _library_files():
        return f"No indexed manuals were found in {OUT_DIR}"
    return None


# ── active vehicle ─────────────────────────────────────────────────────────────
# Retrieval is scoped to one vehicle. specverify proves a stated number was
# copied from a cited chunk; it cannot tell whether that chunk applies to the car
# being asked about. With more than one vehicle in the index those two facts come
# apart: another car's spec is retrieved, cited, and reported VERIFIED. Scoping
# has to happen at retrieval, which is the only place that sees every candidate.
#
# Defaults match what ingest_all.ps1 and ingest_unprocessed.ps1 stamp, so an
# existing index keeps behaving exactly as before. Chunks with nothing stamped
# are always admitted (see retrieve.applies_to_vehicle), so older indexes built
# before applicability was enforced do not silently return nothing.
# VW_VEHICLE_FILTER=0 disables scoping entirely.
VEHICLE_FILTER_ON = os.environ.get("VW_VEHICLE_FILTER", "1").lower() in {
    "1", "true", "yes", "on"
}
VEHICLE_PROFILE = {
    "vehicle": os.environ.get("VW_VEHICLE", "2014 VW CC 2.0T TSI"),
    "engine":  os.environ.get("VW_ENGINE", "CBFA"),
} if VEHICLE_FILTER_ON else None


# ── system prompt ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a factory-manual mechanic assistant for a 2014 VW CC 2.0T TSI.
You receive two types of context: FACTORY MANUAL (canonical) and COMMUNITY VIDEO (supplementary).

Rules you must never break:
1. Every torque value, clearance, fluid capacity, or part number you state must be
   copied CHARACTER-FOR-CHARACTER from the FACTORY MANUAL section of the CONTEXT.
   Do not use numbers from VIDEO sections as specs. Do not round, convert, or paraphrase.
2. Cite every manual fact as [Manual: {manual_id}, Page {physical_page}].
3. Cite every video reference as [Video: "{title}", ~{timestamp}].
4. If the answer is not supported by the FACTORY MANUAL section, say:
   "I cannot find this in the factory manuals I have indexed. Check the source PDF directly."
   You may still mention a related video procedure as context, but never as the spec source.
5. If a fastener is marked "Replace" or "Stretch bolt — replace after removal",
   reproduce that warning verbatim. Never omit it.
6. Angle-tightening stages must be reproduced in full: e.g. "40 Nm + 180°" not "40 Nm".
7. If a VIDEO section mentions a numeric value and it differs from the manual, output:
   "⚠ Note: video mentions [X Nm] but factory manual specifies [Y Nm] — always follow the manual.\
"""


def call_ollama(prompt: str, context: str) -> str | None:
    """POST to Ollama. Returns generated text or None if unreachable."""
    full    = SYSTEM_PROMPT + "\n\nCONTEXT:\n" + context + "\n\nQUESTION: " + prompt
    payload = json.dumps({"model": OLLAMA_MODEL, "prompt": full, "stream": False}).encode()
    req     = urllib.request.Request(
        f"{OLLAMA_BASE}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())["response"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError):
        return None


# ── citation extraction ────────────────────────────────────────────────────────
_CITE_RE = re.compile(r"\[Manual:\s*([^,\]]+),\s*Page\s*(\d+)\]")


def _build_citations(answer: str, manual_results: list) -> list:
    """Return citation objects for every source referenced or retrieved."""
    by_key = {}
    for r in manual_results:
        by_key[(r["manual_id"], r["page_physical"])] = r

    seen, out = set(), []

    def _add(r):
        key = (r["manual_id"], r["page_physical"])
        if key in seen:
            return
        seen.add(key)
        out.append({
            "manual_id":     r["manual_id"],
            "manual_title":  r["manual_title"],
            "page_physical": r["page_physical"],
            "section_title": r.get("section_title") or "",
            "has_diagram":   bool(r.get("has_diagram")),
            "viewer_url":    f"/viewer?manual={r['manual_id']}&page={r['page_physical']}",
        })

    # Explicitly cited in the answer first
    for m in _CITE_RE.finditer(answer):
        key = (m.group(1).strip(), int(m.group(2)))
        if key in by_key:
            _add(by_key[key])

    # Then all retrieved sources
    for r in manual_results:
        _add(r)

    return out


# ── routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/status")
def status():
    unavailable = _library_unavailable()
    ollama_ok = False
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=1) as r:
            ollama_ok = r.status == 200
    except Exception:
        pass

    chunks = 0
    manuals = 0
    embedder_info = EMBEDDER
    load_error = unavailable
    if not unavailable:
        try:
            lib = get_library()
            chunks = len(lib.chunks)
            manuals = len(_manifests)
            embedder_info = lib.embedder.name
            if hasattr(lib, "embedder_b"):
                embedder_info = f"{lib.embedder.name} + {lib.embedder_b.name} (dual RRF)"
        except (Exception, SystemExit) as exc:
            load_error = str(exc)

    return jsonify({
        "ready":     not load_error,
        "chunks":    chunks,
        "manuals":   manuals,
        "embedder":  embedder_info,
        "ollama":    OLLAMA_BASE,
        "model":     OLLAMA_MODEL,
        "ollama_ok": ollama_ok,
        "data_dir":  OUT_DIR,
        "error":     load_error,
        "desktop":   os.environ.get("CC_WORKSHOP_DESKTOP") == "1",
        "vehicle":   VEHICLE_PROFILE,
    })


@app.route("/health")
def health():
    return jsonify({"ok": True, "ready": _library_unavailable() is None})


@app.route("/library")
def library():
    unavailable = _library_unavailable()
    if unavailable:
        return jsonify({"manuals": [], "error": unavailable})
    try:
        get_library()
    except (Exception, SystemExit) as exc:
        return jsonify({"manuals": [], "error": str(exc)}), 503
    manuals = []
    for manual_id, manifest in sorted(_manifests.items()):
        manuals.append({
            "manual_id": manual_id,
            "title": manifest.get("title") or manifest.get("manual_title") or manual_id,
            "vehicle": manifest.get("vehicle") or "",
            "system": manifest.get("system") or "",
            "pages": manifest.get("page_count"),
        })
    return jsonify({"manuals": manuals, "error": None})


@app.route("/query", methods=["POST"])
def query():
    from retrieve import gate, assemble_context as manual_assemble_context
    from specverify import verify_answer

    # Optional video retriever — soft-fail if not present
    try:
        from retrieve_video import VideoRetriever
        from retrieve_video import assemble_context as video_assemble_context
        _video_available = True
    except ImportError:
        _video_available = False

    data = request.get_json(force=True) or {}
    q    = (data.get("q") or "").strip()
    if not q:
        return jsonify({"error": "empty query"}), 400

    unavailable = _library_unavailable()
    if unavailable:
        return jsonify({
            "error": "library_unavailable",
            "message": unavailable,
        }), 503
    try:
        lib = get_library()
    except (Exception, SystemExit) as exc:
        return jsonify({
            "error": "library_unavailable",
            "message": str(exc),
        }), 503

    # 1. Manual retrieval + grounding gate
    retrieval_q           = _expand(q)
    manual_results        = lib.retrieve(retrieval_q, k=7, boost=True,
                                         profile=VEHICLE_PROFILE)
    decision, gate_reason = gate(manual_results, query=retrieval_q)

    if decision == "REFUSE":
        return jsonify({
            "refused":        True,
            "answer":         "I cannot find this in the factory manuals I have indexed. "
                              "Check the source PDF directly.",
            "citations":      [],
            "conflicts":      [],
            "verified":       False,
            "verify_findings": [],
            "gate_reason":    gate_reason,
            "vehicle":        VEHICLE_PROFILE,
        })

    # 2. Video retrieval (optional)
    video_results  = []
    conflict_notes = []
    if _video_available:
        try:
            vr            = VideoRetriever(out_dir=OUT_DIR)
            video_results = vr.query(retrieval_q, k=3)
        except Exception:
            pass

    # 3. Build generation context
    if video_results:
        context_text, manual_cids, conflict_notes = video_assemble_context(
            manual_results, video_results
        )
    else:
        context_text, manual_cids = manual_assemble_context(manual_results)

    # 4. Generate via Ollama
    answer = call_ollama(q, context_text)

    if answer is None:
        return jsonify({
            "refused":        False,
            "answer":         (
                f"⚠ Ollama is not reachable at {OLLAMA_BASE}. "
                f"The relevant manual pages were retrieved (see citations) "
                f"but no answer could be generated. "
                f"Start Ollama and ensure '{OLLAMA_MODEL}' is pulled."
            ),
            "citations":       _build_citations("", manual_results),
            "video_citations": [],
            "conflicts":       conflict_notes,
            "verified":        False,
            "verify_findings": [],
            "gate_reason":     "ollama_unreachable",
        })

    # 5. specverify — numeric values in the answer must match cited chunks exactly
    cited_chunks  = [_chunks_by_id[cid] for cid in manual_cids if cid in _chunks_by_id]
    verify        = verify_answer(answer, cited_chunks)

    if not verify["ok"] and verify["numbers_checked"] > 0:
        bad = [f["stated"] for f in verify["findings"] if f["status"] == "REJECT"]
        answer = (
            "I found relevant information but could not verify all numeric specifications "
            f"against the source chunks. Unverified value(s): {', '.join(bad)}. "
            "Consult the source PDF directly before acting on any spec."
        )

    video_citations = [
        {
            "video_id":        r.get("video_id", ""),
            "title":           r.get("title", ""),
            "channel":         r.get("channel", ""),
            "system":          r.get("system", ""),
            "timestamp_label": r.get("timestamp_label", "?:??"),
            "citation_url":    r.get("citation_url"),
            "frame_url":       f"/video-frame/{r['frame_path']}" if r.get("frame_path") else None,
            "text_preview":    r.get("text", "")[:150],
            "conflict_warning": r.get("conflict_warning"),
        }
        for r in video_results
    ]

    return jsonify({
        "refused":          False,
        "answer":           answer,
        "citations":        _build_citations(answer, manual_results),
        "video_citations":  video_citations,
        "conflicts":        conflict_notes,
        "verified":         verify["ok"],
        "verify_findings":  verify["findings"],
        "gate_reason":      None,
        "vehicle":          VEHICLE_PROFILE,
    })


@app.route("/pdf/<manual_id>")
def serve_pdf(manual_id):
    """Stream the source PDF bytes so the browser can render it natively."""
    try:
        get_library()  # ensure manifests are loaded
    except (Exception, SystemExit) as exc:
        return str(exc), 503
    if manual_id not in _manifests:
        return "Unknown manual", 404
    src = _manifests[manual_id].get("source_path", "")
    if not os.path.isfile(src):
        return f"PDF not found on disk: {src}", 404
    return send_file(src, mimetype="application/pdf")


@app.route("/video-frame/<path:frame_path>")
def serve_video_frame(frame_path):
    """Serve an extracted video frame JPEG from out/videos/{video_id}/frames/."""
    abs_path = os.path.abspath(os.path.join(OUT_DIR, frame_path))
    if os.path.commonpath([OUT_DIR, abs_path]) != OUT_DIR:
        return "Invalid frame path", 400
    if not os.path.isfile(abs_path):
        return "Frame not found", 404
    return send_file(abs_path, mimetype="image/jpeg")


@app.route("/viewer")
def viewer():
    """Open a source PDF in the browser's built-in viewer, jumped to the right page."""
    manual_id = request.args.get("manual", "")
    page      = request.args.get("page", "1")
    try:
        get_library()
    except (Exception, SystemExit) as exc:
        return str(exc), 503
    if manual_id not in _manifests:
        return f"Unknown manual: {manual_id!r}", 404
    # Redirect to the PDF-serving route; browser PDF viewer honours #page=N
    from flask import redirect
    return redirect(f"/pdf/{manual_id}#page={page}")


# ── main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[vw-rag] Loading library from {OUT_DIR} …", flush=True)
    if _library_unavailable():
        print(f"[vw-rag] {_library_unavailable()}")
    else:
        get_library()
        print(f"[vw-rag] {len(_library.chunks):,} chunks across {len(_manifests)} manuals")
        print(f"[vw-rag] Embedder : {_library.embedder.name}")
    print(f"[vw-rag] Ollama   : {OLLAMA_BASE}  model={OLLAMA_MODEL}")
    print(f"[vw-rag] Open     : http://localhost:5000", flush=True)
    app.run(host="0.0.0.0", port=5000, debug=False)
