"""
pack_assembly.py — Assembles StudyPack records from the warm video pool.

Strategy:
  1. Check DB for existing StudyPacks on this exact topic_slug — return them
     immediately if fresh (created within 7 days). Cache hit.
  2. Otherwise build the candidate pool:
       a. PRIMARY   — VideoLesson records whose topic_slug shares the first
                      keyword with the new slug (slug-proximity reuse, Option B)
       b. FALLBACK  — VideoLesson records whose academic_category matches the
                      detected subject of the search (Option A), used only if
                      the primary pool has fewer than MIN_POOL_SIZE candidates
  3. Merge the candidate pool with the freshly scraped videos (deduped by
     youtube_id, fresh scrape takes priority to keep results current).
  4. Run the merged pool through build_learning_path() to score and sequence.
  5. Split the ordered path into packs of PACK_SIZE videos (default 6).
  6. Persist each pack as a StudyPack + StudyPackVideo rows. Skip any pack
     whose title already exists for this topic_slug (idempotent).
  7. Return serialized pack dicts ready for the JSON response.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import db
from app.models import StudyPack, StudyPackVideo, VideoLesson
from app.services.learning_path_builder import build_learning_path

PACK_SIZE     = 6    # videos per pack
MIN_POOL_SIZE = 12   # minimum candidates before falling back to subject-level pool
CACHE_DAYS    = 7    # days before a pack is considered stale and rebuilt


def _first_keyword(slug: str) -> str:
    """Return the first hyphen-separated word of a topic slug.
    
    'calculus-limits' → 'calculus'
    'nuclear-chemistry-part-2' → 'nuclear'
    """
    return slug.split('-')[0] if slug else ''


def _slug_proximity_pool(topic_slug: str, exclude_ids: set[str]) -> list[VideoLesson]:
    """
    PRIMARY pool: VideoLesson records whose topic_slug starts with the same
    first keyword as the current search slug.
    
    Example: searching 'calculus-derivatives' pulls in all records whose
    topic_slug starts with 'calculus' — including 'calculus-limits',
    'calculus-integrals', etc.
    
    Excludes youtube_ids already in exclude_ids (the fresh scrape results).
    """
    keyword = _first_keyword(topic_slug)
    if not keyword:
        return []
    return (
        VideoLesson.query
        .filter(
            VideoLesson.topic_slug.ilike(f'{keyword}%'),
            VideoLesson.topic_slug != topic_slug,  # exclude exact match — those come from fresh scrape
            ~VideoLesson.youtube_id.in_(exclude_ids) if exclude_ids else db.true(),
        )
        .order_by(VideoLesson.order_index.asc(), VideoLesson.created_at.desc())
        .limit(30)
        .all()
    )


def _subject_pool(academic_category: str, exclude_ids: set[str]) -> list[VideoLesson]:
    """
    FALLBACK pool: VideoLesson records whose academic_category matches the
    detected subject. Broader than slug proximity but still relevant.
    
    Only called when the proximity pool is smaller than MIN_POOL_SIZE.
    """
    if not academic_category or academic_category in ('General', 'Pending AI', 'Pending', ''):
        return []
    return (
        VideoLesson.query
        .filter(
            VideoLesson.academic_category == academic_category,
            ~VideoLesson.youtube_id.in_(exclude_ids) if exclude_ids else db.true(),
        )
        .order_by(VideoLesson.order_index.asc(), VideoLesson.created_at.desc())
        .limit(30)
        .all()
    )


def _db_video_to_dict(vl: VideoLesson) -> dict:
    """Convert a VideoLesson ORM record to the same dict shape the scraper returns."""
    return {
        'video_id':       vl.youtube_id,
        'title':          vl.title,
        'thumbnail':      vl.thumbnail or f'https://img.youtube.com/vi/{vl.youtube_id}/hqdefault.jpg',
        'channel':        vl.channel_name or '',
        'subject':        vl.academic_category or '',
        'academic_category': vl.academic_category or '',
        'difficulty':     vl.content_difficulty or '',
        'order_index':    vl.order_index or 0,
        'db_id':          vl.id,
    }


def _existing_packs_fresh(topic_slug: str) -> list[StudyPack]:
    """Return existing StudyPacks for this slug if they are still fresh."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=CACHE_DAYS)
    return (
        StudyPack.query
        .filter(
            StudyPack.topic_slug == topic_slug,
            StudyPack.created_at >= cutoff,
        )
        .order_by(StudyPack.id.asc())
        .all()
    )


def _serialize_pack(pack: StudyPack, existing_map: dict) -> dict:
    """
    Serialize a StudyPack ORM object to a dict the front-end can consume.
    Reuses the same video dict shape as search_videos_api returns.
    """
    videos = []
    for spv in pack.videos:  # already ordered by order_index via relationship
        vl = spv.video
        if not vl:
            continue
        videos.append({
            'video_id':    vl.youtube_id,
            'youtube_id':  vl.youtube_id, # Compatibility
            'title':       vl.title,
            'thumbnail':   vl.thumbnail or f'https://img.youtube.com/vi/{vl.youtube_id}/hqdefault.jpg',
            'channel':     vl.channel_name or '',
            'subject':     vl.academic_category or '',
            'academic_category': vl.academic_category or '',
            'difficulty':  spv.stage or vl.content_difficulty or 'Foundation',
            'stage':       spv.stage or '',
            'order_index': spv.order_index,
            'db_id':       vl.id,
        })
    return {
        'pack_id':     pack.id,
        'title':       pack.title,
        'topic_slug':  pack.topic_slug,
        'share_token': pack.share_token,
        'video_count': len(videos),
        'first_video_youtube_id': videos[0]['youtube_id'] if videos else None,
        'videos':      videos,
        'source':      pack.source,
    }


def assemble_packs(
    topic_slug: str,
    fresh_videos: list[dict],
    academic_category: str = '',
    subject_id: Optional[int] = None,
    created_by: Optional[int] = None,
    existing_map: Optional[dict] = None,
) -> list[dict]:
    """
    Main entry point. Called from search_videos_api after scraping.

    Args:
        topic_slug:        Normalised slug of the search query e.g. 'calculus-limits'
        fresh_videos:      Flat list of video dicts from the scraper + build_learning_path
        academic_category: Detected subject string e.g. 'Calculus' — used for fallback pool
        subject_id:        Subject FK to attach to new StudyPack rows
        created_by:        User ID (None = system-generated)
        existing_map:      Dict of {youtube_id: VideoLesson} already built in routes.py

    Returns:
        List of serialized pack dicts — one dict per StudyPack.
    """
    if existing_map is None:
        existing_map = {}

    # ── Step 1: Return cached packs if still fresh ───────────────────────────
    cached = _existing_packs_fresh(topic_slug)
    if cached:
        return [_serialize_pack(p, existing_map) for p in cached]

    # ── Step 2: Build candidate pool ─────────────────────────────────────────
    fresh_ids = {v['video_id'] for v in fresh_videos}

    # Option B — slug proximity
    proximity_pool = _slug_proximity_pool(topic_slug, fresh_ids)

    # Option A — subject fallback if proximity pool is thin
    if len(proximity_pool) < MIN_POOL_SIZE:
        subject_pool = _subject_pool(academic_category, fresh_ids | {vl.youtube_id for vl in proximity_pool})
        db_candidates = proximity_pool + subject_pool
    else:
        db_candidates = proximity_pool

    # Convert DB records to dicts
    db_candidate_dicts = [_db_video_to_dict(vl) for vl in db_candidates]

    # ── Step 3: Merge fresh scrape + warm pool, dedup by youtube_id ──────────
    # Fresh scrape results take priority (appear first, so dedup keeps them)
    seen_ids: set[str] = set()
    merged: list[dict] = []
    for v in fresh_videos + db_candidate_dicts:
        vid = v.get('video_id') or v.get('youtube_id')
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            merged.append(v)

    if not merged:
        return []

    # ── Step 4: Score and sequence the full merged pool ───────────────────────
    # Use a higher total_cap so we have enough videos to build multiple packs
    ordered = build_learning_path(
        merged,
        max_per_level=max(6, len(merged) // 3),
        total_cap=min(len(merged), PACK_SIZE * 4),  # up to 4 packs worth
    )

    if not ordered:
        return []

    # ── Step 5: Split into packs of PACK_SIZE ────────────────────────────────
    pack_slices = [ordered[i:i + PACK_SIZE] for i in range(0, len(ordered), PACK_SIZE)]
    # Drop the last slice if it has fewer than 2 videos — too thin to be useful
    if len(pack_slices) > 1 and len(pack_slices[-1]) < 2:
        pack_slices = pack_slices[:-1]

    # ── Step 6: Persist packs to DB ──────────────────────────────────────────
    # Fetch existing pack titles for this slug to stay idempotent
    existing_titles = {
        p.title for p in StudyPack.query.filter_by(topic_slug=topic_slug).all()
    }

    result_packs: list[dict] = []
    for pack_num, slice_videos in enumerate(pack_slices, start=1):
        # Generate a human-readable title
        # Use the academic_category as the subject label, fall back to slug
        subject_label = academic_category if academic_category and academic_category not in (
            'General', 'Pending AI', 'Pending', ''
        ) else topic_slug.replace('-', ' ').title()

        title = f"{subject_label} — Pack {pack_num}" if len(pack_slices) > 1 else subject_label

        # Skip if this exact title already exists for this slug
        if title in existing_titles:
            # Try to return the existing pack instead
            existing_pack = StudyPack.query.filter_by(
                topic_slug=topic_slug, title=title
            ).first()
            if existing_pack:
                result_packs.append(_serialize_pack(existing_pack, existing_map))
            continue

        # Create the StudyPack row
        new_pack = StudyPack(
            title=title,
            topic_slug=topic_slug,
            subject_id=subject_id,
            created_by=created_by,
            is_curated=False,
            share_token=StudyPack.generate_share_token(),
            source='search',
        )
        db.session.add(new_pack)

        try:
            db.session.flush()  # get new_pack.id without committing
        except Exception:
            db.session.rollback()
            continue

        # Create StudyPackVideo join rows
        for video_dict in slice_videos:
            yid = video_dict.get('video_id') or video_dict.get('youtube_id')
            vl = existing_map.get(yid)
            if not vl:
                # Look up from DB directly — may have been saved in the same request
                vl = VideoLesson.query.filter_by(youtube_id=yid).first()
            if not vl:
                continue  # skip if we can't resolve the DB record

            spv = StudyPackVideo(
                pack_id=new_pack.id,
                video_id=vl.id,
                order_index=video_dict.get('order_index', 1),
                stage=video_dict.get('stage') or video_dict.get('difficulty') or 'Foundation',
            )
            db.session.add(spv)

        try:
            db.session.commit()
            result_packs.append(_serialize_pack(new_pack, existing_map))
            existing_titles.add(title)
        except Exception:
            db.session.rollback()

    return result_packs
