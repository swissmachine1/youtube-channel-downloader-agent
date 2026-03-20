import time
import anthropic

from .config import get_api_key, MODEL, MAX_TOKENS_SHORT, MAX_TOKENS_LONG, MAX_TOKENS_COMBINED
from .models import VideoMetadata, SummaryResult

_client: anthropic.Anthropic | None = None


def _get_client(api_key: str | None = None) -> anthropic.Anthropic:
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=get_api_key())
    return _client


def _call_with_retry(system: str, user: str, max_tokens: int, api_key: str | None = None) -> str:
    """Call Claude API with exponential backoff on rate limit / connection errors."""
    client = _get_client(api_key)
    max_attempts = 5
    delay = 2.0
    for attempt in range(max_attempts):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return response.content[0].text
        except anthropic.RateLimitError as e:
            if attempt == max_attempts - 1:
                raise
            wait = min(delay * (2 ** attempt), 60.0)
            print(f"  [rate limit] waiting {wait:.0f}s before retry {attempt + 2}/{max_attempts}...")
            time.sleep(wait)
        except anthropic.APIConnectionError as e:
            if attempt == max_attempts - 1:
                raise
            wait = min(delay * (2 ** attempt), 60.0)
            print(f"  [connection error] waiting {wait:.0f}s before retry {attempt + 2}/{max_attempts}...")
            time.sleep(wait)
        except anthropic.APIStatusError as e:
            # Non-retryable 4xx errors
            raise
    raise RuntimeError("Max retry attempts exceeded")


SHORT_SYSTEM = """You are a concise video summarizer. Write a 2-3 sentence summary of the video transcript provided.
Use plain prose, no bullet points. Capture the core message and main takeaways."""

LONG_SYSTEM = """You are an expert video content analyst. Create a structured summary of the video transcript in markdown format.

Use this structure:
## Key Points
(bullet list of the most important points from the video)"""

COMBINED_SYSTEM = """You are synthesizing summaries from multiple YouTube videos into a cohesive batch summary.

Use this structure:
## Batch Overview
(2-3 sentence overview of the entire batch of videos)

## Common Themes
(themes that appear across multiple videos)

## Key Insights
(the most valuable insights from the entire batch)

## Contrasting Viewpoints
(if applicable, note where videos disagree or present different perspectives)"""


def summarize_video(title: str, transcript_text: str, api_key: str | None = None) -> SummaryResult:
    """Generate short and long summaries for a single video."""
    user_message = f"Video title: {title}\n\nTranscript:\n{transcript_text[:50000]}"

    short = _call_with_retry(SHORT_SYSTEM, user_message, MAX_TOKENS_SHORT, api_key)
    long = _call_with_retry(LONG_SYSTEM, user_message, MAX_TOKENS_LONG, api_key)

    return SummaryResult(short=short, long=long)


def generate_combined_summary(videos: list[tuple[str, str]], api_key: str | None = None) -> str:
    """
    Generate a combined summary across all videos.
    videos: list of (title, short_summary) tuples
    """
    parts = []
    for i, (title, short) in enumerate(videos, 1):
        parts.append(f"**Video {i}: {title}**\n{short}")

    user_message = "Here are short summaries of the videos in this batch:\n\n" + "\n\n".join(parts)
    return _call_with_retry(COMBINED_SYSTEM, user_message, MAX_TOKENS_COMBINED, api_key)
