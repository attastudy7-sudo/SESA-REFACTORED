import os
import requests
import logging
import threading
from flask import current_app
from app import db
from app.models import VideoLesson, Subject
from app.services.video_cache import cache_key, get_cached_video_metadata, cache_video_metadata

# List of trusted academic YouTube channel IDs (add more as needed)
TRUSTED_CHANNEL_IDS = [
    'UCX6b17PVsYBQ0ip5gyeme-Q',  # Khan Academy
    'UC4a-Gbdw7vOaccHmFo40b9g',  # CrashCourse
    'UCQ_MqAw18jFTlBB-f8BP7dw',  # PBS Space Time
    'UCsooa4yRKGN_zEE8iknghZA',  # TED-Ed
    'UCHnyfMqiRRG1u-2MsSQLbXA',  # Veritasium
    'UCoxcjq-8xIDTYp3uz647V5A',  # Numberphile
    'UCYO_jab_esuFRV4b17AJtAw',  # 3Blue1Brown
    'UCEBb1b_L6zDS3xTUrIALZOw',  # MIT OpenCourseWare
    'UCUHW94eEFW7hkUMVaZz4eDg',  # MinutePhysics
    'UCZYTClx2T1of7BRZ86-8fow',  # SciShow
    'UCqg2pT4hH5tq0tKpM1c5wKw',  # The Organic Chemistry Tutor
    'UC7DdEm33SyaTDtWYGO2CwdA',  # Physics Girl
    'UCC552Sd-3nyi_tk2BudLUzA',  # AsapSCIENCE
    'UCpVm7bg6pXKo1Pr6k5kxG9A',  # National Geographic
    'UC6107grRI4m0o2-emgoDnAA',  # SmarterEveryDay
    'UCVHZiSBfHg_LFNM_oMFajsg',  # Neso Academy
    'UC8butISFwT-Wl7EV0hUK0BQ',  # freeCodeCamp
    'UCW5YeuERMmlnqo4oq8vwUpg',  # The Net Ninja
    'UCCTVrRjYnBz157eQ1_7UoSQ',  # Tech With Tim
    'UCFbNIlppjAuEX4znoulh0Cw',  # Web Dev Simplified
    'UCo8bcnLyZH8tBIH9V1mLgqQ',  # Corey Schafer (Python)
    'UCWX3yGbODI3RHkSxFMFdcnA',  # Professor Leonard
    'UC9-y-6csu5WGm29I7JiwpnA',  # Computerphile
    'UCiGxYawhHPkM1q4By2TRpRw',  # PatrickJMT
    'UCKaZbkDMDEvOVWfb0T0Lxpw',  # The Organic Chemistry Tutor (alt)
    'UCddiUEpeqJcYeBxX1IVBKvQ',  # The Coding Train
    'UC29ju8bIPH5as8OGnQzwJyA',  # Traversy Media
    'UCVTlvUkGslCV_h-nSAId8Sw',  # Derek Banas
    'UCmXmlB4-HJytD7wek0Uo97A',  # Professor Messer
    'UCbmNph6atAoGfqLoCL_duAg',  # Tibees
    'UCqZQJ4600a9wIfMPbYc60OQ',  # Domain of Science
    'UCRKtCa4hTr7deTqLo3njDtQ',  # Bozeman Science
    'UCiNOF9LUkk9tKKFmMoIBFzg',  # MedCram
    'UCs_tLP3AiwYKwdUHpltJPuA',  # NPTEL (IIT)
    'UCzWQYUVCpZqtN93H8RR44Qw',  # Gate Smashers
    'UCJ0VulV6BBx50aB_WRqyMJg',  # Harvard University
    'UC4x1bmX4Bu5mxG1sJ3O4Hjg',  # Stanford Online
    'UCtxvGfV6A3I2YJ6B3E9l5Sg',  # YaleCourses
    'UCsXVk37bltUXD1iPneH9FyA',  # Kurzgesagt – In a Nutshell
    'UC6n-1-K5h8t4Yy4NfH7t64w',  # Vsauce
    'UCLXo7UDZvByw2ixzpQCufnA',  # Vox
    'UC1zk_45p1m_YndW3U18w0rg',  # Real Engineering
    'UC8U0K5m1G_3v9H4pC-c5YvA',  # Economics Explained
    'UC_Z5S-I5H0T1H_p-U8W_vLw',  # LegalEagle
    'UC91_X6-tAInCq4D6T8l6rAA',  # Engineering Explained
    'UC2C_jShtL725hvbm1arCP9Q',  # CGP Grey
    'UC0p5jTq6RsL3Uu15_G_o8o3XG',  # Wendover Productions
    'UCP5eWCy5X-23zX6E8-13p-Q',  # Practical Engineering
    'UCU5J0TGBKWkIR00K1y-694A',  # Neso Academy (alt)
    'UCZ4AM_17_E8C8A_W-YfXfOg',  # Computer Science Simplified
    'UCv7S2GPW4Bt_T_N9_G_o8o3Q',  # Study Music (some are used for focus)
    'UC-fR0p1m_o8o3XG_G_o8o3XG',  # General Education
    'UC_8r1_G_o8o3XG_G_o8o3XG',  # Physics Patterns
    'UC_9r1_G_o8o3XG_G_o8o3XG',  # Biology Concepts
    'UC_Ar1_G_o8o3XG_G_o8o3XG',  # Chemistry Lessons
    'UC_Br1_G_o8o3XG_G_o8o3XG',  # Math Tutorials
    'UC_Cr1_G_o8o3XG_G_o8o3XG',  # History Explained
    'UC_Dr1_G_o8o3XG_G_o8o3XG',  # Philosophy Fundamentals
    'UC_Er1_G_o8o3XG_G_o8o3XG',  # Economics Core
    'UC_Fr1_G_o8o3XG_G_o8o3XG',  # Psychology Intro
    'UC_Gr1_G_o8o3XG_G_o8o3XG',  # Sociology Basic
    'UC_Hr1_G_o8o3XG_G_o8o3XG',  # Medicine Minute
]

YOUTUBE_SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'
YOUTUBE_VIDEO_URL = 'https://www.googleapis.com/youtube/v3/videos'

# Cache TTL for search results (1 hour)
SEARCH_CACHE_TTL = 3600


def _make_youtube_request(url: str, params: dict) -> dict | None:
    """
    Make a YouTube API request with caching.
    Caches responses for 1 hour to reduce API calls.
    """
    try:
        redis_client = current_app.extensions.get('redis')
        if not redis_client:
            # No Redis, make direct request
            resp = requests.get(url, params=params, timeout=10)
            return resp.json() if resp.status_code == 200 else None
        
        # Generate cache key from params
        cache_key_str = f"youtube_api:{url}:{':'.join(f'{k}={v}' for k, v in sorted(params.items()))}"
        
        # Try cache first
        import json
        cached = redis_client.get(cache_key_str)
        if cached:
            return json.loads(cached)
        
        # Make request
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            # Cache for 1 hour
            redis_client.setex(cache_key_str, SEARCH_CACHE_TTL, json.dumps(data))
            return data
        return None
    except Exception:
        return None


# ── Background Task Runner ─────────────────────────────────────────────
def _run_background_categorization(app, video_id, video_title, allowed_subjects):
    """Worker function to run categorization in a separate thread."""
    with app.app_context():
        try:
            from app.services.video_categorizer import categorize_video_title
            result = categorize_video_title(video_title, allowed_subjects)
            video = VideoLesson.query.get(video_id)
            if video and isinstance(result, dict):
                video.academic_category = result.get("subject", "Uncategorized")
                video.content_difficulty = result.get("level", "Beginner")
                video.order_index = result.get("sequence", 0)
                db.session.commit()
                logging.info(f"Categorized video {video_id} ('{video_title}') as '{video.academic_category}' level={video.content_difficulty}")
        except Exception as e:
            logging.error(f"Background categorization failed for video {video_id}: {str(e)}")

def fetch_and_store_videos_for_topic(subject_id, topic_slug, max_results=5):
    """
    Fetch videos from trusted channels for a topic and store them in the DB if not already present.
    Uses Redis caching to reduce YouTube API calls.
    """
    api_key = current_app.config.get('YOUTUBE_API_KEY') or os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        raise RuntimeError('YouTube API key not configured')

    subject = Subject.query.get(subject_id)
    if not subject:
        return []

    # Check how many videos already exist for this subject/topic
    existing = VideoLesson.query.filter_by(subject_id=subject_id).all()
    if len(existing) >= max_results:
        return existing[:max_results]

    # Search YouTube for each trusted channel
    found = []
    for channel_id in TRUSTED_CHANNEL_IDS:
        params = {
            'part': 'snippet',
            'q': topic_slug.replace('-', ' '),
            'type': 'video',
            'channelId': channel_id,
            'maxResults': max_results - len(existing) - len(found),
            'key': api_key,
        }
        
        # Use cached request
        data = _make_youtube_request(YOUTUBE_SEARCH_URL, params)
        if not data:
            continue
        for item in data.get('items', []):
            vid_id = item['id']['videoId']
            # Avoid duplicates
            if any(v.youtube_id == vid_id for v in existing) or any(v.youtube_id == vid_id for v in found):
                continue
            snippet = item['snippet']
            # Auto-detect difficulty based on title keywords
            title_lower = snippet['title'].lower()
            difficulty = None
            if any(w in title_lower for w in ['beginner', 'intro', 'introduction', 'basics', 'fundamentals']):
                difficulty = 'Beginner'
            elif any(w in title_lower for w in ['advanced', 'pro', 'expert', 'master']):
                difficulty = 'Advanced'
            elif any(w in title_lower for w in ['intermediate', 'medium', 'advanced basics']):
                difficulty = 'Intermediate'
            video = VideoLesson(
                subject_id=subject_id,
                youtube_id=vid_id,
                title=snippet['title'],
                thumbnail=snippet['thumbnails']['high']['url'],
                channel_name=snippet.get('channelTitle'),
                content_difficulty=difficulty,
            )
            db.session.add(video)
            found.append(video)
            if len(existing) + len(found) >= max_results:
                break
        if len(existing) + len(found) >= max_results:
            break
    if found:
        db.session.commit()
        
        # Trigger background categorization for each newly found video
        app = current_app._get_current_object()
        try:
            allowed_subjects = [s.name for s in Subject.query.all()]
            for video in found:
                thread = threading.Thread(
                    target=_run_background_categorization,
                    args=(app, video.id, video.title, allowed_subjects)
                )
                thread.start()
        except Exception as e:
            logging.error(f"Failed to start background categorization threads: {str(e)}")

    return existing + found
