import os
import requests
from flask import current_app
from app import db
from app.models import VideoLesson

def fetch_youtube_stats(youtube_id, api_key=None):
    """
    Fetch YouTube statistics (views, likes) for a given video ID.
    """
    if not api_key:
        api_key = current_app.config.get('YOUTUBE_API_KEY') or os.environ.get('YOUTUBE_API_KEY')
    url = (
        f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={youtube_id}&key={api_key}"
    )
    resp = requests.get(url)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if 'items' in data and data['items']:
        stats = data['items'][0]['statistics']
        return {
            'views': int(stats.get('viewCount', 0)),
            'likes': int(stats.get('likeCount', 0)),
        }
    return None

def update_all_video_stats():
    """
    Update all VideoLesson rows with the latest YouTube stats.
    """
    api_key = current_app.config.get('YOUTUBE_API_KEY') or os.environ.get('YOUTUBE_API_KEY')
    videos = VideoLesson.query.all()
    for video in videos:
        stats = fetch_youtube_stats(video.youtube_id, api_key)
        if stats:
            video.youtube_views = stats['views']
            video.youtube_likes = stats['likes']
    db.session.commit()
    print(f"Updated stats for {len(videos)} videos.")
