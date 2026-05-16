"""
Utilities for YouTube video lessons:
- Extract YouTube ID from any YouTube URL
- Fetch oEmbed metadata (title, thumbnail) — no API key needed
- Uses Redis caching to reduce requests
"""

import re
import urllib.parse
import urllib.request
import json
from flask import current_app


# ── ID extraction ─────────────────────────────────────────────────────────────

_YT_PATTERNS = [
    r'(?:v=|v/)([A-Za-z0-9_-]{11})',          # ?v=ID or /v/ID
    r'youtu\.be/([A-Za-z0-9_-]{11})',          # youtu.be/ID
    r'embed/([A-Za-z0-9_-]{11})',              # /embed/ID
    r'shorts/([A-Za-z0-9_-]{11})',             # /shorts/ID
]


def extract_youtube_id(url: str) -> str | None:
    """
    Extract the 11-character YouTube video ID from any YouTube URL.
    Returns None if no valid ID found.

    Handles:
      https://www.youtube.com/watch?v=dQw4w9WgXcQ
      https://youtu.be/dQw4w9WgXcQ
      https://www.youtube.com/embed/dQw4w9WgXcQ
      https://www.youtube.com/shorts/dQw4w9WgXcQ
      https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s
    """
    if not url:
        return None
    url = url.strip()
    for pattern in _YT_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# ── oEmbed metadata with caching ───────────────────────────────────────────

_OEMBED_URL = 'https://www.youtube.com/oembed?url={}&format=json'

# Cache oEmbed results for 24 hours
OEMBED_CACHE_TTL = 86400


def _get_redis():
    """Get Redis client if available."""
    return current_app.extensions.get('redis')


def fetch_oembed(youtube_id: str) -> dict:
    """
    Fetch title and thumbnail from YouTube's oEmbed endpoint.
    No API key required. Returns a dict with keys:
      title, thumbnail_url, author_name
    Returns empty dict on any error.
    Uses Redis caching to reduce oEmbed calls.
    """
    if not youtube_id:
        return {}

    video_url = f'https://www.youtube.com/watch?v={youtube_id}'
    api_url = _OEMBED_URL.format(urllib.parse.quote(video_url))

    # Try cache first
    redis_client = _get_redis()
    if redis_client:
        cache_key = f"oembed:{youtube_id}"
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    try:
        req = urllib.request.Request(api_url, headers={'User-Agent': 'knowly/1.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        result = {
            'title':         data.get('title', ''),
            'thumbnail_url': data.get('thumbnail_url', ''),
            'author_name':   data.get('author_name', ''),
        }
        
        # Cache the result
        if redis_client:
            try:
                cache_key = f"oembed:{youtube_id}"
                redis_client.setex(cache_key, OEMBED_CACHE_TTL, json.dumps(result))
            except Exception:
                pass
        
        return result
    except Exception:
        return {}


def get_video_meta(url: str) -> dict:
    """
    One-shot helper: takes a YouTube URL, returns:
      { youtube_id, title, thumbnail_url, author_name }
    or None if the URL is invalid.
    """
    youtube_id = extract_youtube_id(url)
    if not youtube_id:
        return None

    meta = fetch_oembed(youtube_id)
    meta['youtube_id'] = youtube_id
    return meta