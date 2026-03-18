import re
from pathlib import Path

from .models import CachedVideo
from .transcript import segments_to_text


def _safe_filename(title: str, max_len: int = 60) -> str:
    """Convert a title to a safe filename component."""
    safe = re.sub(r'[^\w\s-]', '', title)
    safe = re.sub(r'[\s]+', '_', safe.strip())
    return safe[:max_len]


def write_video_file(output_dir: Path, cached: CachedVideo) -> Path:
    """Write a per-video markdown file. Returns the path written."""
    output_dir.mkdir(parents=True, exist_ok=True)

    meta = cached.metadata
    summary = cached.summary

    safe_title = _safe_filename(meta.title)
    filename = f"{safe_title}_{meta.video_id}.md"
    path = output_dir / filename

    # Format duration
    duration_str = ""
    if meta.duration:
        m, s = divmod(meta.duration, 60)
        h, m = divmod(m, 60)
        if h:
            duration_str = f"{h}h {m}m {s}s"
        else:
            duration_str = f"{m}m {s}s"

    # Format upload date
    upload_str = meta.upload_date
    if upload_str and len(upload_str) == 8:
        upload_str = f"{upload_str[:4]}-{upload_str[4:6]}-{upload_str[6:]}"

    lines = [
        f"# {meta.title}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| **Video ID** | `{meta.video_id}` |",
        f"| **URL** | {meta.url} |",
        f"| **Channel** | {meta.channel} |",
        f"| **Duration** | {duration_str} |",
        f"| **Upload Date** | {upload_str} |",
        f"| **Transcript Source** | {cached.transcript_source} |",
        "",
    ]

    if summary:
        lines += [
            "## Short Summary",
            "",
            summary.short,
            "",
            "---",
            "",
            summary.long,
            "",
            "---",
            "",
        ]

    # Transcript in collapsible block
    transcript_text = segments_to_text(cached.transcript)
    if transcript_text:
        lines += [
            "<details>",
            "<summary>Full Transcript</summary>",
            "",
            transcript_text,
            "",
            "</details>",
            "",
        ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_combined_file(output_dir: Path, combined_summary: str, video_titles: list[str]) -> Path:
    """Write the combined batch summary file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "_combined_summary.md"

    lines = [
        "# Combined Batch Summary",
        "",
        f"*{len(video_titles)} videos processed*",
        "",
    ]

    if video_titles:
        lines += ["## Videos in This Batch", ""]
        for i, title in enumerate(video_titles, 1):
            lines.append(f"{i}. {title}")
        lines += ["", "---", ""]

    lines.append(combined_summary)
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
