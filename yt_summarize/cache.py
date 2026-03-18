import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .models import CachedVideo, VideoMetadata, TranscriptSegment, SummaryResult


def _cache_path(cache_dir: Path, video_id: str) -> Path:
    return cache_dir / f"{video_id}.json"


def is_cached(cache_dir: Path, video_id: str) -> bool:
    """Return True if a complete cache entry (with summary) exists."""
    path = _cache_path(cache_dir, video_id)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
        return data.get("summary") is not None
    except Exception:
        return False


def load_cache(cache_dir: Path, video_id: str) -> Optional[CachedVideo]:
    """Load a CachedVideo from disk. Returns None if not found or corrupted."""
    path = _cache_path(cache_dir, video_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        meta = data["metadata"]
        metadata = VideoMetadata(**meta)
        transcript = [TranscriptSegment(**s) for s in data.get("transcript", [])]
        transcript_source = data.get("transcript_source", "none")
        summary = None
        if data.get("summary"):
            summary = SummaryResult(**data["summary"])
        return CachedVideo(
            metadata=metadata,
            transcript=transcript,
            transcript_source=transcript_source,
            summary=summary,
        )
    except Exception:
        return None


def save_cache(cache_dir: Path, cached: CachedVideo) -> None:
    """Atomically write a CachedVideo to disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, cached.metadata.video_id)
    tmp_path = path.with_suffix(".tmp")

    data = {
        "metadata": asdict(cached.metadata),
        "transcript": [asdict(s) for s in cached.transcript],
        "transcript_source": cached.transcript_source,
        "summary": asdict(cached.summary) if cached.summary else None,
    }

    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp_path, path)
