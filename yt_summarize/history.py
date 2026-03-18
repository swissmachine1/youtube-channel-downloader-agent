import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class RunRecord:
    timestamp: str
    command: str        # "channel" | "search"
    input: str          # url or query
    max_results: int
    videos_found: int
    videos_processed: int
    videos_from_cache: int
    videos_failed: int
    output_dir: str


def _history_path(cache_dir: Path) -> Path:
    return cache_dir / "_history.json"


def load_history(cache_dir: Path) -> list[RunRecord]:
    path = _history_path(cache_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [RunRecord(**r) for r in data]
    except Exception:
        return []


def append_run(cache_dir: Path, record: RunRecord) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _history_path(cache_dir)
    tmp = path.with_suffix(".tmp")

    records = load_history(cache_dir)
    records.append(record)

    tmp.write_text(json.dumps([asdict(r) for r in records], indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def make_record(
    command: str,
    input_: str,
    max_results: int,
    videos_found: int,
    videos_processed: int,
    videos_from_cache: int,
    videos_failed: int,
    output_dir: str,
) -> RunRecord:
    return RunRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        command=command,
        input=input_,
        max_results=max_results,
        videos_found=videos_found,
        videos_processed=videos_processed,
        videos_from_cache=videos_from_cache,
        videos_failed=videos_failed,
        output_dir=output_dir,
    )
