from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Semaphore

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.status import Status

from .models import VideoMetadata, CachedVideo
from . import cache as cache_module
from . import transcript as transcript_module
from . import summarizer as summarizer_module
from . import renderer as renderer_module

_console = Console()


def _process_one(
    meta: VideoMetadata,
    output_dir: Path,
    cache_dir: Path,
    progress: Progress,
    overall_task,
    claude_sem: Semaphore,
    on_event: Callable[[dict], None] | None = None,
) -> tuple[CachedVideo | None, str]:
    """
    Process a single video end-to-end.
    Returns (CachedVideo | None, status) where status is one of:
    "cached", "done", "skip", "error"
    """
    label = meta.title[:60]

    def _emit(state: str, message: str) -> None:
        if on_event:
            on_event({"type": "video", "video_id": meta.video_id, "title": label, "state": state, "message": message})

    # Full cache hit
    if cache_module.is_cached(cache_dir, meta.video_id):
        cached = cache_module.load_cache(cache_dir, meta.video_id)
        progress.console.print(f"  [dim][cache][/dim] {label}")
        _emit("cached", f"[cache] {label}")
        progress.advance(overall_task)
        return cached, "cached"

    # Partial cache (transcript but no summary)
    cached = cache_module.load_cache(cache_dir, meta.video_id)

    if cached is None or not cached.transcript:
        progress.console.print(f"  [cyan][transcript][/cyan] {label}")
        _emit("transcript", f"[transcript] {label}")
        segments, source = transcript_module.fetch_transcript(meta.video_id)

        if source == "none" or not segments:
            progress.console.print(f"  [yellow][skip][/yellow] {label}: no transcript")
            _emit("skip", f"[skip] {label}: no transcript")
            progress.advance(overall_task)
            return None, "skip"

        cached = CachedVideo(
            metadata=meta,
            transcript=segments,
            transcript_source=source,
            summary=None,
        )
        cache_module.save_cache(cache_dir, cached)
    else:
        progress.console.print(f"  [cyan][re-summarize][/cyan] {label}")
        _emit("transcript", f"[re-summarize] {label}")

    # Summarize (throttled via semaphore to avoid Claude rate limits)
    progress.console.print(f"  [magenta][summarize][/magenta] {label}")
    _emit("summarize", f"[summarize] {label}")
    try:
        transcript_text = transcript_module.segments_to_text(cached.transcript)
        with claude_sem:
            summary = summarizer_module.summarize_video(meta.title, transcript_text)
        cached.summary = summary
    except Exception as e:
        progress.console.print(f"  [red][error][/red] {label}: {e}")
        _emit("error", f"[error] {label}: {e}")
        progress.advance(overall_task)
        return None, "error"

    cache_module.save_cache(cache_dir, cached)
    out_path = renderer_module.write_video_file(output_dir, cached)
    progress.console.print(f"  [green][done][/green] {label} → {out_path.name}")
    _emit("done", f"[done] {label} → {out_path.name}")
    progress.advance(overall_task)
    return cached, "done"


def process_batch(
    videos: list[VideoMetadata],
    output_dir: Path,
    cache_dir: Path,
    workers: int = 5,
    on_event: Callable[[dict], None] | None = None,
) -> tuple[list[CachedVideo], dict[str, int]]:
    """
    Process a batch of videos concurrently.
    Returns (processed_list, stats_dict).
    stats keys: cached, done, skip, error
    """
    processed = []
    stats = {"cached": 0, "done": 0, "skip": 0, "error": 0}
    # Limit concurrent Claude calls independently of worker count
    claude_sem = Semaphore(min(workers, 3))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
    ) as progress:
        overall = progress.add_task(
            f"[bold]Processing {len(videos)} videos[/bold]", total=len(videos)
        )

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _process_one, meta, output_dir, cache_dir, progress, overall, claude_sem, on_event
                ): meta
                for meta in videos
            }
            for future in as_completed(futures):
                try:
                    cached, status = future.result()
                except Exception as e:
                    meta = futures[future]
                    progress.console.print(f"  [red][fatal][/red] {meta.title[:60]}: {e}")
                    if on_event:
                        on_event({"type": "video", "video_id": meta.video_id, "title": meta.title[:60], "state": "error", "message": f"[fatal] {meta.title[:60]}: {e}"})
                    stats["error"] += 1
                    progress.advance(overall)
                    continue

                stats[status] += 1
                if cached is not None:
                    processed.append(cached)

    return processed, stats


def generate_and_write_combined(
    processed: list[CachedVideo],
    output_dir: Path,
    on_event: Callable[[dict], None] | None = None,
) -> None:
    """Generate and write the combined batch summary."""
    if not processed:
        return

    video_summaries = [
        (c.metadata.title, c.summary.short)
        for c in processed
        if c.summary
    ]

    if not video_summaries:
        return

    if on_event:
        on_event({"type": "log", "message": f"Generating combined summary for {len(video_summaries)} videos..."})

    with Status(
        f"[bold]Generating combined summary for {len(video_summaries)} videos...[/bold]",
        console=_console,
    ):
        try:
            combined = summarizer_module.generate_combined_summary(video_summaries)
        except Exception as e:
            _console.print(f"[red][combined error][/red] {e}")
            if on_event:
                on_event({"type": "log", "message": f"[combined error] {e}"})
            return

    titles = [c.metadata.title for c in processed]
    out_path = renderer_module.write_combined_file(output_dir, combined, titles)
    _console.print(f"[combined] → {out_path.name}")
    if on_event:
        on_event({"type": "log", "message": f"[combined] → {out_path.name}"})
