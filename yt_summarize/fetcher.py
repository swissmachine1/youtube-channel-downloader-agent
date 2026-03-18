import yt_dlp
from .models import VideoMetadata


def _extract_videos_from_info(info: dict, max_results: int, channel_name: str = "") -> list[VideoMetadata]:
    """Recursively extract individual videos from yt-dlp info dict."""
    videos = []
    entries = info.get("entries", [])

    for entry in entries:
        if entry is None or len(videos) >= max_results:
            break
        # If entry is a nested playlist/tab, recurse into it
        if entry.get("_type") in ("playlist", "url") and not entry.get("ie_key", "").lower().startswith("youtube") or entry.get("entries"):
            videos.extend(_extract_videos_from_info(entry, max_results - len(videos), channel_name))
            continue
        video_id = entry.get("id", "")
        title = entry.get("title", "")
        # Skip non-video entries (tabs, playlists named "Videos"/"Live"/etc.)
        if not video_id or not title:
            continue
        if len(video_id) != 11:
            continue
        videos.append(VideoMetadata(
            video_id=video_id,
            title=title,
            url=f"https://www.youtube.com/watch?v={video_id}",
            channel=entry.get("channel", channel_name),
            duration=entry.get("duration", 0) or 0,
            upload_date=entry.get("upload_date", ""),
            description=entry.get("description", ""),
        ))

    return videos


def fetch_channel_videos(url: str, max_results: int) -> list[VideoMetadata]:
    """Fetch video metadata from a YouTube channel using yt-dlp."""
    # Append /videos to target the Videos tab directly
    if not url.rstrip("/").endswith("/videos"):
        videos_url = url.rstrip("/") + "/videos"
    else:
        videos_url = url

    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "playlist_items": f"1:{max_results}",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(videos_url, download=False)
        channel_name = info.get("channel", info.get("uploader", ""))
        return _extract_videos_from_info(info, max_results, channel_name)


def search_videos(query: str, max_results: int) -> list[VideoMetadata]:
    """Search YouTube and return video metadata."""
    search_url = f"ytsearch{max_results}:{query}"
    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
    }
    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_url, download=False)
        entries = info.get("entries", [])
        for entry in entries:
            if entry is None:
                continue
            video_id = entry.get("id", "")
            title = entry.get("title", "")
            if not video_id or not title:
                continue
            videos.append(VideoMetadata(
                video_id=video_id,
                title=title,
                url=f"https://www.youtube.com/watch?v={video_id}",
                channel=entry.get("channel", ""),
                duration=entry.get("duration", 0) or 0,
                upload_date=entry.get("upload_date", ""),
                description=entry.get("description", ""),
            ))
    return videos
