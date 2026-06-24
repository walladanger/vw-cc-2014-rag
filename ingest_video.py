#!/usr/bin/env python3
"""
Video Ingestion Pipeline (v2) — community-source supplement for the VW CC RAG assistant.

Transcribes repair videos with Whisper, chunks by topic breaks, writes
timestamped JSONL chunks + a video_index.json, downloads 1080p video files,
and extracts one representative frame per chunk for visual context.

SAFETY TIER:  All video chunks are tagged  safety_tier = "community".
              They MUST NOT be used by specverify.  Torque values, clearances,
              stretch-bolt flags, and fluid specs must always cite the factory
              manual.  Videos are "see also" only for those values.

Conflict rule: if a video chunk contains a number that looks like a torque spec,
              the conflict is logged and surfaced to the user — never silently
              resolved in favour of the video.

Usage:
  python ingest_video.py inspect <video_or_url>
  python ingest_video.py ingest  <video_or_url> \\
      --video-id dsg_fluid_change_01 \\
      --title "VW CC DSG Fluid Change Full Walk-through" \\
      --channel "EuroWrench" \\
      --vehicle "2014 VW CC 2.0T TSI" \\
      --system "DSG/DQ250" \\
      --out ./out

  python ingest_video.py add-frames --out ./out              # all videos
  python ingest_video.py add-frames --out ./out --video-id X # one video

  python ingest_video.py list-videos --out ./out
  python ingest_video.py conflicts   --out ./out

Dependencies:
  pip install openai-whisper yt-dlp rank-bm25 numpy
  ffmpeg must be on PATH (used by yt-dlp for merging and frame extraction)
"""

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

# Force UTF-8 output on Windows (avoids CP1252 crashes on Unicode symbols)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ──────────────────────────────────────────── optional heavy deps (lazy import)

def _import_whisper():
    try:
        import whisper
        return whisper
    except ImportError:
        sys.exit("openai-whisper not installed.  Run:  pip install openai-whisper")

def _import_ytdlp():
    try:
        import yt_dlp
        return yt_dlp
    except ImportError:
        sys.exit("yt-dlp not installed.  Run:  pip install yt-dlp")

# ──────────────────────────────────────────── constants

PIPELINE_VERSION = "ingest-video-v2"
VIDEO_INDEX_NAME = "video_index.json"

# yt-dlp format string: best available resolution merged with best audio
VIDEO_FORMAT = (
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]"
    "/bestvideo+bestaudio"
    "/best"
)

# Silence gap that suggests a topic boundary (seconds)
TOPIC_SILENCE_GAP = 3.5
# Chunk target length in words (soft limit — never split mid-sentence)
CHUNK_TARGET_WORDS = 180
CHUNK_MAX_WORDS    = 320

# JPEG quality for extracted frames (2 = near-lossless, 31 = worst)
FRAME_JPEG_QUALITY = 2

# Patterns that look like torque / safety-critical specs in transcripts.
TORQUE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:nm|newton.?met(?:er|re)|foot.?pound|ft.?lb|"
    r"in.?lb|n\.m)\b"
    r"|(?:torque|tighten(?:ing)?|torqued?)\s+(?:to|at|is|of)?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
SPEC_KEYWORDS = re.compile(
    r"\b(stretch bolt|replace after|one.?time use|cannot be reused|"
    r"single.?use|fluid capacit|change interval|gap spec|clearance)\b",
    re.IGNORECASE,
)

# ──────────────────────────────────────────── helpers

def now_iso():
    return _dt.datetime.now(_dt.timezone.utc).isoformat()

def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

def sha256_file(path: str, buf=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(buf), b""):
            h.update(block)
    return h.hexdigest()

def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "www.", "youtu"))

def safe_id(s: str) -> str:
    return re.sub(r"[^\w]", "_", s)[:48].lower().strip("_")

def word_count(text: str) -> int:
    return len(text.split())

# ──────────────────────────────────────────── download (audio-only fallback)

def download_audio(url_or_path: str, tmp_dir: str, quiet: bool = False) -> tuple[str, dict]:
    """Audio-only download for --no-video mode. Returns (audio_path, metadata)."""
    if not is_url(url_or_path) and os.path.isfile(url_or_path):
        dst = os.path.join(tmp_dir, "audio" + Path(url_or_path).suffix)
        shutil.copy2(url_or_path, dst)
        meta = {
            "url": url_or_path, "title": Path(url_or_path).stem,
            "channel": "local", "duration": None,
            "upload_date": None, "webpage_url": None,
        }
        return dst, meta

    yt_dlp = _import_ytdlp()
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(tmp_dir, "audio.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "64",
        }],
        "quiet": quiet,
        "no_warnings": quiet,
    }
    meta = {}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url_or_path, download=True)
        meta = {
            "url": url_or_path,
            "title": info.get("title", ""),
            "channel": info.get("uploader", info.get("channel", "")),
            "duration": info.get("duration"),
            "upload_date": info.get("upload_date"),
            "webpage_url": info.get("webpage_url", url_or_path),
        }
    audio_path = os.path.join(tmp_dir, "audio.mp3")
    for f in os.listdir(tmp_dir):
        if f.startswith("audio.") and f.endswith(".mp3"):
            audio_path = os.path.join(tmp_dir, f)
            break
    return audio_path, meta

# ──────────────────────────────────────────── download (1080p video + audio)

def download_video(url_or_path: str, video_dest: str, tmp_dir: str,
                   quiet: bool = False) -> tuple[str, str, dict]:
    """
    Downloads 1080p video to video_dest (permanent), extracts audio to tmp_dir.
    Returns (video_path, audio_path, metadata).
    """
    if not is_url(url_or_path) and os.path.isfile(url_or_path):
        video_path = url_or_path
        audio_path = os.path.join(tmp_dir, "audio.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn",
             "-acodec", "libmp3lame", "-q:a", "2", audio_path],
            check=True, capture_output=True,
        )
        meta = {
            "url": url_or_path, "title": Path(url_or_path).stem,
            "channel": "local", "duration": None,
            "upload_date": None, "webpage_url": None,
        }
        return video_path, audio_path, meta

    yt_dlp = _import_ytdlp()
    os.makedirs(os.path.dirname(video_dest), exist_ok=True)

    base_no_ext = os.path.splitext(video_dest)[0]
    ydl_opts = {
        "format": VIDEO_FORMAT,
        "outtmpl": base_no_ext + ".%(ext)s",
        "merge_output_format": "mp4",
        "quiet": quiet,
        "no_warnings": quiet,
    }
    meta = {}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url_or_path, download=True)
        meta = {
            "url": url_or_path,
            "title": info.get("title", ""),
            "channel": info.get("uploader", info.get("channel", "")),
            "duration": info.get("duration"),
            "upload_date": info.get("upload_date"),
            "webpage_url": info.get("webpage_url", url_or_path),
            "height": info.get("height"),
            "width": info.get("width"),
        }

    # Locate the actual downloaded file (yt-dlp may write .mp4 or .mkv)
    video_path = video_dest
    if not os.path.isfile(video_path):
        for ext in (".mp4", ".mkv", ".webm"):
            candidate = base_no_ext + ext
            if os.path.isfile(candidate):
                video_path = candidate
                break

    # Extract audio from the video for Whisper
    audio_path = os.path.join(tmp_dir, "audio.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn",
         "-acodec", "libmp3lame", "-q:a", "2", audio_path],
        check=True, capture_output=quiet,
    )

    return video_path, audio_path, meta

# ──────────────────────────────────────────── frame extraction

def extract_frame(video_path: str, timestamp: float, output_path: str) -> bool:
    """
    Extract one JPEG frame from video_path at timestamp seconds.
    Seeking before -i is fast (hits nearest keyframe then decodes forward).
    Returns True on success.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    result = subprocess.run(
        ["ffmpeg", "-y",
         "-ss", str(timestamp),
         "-i", video_path,
         "-vframes", "1",
         "-q:v", str(FRAME_JPEG_QUALITY),
         output_path],
        capture_output=True,
    )
    return result.returncode == 0 and os.path.isfile(output_path)


def extract_frames_for_chunks(chunks: list[dict], video_path: str,
                               frames_dir: str, video_id: str) -> list[dict]:
    """
    Extract one midpoint frame per chunk. Stores frames as
    {frames_dir}/{chunk_id}.jpg and adds frame_path / frame_timestamp
    to each chunk dict (relative path from out_dir root).
    """
    os.makedirs(frames_dir, exist_ok=True)
    ok_count = 0
    for chunk in chunks:
        midpoint = (chunk["timestamp_start"] + chunk["timestamp_end"]) / 2.0
        frame_filename = f"{chunk['chunk_id']}.jpg"
        abs_frame_path = os.path.join(frames_dir, frame_filename)
        # Store relative path (relative to out_dir) so app.py can serve it
        rel_frame_path = os.path.join("videos", video_id, "frames", frame_filename)
        ok = extract_frame(video_path, midpoint, abs_frame_path)
        if ok:
            chunk["frame_path"] = rel_frame_path.replace("\\", "/")
            chunk["frame_timestamp"] = round(midpoint, 2)
            ok_count += 1
        else:
            chunk["frame_path"] = None
            chunk["frame_timestamp"] = None
    print(f"[{video_id}] Extracted {ok_count}/{len(chunks)} frames")
    return chunks

# ──────────────────────────────────────────── transcription

def transcribe(audio_path: str, model_size: str = "medium") -> list[dict]:
    """Returns list of Whisper segments: {id, start, end, text}"""
    whisper = _import_whisper()
    print(f"  Loading Whisper model '{model_size}' ...", file=sys.stderr)
    model = whisper.load_model(model_size)
    print(f"  Transcribing {audio_path} ...", file=sys.stderr)
    result = model.transcribe(audio_path, verbose=False, word_timestamps=False)
    return result.get("segments", [])

# ──────────────────────────────────────────── chunking

def _gap_before(segments: list[dict], idx: int) -> float:
    if idx == 0:
        return 0.0
    return segments[idx]["start"] - segments[idx - 1]["end"]

def chunk_segments(segments: list[dict]) -> list[dict]:
    if not segments:
        return []
    chunks = []
    current_segs = []
    current_words = 0

    def flush(segs):
        if not segs:
            return
        text = " ".join(s["text"].strip() for s in segs).strip()
        chunks.append({
            "timestamp_start": round(segs[0]["start"], 2),
            "timestamp_end":   round(segs[-1]["end"],  2),
            "text": text,
        })

    for i, seg in enumerate(segments):
        gap = _gap_before(segments, i)
        seg_words = word_count(seg["text"])
        force_break = (
            gap >= TOPIC_SILENCE_GAP
            or (current_words + seg_words > CHUNK_MAX_WORDS and current_words >= CHUNK_TARGET_WORDS)
        )
        if force_break and current_segs:
            flush(current_segs)
            current_segs = []
            current_words = 0
        current_segs.append(seg)
        current_words += seg_words

    flush(current_segs)
    return chunks

# ──────────────────────────────────────────── spec conflict detection

def detect_spec_conflicts(text: str) -> list[dict]:
    conflicts = []
    for m in TORQUE_RE.finditer(text):
        value = m.group(1) or m.group(2)
        conflicts.append({
            "type": "torque_value",
            "value": value,
            "context": text[max(0, m.start()-40):m.end()+40].replace("\n", " "),
        })
    for m in SPEC_KEYWORDS.finditer(text):
        conflicts.append({
            "type": "spec_keyword",
            "keyword": m.group(0),
            "context": text[max(0, m.start()-40):m.end()+40].replace("\n", " "),
        })
    return conflicts

# ──────────────────────────────────────────── embedding (pluggable)

def embed_texts(texts: list[str], embedder: str = "local",
                ollama_base: str = "http://localhost:11434") -> list[list[float]]:
    if embedder == "ollama":
        import httpx
        vecs = []
        for t in texts:
            r = httpx.post(
                f"{ollama_base}/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": t},
                timeout=30,
            )
            vecs.append(r.json()["embedding"])
        return vecs
    else:
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            return model.encode(texts, show_progress_bar=False).tolist()
        except ImportError:
            print("  Warning: sentence-transformers not installed -- skipping embeddings.",
                  file=sys.stderr)
            return [[] for _ in texts]

# ──────────────────────────────────────────── index helpers

def load_video_index(out_dir: str) -> dict:
    path = os.path.join(out_dir, VIDEO_INDEX_NAME)
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"pipeline_version": PIPELINE_VERSION, "videos": []}

def save_video_index(index: dict, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, VIDEO_INDEX_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

def index_has_video(index: dict, video_id: str) -> bool:
    return any(v["video_id"] == video_id for v in index.get("videos", []))

def get_index_entry(index: dict, video_id: str) -> dict | None:
    for v in index.get("videos", []):
        if v["video_id"] == video_id:
            return v
    return None

# ──────────────────────────────────────────── main ingest

def ingest_video(
    source: str,
    video_id: str,
    title: str,
    channel: str,
    vehicle: str,
    system: str,
    out_dir: str,
    whisper_model: str = "medium",
    embedder: str = "local",
    ollama_base: str = "http://localhost:11434",
    skip_embed: bool = False,
    force: bool = False,
    with_video: bool = True,
):
    index = load_video_index(out_dir)

    if index_has_video(index, video_id) and not force:
        print(f"  {video_id} already in video_index.json -- skipping (use --force to re-ingest)")
        return

    video_out = os.path.join(out_dir, "videos", video_id)
    os.makedirs(video_out, exist_ok=True)
    frames_dir = os.path.join(video_out, "frames")

    video_file_path = None
    duration = None
    webpage_url = None

    with tempfile.TemporaryDirectory() as tmp:
        if with_video:
            print(f"[{video_id}] Downloading 1080p video ...")
            video_dest = os.path.join(video_out, "video.mp4")
            video_file_path, audio_path, dl_meta = download_video(source, video_dest, tmp)
        else:
            print(f"[{video_id}] Downloading audio ...")
            audio_path, dl_meta = download_audio(source, tmp)

        if not title:
            title = dl_meta.get("title", video_id)
        if not channel:
            channel = dl_meta.get("channel", "unknown")
        duration = dl_meta.get("duration")
        webpage_url = dl_meta.get("webpage_url") or (source if is_url(source) else None)

        # ── 2. Transcribe
        print(f"[{video_id}] Transcribing ({whisper_model}) ...")
        segments = transcribe(audio_path, model_size=whisper_model)

    # ── 3. Chunk
    print(f"[{video_id}] Chunking {len(segments)} segments ...")
    raw_chunks = chunk_segments(segments)
    print(f"[{video_id}] -> {len(raw_chunks)} chunks")

    # ── 4. Build chunk objects + detect conflicts
    all_conflicts = []
    chunk_objects  = []
    for i, rc in enumerate(raw_chunks):
        chunk_id = f"{video_id}_c{i:04d}"
        conflicts = detect_spec_conflicts(rc["text"])
        all_conflicts.extend([{"chunk_id": chunk_id, **c} for c in conflicts])
        chunk_objects.append({
            "chunk_id":          chunk_id,
            "video_id":          video_id,
            "safety_tier":       "community",
            "title":             title,
            "channel":           channel,
            "vehicle":           vehicle,
            "system":            system,
            "webpage_url":       webpage_url,
            "timestamp_start":   rc["timestamp_start"],
            "timestamp_end":     rc["timestamp_end"],
            "timestamp_label":   _fmt_ts(rc["timestamp_start"]),
            "text":              rc["text"],
            "word_count":        word_count(rc["text"]),
            "has_spec_conflict": bool(conflicts),
            "spec_conflicts":    conflicts,
            "frame_path":        None,
            "frame_timestamp":   None,
            "embedding":         [],
        })

    # ── 5. Extract frames (if we have a video file)
    if with_video and video_file_path and os.path.isfile(video_file_path):
        print(f"[{video_id}] Extracting frames ...")
        extract_frames_for_chunks(chunk_objects, video_file_path, frames_dir, video_id)

    # ── 6. Embed
    if not skip_embed and chunk_objects:
        print(f"[{video_id}] Embedding {len(chunk_objects)} chunks ({embedder}) ...")
        texts = [c["text"] for c in chunk_objects]
        vecs  = embed_texts(texts, embedder=embedder, ollama_base=ollama_base)
        for c, v in zip(chunk_objects, vecs):
            c["embedding"] = v

    # ── 7. Write chunks.jsonl
    chunks_path = os.path.join(video_out, "chunks.jsonl")
    with open(chunks_path, "w", encoding="utf-8") as f:
        for c in chunk_objects:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"[{video_id}] Wrote {chunks_path}")

    # ── 8. Write conflict log
    if all_conflicts:
        conflicts_path = os.path.join(video_out, "spec_conflicts.json")
        with open(conflicts_path, "w", encoding="utf-8") as f:
            json.dump(all_conflicts, f, indent=2, ensure_ascii=False)
        print(f"[{video_id}] {len(all_conflicts)} spec conflicts logged -> {conflicts_path}")

    # ── 9. Update video_index.json
    entry = {
        "video_id":       video_id,
        "title":          title,
        "channel":        channel,
        "vehicle":        vehicle,
        "system":         system,
        "source":         source,
        "webpage_url":    webpage_url,
        "duration_sec":   duration,
        "whisper_model":  whisper_model,
        "embedder":       embedder,
        "chunk_count":    len(chunk_objects),
        "conflict_count": len(all_conflicts),
        "safety_tier":    "community",
        "has_video":      with_video and video_file_path is not None and os.path.isfile(video_file_path),
        "has_frames":     with_video and any(c["frame_path"] for c in chunk_objects),
        "video_path":     os.path.join("videos", video_id, "video.mp4").replace("\\", "/") if with_video else None,
        "ingested_at":    now_iso(),
        "chunks_path":    chunks_path,
    }
    index["videos"] = [v for v in index["videos"] if v["video_id"] != video_id]
    index["videos"].append(entry)
    save_video_index(index, out_dir)
    frames_ok = sum(1 for c in chunk_objects if c.get("frame_path"))
    print(f"[{video_id}] Done -- {len(chunk_objects)} chunks, {frames_ok} frames, {len(all_conflicts)} conflicts")

def _fmt_ts(seconds: float) -> str:
    """Format 254.3 -> '4:14'"""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

# ──────────────────────────────────────────── add-frames (post-hoc frame extraction)

def add_frames_to_existing(out_dir: str, video_id: str | None = None, force: bool = False):
    """
    For already-ingested videos (text-only), downloads the 1080p video and
    extracts frames without re-transcribing. Updates chunks.jsonl in place.
    Pass video_id=None to process all videos in the index.
    """
    index = load_video_index(out_dir)
    targets = index.get("videos", [])
    if video_id:
        targets = [v for v in targets if v["video_id"] == video_id]
        if not targets:
            print(f"video_id '{video_id}' not found in index.")
            return

    for entry in targets:
        vid = entry["video_id"]
        video_out = os.path.join(out_dir, "videos", vid)
        video_dest = os.path.join(video_out, "video.mp4")
        frames_dir = os.path.join(video_out, "frames")
        chunks_path = os.path.join(video_out, "chunks.jsonl")

        if not os.path.isfile(chunks_path):
            print(f"[{vid}] No chunks.jsonl found -- skipping")
            continue

        # Skip if already has frames and not forced
        if entry.get("has_frames") and not force:
            frame_count = sum(1 for f in os.listdir(frames_dir) if f.endswith(".jpg")) if os.path.isdir(frames_dir) else 0
            print(f"[{vid}] Already has {frame_count} frames -- skipping (use --force to redo)")
            continue

        # Download video if not already present
        if not os.path.isfile(video_dest):
            source = entry.get("source") or entry.get("webpage_url")
            if not source:
                print(f"[{vid}] No source URL in index -- skipping")
                continue
            print(f"[{vid}] Downloading 1080p video ...")
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    video_path, _, _ = download_video(source, video_dest, tmp)
                except Exception as e:
                    print(f"[{vid}] Download failed: {e}")
                    continue
        else:
            video_path = video_dest
            print(f"[{vid}] Video already on disk: {video_dest}")

        # Load chunks
        chunks = []
        with open(chunks_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunks.append(json.loads(line))

        # Extract frames
        print(f"[{vid}] Extracting {len(chunks)} frames ...")
        extract_frames_for_chunks(chunks, video_path, frames_dir, vid)

        # Rewrite chunks.jsonl
        with open(chunks_path, "w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        # Update index entry
        entry["has_video"] = True
        entry["has_frames"] = any(c.get("frame_path") for c in chunks)
        entry["video_path"] = os.path.join("videos", vid, "video.mp4").replace("\\", "/")
        save_video_index(index, out_dir)
        frames_ok = sum(1 for c in chunks if c.get("frame_path"))
        print(f"[{vid}] Done -- {frames_ok}/{len(chunks)} frames extracted")

# ──────────────────────────────────────────── batch ingest

def ingest_batch(batch_file: str, out_dir: str, whisper_model: str, embedder: str,
                 ollama_base: str, skip_embed: bool, force: bool, with_video: bool):
    with open(batch_file, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    print(f"Batch: {len(lines)} videos")
    for line in lines:
        entry = json.loads(line)
        ingest_video(
            source        = entry["source"],
            video_id      = entry.get("video_id", safe_id(entry.get("title", "video"))),
            title         = entry.get("title", ""),
            channel       = entry.get("channel", ""),
            vehicle       = entry.get("vehicle", ""),
            system        = entry.get("system", ""),
            out_dir       = out_dir,
            whisper_model = whisper_model,
            embedder      = embedder,
            ollama_base   = ollama_base,
            skip_embed    = skip_embed,
            force         = force,
            with_video    = with_video,
        )

# ──────────────────────────────────────────── inspect

def inspect_video(source: str, whisper_model: str):
    with tempfile.TemporaryDirectory() as tmp:
        print(f"Downloading / locating: {source}")
        audio_path, meta = download_audio(source, tmp)
        print(f"  Title:    {meta.get('title', 'unknown')}")
        print(f"  Channel:  {meta.get('channel', 'unknown')}")
        dur = meta.get("duration")
        print(f"  Duration: {_fmt_ts(dur) if dur else 'unknown'}")
        print(f"  Transcribing ({whisper_model}) ...")
        segments = transcribe(audio_path, model_size=whisper_model)
    chunks = chunk_segments(segments)
    print(f"\n  Segments: {len(segments)}  ->  Chunks: {len(chunks)}")
    print("\n  First 5 chunks:")
    for c in chunks[:5]:
        print(f"  [{_fmt_ts(c['timestamp_start'])} - {_fmt_ts(c['timestamp_end'])}]")
        preview = c["text"][:120].replace("\n", " ")
        print(f"    {preview}...")

# ──────────────────────────────────────────── list / conflicts

def list_videos(out_dir: str):
    index = load_video_index(out_dir)
    videos = index.get("videos", [])
    if not videos:
        print("No videos indexed yet.")
        return
    print(f"{'video_id':<36} {'chunks':>6} {'frames':>6}  title")
    print("-" * 85)
    for v in videos:
        has_v = "[V]" if v.get("has_video") else "   "
        has_f = "[F]" if v.get("has_frames") else "   "
        print(f"{v['video_id']:<36} {v['chunk_count']:>6} {has_v}{has_f}  {v['title'][:38]}")

def show_conflicts(out_dir: str):
    index = load_video_index(out_dir)
    any_found = False
    for v in index.get("videos", []):
        cf_path = os.path.join(out_dir, "videos", v["video_id"], "spec_conflicts.json")
        if not os.path.isfile(cf_path):
            continue
        with open(cf_path, "r", encoding="utf-8") as f:
            conflicts = json.load(f)
        if not conflicts:
            continue
        any_found = True
        print(f"\n{'='*60}")
        print(f"VIDEO: {v['video_id']}  --  {v['title']}")
        print(f"{'='*60}")
        for c in conflicts:
            print(f"  [{c['type']}] chunk={c['chunk_id']}")
            if c.get("value"):   print(f"    value:   {c['value']}")
            if c.get("keyword"): print(f"    keyword: {c['keyword']}")
            print(f"    context: ...{c['context']}...")
    if not any_found:
        print("No spec conflicts found across all videos.")
    else:
        print("\nCross-check every conflict above against the factory manual before trusting any value.")

# ──────────────────────────────────────────── CLI

def main():
    parser = argparse.ArgumentParser(
        description="Ingest repair videos into the VW CC RAG assistant (community tier).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # inspect
    p_ins = sub.add_parser("inspect", help="Preview a video without ingesting")
    p_ins.add_argument("source")
    p_ins.add_argument("--whisper-model", default="medium",
                       choices=["tiny","base","small","medium","large","large-v2","large-v3"])

    # ingest
    p_ing = sub.add_parser("ingest", help="Ingest a single video")
    p_ing.add_argument("source")
    p_ing.add_argument("--video-id",      required=True)
    p_ing.add_argument("--title",         default="")
    p_ing.add_argument("--channel",       default="")
    p_ing.add_argument("--vehicle",       default="2014 VW CC 2.0T TSI DSG")
    p_ing.add_argument("--system",        default="")
    p_ing.add_argument("--out",           default="./out")
    p_ing.add_argument("--whisper-model", default="medium",
                       choices=["tiny","base","small","medium","large","large-v2","large-v3"])
    p_ing.add_argument("--embedder",      default="local", choices=["local","ollama"])
    p_ing.add_argument("--ollama-base",   default="http://localhost:11434")
    p_ing.add_argument("--skip-embed",    action="store_true")
    p_ing.add_argument("--force",         action="store_true")
    p_ing.add_argument("--no-video",      action="store_true",
                       help="Download audio only, skip video file and frame extraction")

    # ingest-batch
    p_bat = sub.add_parser("ingest-batch", help="Ingest multiple videos from a JSON-lines file")
    p_bat.add_argument("batch_file")
    p_bat.add_argument("--out",           default="./out")
    p_bat.add_argument("--whisper-model", default="medium")
    p_bat.add_argument("--embedder",      default="local", choices=["local","ollama"])
    p_bat.add_argument("--ollama-base",   default="http://localhost:11434")
    p_bat.add_argument("--skip-embed",    action="store_true")
    p_bat.add_argument("--force",         action="store_true")
    p_bat.add_argument("--no-video",      action="store_true")

    # add-frames
    p_af = sub.add_parser("add-frames",
                           help="Download 1080p video and extract frames for already-ingested videos")
    p_af.add_argument("--out",      default="./out")
    p_af.add_argument("--video-id", default=None,
                      help="Process one specific video (default: all videos in index)")
    p_af.add_argument("--force",    action="store_true",
                      help="Re-extract frames even if already present")

    # list-videos
    p_lst = sub.add_parser("list-videos", help="List all indexed videos")
    p_lst.add_argument("--out", default="./out")

    # conflicts
    p_con = sub.add_parser("conflicts", help="Show spec conflict log")
    p_con.add_argument("--out", default="./out")

    args = parser.parse_args()

    if args.cmd == "inspect":
        inspect_video(args.source, args.whisper_model)

    elif args.cmd == "ingest":
        ingest_video(
            source        = args.source,
            video_id      = args.video_id,
            title         = args.title,
            channel       = args.channel,
            vehicle       = args.vehicle,
            system        = args.system,
            out_dir       = args.out,
            whisper_model = args.whisper_model,
            embedder      = args.embedder,
            ollama_base   = args.ollama_base,
            skip_embed    = args.skip_embed,
            force         = args.force,
            with_video    = not args.no_video,
        )

    elif args.cmd == "ingest-batch":
        ingest_batch(
            batch_file    = args.batch_file,
            out_dir       = args.out,
            whisper_model = args.whisper_model,
            embedder      = args.embedder,
            ollama_base   = args.ollama_base,
            skip_embed    = args.skip_embed,
            force         = args.force,
            with_video    = not args.no_video,
        )

    elif args.cmd == "add-frames":
        add_frames_to_existing(
            out_dir  = args.out,
            video_id = args.video_id,
            force    = args.force,
        )

    elif args.cmd == "list-videos":
        list_videos(args.out)

    elif args.cmd == "conflicts":
        show_conflicts(args.out)


if __name__ == "__main__":
    main()
