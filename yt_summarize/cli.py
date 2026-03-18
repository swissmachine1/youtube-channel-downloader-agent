from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .config import get_api_key
from .fetcher import fetch_channel_videos, search_videos
from .pipeline import process_batch, generate_and_write_combined
from . import history as history_module

console = Console()


@click.group()
def cli():
    """yt-summarize: Download YouTube transcripts and summarize with Claude."""
    get_api_key()


@cli.command()
@click.option("--url", required=True, help="YouTube channel URL (e.g. https://youtube.com/@SomeChannel)")
@click.option("--max", "max_results", default=20, show_default=True, help="Maximum number of videos to process")
@click.option("--output", "output_dir", default="./output", show_default=True, help="Output directory for markdown files")
@click.option("--cache", "cache_dir", default="./cache", show_default=True, help="Cache directory for JSON files")
@click.option("--workers", default=5, show_default=True, help="Number of concurrent workers")
@click.option("--since", default=None, metavar="YYYY-MM-DD", help="Only process videos uploaded on or after this date")
def channel(url: str, max_results: int, output_dir: str, cache_dir: str, workers: int, since: str | None):
    """Fetch and summarize videos from a YouTube channel."""
    output_path = Path(output_dir)
    cache_path = Path(cache_dir)

    # Validate --since
    since_compact = None
    if since:
        try:
            since_compact = since.replace("-", "")
            if len(since_compact) != 8 or not since_compact.isdigit():
                raise ValueError
        except ValueError:
            raise click.BadParameter("must be YYYY-MM-DD", param_hint="--since")

    console.print(f"Fetching up to [bold]{max_results}[/bold] videos from: [cyan]{url}[/cyan]")
    try:
        videos = fetch_channel_videos(url, max_results)
    except Exception as e:
        raise click.ClickException(f"Failed to fetch channel videos: {e}")

    if since_compact:
        before = len(videos)
        videos = [v for v in videos if v.upload_date >= since_compact]
        console.print(f"Filtered to [bold]{len(videos)}[/bold] videos since {since} ({before - len(videos)} older skipped)")

    if not videos:
        console.print("No videos found.")
        return

    console.print(f"Found [bold]{len(videos)}[/bold] videos. Processing with {workers} workers...\n")
    processed, stats = process_batch(videos, output_path, cache_path, workers=workers)
    generate_and_write_combined(processed, output_path)

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

    console.print(
        f"\nDone! [green]{stats['done']}[/green] new, "
        f"[dim]{stats['cached']}[/dim] cached, "
        f"[yellow]{stats['skip']}[/yellow] skipped, "
        f"[red]{stats['error']}[/red] errors."
    )
    console.print(f"Output: {output_path.resolve()}")


@cli.command()
@click.option("--query", required=True, help="YouTube search query")
@click.option("--max", "max_results", default=10, show_default=True, help="Maximum number of videos to process")
@click.option("--output", "output_dir", default="./output", show_default=True, help="Output directory for markdown files")
@click.option("--cache", "cache_dir", default="./cache", show_default=True, help="Cache directory for JSON files")
@click.option("--workers", default=5, show_default=True, help="Number of concurrent workers")
def search(query: str, max_results: int, output_dir: str, cache_dir: str, workers: int):
    """Search YouTube and summarize matching videos."""
    output_path = Path(output_dir)
    cache_path = Path(cache_dir)

    console.print(f"Searching YouTube for: [bold]{query!r}[/bold] (max {max_results})")
    try:
        videos = search_videos(query, max_results)
    except Exception as e:
        raise click.ClickException(f"Failed to search YouTube: {e}")

    if not videos:
        console.print("No videos found.")
        return

    console.print(f"Found [bold]{len(videos)}[/bold] videos. Processing with {workers} workers...\n")
    processed, stats = process_batch(videos, output_path, cache_path, workers=workers)
    generate_and_write_combined(processed, output_path)

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

    console.print(
        f"\nDone! [green]{stats['done']}[/green] new, "
        f"[dim]{stats['cached']}[/dim] cached, "
        f"[yellow]{stats['skip']}[/yellow] skipped, "
        f"[red]{stats['error']}[/red] errors."
    )
    console.print(f"Output: {output_path.resolve()}")


@cli.command()
@click.option("--cache", "cache_dir", default="./cache", show_default=True, help="Cache directory")
@click.option("--limit", default=20, show_default=True, help="Number of recent runs to show")
def history(cache_dir: str, limit: int):
    """Show history of past runs."""
    cache_path = Path(cache_dir)
    records = history_module.load_history(cache_path)

    if not records:
        console.print("[dim]No history found.[/dim]")
        return

    recent = records[-limit:][::-1]  # most recent first

    table = Table(title=f"Run History (last {len(recent)})", show_lines=True)
    table.add_column("Timestamp", style="dim", no_wrap=True)
    table.add_column("Cmd", style="cyan", width=7)
    table.add_column("Input")
    table.add_column("Found", justify="right")
    table.add_column("New", justify="right", style="green")
    table.add_column("Cached", justify="right", style="dim")
    table.add_column("Failed", justify="right", style="red")
    table.add_column("Output", style="dim")

    for r in recent:
        ts = r.timestamp[:16].replace("T", " ")
        table.add_row(
            ts,
            r.command,
            r.input,
            str(r.videos_found),
            str(r.videos_processed),
            str(r.videos_from_cache),
            str(r.videos_failed),
            r.output_dir,
        )

    console.print(table)


if __name__ == "__main__":
    cli()
