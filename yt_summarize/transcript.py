import re
import tempfile
import shutil
from pathlib import Path

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

from .models import TranscriptSegment


def fetch_transcript(video_id: str) -> tuple[list[TranscriptSegment], str]:
    """
    Fetch transcript for a video.
    Returns (segments, source_label).
    source_label is one of: "youtube-transcript-api", "yt-dlp", "none"
    """
    # Layer 1: youtube-transcript-api
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # Prefer manual captions, fall back to auto-generated
        transcript = None
        try:
            transcript = transcript_list.find_manually_created_transcript(
                transcript_list._manually_created_transcripts.keys()
                if transcript_list._manually_created_transcripts
                else ["en"]
            )
        except Exception:
            pass
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(
                    transcript_list._generated_transcripts.keys()
                    if transcript_list._generated_transcripts
                    else ["en"]
                )
            except Exception:
                pass
        if transcript is None:
            # Just get the first available
            for t in transcript_list:
                transcript = t
                break
        if transcript is not None:
            data = transcript.fetch()
            segments = []
            for item in data:
                # Handle both dict and FetchedTranscriptSnippet objects
                if hasattr(item, 'text'):
                    text = item.text
                    start = item.start
                    duration = item.duration
                else:
                    text = item.get("text", "")
                    start = item.get("start", 0.0)
                    duration = item.get("duration", 0.0)
                segments.append(TranscriptSegment(
                    text=text,
                    start=start,
                    duration=duration,
                ))
            if segments:
                return segments, "youtube-transcript-api"
    except (NoTranscriptFound, TranscriptsDisabled):
        pass
    except Exception:
        pass

    # Layer 2: yt-dlp subtitle download
    tmpdir = tempfile.mkdtemp()
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en"],
            "skip_download": True,
            "outtmpl": str(Path(tmpdir) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Find any .vtt file
        vtt_files = list(Path(tmpdir).glob("*.vtt"))
        if vtt_files:
            segments = _parse_vtt(vtt_files[0])
            if segments:
                return segments, "yt-dlp"
    except Exception:
        pass
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return [], "none"


def _parse_vtt(path: Path) -> list[TranscriptSegment]:
    """Parse a WebVTT subtitle file into TranscriptSegment list."""
    content = path.read_text(encoding="utf-8", errors="replace")
    segments = []
    # Match timestamp lines and associated text
    pattern = re.compile(
        r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})[^\n]*\n((?:(?!\d{2}:\d{2}:\d{2}).+\n?)*)",
        re.MULTILINE,
    )
    for match in pattern.finditer(content):
        start_str, end_str, text_block = match.groups()
        text = re.sub(r"<[^>]+>", "", text_block).strip()
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&nbsp;", " ", text)
        if not text:
            continue
        start = _vtt_time_to_seconds(start_str)
        end = _vtt_time_to_seconds(end_str)
        segments.append(TranscriptSegment(text=text, start=start, duration=end - start))
    return segments


def _vtt_time_to_seconds(time_str: str) -> float:
    """Convert VTT timestamp (HH:MM:SS.mmm) to seconds."""
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def segments_to_text(segments: list[TranscriptSegment]) -> str:
    """Join transcript segments into plain text."""
    return " ".join(seg.text for seg in segments)
