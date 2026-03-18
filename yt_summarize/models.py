from dataclasses import dataclass, field
from typing import Optional

@dataclass
class VideoMetadata:
    video_id: str
    title: str
    url: str
    channel: str = ""
    duration: int = 0  # seconds
    upload_date: str = ""
    description: str = ""

@dataclass
class TranscriptSegment:
    text: str
    start: float
    duration: float

@dataclass
class SummaryResult:
    short: str
    long: str

@dataclass
class CachedVideo:
    metadata: VideoMetadata
    transcript: list[TranscriptSegment]
    transcript_source: str  # "youtube-transcript-api", "yt-dlp", or "none"
    summary: Optional[SummaryResult] = None
