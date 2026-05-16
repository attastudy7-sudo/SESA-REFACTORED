import requests
from flask import current_app

def fetch_youtube_stats(youtube_id):
    """
    Fetches viewCount, likeCount, commentCount for a YouTube video using the YouTube Data API v3.
    Returns a dict with those keys, or None on error.
    """
    api_key = current_app.config.get('YOUTUBE_API_KEY')
    if not api_key:
        return None
    url = (
        f'https://www.googleapis.com/youtube/v3/videos?part=statistics&id={youtube_id}&key={api_key}'
    )
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        items = data.get('items', [])
        if not items:
            return None
        stats = items[0].get('statistics', {})
        return {
            'viewCount': int(stats.get('viewCount', 0)),
            'likeCount': int(stats.get('likeCount', 0)),
            'commentCount': int(stats.get('commentCount', 0)),
        }
    except Exception:
        return None
