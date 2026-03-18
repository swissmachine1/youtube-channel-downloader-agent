"""FastAPI web frontend for yt-summarize."""
from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Project root is one level up from web/
PROJECT_ROOT = Path(__file__).parent.parent

# On Render (and other cloud platforms), use /tmp for ephemeral storage.
# Override via OUTPUT_DIR / CACHE_DIR environment variables.
DEFAULT_OUTPUT = Path(os.environ.get("OUTPUT_DIR", "/tmp/yt-summarize/output"))
DEFAULT_CACHE = Path(os.environ.get("CACHE_DIR", "/tmp/yt-summarize/cache"))

app = FastAPI(title="yt-summarize UI")

# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}  # job_id -> {queue, status, stats, error}


def _make_job() -> tuple[str, queue.Queue]:
    job_id = str(uuid.uuid4())
    q: queue.Queue = queue.Queue()
    _jobs[job_id] = {"queue": q, "status": "running", "stats": None, "error": None}
    return job_id, q


def _finish_job(job_id: str, stats: dict | None = None, error: str | None = None) -> None:
    _jobs[job_id]["status"] = "error" if error else "done"
    _jobs[job_id]["stats"] = stats
    _jobs[job_id]["error"] = error
    _jobs[job_id]["queue"].put(None)  # sentinel


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

def _run_channel(job_id: str, url: str, max_results: int, output_dir: str, cache_dir: str, workers: int, since: str | None) -> None:
    from yt_summarize.fetcher import fetch_channel_videos
    from yt_summarize.pipeline import process_batch, generate_and_write_combined
    from yt_summarize import history as history_module

    q = _jobs[job_id]["queue"]

    def emit(event: dict) -> None:
        q.put(json.dumps(event))

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        emit({"type": "log", "message": f"Fetching videos from {url}…"})
        videos = fetch_channel_videos(url, max_results)

        if since:
            since_compact = since.replace("-", "")
            before = len(videos)
            videos = [v for v in videos if v.upload_date >= since_compact]
            emit({"type": "log", "message": f"Filtered to {len(videos)} videos since {since} ({before - len(videos)} older skipped)"})

        emit({"type": "found", "count": len(videos), "message": f"Found {len(videos)} videos – starting processing…"})

        output_path = Path(output_dir)
        cache_path = Path(cache_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        cache_path.mkdir(parents=True, exist_ok=True)

        processed, stats = process_batch(videos, output_path, cache_path, workers=workers, on_event=emit)
        generate_and_write_combined(processed, output_path, on_event=emit)

        history_module.append_run(
            cache_path,
            history_module.make_record(
                command="channel",
                input_=url,
                max_results=max_results,
                videos_found=len(videos),
                videos_processed=stats["done"],
                videos_from_cache=stats["cached"],
                videos_failed=stats["error"] + stats["skip"],
                output_dir=str(output_path.resolve()),
            ),
        )
        _finish_job(job_id, stats=stats)

    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
        _finish_job(job_id, error=str(exc))


def _run_search(job_id: str, query: str, max_results: int, output_dir: str, cache_dir: str, workers: int) -> None:
    from yt_summarize.fetcher import search_videos
    from yt_summarize.pipeline import process_batch, generate_and_write_combined
    from yt_summarize import history as history_module

    q = _jobs[job_id]["queue"]

    def emit(event: dict) -> None:
        q.put(json.dumps(event))

    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        emit({"type": "log", "message": f'Searching YouTube for "{query}"…'})
        videos = search_videos(query, max_results)

        emit({"type": "found", "count": len(videos), "message": f"Found {len(videos)} videos – starting processing…"})

        output_path = Path(output_dir)
        cache_path = Path(cache_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        cache_path.mkdir(parents=True, exist_ok=True)

        processed, stats = process_batch(videos, output_path, cache_path, workers=workers, on_event=emit)
        generate_and_write_combined(processed, output_path, on_event=emit)

        history_module.append_run(
            cache_path,
            history_module.make_record(
                command="search",
                input_=query,
                max_results=max_results,
                videos_found=len(videos),
                videos_processed=stats["done"],
                videos_from_cache=stats["cached"],
                videos_failed=stats["error"] + stats["skip"],
                output_dir=str(output_path.resolve()),
            ),
        )
        _finish_job(job_id, stats=stats)

    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
        _finish_job(job_id, error=str(exc))


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ChannelRequest(BaseModel):
    url: str
    max_results: int = 20
    output_dir: str = str(DEFAULT_OUTPUT)
    cache_dir: str = str(DEFAULT_CACHE)
    workers: int = 5
    since: str | None = None


class SearchRequest(BaseModel):
    query: str
    max_results: int = 10
    output_dir: str = str(DEFAULT_OUTPUT)
    cache_dir: str = str(DEFAULT_CACHE)
    workers: int = 5


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/api/run/channel")
def start_channel(req: ChannelRequest) -> dict:
    job_id, _ = _make_job()
    threading.Thread(
        target=_run_channel,
        args=(job_id, req.url, req.max_results, req.output_dir, req.cache_dir, req.workers, req.since),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.post("/api/run/search")
def start_search(req: SearchRequest) -> dict:
    job_id, _ = _make_job()
    threading.Thread(
        target=_run_search,
        args=(job_id, req.query, req.max_results, req.output_dir, req.cache_dir, req.workers),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    q = _jobs[job_id]["queue"]
    loop = asyncio.get_event_loop()

    async def generate():
        while True:
            try:
                item = await loop.run_in_executor(None, q.get, True, 1.0)
                if item is None:
                    job = _jobs[job_id]
                    end_payload = {"type": "end", "status": job["status"], "stats": job["stats"], "error": job["error"]}
                    yield f"data: {json.dumps(end_payload)}\n\n"
                    break
                yield f"data: {item}\n\n"
            except Exception:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/history")
def get_history(cache_dir: str = str(DEFAULT_CACHE), limit: int = 50) -> list[dict]:
    from yt_summarize import history as history_module
    records = history_module.load_history(Path(cache_dir))
    recent = records[-limit:][::-1]
    return [asdict(r) for r in recent]


@app.get("/api/output")
def list_output(output_dir: str = str(DEFAULT_OUTPUT)) -> list[dict]:
    path = Path(output_dir)
    if not path.exists():
        return []
    files = sorted(path.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [
        {"name": f.name, "size": f.stat().st_size, "mtime": f.stat().st_mtime}
        for f in files
    ]


@app.get("/api/output/{filename}")
def get_output_file(filename: str, output_dir: str = str(DEFAULT_OUTPUT)) -> dict:
    path = Path(output_dir) / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Safety: ensure file is within output_dir
    try:
        path.resolve().relative_to(Path(output_dir).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    return {"name": filename, "content": path.read_text(encoding="utf-8")}


@app.get("/api/status")
def status() -> dict:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {"api_key_set": has_key}


# ---------------------------------------------------------------------------
# Serve frontend
# ---------------------------------------------------------------------------

_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/")
def index():
    return FileResponse(str(_static_dir / "index.html"))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    port = int(os.environ.get("PORT", 8000))
    reload = os.environ.get("DEV", "").lower() in ("1", "true", "yes")
    uvicorn.run("web.app:app", host="0.0.0.0", port=port, reload=reload)


if __name__ == "__main__":
    main()
