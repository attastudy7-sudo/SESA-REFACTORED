"""
LearningPathBuilder — arranges scraped YouTube videos into a logical
learning progression for any topic. No API key needed.

Plugs into the existing search_videos pipeline in routes.py.
"""

import re
from typing import Optional

# ── Quality signals extractable from title + channel alone ──────────────────

BEGINNER_SIGNALS = [
    'introduction', 'intro', 'basics', 'beginner', 'fundamentals',
    'what is', 'overview', 'explained', 'for beginners', 'getting started',
    'start here', 'part 1', 'episode 1', '101', 'simple', 'easy',
    'made easy', 'in 5 minutes', 'in 10 minutes', 'crash course',
    'quick guide', 'first look', 'from scratch',
]

INTERMEDIATE_SIGNALS = [
    'examples', 'practice', 'problems', 'walkthrough', 'step by step',
    'how to', 'proof', 'solving', 'tutorial', 'part 2', 'part 3',
    'deeper', 'continue', 'more', 'next', 'applying', 'using',
    'worksheet', 'exercises',
]

ADVANCED_SIGNALS = [
    'advanced', 'expert', 'master', 'deep dive', 'in depth', 'rigorous',
    'proof by', 'strong induction', 'formal', 'theorem', 'generalization',
    'extension', 'complex', 'hard problems', 'olympiad', 'competition',
    'university level', 'graduate',
]

# Channels with known quality — bonus score
HIGH_QUALITY_CHANNELS = {
    '3blue1brown', '3b1b', 'khan academy', 'mit opencourseware', 'mit',
    'numberphile', 'veritasium', 'ted-ed', 'teded', 'crashcourse',
    'crash course', 'professor leonard', 'patrickjmt', 'the organic chemistry tutor',
    'organic chemistry tutor', 'trefor bazett', 'dr trefor', 'blackpenredpen',
    'freecodecamp', 'free code camp', 'neso academy', 'computerphile',
    'kurzgesagt', 'scishow', 'bozeman science', 'trevtutor',
    'sentdex', 'corey schafer', 'traversy media', 'web dev simplified',
    'medcram', 'osmosis', 'ninja nerd', 'armando hasudungan',
}

# Signals that suggest lower quality or irrelevance
PENALTY_SIGNALS = [
    'reaction', 'compilation', 'shorts', '#shorts', 'tiktok',
    'unboxing', 'vlog', 'storytime', 'my experience',
    'i failed', 'watch me', 'live stream', 'live session',
]


def _classify_difficulty(title: str, channel: str) -> str:
    """
    Classify a video as Beginner / Intermediate / Advanced
    based on title + channel keywords. Returns 'Intermediate' as default.
    """
    combined = f"{title} {channel}".lower()

    # Score each level
    scores = {'Beginner': 0, 'Intermediate': 0, 'Advanced': 0}

    for sig in BEGINNER_SIGNALS:
        if sig in combined:
            scores['Beginner'] += 1

    for sig in INTERMEDIATE_SIGNALS:
        if sig in combined:
            scores['Intermediate'] += 1

    for sig in ADVANCED_SIGNALS:
        if sig in combined:
            scores['Advanced'] += 1

    # Return the highest scoring level; Intermediate is the tiebreak default
    max_score = max(scores.values())
    if max_score == 0:
        return 'Intermediate'

    # Priority order when tied: Beginner > Intermediate > Advanced
    for level in ['Beginner', 'Intermediate', 'Advanced']:
        if scores[level] == max_score:
            return level

    return 'Intermediate'


def _quality_score(title: str, channel: str) -> float:
    """
    Score a video 0.0–1.0 based on extractable quality signals.
    Higher = better quality / more likely to be useful.
    """
    score = 0.5  # Neutral baseline
    title_lower = title.lower()
    channel_lower = channel.lower()

    # Channel quality bonus (biggest signal)
    for known in HIGH_QUALITY_CHANNELS:
        if known in channel_lower:
            score += 0.3
            break

    # Penalty signals
    for bad in PENALTY_SIGNALS:
        if bad in title_lower:
            score -= 0.4
            break

    # Academic structure signals (good)
    if re.search(r'\b(lecture|lesson|part\s*\d+|chapter|module)\b', title_lower):
        score += 0.1
    if re.search(r'\b(explained|tutorial|guide|course)\b', title_lower):
        score += 0.05
    if re.search(r'\b(proof|theorem|derivation|formula)\b', title_lower):
        score += 0.05

    # Title length heuristic — very short titles are often clickbait
    if len(title) < 15:
        score -= 0.1
    elif len(title) > 20:
        score += 0.05

    return max(0.0, min(1.0, score))


def build_learning_path(
    videos: list[dict],
    max_per_level: int = 3,
    total_cap: int = 9,
) -> list[dict]:
    """
    Takes a flat list of raw scraped video dicts and returns them
    arranged as a logical learning path:
        [Beginner × n] → [Intermediate × n] → [Advanced × n]

    Each video gets:
        - 'difficulty'   : 'Beginner' | 'Intermediate' | 'Advanced'
        - 'quality_score': float 0–1
        - 'order_index'  : int (1-based position in the path)
        - 'stage'        : 'Foundation' | 'Practice' | 'Mastery'

    Args:
        videos:        Raw list from search_videos() / scraper
        max_per_level: Max videos to include per difficulty level
        total_cap:     Hard cap on total videos returned

    Returns:
        Ordered list of video dicts ready to display or persist.
    """
    if not videos:
        return []

    # ── Step 1: Score and classify every video ──────────────────────────────
    scored = []
    for v in videos:
        title   = v.get('title', '')
        channel = v.get('channel', '')
        difficulty    = _classify_difficulty(title, channel)
        quality       = _quality_score(title, channel)
        scored.append({**v, 'difficulty': difficulty, 'quality_score': quality})

    # ── Step 2: Bucket by difficulty, sort each bucket by quality desc ───────
    buckets = {'Beginner': [], 'Intermediate': [], 'Advanced': []}
    for v in scored:
        buckets[v['difficulty']].append(v)

    for level in buckets:
        buckets[level].sort(key=lambda x: x['quality_score'], reverse=True)

    # ── Step 3: Pick the best from each bucket ───────────────────────────────
    # If a bucket is empty, pull from the next closest level
    def _pick(bucket_list, n):
        return bucket_list[:n]

    beginners     = _pick(buckets['Beginner'],     max_per_level)
    intermediates = _pick(buckets['Intermediate'], max_per_level)
    advanced      = _pick(buckets['Advanced'],     max_per_level)

    # Fallback: if beginner bucket is empty, use top intermediates as foundation
    if not beginners and intermediates:
        beginners = [intermediates.pop(0)]

    # ── Step 4: Assemble the path and assign order_index + stage ────────────
    stage_map = {
        'Beginner':     'Foundation',
        'Intermediate': 'Practice',
        'Advanced':     'Mastery',
    }

    path = []
    for level_videos in [beginners, intermediates, advanced]:
        for v in level_videos:
            v['stage'] = stage_map[v['difficulty']]
            path.append(v)

    # Assign 1-based order_index
    for i, v in enumerate(path):
        v['order_index'] = i + 1

    return path[:total_cap]


def apply_path_to_db_videos(path: list[dict], existing_map: dict) -> None:
    """
    Persist order_index and content_difficulty back to VideoLesson DB records.
    Call this after build_learning_path() when you have existing DB records.

    Args:
        path:         Output of build_learning_path()
        existing_map: Dict of {youtube_id: VideoLesson} from your existing query
    """
    from app import db
    for v in path:
        yid = v.get('video_id') or v.get('youtube_id')
        db_video = existing_map.get(yid)
        if db_video:
            db_video.order_index        = v['order_index']
            db_video.content_difficulty = v['difficulty']
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()