from flask import render_template, redirect, url_for, request, flash, jsonify, session, abort
# Default XP reward for home/index page (used in render_template)
XP_REWARD = 10

# Ensure Blueprint and Flask-Login are imported first
from app.models import QuizAttempt
from flask import Blueprint, render_template, request, current_app, redirect, url_for, session, abort, make_response, send_from_directory, jsonify, flash
from flask_login import login_required, current_user
from app import db
from app.utils.turbo import turbo_frame
from app.utils.serializers import format_pack_data, update_pack_progress
from app.models import User, Post, Document, Subject, Like, Comment, Programme, Notification, Bookmark, VideoLesson, VideoCompletion, VideoLike, VideoComment, QuizAssessment, WeakTopic, AuraTransaction, StudyPack, StudyPackVideo
from sqlalchemy.orm import selectinload, joinedload
import random as _random
import re
import json
import math
import types
from datetime import datetime, timedelta, timezone
from sqlalchemy import func as sqlfunc, func
from datetime import date as _date
import random

bp = Blueprint('main', __name__)


def _slugify_topic(text: str) -> str:
    """Normalise a search query into a URL-safe topic slug.

    Example: 'Calculus 1 — Limits & Continuity' → 'calculus-1-limits-continuity'
    """
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s]+', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


# ─────────────────────────────────────────────────────────────────────────────
# REFRESH VIDEOS ENDPOINT (for topnav button)
# ─────────────────────────────────────────────────────────────────────────────
@bp.route('/library/refresh_videos/<slug>')
@login_required
def refresh_videos(slug):
    # TODO: Add logic to actually refresh videos for the subject if needed
    # For now, just redirect to the subject videos page
    return redirect(url_for('main.library_subject', slug=slug))


@bp.route('/api/csrf-token')
def api_csrf_token():
    """Return a fresh CSRF token for JavaScript requests after Turbo navigation."""
    from flask_wtf.csrf import generate_csrf
    return jsonify({'csrf_token': generate_csrf()})

@bp.route('/api/user-stats')
@login_required
def api_user_stats():
    return jsonify({
        "xp": current_user.xp,
        "level": current_user.level if hasattr(current_user, 'level') else 1,
        "username": current_user.username
    })

@bp.route('/api/search-by-image', methods=['POST'])
@login_required
def api_search_by_image():
    """Analyze an uploaded image and return search keywords."""
    if 'image' not in request.files:
        return jsonify({"error": "No image provided"}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    try:
        image_data = file.read()
        mime_type = file.content_type or "image/jpeg"
        
        from app.services.ai_service import analyze_image_for_search
        result = analyze_image_for_search(image_data, mime_type)
        
        if "error" in result:
            return jsonify(result), 500
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.app_context_processor
def inject_user_subject_slug():
    subject_slug = None
    if current_user.is_authenticated and current_user.programme:
        programme_obj = Programme.query.filter_by(name=current_user.programme).first()
        if programme_obj and programme_obj.subjects:
            subject_obj = programme_obj.subjects[0]
            if subject_obj:
                subject_slug = subject_obj.slug
    return dict(user_subject_slug=subject_slug)

@bp.app_context_processor
def inject_onboarding_status():
    show_onboarding = False
    if current_user.is_authenticated and not current_user.onboarding_skipped:
        show_onboarding = True
    return dict(show_onboarding=show_onboarding)


@bp.app_context_processor
def inject_suggestions_status():
    show_suggestions = False
    suggested_users = {'same_school': [], 'same_programme': [], 'random': []}
    
    if current_user.is_authenticated and not session.get('suggestions_shown'):
        if current_user.school or current_user.programme:
            show_suggestions = True
            session['suggestions_shown'] = True
            
            already_following = [u.id for u in current_user.following.all()]
            exclude = already_following + [current_user.id]
            
            if current_user.school:
                suggested_users['same_school'] = User.query.filter(
                    User.school == current_user.school,
                    ~User.id.in_(exclude)
                ).limit(4).all()
            
            if current_user.programme:
                suggested_users['same_programme'] = User.query.filter(
                    User.programme == current_user.programme,
                    ~User.id.in_(exclude)
                ).limit(4).all()
            
            candidates = User.query.filter(
                ~User.id.in_(exclude)
            ).limit(50).all()
            suggested_users['random'] = _random.sample(candidates, min(4, len(candidates)))
    
    return dict(show_suggestions=show_suggestions, suggested_users=suggested_users)

# ─────────────────────────────────────────────────────────────────────────────
# VIDEO PLAYER PAGE
# ─────────────────────────────────────────────────────────────────────────────

# ── Study Room home (empty shell) ──
@bp.route('/study-room')
@turbo_frame('main-content', 'frames/study_room.html', 'library/study_room.html')
def study_room_home():
    """
    Entry point for the Study Room without a specific video or pack.
    Renders the study room shell — ready for future features like
    slide uploads or pasted video links.
    """
    return dict(
        video=None,
        subject=None,
        display_subject='Study Room',
        programme=None,
        completed=False,
        completed_video_ids=set(),
        net_likes=0,
        user_like=None,
        comments=[],
        curriculum_videos=[],
        topic_key=None,
        topic_resources={
            'notes': None,
            'flashcard': None,
            'cheatsheet': None,
            'quiz': None,
        },
        active_pack_resources={},
        has_assessment=False,
        next_url=None,
        resource_status={},
        syllabus_items=[],
        pack_id=None,
    )




@bp.route('/library/video/<int:video_id>', methods=['GET', 'POST'])
def video_player(video_id):
    video = VideoLesson.query.filter_by(id=video_id).first_or_404()
    subject = video.subject
    programme = None
    if subject:
        programme = Programme.query.filter(
            Programme.subjects.any(id=subject.id),
            Programme.is_active == True
        ).first()
    
    # DETERMINE APPROPRIATE CATEGORY/SUBJECT NAME
    display_subject = subject.name if subject else 'Videos'
    is_academic = video.academic_category and video.academic_category not in ['Pending', 'Pending AI', 'General', '']
    if is_academic:
        display_subject = video.academic_category

    completed = False
    user_like = None
    if current_user.is_authenticated:
        user_like = video.likes.filter_by(user_id=current_user.id).first()
        if request.method == 'POST' and 'complete' in request.form:
            existing = VideoCompletion.query.filter_by(user_id=current_user.id, video_id=video.id).first()
            if not existing:
                vc = VideoCompletion(user_id=current_user.id, video_id=video.id, xp_earned=video.xp_reward)
                db.session.add(vc)
                current_user.add_xp(video.xp_reward, apply_streak_multiplier=True, reason=f'Video: {video.title[:50]}')
                db.session.commit()
                # Update cached pack progress
                update_pack_progress(current_user.id, video.id)
            flash(f'Lesson completed! +{video.xp_reward} Aura earned.', 'success')
            return redirect(url_for('main.video_player', video_id=video.id))
        else:
            completed = VideoCompletion.query.filter_by(user_id=current_user.id, video_id=video.id).first() is not None
    net_likes = video.likes.with_entities(db.func.sum(VideoLike.value)).scalar() or 0

    comments = video.comments.order_by(VideoComment.created_at.desc()).all()
    
    # FETCH ALL VIDEOS IN THIS CURRICULUM/SUBJECT (Stable List)
    # Primary: scope by topic_slug so the playlist only contains videos from
    # the same search topic, not every video ever saved under the same subject.
    if video.topic_slug:
        curriculum_videos = (
            VideoLesson.query
            .filter_by(topic_slug=video.topic_slug)
            .order_by(VideoLesson.order_index.asc(), VideoLesson.created_at.desc())
            .all()
        )
    elif is_academic:
        curriculum_videos = (
            VideoLesson.query
            .filter_by(academic_category=video.academic_category)
            .order_by(VideoLesson.order_index.asc(), VideoLesson.created_at.desc())
            .all()
        )
    else:
        curriculum_videos = (
            VideoLesson.query
            .filter_by(subject_id=video.subject_id)
            .order_by(VideoLesson.order_index.asc(), VideoLesson.created_at.desc())
            .all()
        )

    topic_key = _topic_key_from_text(video.title)
    topic_resources = {"notes": None, "quiz": None, "cheatsheet": None, "flashcard": None}
    if subject:
        posts = Post.query.filter_by(subject_id=subject.id, status='approved').all()
        for post in posts:
            key, _ = _topic_info_from_post(post)
            if key == topic_key and post.content_type in topic_resources and topic_resources[post.content_type] is None:
                topic_resources[post.content_type] = post

    completed_video_ids = set()
    session_completed = session.get('completed_video_ids', [])
    for vid in session_completed:
        try: completed_video_ids.add(int(vid))
        except: pass

    if current_user.is_authenticated:
        db_completed = {
            vc.video_id for vc in VideoCompletion.query.filter_by(user_id=current_user.id).all()
        }
        completed_video_ids.update(db_completed)

    # Determine next video in sequence
    next_url = None
    next_video = None
    if curriculum_videos:
        # Find the index of current video, then pick the next uncompleted one
        found_current = False
        for cv in curriculum_videos:
            if cv.id == video.id:
                found_current = True
                continue
            if found_current and cv.id not in completed_video_ids:
                next_video = cv
                break
        
        # Fallback to the first non-completed video if we didn't find one after current
        if not next_video:
            for cv in curriculum_videos:
                if cv.id not in completed_video_ids and cv.id != video.id:
                    next_video = cv
                    break
            
        if next_video:
            next_url = url_for('main.video_player', video_id=next_video.id)

    # Check for assessment (Quiz/Flashcards)
    has_assessment = topic_resources.get('quiz') is not None or topic_resources.get('flashcard') is not None

    # Resolve pack_id for resource generation trigger
    pack_id = None
    if hasattr(video, 'pack_memberships') and video.pack_memberships:
        pack_id = video.pack_memberships[0].pack_id

    # ── Patch 8a: Trigger background resource generation on pack open ─────────
    resource_status = {}
    if current_user.is_authenticated and pack_id:
        from app.models import PackResource
        
        # Check if this pack already has any completed resources
        has_resources = PackResource.query.filter_by(
            pack_id=pack_id, generation_status='done'
        ).first() is not None
        
        can_generate = True
        if not has_resources and not current_user.is_premium:
            # First time generation for this pack — consume a free attempt
            if not current_user.use_free_attempt():
                can_generate = False
                resource_status = {'quota_exceeded': True}
        
        if can_generate:
            try:
                from app.services.resource_generator import generate_pack_resources
                resource_status = generate_pack_resources(pack_id)
            except Exception as _rg_exc:
                import logging
                logging.getLogger(__name__).warning("Resource generation trigger failed: %s", _rg_exc)

    # ── Patch 8b: Build interleaved syllabus (videos + checkpoints) ───────────
    syllabus_items = []
    checkpoint_positions = resource_status.get('checkpoint_positions', {}) if resource_status else {}

    if pack_id and checkpoint_positions:
        from app.models import StudyPack, PackResource
        pack = StudyPack.query.get(pack_id)
        pack_videos = sorted(pack.videos, key=lambda spv: spv.order_index) if pack else []

        # Build a lookup: order_index → VideoLesson
        for spv in pack_videos:
            syllabus_items.append({
                'type': 'video',
                'video': spv.video,
                'order_index': spv.order_index,
                'stage': spv.stage or 'Foundation',
            })
            # Inject checkpoint after this video if one is scheduled here
            if spv.order_index in checkpoint_positions:
                cp_type = checkpoint_positions[spv.order_index]
                # Check if the resource is already generated
                cp_resource = PackResource.query.filter_by(
                    pack_id=pack_id,
                    video_id=spv.video.id if cp_type == 'flashcards' else None,
                    resource_type=cp_type,
                ).first()
                cp_status = cp_resource.generation_status if cp_resource else 'pending'
                # Extract meta count/label if done
                cp_meta = None
                if cp_resource and cp_resource.generation_status == 'done':
                    cp_content = cp_resource.get_content()
                    if cp_content:
                        if cp_type == 'flashcards':
                            cp_meta = f"{len(cp_content.get('flashcards', []))} cards"
                        elif cp_type == 'micro_quiz':
                            q_count = cp_content.get('metadata', {}).get('total_questions') or len(cp_content.get('questions', []))
                            cp_meta = f"{q_count} questions"

                syllabus_items.append({
                    'type': 'checkpoint',
                    'checkpoint_type': cp_type,
                    'after_order_index': spv.order_index,
                    'after_video_id': spv.video.id,
                    'resource_status': cp_status,
                    'resource_id': cp_resource.id if cp_resource else None,
                    'resource_meta': cp_meta,
                })

        # Pack-level resources appended after all videos
        for res_type in ('notes', 'cheatsheet', 'boss_quiz'):
            pr = PackResource.query.filter_by(
                pack_id=pack_id, video_id=None, resource_type=res_type
            ).first()
            
            # Extract meta count/label if done
            pr_meta = None
            if pr and pr.generation_status == 'done':
                pr_content = pr.get_content()
                if pr_content:
                    if res_type == 'boss_quiz':
                        q_count = pr_content.get('metadata', {}).get('total_questions') or len(pr_content.get('questions', []))
                        pr_meta = f"{q_count} questions"
                    elif res_type == 'notes':
                        pr_meta = "Full study guide"
                    elif res_type == 'cheatsheet':
                        pr_meta = "Formula reference"

            syllabus_items.append({
                'type': 'checkpoint',
                'checkpoint_type': res_type,
                'after_order_index': len(pack_videos),
                'after_video_id': None,
                'resource_status': pr.generation_status if pr else 'pending',
                'resource_id': pr.id if pr else None,
                'resource_meta': pr_meta,
            })
    else:
        # No pack context — fall back to plain video list
        for cv in curriculum_videos:
            syllabus_items.append({
                'type': 'video',
                'video': cv,
                'order_index': 0,
                'stage': '',
            })

    # Fetch resources for the active context (current video or pack-level)
    active_pack_resources = {}
    if pack_id:
        from app.models import PackResource
        res_list = PackResource.query.filter_by(pack_id=pack_id).all()
        for res in res_list:
            if res.video_id == video.id or res.video_id is None:
                # Add dynamic meta for the resource center tabs
                res_meta = None
                if res.generation_status == 'done':
                    res_content = res.get_content()
                    if res_content:
                        if res.resource_type == 'flashcards':
                            res_meta = f"{len(res_content.get('flashcards', []))} cards"
                        elif res.resource_type in ('micro_quiz', 'boss_quiz'):
                            q_count = res_content.get('metadata', {}).get('total_questions') or len(res_content.get('questions', []))
                            res_meta = f"{q_count} questions"
                
                # We'll store both the object and its meta for convenience
                active_pack_resources[res.resource_type] = {
                    'obj': res,
                    'meta': res_meta
                }

    return render_template(
        'library/study_room.html',
        video=video,
        subject=subject,
        display_subject=display_subject,
        programme=programme,
        completed=completed,
        completed_video_ids=completed_video_ids,
        net_likes=net_likes,
        user_like=user_like,
        comments=comments,
        current_user=current_user,
        curriculum_videos=curriculum_videos,
        topic_key=topic_key,
        topic_resources=topic_resources,
        active_pack_resources=active_pack_resources,
        has_assessment=has_assessment,
        next_url=next_url,
        resource_status=resource_status,
        syllabus_items=syllabus_items,
        pack_id=pack_id
    )

@bp.route('/library/video/ext', methods=['GET', 'POST'])
def video_player_external():
    """Convert external YouTube videos (from search) to internal videos in DB."""
    yt_id = request.args.get('yt')
    title = request.args.get('t', 'Video')
    channel = request.args.get('c', 'YouTube')
    category = request.args.get('cat', '')  # subject/programme name
    
    if not yt_id or len(yt_id) not in [11, 12]:
        abort(404)
    
    # Check if video already exists in DB
    existing = VideoLesson.query.filter_by(youtube_id=yt_id).first()
    if existing:
        return redirect(url_for('main.video_player', video_id=existing.id))
    
    # Find a subject to associate with
    subject = None
    if category:
        # Try to find subject by category name
        subject = Subject.query.filter(
            Subject.is_active == True,
            Subject.name.ilike(f'%{category}%')
        ).first()
    
    if not subject:
        # Get first active subject as fallback
        subject = Subject.query.filter(Subject.is_active == True).first()
    
    if not subject:
        abort(404)
    
    # Create new video in DB
    thumbnail = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
    new_video = VideoLesson(
        subject_id=subject.id,
        youtube_id=yt_id,
        title=title,
        thumbnail=thumbnail,
        channel_name=channel,
        topic_slug=_slugify_topic(title)
    )
    db.session.add(new_video)
    db.session.commit()
    
    # Trigger background AI categorization for the new video
    try:
        from app.services.youtube_video_fetcher import _run_background_categorization
        import threading
        allowed_subjects = [s.name for s in Subject.query.filter_by(is_active=True).all()]
        app = current_app._get_current_object()
        thread = threading.Thread(
            target=_run_background_categorization,
            args=(app, new_video.id, new_video.title, allowed_subjects)
        )
        thread.start()
    except Exception:
        pass
    
    return redirect(url_for('main.video_player', video_id=new_video.id))

@bp.route('/library/pack/<int:pack_id>/video-complete', methods=['POST'])
def pack_video_complete(pack_id):
    """
    Called by JS when a user finishes a video inside a pack.
    Triggers background generation of the next checkpoint's resources.
    Returns updated resource statuses for the pack so the front-end
    can refresh checkpoint states without a full page reload.
    """
    if not current_user.is_authenticated:
        return jsonify({'error': 'login_required'}), 401

    data = request.get_json(silent=True) or {}
    completed_video_id = data.get('video_id')
    completed_order_index = data.get('order_index', 0)

    from app.models import StudyPack, PackResource
    from app.services.resource_generator import (
        generate_pack_resources,
        compute_checkpoint_positions,
        _generate_and_save_flashcards,
    )

    pack = StudyPack.query.get_or_404(pack_id)
    pack_videos = sorted(pack.videos, key=lambda spv: spv.order_index)
    checkpoint_positions = compute_checkpoint_positions(pack_videos)

    triggered = []

    # If the completed video sits at a checkpoint boundary, trigger that
    # checkpoint's resource generation now (background thread)
    if completed_order_index in checkpoint_positions:
        cp_type = checkpoint_positions[completed_order_index]

        if cp_type == 'flashcards' and current_user.is_premium:
            # Find the video at this order_index
            target_spv = next(
                (spv for spv in pack_videos if spv.order_index == completed_order_index), None
            )
            if target_spv and target_spv.video:
                existing = PackResource.query.filter_by(
                    pack_id=pack_id,
                    video_id=target_spv.video.id,
                    resource_type='flashcards',
                ).first()
                if not existing or existing.generation_status != 'done':
                    import threading
                    from flask import current_app
                    app = current_app._get_current_object()
                    t = threading.Thread(
                        target=_generate_and_save_flashcards,
                        args=(pack_id, target_spv.video, app),
                        daemon=True,
                    )
                    t.start()
                    triggered.append(f'flashcards:video_{completed_order_index}')

        elif cp_type == 'micro_quiz' and current_user.is_premium:
            from app.services.resource_generator import _generate_micro_quiz_and_save
            target_spv = next(
                (spv for spv in pack_videos if spv.order_index == completed_order_index), None
            )
            if target_spv and target_spv.video:
                existing = PackResource.query.filter_by(
                    pack_id=pack_id,
                    video_id=target_spv.video.id,
                    resource_type='micro_quiz',
                ).first()
                if not existing or existing.generation_status != 'done':
                    import threading
                    from flask import current_app
                    app = current_app._get_current_object()
                    t = threading.Thread(
                        target=_generate_micro_quiz_and_save,
                        args=(pack_id, target_spv.video, app),
                        daemon=True,
                    )
                    t.start()
                    triggered.append(f'micro_quiz:video_{completed_order_index}')

    # If this was the final video in the pack, trigger notes, cheatsheet, and boss quiz
    if completed_order_index == len(pack_videos) and current_user.is_premium:
        from app.services.resource_generator import _generate_notes_cheatsheet_and_save
        import threading
        from flask import current_app
        app = current_app._get_current_object()
        t = threading.Thread(
            target=_generate_notes_cheatsheet_and_save,
            args=(pack_id, app),
            daemon=True,
        )
        t.start()
        triggered.append('pack_level_resources')


    # Return current resource statuses for all checkpoints so the front-end
    # can update the syllabus pane
    resource_statuses = {}
    for res in PackResource.query.filter_by(pack_id=pack_id).all():
        key = f"{res.resource_type}:{res.video_id or 'pack'}"
        resource_statuses[key] = res.generation_status

    return jsonify({
        'ok': True,
        'triggered': triggered,
        'resource_statuses': resource_statuses,
        'is_premium': current_user.is_premium,
    })


@bp.route('/library/pack/<int:pack_id>/resource-status')
@login_required
def pack_resource_status(pack_id):
    """
    Endpoint for polling resource generation status.
    Returns a map: { "resource_type:video_id|pack": "status" }
    """
    from app.models import PackResource
    resources = PackResource.query.filter_by(pack_id=pack_id).all()
    statuses = {}
    for res in resources:
        key = f"{res.resource_type}:{res.video_id or 'pack'}"
        statuses[key] = res.generation_status
    
    return jsonify({
        'pack_id': pack_id,
        'statuses': statuses
    })



# ── XP awards per resource type ───────────────────────────────────────────────
_RESOURCE_XP = {
    'flashcards': 10,
    'micro_quiz': 15,
    'notes':      20,
    'cheatsheet': 10,
    'boss_quiz':  50,
}

@bp.route('/library/pack/<int:pack_id>/resource/<int:resource_id>')
def pack_resource_viewer(pack_id, resource_id):
    """
    Render the resource viewer for a single PackResource.

    Access rules:
      - Guests        → redirect to study room on first video of pack
      - Free users    → flashcards only; all others get inline upgrade card
      - Premium users → full access to all resource types
    """
    from app.models import PackResource, PackResourceCompletion, StudyPack

    pack = StudyPack.query.get_or_404(pack_id)
    resource = PackResource.query.filter_by(
        id=resource_id, pack_id=pack_id
    ).first_or_404()

    # Guest gate — redirect to pack's first video
    if not current_user.is_authenticated:
        first_spv = sorted(pack.videos, key=lambda s: s.order_index)[0] if pack.videos else None
        if first_spv and first_spv.video:
            return redirect(url_for('main.video_player', video_id=first_spv.video.id))
        return redirect(url_for('main.library_all_videos'))

    # Resolve next video URL for the "Continue watching" button
    pack_videos = sorted(pack.videos, key=lambda s: s.order_index)
    next_video = None
    if resource.video_id:
        # Find the video after the one this resource belongs to
        found = False
        for spv in pack_videos:
            if found and spv.video:
                next_video = spv.video
                break
            if spv.video and spv.video.id == resource.video_id:
                found = True
    if not next_video and pack_videos:
        # Pack-level resource: next is nothing (pack complete)
        pass

    next_url = url_for('main.video_player', video_id=next_video.id) if next_video else \
               url_for('main.library_all_videos')

    # Check if user already completed this resource
    already_done = PackResourceCompletion.query.filter_by(
        user_id=current_user.id,
        resource_id=resource.id,
    ).first() is not None

    # Determine access level
    premium_types = {'micro_quiz', 'notes', 'cheatsheet', 'boss_quiz'}
    is_premium_resource = resource.resource_type in premium_types
    can_view = current_user.is_premium or not is_premium_resource

    # Deserialize content only if the user can view it
    content = resource.get_content() if (can_view and resource.generation_status == 'done') else None

    return render_template(
        'library/resource_viewer.html',
        pack=pack,
        resource=resource,
        content=content,
        can_view=can_view,
        is_premium_resource=is_premium_resource,
        already_done=already_done,
        next_url=next_url,
        pack_id=pack_id,
        xp_reward=_RESOURCE_XP.get(resource.resource_type, 10),
    )


@bp.route('/library/pack/<int:pack_id>/resource/<int:resource_id>/complete', methods=['POST'])
def pack_resource_complete(pack_id, resource_id):
    """
    Mark a resource as completed for the current user and award XP.
    Called by JS when the user finishes a flashcard deck or submits a quiz.
    """
    if not current_user.is_authenticated:
        return jsonify({'error': 'login_required'}), 401

    from app.models import PackResource, PackResourceCompletion

    resource = PackResource.query.filter_by(
        id=resource_id, pack_id=pack_id
    ).first_or_404()

    # Idempotent — don't double-award XP
    existing = PackResourceCompletion.query.filter_by(
        user_id=current_user.id,
        resource_id=resource.id,
    ).first()

    if existing:
        return jsonify({'ok': True, 'already_done': True, 'xp': 0})

    data = request.get_json(silent=True) or {}
    score = data.get('score')
    total = data.get('total')
    xp = _RESOURCE_XP.get(resource.resource_type, 10)

    completion = PackResourceCompletion(
        user_id=current_user.id,
        resource_id=resource.id,
        score=score,
        total=total,
        xp_earned=xp,
    )
    db.session.add(completion)

    try:
        current_user.add_xp(
            xp,
            apply_streak_multiplier=False,
            reason=f'Resource: {resource.resource_type} in pack {pack_id}',
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 500

    return jsonify({'ok': True, 'already_done': False, 'xp': xp})
@bp.route('/library/video/<int:video_id>/complete', methods=['POST'])
def complete_video(video_id):
    if not current_user.is_authenticated:
        # Record for guests in session
        cv_ids = session.get('completed_video_ids', [])
        if video_id not in cv_ids:
            cv_ids.append(video_id)
            session['completed_video_ids'] = cv_ids
        return jsonify({'status': 'ok', 'xp': 0, 'guest': True})
    
    """AJAX endpoint — marks video complete and awards XP. Returns JSON."""
    video = VideoLesson.query.get_or_404(video_id)
    existing = VideoCompletion.query.filter_by(user_id=current_user.id, video_id=video.id).first()
    
    if not existing:
        vc = VideoCompletion(user_id=current_user.id, video_id=video.id, xp_earned=video.xp_reward)
        db.session.add(vc)
        # Update streak BEFORE adding XP so multiplier is calculated correctly
        current_user.update_streak()
        current_user.add_xp(video.xp_reward, apply_streak_multiplier=True, reason=f'Video: {video.title[:50]}')
        db.session.commit()
        # Update cached pack progress
        update_pack_progress(current_user.id, video.id)
    
    # Find next video in pack if pack_id is provided
    data = request.get_json(silent=True) or {}
    pack_id = data.get('pack_id')
    next_video = None
    if pack_id:
        from app.models import StudyPackVideo
        current_spv = StudyPackVideo.query.filter_by(pack_id=pack_id, video_id=video.id).first()
        if current_spv:
            next_spv = StudyPackVideo.query.filter_by(pack_id=pack_id, order_index=current_spv.order_index + 1).first()
            if next_spv:
                next_video = next_spv.video

    return jsonify({
        'status': 'ok',
        'xp': video.xp_reward,
        'current_streak': current_user.current_streak,
        'longest_streak': current_user.longest_streak,
        'total_aura': current_user.aura_balance,
        'next_video_id': next_video.id if next_video else None,
        'next_video_title': next_video.title if next_video else None
    })

@bp.route('/library/video/<int:video_id>/ask', methods=['POST'])
@login_required
def video_ask(video_id):
    """AI Tutor chat endpoint for the Study Room."""
    video = VideoLesson.query.filter_by(id=video_id).first_or_404()
    data = request.get_json(silent=True) or {}
    question = data.get('question', '').strip()
    history = data.get('history', [])  # [{role, content}, ...]
    
    if not question:
        return jsonify({'error': 'No question provided'}), 400
    if len(question) > 500:
        return jsonify({'error': 'Question too long'}), 400

    subject_name = video.subject.name if video.subject else 'this subject'
    
    # Build system prompt grounded in the video
    sys_prompt = (
        f"You are a concise academic tutor helping a student understand: "
        f"\"{video.title}\" (subject: {subject_name}). "
        f"Answer only academic questions about this topic. "
        f"Keep responses under 150 words. Use plain text, no markdown."
    )
    
    # Build message history for context
    messages = [{'role': 'system', 'content': sys_prompt}]
    for msg in history[-6:]:  # last 3 exchanges only — keep tokens low
        if msg.get('role') in ('user', 'assistant') and msg.get('content'):
            messages.append({'role': msg['role'], 'content': msg['content'][:300]})
    messages.append({'role': 'user', 'content': question})

    try:
        from app.services.ai_service import _load_keys, _GENAI_AVAILABLE
        import os, json
        from urllib import request as urlrequest

        # Try Gemini first (free)
        keys = _load_keys()
        if _GENAI_AVAILABLE and keys:
            import google.generativeai as genai
            genai.configure(api_key=keys[0])
            model = genai.GenerativeModel('gemini-2.0-flash-lite')
            # Build Gemini chat history
            gemini_history = []
            for msg in messages[1:-1]:  # skip system, skip last user msg
                gemini_history.append({
                    'role': 'user' if msg['role'] == 'user' else 'model',
                    'parts': [msg['content']]
                })
            chat = model.start_chat(history=gemini_history)
            response = chat.send_message(
                sys_prompt + '\n\n' + question if not gemini_history else question
            )
            answer = response.text.strip()
            return jsonify({'answer': answer})

        # Fallback: OpenRouter
        api_key = (os.environ.get('OPENROUTER_API_KEY') or '').strip()
        if api_key:
            payload = {
                'model': 'mistralai/mistral-7b-instruct:free',
                'messages': messages,
                'max_tokens': 300,
                'temperature': 0.5,
            }
            req = urlrequest.Request(
                'https://openrouter.ai/api/v1/chat/completions',
                data=json.dumps(payload).encode(),
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                }
            )
            with urlrequest.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                answer = result['choices'][0]['message']['content'].strip()
                return jsonify({'answer': answer})

        return jsonify({'error': 'AI service unavailable'}), 503

    except Exception as e:
        return jsonify({'error': 'Could not reach AI tutor right now.'}), 500

@bp.route('/library/video/<int:video_id>/confidence', methods=['POST'])
def save_confidence(video_id):
    """Save confidence slider value. Works for guests (no-op) and users."""
    if not current_user.is_authenticated:
        return jsonify({'status': 'guest'})
    
    data = request.get_json(silent=True) or {}
    score = data.get('score')
    if score is None or not (0 <= int(score) <= 100):
        return jsonify({'status': 'error', 'msg': 'Invalid score'}), 400

    from app.models import UserVideoProgress
    prog = UserVideoProgress.query.filter_by(
        user_id=current_user.id, video_id=video_id
    ).first()
    if not prog:
        prog = UserVideoProgress(user_id=current_user.id, video_id=video_id)
        db.session.add(prog)
    prog.confidence_score = int(score)
    db.session.commit()
    return jsonify({'status': 'ok', 'score': prog.confidence_score})

# Video comment submission
@bp.route('/library/video/<int:video_id>/comment', methods=['POST'])
@login_required
def video_comment(video_id):
    video = VideoLesson.query.filter_by(id=video_id).first_or_404()
    content = request.form.get('content', '').strip()
    if not content:
        return redirect(url_for('main.video_player', video_id=video.id))
    comment = VideoComment(user_id=current_user.id, video_id=video.id, content=content)
    db.session.add(comment)
    db.session.commit()
    return redirect(url_for('main.video_player', video_id=video.id))

# Like/dislike endpoint
@bp.route('/library/video/<int:video_id>/like', methods=['POST'])
@login_required
def video_like(video_id):
    video = VideoLesson.query.filter_by(id=video_id).first_or_404()
    value = int(request.form.get('value', 1))
    if value not in [1, -1]:
        abort(400)
    like = video.likes.filter_by(user_id=current_user.id).first()
    if like:
        if like.value == value:
            db.session.delete(like)  # Toggle off
        else:
            like.value = value
    else:
        like = VideoLike(user_id=current_user.id, video_id=video.id, value=value)
        db.session.add(like)
    db.session.commit()
    # Return new net likes
    net_likes = video.likes.with_entities(db.func.sum(VideoLike.value)).scalar() or 0
    return {'net_likes': net_likes, 'user_like': value if like and like.value == value else 0}

@bp.route('/library/video/save', methods=['POST'])
@login_required
def video_save():
    from app.models import VideoBookmark, VideoLesson, Subject
    data = request.get_json() or {}
    video_id = data.get('video_id')
    youtube_id = data.get('youtube_id')
    
    if not video_id and not youtube_id:
        return jsonify({'error': 'Missing video identification'}), 400
        
    if video_id:
        video = VideoLesson.query.get_or_404(video_id)
    else:
        # Check if video already exists by youtube_id
        video = VideoLesson.query.filter_by(youtube_id=youtube_id).first()
        if not video:
            # Create external video record
            # Find subject from metadata if provided, or default
            category = data.get('category')
            subject = None
            if category:
                subject = Subject.query.filter(Subject.is_active == True, Subject.name.ilike(f'%{category}%')).first()
            if not subject:
                subject = Subject.query.filter(Subject.is_active == True).first()
                
            if not subject:
                return jsonify({'error': 'No subject to associate with'}), 500
                
            video = VideoLesson(
                subject_id=subject.id,
                youtube_id=youtube_id,
                title=data.get('title', 'YouTube Video'),
                channel_name=data.get('channel', 'YouTube'),
                thumbnail=f"https://img.youtube.com/vi/{youtube_id}/hqdefault.jpg"
            )
            db.session.add(video)
            db.session.commit()
            
    existing = VideoBookmark.query.filter_by(user_id=current_user.id, video_id=video.id).first()
    if existing:
        db.session.delete(existing)
        saved = False
    else:
        db.session.add(VideoBookmark(user_id=current_user.id, video_id=video.id))
        saved = True
        
    db.session.commit()
    return jsonify({'saved': saved, 'video_id': video.id})

# ─────────────────────────────────────────────────────────────────────────────
# SUBJECT VIDEO LISTING
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/library/subject/videos', endpoint='library_all_videos')
@bp.route('/library/subject/<slug>/videos', endpoint='library_subject_videos')
@turbo_frame('main-content', 'frames/library_subject_videos.html', 'library/subject_videos.html')
def library_subject_videos(slug=None):
    user_programme = None
    if current_user.is_authenticated and current_user.programme:
        user_programme = Programme.query.filter_by(name=current_user.programme).first()

    if user_programme:
        # Only subjects in user's programme
        all_subjects = Subject.query.filter(
            Subject.is_active == True,
            Subject.programmes.any(Programme.id == user_programme.id)
        ).order_by(Subject.order, Subject.name).all()
    else:
        all_subjects = _get_active_subjects()

    # Attach video_count to each subject
    for s in all_subjects:
        s.video_count = len(s.video_lessons) if hasattr(s, 'video_lessons') else 0

    if slug:
        subject = Subject.query.filter_by(slug=slug, is_active=True).first_or_404()
        programme = subject.programmes[0] if subject.programmes else None
        # Only show videos if subject is in user's programme (or show none)
        if user_programme and user_programme.id not in [p.id for p in subject.programmes]:
            videos = []
        else:
            videos = subject.video_lessons.order_by('created_at').all()
            # Personalise: if user has a programme and we're on the all-videos page,
            # surface their programme's videos first
        title = f"{subject.name} — Videos"
    else:
        subject = None
        programme = user_programme
        if user_programme:
            subject_ids = [s.id for s in all_subjects]
            videos = VideoLesson.query.filter(
                VideoLesson.subject_id.in_(subject_ids)
            ).order_by(VideoLesson.created_at.desc()).all()
        else:
            videos = VideoLesson.query.order_by(VideoLesson.created_at.desc()).all()
        title = "All Videos"

    search_query = request.args.get('q', '').strip()
    study_mode = request.args.get('study', '0') == '1'
    
    # Get user's saved video IDs
    saved_video_ids = []
    if current_user.is_authenticated:
        from app.models import VideoBookmark
        saved_video_ids = [b.video_id for b in current_user.video_bookmarks if b.video]

    all_programmes = Programme.query.filter_by(is_active=True).all()

    from app.models import StudyPack
    recent_packs = StudyPack.query.options(joinedload(StudyPack.subject)).order_by(StudyPack.created_at.desc()).limit(12).all()

    return dict(
        title=title,
        subject=subject,
        programme=programme,
        videos=videos,
        recent_packs=recent_packs,
        all_subjects=all_subjects,
        initial_query=search_query,
        saved_video_ids=saved_video_ids,
        all_programmes=all_programmes,
        study_mode=study_mode
    )

@bp.route('/library/browse', endpoint='video_browse')
@turbo_frame('main-content', 'frames/video_browse.html', 'library/subject_videos.html')
def video_browse():
    """Watch Videos page — flat video search without pack assembly."""
    user_programme = None
    if current_user.is_authenticated and current_user.programme:
        user_programme = Programme.query.filter_by(name=current_user.programme).first()

    if user_programme:
        subject_ids = [s.id for s in Subject.query.filter(
            Subject.is_active == True,
            Subject.programmes.any(Programme.id == user_programme.id)
        ).all()]
        videos = VideoLesson.query.filter(
            VideoLesson.subject_id.in_(subject_ids)
        ).order_by(VideoLesson.created_at.desc()).limit(48).all()
    else:
        videos = VideoLesson.query.order_by(VideoLesson.created_at.desc()).limit(48).all()

    saved_video_ids = []
    if current_user.is_authenticated:
        from app.models import VideoBookmark
        saved_video_ids = [b.video_id for b in current_user.video_bookmarks if b.video]

    search_query = request.args.get('q', '').strip()
    all_programmes = Programme.query.filter_by(is_active=True).all()

    return dict(
        videos=videos,
        saved_video_ids=saved_video_ids,
        initial_query=search_query,
        all_programmes=all_programmes,
        user_programme=user_programme,
    )


@bp.route('/library/videos-page')
def library_videos_page():
    """Infinite scroll endpoint for video browsing."""
    page = request.args.get('page', 1, type=int)
    per_page = 12
    subject = request.args.get('subject')
    
    # Start with base query
    query = VideoLesson.query
    
    # Filter by subject if provided
    if subject:
        # Find subject by slug or name
        subject_obj = Subject.query.filter(
            (Subject.slug == subject) | (Subject.name == subject)
        ).first()
        if subject_obj:
            query = query.filter_by(subject_id=subject_obj.id)
    
    # Get paginated results
    pagination = query.order_by(VideoLesson.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    videos = pagination.items
    
    # Get saved video IDs for current user
    saved_video_ids = []
    if current_user.is_authenticated:
        from app.models import VideoBookmark
        saved_video_ids = [b.video_id for b in current_user.video_bookmarks if b.video]
    
    # Build video data for JSON response
    video_data = []
    for video in videos:
        video_data.append({
            'id': video.id,
            'title': video.title,
            'description': getattr(video, 'description', None) or '',
            'thumbnail_url': getattr(video, 'thumbnail_url', None) or video.thumbnail,
            'youtube_id': video.youtube_id,
            'channel': getattr(video, 'channel', None) or video.channel_name,
            'subject': video.subject.name if video.subject else None,
            'duration': getattr(video, 'duration', None),
            'is_saved': video.id in saved_video_ids
        })
    
    return jsonify({
        'videos': video_data,
        'has_next': pagination.has_next,
        'page': page,
        'pages': pagination.pages,
        'total': pagination.total
    })

@bp.route('/library/video/validate-url', methods=['POST'])
def validate_video_url():
    """Validate a pasted YouTube URL for the study room guest player."""
    from app.services.youtube_scraper import is_academic_query
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'valid': False, 'error': 'No URL provided'})

    import re
    yt_match = re.search(r'(?:v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})', url)
    if not yt_match:
        return jsonify({'valid': False, 'error': 'Not a valid YouTube URL'})

    youtube_id = yt_match.group(1)

    # Check if it already exists in DB
    existing = VideoLesson.query.filter_by(youtube_id=youtube_id).first()
    if existing:
        return jsonify({
            'valid': True,
            'youtube_id': youtube_id,
            'title': existing.title,
            'embed_url': f'https://www.youtube.com/embed/{youtube_id}',
            'in_db': True,
            'video_id': existing.id
        })

    # Try to get title from oEmbed (no API key needed)
    try:
        import urllib.request, json as _json
        oembed_url = f'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={youtube_id}&format=json'
        with urllib.request.urlopen(oembed_url, timeout=4) as resp:
            oembed = _json.loads(resp.read())
        title = oembed.get('title', '')
    except Exception:
        title = ''

    if not title:
        return jsonify({'valid': False, 'error': 'Could not fetch video info'})

    if not is_academic_query(title):
        return jsonify({'valid': False, 'error': 'non_academic', 'title': title})

    return jsonify({
        'valid': True,
        'youtube_id': youtube_id,
        'title': title,
        'embed_url': f'https://www.youtube.com/embed/{youtube_id}',
        'in_db': False
    })

@bp.route('/library/search-videos')
def search_videos_api():
    """Search videos using scraper (no quota) or API fallback with academic categorization."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'videos': [], 'error': 'No search query'})
    
    # Honeypot check - reject bots
    if request.args.get('website'):
        return jsonify({'videos': [], 'error': 'Bot detected'})
    
    max_results = min(int(request.args.get('limit', 20)), 30)
    offset = max(int(request.args.get('offset', 0)), 0)    
    # Build academic keywords from DB for categorization
    from app.models import Programme, Subject
    from app.services.youtube_scraper import search_videos, categorize_video, is_academic_query

    _all_academic_kw = set()
    for _prog in Programme.query.filter_by(is_active=True).all():
        for _word in _prog.name.lower().split():
            if len(_word) > 2:
                _all_academic_kw.add(_word)
    for _subj in Subject.query.filter_by(is_active=True).all():
        for _word in _subj.name.lower().split():
            if len(_word) > 2:
                _all_academic_kw.add(_word)

    # Pass None if no academic keywords, to allow fallback to ACADEMIC_INDICATORS
    academic_kw_arg = _all_academic_kw if _all_academic_kw else None
    if not is_academic_query(query, academic_keywords=academic_kw_arg):
        return jsonify({
            'videos': [],
            'error': 'non_academic',
            'message': f'Search for "{query}" blocked. Please use academic terms related to your studies.'
        })

    # Get user's programme to filter results
    user_programme = None
    if current_user.is_authenticated and current_user.programme:
        user_programme = Programme.query.filter(
            Programme.name.ilike(f'%{current_user.programme}%'),
            Programme.is_active == True
        ).first()
    
    # Build keyword mappings - prioritize user's programme subjects
    programme_keywords = {}
    subject_keywords = {}
    
    # First add subjects from user's programme if logged in
    if user_programme:
        for subj in user_programme.subjects:
            subj_name_lower = subj.name.lower()
            subject_keywords[subj_name_lower] = (subj.name, user_programme.name)
            for word in subj_name_lower.split():
                if len(word) > 2:
                    if word not in subject_keywords:
                        subject_keywords[word] = (subj.name, user_programme.name)
    
    # Add all programmes
    for prog in Programme.query.filter_by(is_active=True).all():
        prog_name_lower = prog.name.lower()
        programme_keywords[prog_name_lower] = prog.name
        for word in prog_name_lower.split():
            if len(word) > 2:
                if word not in programme_keywords:
                    programme_keywords[word] = prog.name
    
    # Add all subjects
    for subj in Subject.query.filter_by(is_active=True).all():
        subj_name_lower = subj.name.lower()
        # Skip if already added (prioritized user's programme)
        if subj_name_lower in subject_keywords:
            continue
        subj_prog = subj.programmes[0].name if subj.programmes else None
        subject_keywords[subj_name_lower] = (subj.name, subj_prog)
        for word in subj_name_lower.split():
            if len(word) > 2:
                if word not in subject_keywords:
                    subject_keywords[word] = (subj.name, subj_prog)
    
    # Search videos — fetch more than needed so the path builder has choices
    videos = search_videos(query, max_results=max(max_results * 3, 18), offset=offset)

    if not videos:
        return jsonify({'videos': [], 'count': 0})

    # Categorize each video
    categorized = []
    for video in videos:
        category = categorize_video(
            video.get('title', ''),
            video.get('channel', ''),
            programme_keywords,
            subject_keywords
        )
        if category:
            video['category'] = category['category']
            video['subject']  = category.get('subject', '')
        else:
            video['category'] = 'General'
            video['subject']  = ''
        categorized.append(video)

    # ── Build learning path (sorts + sequences by difficulty/quality) ────────
    from app.services.learning_path_builder import build_learning_path, apply_path_to_db_videos
    categorized = build_learning_path(
        categorized,
        max_per_level=3,
        total_cap=max_results
    )
    
    # If user has a programme, prioritize those results (move to front), but keep all
    if user_programme:
        user_prog_lower = user_programme.name.lower()
        prioritized = []
        others = []
        for v in categorized:
            cat_lower = (v.get('category') or '').lower()
            if user_prog_lower in cat_lower or cat_lower == '':
                prioritized.append(v)
            else:
                others.append(v)
        categorized = prioritized + others
    
    # Only reject if the scraper itself returned nothing at all
    if not categorized:
        return jsonify({
            'videos': [],
            'error': 'no_results',
            'message': 'No results found for that search. Try different keywords.'
        })
    
    # ── AUTO-SAVE scraped videos to DB (self-warming cache) ──
    from app.models import VideoLesson, Subject
    from app.services.youtube_video_fetcher import _run_background_categorization
    import threading

    yt_ids = [v['video_id'] for v in categorized]
    # Fetch existing records to get academic_category
    existing_videos = VideoLesson.query.filter(VideoLesson.youtube_id.in_(yt_ids)).all()
    existing_map = {vl.youtube_id: vl for vl in existing_videos}
    
    allowed_subjects = [s.name for s in Subject.query.filter_by(is_active=True).all()]
    app = current_app._get_current_object()

    for v in categorized:
        yid = v['video_id']
        if yid not in existing_map:
            # Resolve subject from rule-based categorization metadata
            subj_name = v.get('subject', '').strip()
            subj = Subject.query.filter(Subject.name.ilike(f'%{subj_name}%'), Subject.is_active == True).first() if subj_name else None
            
            new_vl = VideoLesson(
                youtube_id   = yid,
                title        = v.get('title', '')[:300],
                thumbnail    = v.get('thumbnail', ''),
                channel_name = v.get('channel', '')[:200],
                subject_id   = subj.id if subj else None,
                academic_category = 'Pending AI',
                topic_slug   = _slugify_topic(query)
            )
            db.session.add(new_vl)
            
            # Trigger background AI categorization for the new video
            try:
                db.session.flush() # Get ID before commit if possible, or commit first
                existing_map[yid] = new_vl  # ← register so apply_path_to_db_videos can see it
                thread = threading.Thread(
                    target=_run_background_categorization,
                    args=(app, new_vl.id, new_vl.title, allowed_subjects)
                )
                thread.start()
            except Exception:
                pass
        else:
            # Enrich search result with AI category if we already have it
            db_video = existing_map[yid]
            if db_video.academic_category and db_video.academic_category != 'Pending AI':
                v['subject'] = db_video.academic_category
                v['academic_category'] = db_video.academic_category
            v['db_id'] = db_video.id
            # Silently backfill topic_slug on records created before this column existed.
            # Committed as part of the db.session.commit() a few lines below.
            if not db_video.topic_slug:
                db_video.topic_slug = _slugify_topic(query)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

    # ── Persist learning path ordering back to DB records ────────────────────
    from app.services.learning_path_builder import apply_path_to_db_videos
    apply_path_to_db_videos(categorized, existing_map)

    # Check for user saves
    if current_user.is_authenticated:               
        saved_yt_ids = {vb.video.youtube_id for vb in current_user.video_bookmarks if vb.video}
        for v in categorized:
            yid = v['video_id']
            v['is_saved'] = yid in saved_yt_ids

    # ── Assemble StudyPacks from warm pool + fresh results ───────────────────
    from app.services.pack_assembly import assemble_packs

    # Detect the dominant academic_category from categorized results
    # (most common non-empty value across the result set)
    from collections import Counter
    cat_counts = Counter(
        v.get('academic_category', '') for v in categorized
        if v.get('academic_category') and v['academic_category'] not in ('General', 'Pending AI', 'Pending', '')
    )
    dominant_category = cat_counts.most_common(1)[0][0] if cat_counts else ''

    # Detect subject_id from the first categorized result that has one in the DB
    pack_subject_id = None
    for v in categorized:
        yid = v.get('video_id')
        vl = existing_map.get(yid)
        if vl and vl.subject_id:
            pack_subject_id = vl.subject_id
            break

    pack_created_by = current_user.id if current_user.is_authenticated else None
    topic_slug_for_pack = _slugify_topic(query)

    packs = assemble_packs(
        topic_slug=topic_slug_for_pack,
        fresh_videos=categorized,
        academic_category=dominant_category,
        subject_id=pack_subject_id,
        created_by=pack_created_by,
        existing_map=existing_map,
    )
    
    # Enhance packs with additional fields expected by the template
    gradients = [
        'linear-gradient(135deg, #7c6af7 0%, #a291f9 100%)',
        'linear-gradient(135deg, #3ddc84 0%, #6be5a1 100%)',
        'linear-gradient(135deg, #f5c542 0%, #f7d67a 100%)',
        'linear-gradient(135deg, #f06b6b 0%, #f49292 100%)',
        'linear-gradient(135deg, #60a5fa 0%, #93c5fd 100%)'
    ]
    
    # Determine if packs are new (created within last 7 days)
    from datetime import datetime, timedelta, timezone
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    
    for idx, pack in enumerate(packs):
        # Add id as alias for pack_id (for consistency)
        pack['id'] = pack.get('pack_id')
        
        # Add gradient
        pack['gradient'] = gradients[idx % len(gradients)]
        
        # Add is_new (pack created within last 7 days)
        pack_created_at = pack.get('created_at')
        if pack_created_at:
            # Handle both datetime objects and strings
            if isinstance(pack_created_at, str):
                try:
                    pack_created_at = datetime.fromisoformat(pack_created_at.replace('Z', '+00:00'))
                except:
                    pack_created_at = datetime.now(timezone.utc)
            pack['is_new'] = pack_created_at >= seven_days_ago
        else:
            pack['is_new'] = False
            
        # Add is_top (top 25% by view count) - we'll set this after processing all packs
        pack['is_top'] = False  # Will be set below after we have all view counts
        
        # Add is_trending (placeholder - could be based on recent views)
        pack['is_trending'] = False
        
        # Add learner_count (use view_count)
        pack['learner_count'] = pack.get('view_count', 0)
        
        # Add rating (not stored, default to None)
        pack['rating'] = None
        
        # Add creator (if created_by exists)
        if pack.get('created_by'):
            from app.models import User
            creator = User.query.get(pack['created_by'])
            pack['creator'] = creator
        else:
            pack['creator'] = None
    
    # Now determine which packs are "top" based on view count (top 25%)
    if packs:
        # Sort packs by view_count descending
        sorted_packs = sorted(packs, key=lambda p: p.get('view_count', 0), reverse=True)
        # Top 25% (at least 1 if we have packs)
        top_count = max(1, len(sorted_packs) // 4)
        top_pack_ids = {p['id'] for p in sorted_packs[:top_count]}
        # Mark the top packs
        for pack in packs:
            if pack['id'] in top_pack_ids:
                pack['is_top'] = True

    return jsonify({
        'videos': categorized,       # keep for backwards compatibility
        'packs': packs,              # new — list of assembled pack dicts
        'count': len(categorized),
        'categorized': True,
        'has_packs': len(packs) > 0,
        'user_programme': (user_programme.name if hasattr(user_programme, 'name') else user_programme),
        'has_more': len(categorized) >= max_results,
        'next_offset': offset + len(categorized)
    })



# ─────────────────────────────────────────────────────────────────────────────
# SHORTCUT REDIRECTS — so /login and /signup work without the /auth prefix
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/login')
def login_redirect():
    """Convenience redirect: /login → /auth/login"""
    return redirect(url_for('auth.login'))


@bp.route('/signup')
@bp.route('/register')
def signup_redirect():
    """Convenience redirect: /signup or /register → /auth/signup"""
    return redirect(url_for('auth.signup'))


# ─────────────────────────────────────────────────────────────────────────────
# ONBOARDING — post-signup profile setup
# ─────────────────────────────────────────────────────────────────────────────

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return re.sub(r'^-+|-+$', '', text)

@bp.route('/onboarding', methods=['POST'])
@login_required
def onboarding():
    nickname = request.form.get('nickname', '').strip()
    username = request.form.get('username', '').strip()
    school = request.form.get('school', '').strip()
    prog_name = request.form.get('programme', '').strip()

    if nickname:
        current_user.nickname = nickname
    if username and username != current_user.username:
        # Check uniqueness
        existing = User.query.filter_by(username=username).first()
        if not existing or existing.id == current_user.id:
            current_user.username = username
    if school:
        current_user.school = school
        
    if prog_name:
        current_user.programme = prog_name
        # Auto-create programme if it doesn't exist
        existing_prog = Programme.query.filter(db.func.lower(Programme.name) == prog_name.lower()).first()
        if not existing_prog:
            new_prog = Programme(
                name=prog_name,
                slug=slugify(prog_name),
                faculty='Other',
                icon='graduation-cap',
                color='#8b5cf6'
            )
            db.session.add(new_prog)
            db.session.flush() # Get the new_prog.id if needed, or just prepare for commit

    current_user.onboarding_skipped = True
    db.session.commit()
    flash('Profile set up! Welcome to Knowly.', 'success')
    return redirect(request.referrer or url_for('main.index'))


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_suggestions():
    show_suggestions = False
    suggested_users = {'same_school': [], 'same_programme': [], 'random': []}

    if current_user.is_authenticated and not session.get('suggestions_shown'):
        if current_user.school or current_user.programme:
            show_suggestions = True
            session['suggestions_shown'] = True

            already_following = [u.id for u in current_user.following.all()]
            exclude = already_following + [current_user.id]

            if current_user.school:
                suggested_users['same_school'] = User.query.filter(
                    User.school == current_user.school,
                    ~User.id.in_(exclude)
                ).limit(4).all()

            if current_user.programme:
                suggested_users['same_programme'] = User.query.filter(
                    User.programme == current_user.programme,
                    ~User.id.in_(exclude)
                ).limit(4).all()

           
            candidates = User.query.filter(
                ~User.id.in_(exclude)
            ).limit(50).all()   # index-friendly; sample in Python
            suggested_users['random'] = _random.sample(candidates, min(4, len(candidates)))

    return show_suggestions, suggested_users


# ─────────────────────────────────────────────────────────────────────────────
# VALID CONTENT TYPES  (single source of truth — import from here if needed)
# ─────────────────────────────────────────────────────────────────────────────

VALID_CONTENT_TYPES = {'notes', 'cheatsheet', 'quiz', 'flashcards', 'mixed'}

# ── In-process TTL caches (no Redis required) ─────────────────────────────────
import time as _time

_subject_cache   = {'data': None, 'at': 0}
_programme_cache = {'data': None, 'at': 0}
_count_cache     = {'posts': None, 'subjects': None, 'at': 0}

def _get_active_subjects():
    """Cache active subjects for 5 minutes — they almost never change.
    Pre-computes video_count on each subject so templates don't need lazy loads."""
    now = _time.time()
    if not _subject_cache['data'] or now - _subject_cache['at'] > 300:
        subjects = Subject.query.filter_by(is_active=True).order_by(Subject.order, Subject.name).all()
        # Bulk-compute active video counts in a single query
        from sqlalchemy import func as sqlfunc_local
        video_counts = dict(
            db.session.query(VideoLesson.subject_id, sqlfunc_local.count(VideoLesson.id))
            .group_by(VideoLesson.subject_id)
            .all()
        )
        subjects_data = []
        for s in subjects:
            subjects_data.append(types.SimpleNamespace(
                id=s.id,
                name=s.name,
                slug=s.slug,
                video_count=video_counts.get(s.id, 0)
            ))
        _subject_cache['data'] = subjects_data
        _subject_cache['at'] = now
    return _subject_cache['data']

def _get_active_programmes(limit=6):
    """Cache active programmes for 5 minutes with pre-computed subject counts."""
    now = _time.time()
    if not _programme_cache['data'] or now - _programme_cache['at'] > 300:
        from app.models import Subject, subject_programme
        from sqlalchemy import func
        
        # Get active programmes
        programmes = Programme.query.filter_by(is_active=True).order_by(Programme.order, Programme.name).all()
        prog_ids = [p.id for p in programmes]
        
        # Bulk query subject counts
        subject_counts = dict(
            db.session.query(
                subject_programme.c.programme_id,
                func.count(Subject.id)
            )
            .join(Subject, Subject.id == subject_programme.c.subject_id)
            .filter(subject_programme.c.programme_id.in_(prog_ids), Subject.is_active == True)
            .group_by(subject_programme.c.programme_id)
            .all()
        )
        
        programmes_data = []
        for p in programmes:
            programmes_data.append(types.SimpleNamespace(
                id=p.id,
                name=p.name,
                subject_count=subject_counts.get(p.id, 0)
            ))
        _programme_cache['data'] = programmes_data
        _programme_cache['at'] = now
    return _programme_cache['data'][:limit]

def _get_post_counts():
    """Cache total post/subject counts for 2 minutes."""
    now = _time.time()
    if _count_cache['posts'] is None or now - _count_cache['at'] > 120:
        _count_cache['posts']    = Post.query.filter_by(status='approved').count()
        _count_cache['subjects'] = Subject.query.filter_by(is_active=True).count()
        _count_cache['at']       = now
    return _count_cache['posts'], _count_cache['subjects']

def _eager_posts_query(query):
    """Apply eager loading so post cards cause zero extra queries."""
    return query.options(
        joinedload(Post.subject),
        joinedload(Post.author),
    )


class _SimplePagination:
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = max(1, math.ceil(total / per_page)) if total else 1
        self.has_prev = page > 1
        self.has_next = page < self.pages
        self.prev_num = page - 1
        self.next_num = page + 1

    def iter_pages(self, left_edge=1, right_edge=1, left_current=2, right_current=2):
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (num > self.page - left_current - 1 and num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num


def _topic_key_from_text(value: str) -> str:
    text = (value or "").lower().strip()
    text = re.sub(r"\b(notes?|quiz(?:zes)?|cheat\s*sheet|cheatsheet|flashcards?|summary|guide|study\s+guide)\b", "", text)
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return text[:80] or "general-topic"


def _topic_info_from_post(post: Post) -> tuple[str, str]:
    meta = {}
    if getattr(post, "quiz", None) and getattr(post.quiz, "meta", None):
        try:
            parsed = json.loads(post.quiz.meta)
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            meta = {}

    label = (
        str(meta.get("topic_label") or "").strip()
        or str(meta.get("topic") or "").strip()
        or str(post.title or "").strip()
        or "General Topic"
    )
    key = str(meta.get("topic_key") or "").strip() or _topic_key_from_text(label)
    return key, label


def _subject_topic_groups(subject_id: int) -> list[dict]:
    # Hoist the VideoLesson query — run once, not once per post
    first_vid = (
        VideoLesson.query
        .filter_by(subject_id=subject_id)
        .order_by(VideoLesson.created_at.desc())
        .first()
    )
    first_youtube_id = first_vid.youtube_id if first_vid else None

    posts = (
        Post.query
        .filter(Post.subject_id == subject_id, Post.status == 'approved')
        .options(selectinload(Post.quiz))
        .order_by(Post.created_at.desc())
        .all()
    )

    subject = Subject.query.get(subject_id)
    groups: dict[str, dict] = {}
    for post in posts:
        topic_key, topic_label = _topic_info_from_post(post)
        bucket = groups.setdefault(
            topic_key,
            {
                "title": topic_label,
                "topic_key": topic_key,
                "topic_label": topic_label,
                "subject": subject,
                "subject_name": subject.name if subject else 'Study Pack',
                "color": subject.color if subject else '#2a5cff',
                "type": "topic_bundle",
                "notes": 0,
                "cheatsheet": 0,
                "quiz": 0,
                "total": 0,
                "total_count": 0,
                "resource_count": 0,
                "video_count": 0,
                "completed_count": 0,
                "progress_pct": 0,
                "latest_at": post.created_at,
                "first_video_youtube_id": first_youtube_id,
                "url": url_for('main.study_room_topic', subject_slug=subject.slug, topic_key=topic_key) if subject else '#',
            },
        )
        bucket["total"] += 1
        bucket["total_count"] = bucket["total"]
        bucket["resource_count"] = bucket["total"]
        if post.content_type in {"notes", "cheatsheet", "quiz"}:
            bucket[post.content_type] += 1
        if post.created_at and post.created_at > bucket["latest_at"]:
            bucket["latest_at"] = post.created_at

    return sorted(
        groups.values(),
        key=lambda row: (
            (row.get("latest_at") or datetime(1970, 1, 1, tzinfo=timezone.utc)),
            row.get("total", 0),
        ),
        reverse=True,
    )





_TOPIC_ICONS = [
    "atom",
    "flask",
    "compass-drafting",
    "diagram-project",
    "cubes",
    "bezier-curve",
    "wave-square",
    "brain",
]


def _topic_icon(topic_key: str) -> str:
    if not topic_key:
        return "layer-group"
    idx = sum(ord(ch) for ch in topic_key) % len(_TOPIC_ICONS)
    return _TOPIC_ICONS[idx]


def _build_topic_cards(
    posts: list[Post],
    like_counts: dict[int, int] | None = None,
    comment_counts: dict[int, int] | None = None,
) -> list[dict]:
    like_counts = like_counts or {}
    comment_counts = comment_counts or {}
    cards: dict[str, dict] = {}
    for post in posts:
        if not post.subject:
            continue

        topic_key, topic_label = _topic_info_from_post(post)
        card_key = f"{post.subject_id}:{topic_key}"

        if card_key not in cards:
            cards[card_key] = {
                "topic_key": topic_key,
                "topic_label": topic_label,
                "title": topic_label,
                "topic_icon": _topic_icon(topic_key),
                "subject": post.subject,
                "subject_name": post.subject.name,
                "color": post.subject.color or '#2a5cff',
                "type": "topic_bundle",
                "progress_pct": 0,
                "url": url_for('main.study_room_topic', subject_slug=post.subject.slug, topic_key=topic_key),
                "latest_at": post.created_at,
                "latest_post_id": post.id,
                "notes_post_id": None,
                "quiz_post_id": None,
                "cheatsheet_post_id": None,
                "notes_count": 0,
                "quiz_count": 0,
                "cheatsheet_count": 0,
                "total_count": 0,
                "resource_count": 0,
                "video_count": 0,
                "engagement_count": 0,
                "first_video_youtube_id": VideoLesson.query.filter_by(subject_id=post.subject_id).order_by(VideoLesson.created_at.desc()).first().youtube_id if VideoLesson.query.filter_by(subject_id=post.subject_id).first() else None
            }

        card = cards[card_key]
        card["total_count"] += 1
        card["resource_count"] = card["total_count"]
        card["engagement_count"] += like_counts.get(post.id, 0) + comment_counts.get(post.id, 0)

        if post.content_type == "notes":
            card["notes_count"] += 1
            if card["notes_post_id"] is None:
                card["notes_post_id"] = post.id
        elif post.content_type == "quiz":
            card["quiz_count"] += 1
            if card["quiz_post_id"] is None:
                card["quiz_post_id"] = post.id
        elif post.content_type == "cheatsheet":
            card["cheatsheet_count"] += 1
            if card["cheatsheet_post_id"] is None:
                card["cheatsheet_post_id"] = post.id

        if post.created_at and post.created_at > card["latest_at"]:
            card["latest_at"] = post.created_at
            card["latest_post_id"] = post.id

    return sorted(cards.values(), key=lambda c: c["latest_at"], reverse=True)


def _paginate_topic_cards(query, page: int, per_page: int):
    posts = (
        query
        .options(joinedload(Post.subject), selectinload(Post.quiz))
        .all()
    )
    post_ids = [p.id for p in posts if p.id is not None]
    like_counts = {}
    comment_counts = {}

    if post_ids:
        like_counts = dict(
            db.session.query(Like.post_id, db.func.count(Like.id))
            .filter(Like.post_id.in_(post_ids))
            .group_by(Like.post_id)
            .all()
        )
        comment_counts = dict(
            db.session.query(Comment.post_id, db.func.count(Comment.id))
            .filter(Comment.post_id.in_(post_ids))
            .group_by(Comment.post_id)
            .all()
        )

    cards = _build_topic_cards(posts, like_counts=like_counts, comment_counts=comment_counts)
    start = (page - 1) * per_page
    end = start + per_page
    return _SimplePagination(cards[start:end], page, per_page, len(cards))


def _user_has_saved_files(user_id: int) -> bool:
    """Saved files are bookmark entries used by the home continue strip."""
    if not user_id:
        return False
    return db.session.query(Bookmark.id).filter(Bookmark.user_id == user_id).first() is not None



# ─────────────────────────────────────────────────────────────────────────────
# MAIN ROUTES
# ─────────────────────────────────────────────────────────────────────────────

def _get_recommendation(user, user_subjects):
    """Return a single recommended action dict for the home page."""
    # 1. Find a quiz post the user hasn't attempted yet
    from sqlalchemy import select
    attempted_post_ids = select(QuizAttempt.post_id).where(QuizAttempt.user_id == user.id)
    
    if user_subjects:
        subject_ids = [s.id for s in user_subjects]
        quiz = Post.query.filter(
            Post.status == 'approved',
            Post.content_type == 'quiz',
            Post.subject_id.in_(subject_ids),
            ~Post.id.in_(attempted_post_ids)
        ).order_by(Post.created_at.desc()).first()
    else:
        quiz = Post.query.filter(
            Post.status == 'approved',
            Post.content_type == 'quiz',
            ~Post.id.in_(attempted_post_ids)
        ).order_by(Post.created_at.desc()).first()
    if quiz:
        title = quiz.title
        meta = quiz.subject.name if quiz.subject else 'Quiz'
        if ':' in title:
            title = title.split(':', 1)[1].strip()
        if ':' in meta:
            meta = meta.split(':', 1)[1].strip()
        return {
            'type': 'quiz',
            'title': title,
            'meta': meta,
            'url': url_for('posts.view', post_id=quiz.id),
            'icon': 'brain',
            'color': quiz.subject.color if quiz.subject else '#6366f1',
            'cta': 'Take quiz',
        }
    # 2. Find an unwatched video from their programme
    watched_ids = db.session.query(VideoCompletion.video_id).filter_by(user_id=user.id).subquery()
    if user_subjects:
        subject_ids = [s.id for s in user_subjects]
        video = VideoLesson.query.filter(
            VideoLesson.subject_id.in_(subject_ids),
            ~VideoLesson.id.in_(watched_ids)
        ).order_by(VideoLesson.created_at.desc()).first()
    else:
        video = VideoLesson.query.filter(
            ~VideoLesson.id.in_(watched_ids)
        ).order_by(VideoLesson.created_at.desc()).first()
    if video:
        title = video.title
        meta = video.subject.name if video.subject else 'Video'
        if ':' in title:
            title = title.split(':', 1)[1].strip()
        if ':' in meta:
            meta = meta.split(':', 1)[1].strip()
        return {
            'type': 'video',
            'title': title,
            'meta': meta,
            'url': url_for('main.video_player', video_id=video.id),
            'icon': 'play-circle',
            'color': video.subject.color if video.subject else '#2563eb',
            'cta': f'Watch · +{video.xp_reward} XP',
        }
    return None
    

@bp.route('/join')
def join():
    """Landing CTA → sets the visited cookie and redirects to index with modal open."""
    from flask import make_response, redirect, url_for, current_app
    response = make_response(redirect(url_for('main.index', signup='1')))
    response.set_cookie(
        'knowly_visited', '1',
        max_age=60 * 60 * 24 * 30,
        samesite='Lax',
        secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
    )
    return response

@bp.route('/')
@bp.route('/index')
@turbo_frame('main-content', 'frames/index.html', 'index.html')
def index():
    # Check if user came from landing with signup parameter - always show index in this case
    signup_param = request.args.get('signup')
    
    if not current_user.is_authenticated:
        # First-time visitors see the landing/marketing page.
        # A 30-day cookie marks them as returning so subsequent visits
        # land directly on the feed.
        if not request.cookies.get('knowly_visited') and not signup_param:
            response = make_response(redirect(url_for('main.landing')))
            response.set_cookie(
                'knowly_visited', '1',
                max_age=60 * 60 * 24 * 30,   # 30 days
                samesite='Lax',
                secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
            )
            return response

        # Returning guest — show the home feed without user-specific content
        page = request.args.get('page', 1, type=int)
        subjects_param = request.args.get('subjects', '') or request.args.get('subject', '')
        selected_subjects = []
        if subjects_param:
            try:
                selected_subjects = [int(sid) for sid in subjects_param.split(',') if sid.strip()]
            except ValueError:
                pass
        query = Post.query.filter(Post.status == 'approved')
        if selected_subjects:
            query = query.filter(Post.subject_id.in_(selected_subjects))
        query = query.order_by(Post.created_at.desc())
        topic_cards = _paginate_topic_cards(
            query,
            page=page,
            per_page=current_app.config['POSTS_PER_PAGE'],
        )
        subjects       = _get_active_subjects()
        total_posts, total_subjects = _get_post_counts()
        all_subjects   = subjects[:10]
        guest_programmes = _get_active_programmes(limit=6)
        return dict(
            title='Home',
            xp_reward=XP_REWARD,
            topic_cards=topic_cards,
            feed_type='home',
            subjects=subjects,
            selected_subjects=selected_subjects,
            show_suggestions=False,
            suggested_users=[],
            programmes=guest_programmes,
            user_programme=None,
            user_subjects=[],
            all_subjects=all_subjects,
            total_posts=total_posts,
            total_subjects=total_subjects,
            has_saved_files=False,
            attempted_quiz_ids=set(),
        )

    


    # Get cached programmes (now with pre-computed counts)
    programmes = _get_active_programmes(limit=6)

    user_programme = None
    user_subjects  = []
    if current_user.programme:
        user_programme = Programme.query.filter(
            sqlfunc.lower(Programme.name).contains(current_user.programme.lower())
        ).first()
        if user_programme:
            # user_programme.subjects is an InstrumentedList, not a query
            user_subjects = [s for s in user_programme.subjects if s.is_active]
            user_subjects = sorted(user_subjects, key=lambda s: (s.order, s.name))[:8]

    all_subjects = _get_active_subjects()[:8]

    show_suggestions, suggested_users = _build_suggestions()

    page = request.args.get('page', 1, type=int)
    subjects_param = request.args.get('subjects', '')
    selected_subjects = []
    if subjects_param:
        try:
            # Support both single and comma-separated values
            selected_subjects = [int(sid) for sid in subjects_param.split(',') if sid.strip().isdigit()]
        except ValueError:
            selected_subjects = []

    query = Post.query.filter(Post.status == 'approved')
    if selected_subjects:
        query = query.filter(Post.subject_id.in_(selected_subjects))
    elif user_programme and user_subjects:
        prog_subject_ids = [s.id for s in user_subjects]
        query = query.filter(Post.subject_id.in_(prog_subject_ids))
    query = query.order_by(Post.created_at.desc())
    topic_cards = _paginate_topic_cards(
        query,
        page=page,
        per_page=current_app.config['POSTS_PER_PAGE'],
    )

    subjects = _get_active_subjects()
    programmes = _get_active_programmes(limit=6)

    user_programme = None
    user_subjects  = []
    if current_user.programme:
        user_programme = Programme.query.filter(
            sqlfunc.lower(Programme.name).contains(current_user.programme.lower())
        ).first()
        if user_programme:
            user_subjects = [s for s in user_programme.subjects if s.is_active]
            user_subjects = sorted(user_subjects, key=lambda s: (s.order, s.name))[:8]

    all_subjects   = _get_active_subjects()[:8]
    total_posts, total_subjects = _get_post_counts()
    has_saved_files = _user_has_saved_files(current_user.id)

    # Quiz post IDs this user has already attempted — used for "completed" badges on bundle cards
    attempted_quiz_ids = set(
        r[0] for r in db.session.query(QuizAttempt.post_id)
        .filter(QuizAttempt.user_id == current_user.id)
        .all()
    )

    # Video strip — pull from user's programme subjects first, fall back to global
    home_videos = []
    if user_programme and user_subjects:
        subject_ids = [s.id for s in user_subjects]
        home_videos = (VideoLesson.query
                       .filter(VideoLesson.subject_id.in_(subject_ids))
                       .order_by(VideoLesson.created_at.desc())
                       .all())
    if not home_videos:
        home_videos = (VideoLesson.query
                       .order_by(VideoLesson.created_at.desc())
                       .all())

    # Select up to 3 random videos for homepage
    if len(home_videos) > 3:
        videos = random.sample(home_videos, 3)
    else:
        videos = home_videos

    # Active packs for the resume banner
    active_packs = []
    continue_title = None
    if current_user.is_authenticated:
        active_packs = (
            Post.query
            .filter_by(user_id=current_user.id, status='approved')
            .filter((Post.completion_pct == None) | (Post.completion_pct < 100))
            .order_by(Post.updated_at.desc())
            .limit(5)
            .all()
        )
        
        # Most recent activity title for headline
        last_vc = VideoCompletion.query.filter_by(user_id=current_user.id).order_by(VideoCompletion.created_at.desc()).first()
        last_pack = Post.query.filter_by(user_id=current_user.id, status='approved').order_by(Post.updated_at.desc()).first()
        
        if last_vc and last_pack:
            if last_vc.created_at > last_pack.updated_at:
                continue_title = last_vc.video.title
            else:
                continue_title = last_pack.title
        elif last_vc:
            continue_title = last_vc.video.title
        elif last_pack:
            continue_title = last_pack.title
        else:
            continue_title = current_user.programme or 'studying'

    return dict(
        title='Home',
        xp_reward=XP_REWARD,
        topic_cards=topic_cards,
        feed_type='home',
        subjects=subjects,
        selected_subjects=selected_subjects,
        show_suggestions=show_suggestions,
        suggested_users=suggested_users,
        programmes=programmes,
        user_programme=user_programme,
        user_subjects=user_subjects,
        all_subjects=all_subjects,
        total_posts=total_posts,
        total_subjects=total_subjects,
        has_saved_files=has_saved_files,
        # leaderboard=top_users,  # TODO: implement if needed
        # user_rank=user_rank,
        videos=videos,

        attempted_quiz_ids=attempted_quiz_ids,
        now=__import__('datetime').datetime.now(),
        recommended=_get_recommendation(current_user, user_subjects),
        posts=topic_cards,
        active_packs=active_packs,
        continue_title=continue_title,
    )

@bp.route('/api/programmes')
def api_programmes():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    progs = Programme.query.filter(
        Programme.name.ilike(f'%{q}%')
    ).order_by(Programme.name).limit(10).all()
    return jsonify([p.name for p in progs])
    

@bp.app_context_processor
def inject_programmes():
    from app.models import Programme
    return dict(programmes=Programme.query.filter_by(is_active=True).order_by(Programme.name).all())

@bp.route('/landing')
def landing():
    """Landing/marketing page — always accessible directly."""
    return render_template('landing.html', title='Welcome')

@bp.route('/api/stats')
def api_stats():
    docs        = Document.query.count()
    users       = User.query.count()
    subjects    = Subject.query.filter_by(is_active=True).count()
    likes       = Like.query.count()
    comments    = Comment.query.count()
    engagements = likes + comments

    return jsonify({
        'documents':    docs,
        'users':        users,
        'subjects':     subjects,
        'engagements':  engagements,
    })

@bp.route('/feed')
@turbo_frame('main-content', 'frames/index.html', 'index.html')
@login_required
def feed():
    

    show_suggestions, suggested_users = _build_suggestions()

    page = request.args.get('page', 1, type=int)
    subjects_param = request.args.get('subjects', '')

    selected_subjects = []
    if subjects_param:
        try:
            # Support both single and comma-separated values
            selected_subjects = [int(sid) for sid in subjects_param.split(',') if sid.strip().isdigit()]
        except ValueError:
            selected_subjects = []

    following_ids = [user.id for user in current_user.following.all()]

    if following_ids:
        query = Post.query.filter(
            Post.status == 'approved',
            or_(
                Post.user_id.in_(following_ids),
                Post.user_id == current_user.id
            )
        )
    else:
        query = Post.query.filter(
            Post.status == 'approved',
            Post.user_id == current_user.id
        )

    if selected_subjects:
        query = query.filter(Post.subject_id.in_(selected_subjects))

    query = query.order_by(Post.created_at.desc())
    topic_cards = _paginate_topic_cards(
        query,
        page=page,
        per_page=current_app.config['POSTS_PER_PAGE'],
    )

    subjects = _get_active_subjects()
    programmes = _get_active_programmes(limit=6)

    user_programme = None
    user_subjects  = []
    if current_user.programme:
        user_programme = Programme.query.filter(
            sqlfunc.lower(Programme.name).contains(current_user.programme.lower())
        ).first()
        if user_programme:
            user_subjects = [s for s in user_programme.subjects if s.is_active]
            user_subjects = sorted(user_subjects, key=lambda s: (s.order, s.name))[:8]

    all_subjects   = _get_active_subjects()[:8]
    total_posts, total_subjects = _get_post_counts()
    has_saved_files = _user_has_saved_files(current_user.id)

    # Quiz post IDs this user has already attempted — used for "completed" badges on bundle cards
    attempted_quiz_ids = set(
        r[0] for r in db.session.query(QuizAttempt.post_id)
        .filter(QuizAttempt.user_id == current_user.id)
        .all()
    )

    return dict(
        title='Home',
        topic_cards=topic_cards,
        feed_type='personal',
        subjects=subjects,
        selected_subjects=selected_subjects,
        show_suggestions=show_suggestions,
        suggested_users=suggested_users,
        programmes=programmes,
        user_programme=user_programme,
        user_subjects=user_subjects,
        all_subjects=all_subjects,
        total_posts=total_posts,
        total_subjects=total_subjects,
        has_saved_files=has_saved_files,
    )

@bp.route('/search')
@turbo_frame('main-content', 'frames/search.html', 'search.html')
def search():
    """Search results page for the new Search Hub."""
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    study_mode = request.args.get('study', '0') == '1' or None
    subjects_param = request.args.get('subjects', '')
    selected_type = request.args.get('type', '').strip().lower() or None

    # Handle subject filtering logic
    selected_subjects = []
    if subjects_param:
        try:
            # Support both single and comma-separated values
            selected_subjects = [int(sid) for sid in subjects_param.split(',') if sid.strip().isdigit()]
        except ValueError:
            selected_subjects = []

    # Base query for approved study packs
    query = StudyPack.query.options(joinedload(StudyPack.subject))

    if search_query:
        like_pat = f'%{search_query}%'
        query = query.filter(
            StudyPack.title.ilike(like_pat) | 
            StudyPack.topic_slug.ilike(like_pat)
        )

    if selected_subjects:
        query = query.filter(StudyPack.subject_id.in_(selected_subjects))

    query = query.order_by(StudyPack.view_count.desc(), StudyPack.created_at.desc())

    # Paginate StudyPack results
    packs = query.all()
    
    # Process into cards (adding progress if authenticated)
    completed_vid_ids = set()
    if current_user.is_authenticated:
        completed_records = VideoCompletion.query.filter_by(user_id=current_user.id).all()
        completed_vid_ids = {vc.video_id for vc in completed_records}

    topic_cards_list = []
    for pack in packs:
        card = format_pack_data(pack, current_user.id if current_user.is_authenticated else None)
        card['topic_key'] = pack.topic_slug
        topic_cards_list.append(card)

    start = (page - 1) * 20
    end = start + 20
    topic_cards = _SimplePagination(topic_cards_list[start:end], page, 20, len(topic_cards_list))

    # Context data for filters
    subjects = _get_active_subjects()
    total_posts, total_subjects = _get_post_counts()

    return dict(
        title=f'Search: {search_query}' if search_query else 'Search Study Packs',
        topic_cards=topic_cards,
        query=search_query,
        subjects=subjects,
        subject_id=None,           # no single-subject filter on this route
        content_type='',           # no content_type filter — StudyPack has no content_type
        users=[],                  # no user results on this route
        total_results=len(topic_cards_list),
        is_pack_search=True,       # signals template to hide type-filter chips
    )

@bp.route('/study-room/<subject_slug>/<topic_key>')
def study_room_topic(subject_slug, topic_key):
    """
    Unified entry point for a study pack/topic.
    Resolves the first video for the topic and loads the Study Room.
    If no video is found, it still opens the room to show resources.
    """
    subject = Subject.query.filter_by(slug=subject_slug, is_active=True).first()
    
    # 1. Try to find the first video for this topic
    vid = VideoLesson.query.filter(
        (VideoLesson.topic_slug == topic_key) | 
        (VideoLesson.title.ilike(f"%{topic_key.replace('-', ' ')}%"))
    ).order_by(VideoLesson.order_index.asc(), VideoLesson.created_at.desc()).first()
    
    if vid:
        return redirect(url_for('main.video_player', video_id=vid.id))
        
    # 2. If no video found, try any video in the subject
    if subject:
        fallback_vid = VideoLesson.query.filter_by(subject_id=subject.id).first()
        if fallback_vid:
            return redirect(url_for('main.video_player', video_id=fallback_vid.id))
            
    flash("This study pack is still being prepared. Check back soon!", "info")
    return redirect(url_for('main.library'))


@bp.route('/leaderboard')
@login_required
@turbo_frame('main-content', 'frames/leaderboard.html', 'leaderboard.html')
def leaderboard():
    top_users = User.query.filter(User.is_active == True, User.xp_points > 0).order_by(User.xp_points.desc()).limit(100).all()
    user_rank = None
    if current_user.is_authenticated:
        user_rank = User.query.filter(User.xp_points > current_user.xp_points, User.is_active == True).count() + 1
    return dict(title='Global Leaderboard', top_users=top_users, user_rank=user_rank)


@bp.route('/about')
@turbo_frame('main-content', 'frames/about.html', 'about.html')
def about():
    return dict(title='About')


@bp.route('/terms')
def terms():
    return render_template('terms.html', title='Terms of Service')


@bp.route('/library')
@turbo_frame('main-content', 'frames/library_index.html', 'library/index.html')
def library():
    # Show all curated study packs
    user_programme = None
    packs_query = StudyPack.query.filter_by(is_curated=True).options(joinedload(StudyPack.subject))
        
    if current_user.is_authenticated and current_user.programme:
        user_programme = Programme.query.filter(
            func.lower(Programme.name).contains(current_user.programme.lower())
        ).first()

    packs = packs_query.order_by(StudyPack.created_at.desc()).all()
    
    completed_vid_ids = set()
    if current_user.is_authenticated:
        completed_records = VideoCompletion.query.filter_by(user_id=current_user.id).all()
        completed_vid_ids = {vc.video_id for vc in completed_records}

    topic_cards = []
    for pack in packs:
        topic_cards.append(format_pack_data(pack, current_user.id if current_user.is_authenticated else None))

    topic_cards.sort(key=lambda x: (x['progress_pct'] > 0 and x['progress_pct'] < 100), reverse=True)

    return dict(
        title='Library',
        bundles=topic_cards,  # Template uses 'bundles' variable name
        topic_cards=topic_cards,  # Keep for backwards compatibility
        user_programme=user_programme,
    )


@bp.route('/library/faculty/<faculty_slug>')
def library_faculty(faculty_slug):
    """Faculty page — shows all programmes within a faculty."""

    def _slugify(text):
        text = text.lower()
        text = text.replace("'", '').replace('&', 'and').replace('/', '')
        text = re.sub(r'[-\s]+', '-', text)
        text = re.sub(r'[^\w-]', '', text)
        return text.strip('-')

    all_programmes = Programme.query.filter_by(is_active=True).all()

    # Handle unassigned
    if faculty_slug == 'unassigned':
        faculty_name = 'Unassigned'
        programmes   = [p for p in all_programmes if not p.faculty]
    else:
        faculty_name = None
        programmes   = []
        for p in all_programmes:
            if p.faculty and _slugify(p.faculty) == faculty_slug:
                faculty_name = p.faculty
                programmes.append(p)

    if not programmes:
        abort(404)

    programmes.sort(key=lambda p: p.name)

    return render_template(
        'library/faculty.html',
        title=faculty_name,
        faculty_name=faculty_name,
        faculty_slug=faculty_slug,
        programmes=programmes,
    )

@bp.route('/library/programme/<slug>')
@turbo_frame('main-content', 'frames/library_programme.html', 'library/programme.html')
def library_programme(slug):
    """Programme page — shows all subjects/courses within a programme."""
    programme = Programme.query.filter_by(slug=slug, is_active=True).first_or_404()
    subjects = Subject.query.filter(
        Subject.is_active == True,
        Subject.programmes.any(Programme.id == programme.id)
    ).order_by(Subject.order, Subject.name).all()

    subject_ids = [s.id for s in subjects]
    latest_bundles_by_subject = {s.id: [] for s in subjects}
    
    if subject_ids:
        # Fetch curated packs for all subjects in the programme
        packs = StudyPack.query.filter(
            StudyPack.subject_id.in_(subject_ids),
            StudyPack.is_curated == True
        ).options(joinedload(StudyPack.subject)).order_by(StudyPack.created_at.desc()).all()
        
        completed_vid_ids = set()
        if current_user.is_authenticated:
            completed_records = VideoCompletion.query.filter_by(user_id=current_user.id).all()
            completed_vid_ids = {vc.video_id for vc in completed_records}

        for pack in packs:
            card = format_pack_data(pack, current_user.id if current_user.is_authenticated else None)
            card['gradient'] = gradients[idx % len(gradients)]
            
            if len(latest_bundles_by_subject[pack.subject_id]) < 5:
                latest_bundles_by_subject[pack.subject_id].append(card)

    return dict(
        title=programme.name,
        programme=programme,
        subjects=subjects,
        latest_bundles_by_subject=latest_bundles_by_subject,
    )

# ─────────────────────────────────────────────────────────────────────────────
# SUBJECT PAGE  — the key fix
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/library/subject/<slug>')
@turbo_frame('main-content', 'frames/subject_topics.html', 'library/subject_topics.html')
def library_subject(slug):
    """
    Subject page now defaults to topic directories.
    Legacy tabbed listing is available on the topic-detail route.
    """
    subject = Subject.query.filter_by(slug=slug, is_active=True).first_or_404()

    programme = None
    from_slug = request.args.get('from', '')
    if from_slug:
        candidate = Programme.query.filter_by(slug=from_slug, is_active=True).first()
        if candidate and candidate in subject.programmes:
            programme = candidate
    if not programme:
        programme = Programme.query.filter(
            Programme.subjects.any(id=subject.id),
            Programme.is_active == True
        ).first()

    topic_groups = _subject_topic_groups(subject.id)

    return dict(
        title=f'{subject.name} — Library',
        subject=subject,
        programme=programme,
        topic_groups=topic_groups,
    )


# LEGACY REDIRECT STUB — safe to delete once old /library/subject/<slug>/topic/<topic_key>
# URLs are confirmed out of circulation. The only template that generated these links
# (library/subject.html) has been deleted. No live code generates this URL pattern.
@bp.route('/library/subject/<slug>/topic/<topic_key>')
def library_subject_topic(slug, topic_key):
    return redirect(url_for('main.study_room_topic', subject_slug=slug, topic_key=topic_key))


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS API
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/notifications')
@login_required
def notifications():
    """Return the 30 most recent notifications for the current user."""
    notifs = (
        Notification.query
        .filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(30)
        .all()
    )
    return jsonify([{
        'id':      n.id,
        'message': n.message,
        'type':    n.notification_type,
        'link':    n.link,
        'is_read': n.is_read,
        'created_at': n.created_at.isoformat(),
    } for n in notifs])


@bp.route('/notifications/mark-read', methods=['POST'])
@login_required
def notifications_mark_read():
    """Mark all unread notifications as read."""
    Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False,
    ).update({'is_read': True})
    db.session.commit()
    return jsonify({'status': 'ok'})


_notif_cache: dict = {}  # {user_id: (count, timestamp)}

@bp.route('/notifications/unread-count')
@login_required
def notifications_unread_count():
    """Lightweight poll endpoint for the nav badge. Cached 30s per user."""
    import time as _t
    uid = current_user.id
    cached = _notif_cache.get(uid)
    if cached and _t.time() - cached[1] < 30:
        return jsonify({'count': cached[0]})
    count = Notification.query.filter_by(user_id=uid, is_read=False).count()
    _notif_cache[uid] = (count, _t.time())
    return jsonify({'count': count})


def invalidate_notif_cache(user_id):
    """Call this when notifications are marked read."""
    _notif_cache.pop(user_id, None)


# ─────────────────────────────────────────────────────────────────────────────
# PWA — Offline fallback page
# Served by the service worker when a navigation request fails with no cache.
# Must be a real route so the SW can pre-cache it during install.
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/debug-storage')
def debug_storage():
    d = Document.query.first()
    if not d:
        return "No documents in DB"
    return f"file_path: {d.file_path}<br>sidecar: {d.json_sidecar_path}"

    
@bp.route('/offline')
def offline():
    """PWA offline fallback page."""
    return render_template('offline.html'), 200


# ─────────────────────────────────────────────────────────────────────────────
# USER DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
@bp.route('/dashboard')
@login_required
@turbo_frame('main-content', 'frames/dashboard.html', 'dashboard.html')
def dashboard():
    """
    Personal progress dashboard.
    Shows XP, streaks, rank, and learning history.
    """
    # 1. Rank calculation (Optimized)
    rank = User.query.filter(User.xp_points > current_user.xp_points).count() + 1
    
    # 2. XP This week
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    weekly_aura = db.session.query(sqlfunc.sum(AuraTransaction.amount)).filter(
        AuraTransaction.user_id == current_user.id,
        AuraTransaction.created_at >= seven_days_ago
    ).scalar() or 0
    
    # 3. Total completed videos
    total_completed_videos = VideoCompletion.query.filter_by(user_id=current_user.id).count()
    
    # 4. Pack Progress
    # Get user's completed video IDs
    completed_records = VideoCompletion.query.filter_by(user_id=current_user.id).all()
    completed_vid_ids = {vc.video_id for vc in completed_records}
    
    # Streak at risk calculation
    today = _date.today()
    yesterday = today - timedelta(days=1)
    streak_at_risk = False
    if current_user.current_streak > 0:
        # If last activity was yesterday and no activity today, it's at risk
        if current_user.last_activity_date == yesterday:
            streak_at_risk = True
    
    # Find packs the user has interacted with (via completed videos)
    active_pack_ids = db.session.query(StudyPackVideo.pack_id).filter(
        StudyPackVideo.video_id.in_(completed_vid_ids)
    ).distinct().all()
    active_pack_ids = [p[0] for p in active_pack_ids]
    
    active_packs_objs = StudyPack.query.options(joinedload(StudyPack.subject)).filter(StudyPack.id.in_(active_pack_ids)).all()
    
    in_progress_packs = []
    completed_packs = []
    
    gradients = [
        'linear-gradient(135deg, #7c6af7 0%, #a291f9 100%)',
        'linear-gradient(135deg, #3ddc84 0%, #6be5a1 100%)',
        'linear-gradient(135deg, #f5c542 0%, #f7d67a 100%)',
        'linear-gradient(135deg, #f06b6b 0%, #f49292 100%)',
        'linear-gradient(135deg, #60a5fa 0%, #93c5fd 100%)'
    ]

    for idx, pack in enumerate(active_packs_objs):
        videos = pack.videos
        if not videos:
            continue
        
        pack_item = format_pack_data(pack, current_user.id if current_user.is_authenticated else None)
        pack_item['gradient'] = gradients[idx % len(gradients)]
        
        if pack_item['completed_count'] == pack_item['total_count']:
            # Find completion date
            last_vc = VideoCompletion.query.filter(
                VideoCompletion.user_id == current_user.id,
                VideoCompletion.video_id.in_([spv.video_id for spv in videos])
            ).order_by(VideoCompletion.created_at.desc()).first()
            pack_item['completed_at'] = last_vc.created_at if last_vc else pack.created_at
            
            # first_video_id for review
            sorted_vids = sorted(videos, key=lambda v: v.order_index)
            pack_item['first_video_id'] = sorted_vids[0].video_id if sorted_vids else None
            pack_item['first_video_youtube_id'] = sorted_vids[0].video.youtube_id if sorted_vids and sorted_vids[0].video else None
            pack_item['url'] = url_for('main.video_player', video_id=pack_item['first_video_id']) if pack_item['first_video_id'] else '#'
            completed_packs.append(pack_item)
        else:
            # next_video_id
            sorted_vids = sorted(videos, key=lambda v: v.order_index)
            unfinished = [v for v in sorted_vids if v.video_id not in completed_vid_ids]
            pack_item['next_video_id'] = unfinished[0].video_id if unfinished else videos[0].video_id
            pack_item['first_video_youtube_id'] = sorted_vids[0].video.youtube_id if sorted_vids and sorted_vids[0].video else None
            pack_item['url'] = url_for('main.video_player', video_id=pack_item['next_video_id'])
            in_progress_packs.append(pack_item)

    # Sort completed packs by date desc
    completed_packs.sort(key=lambda x: x.get('completed_at', datetime.min), reverse=True)
    
    # Recent Activity (Activity Feed)
    recent_txs = AuraTransaction.query.filter_by(user_id=current_user.id).order_by(AuraTransaction.created_at.desc()).limit(8).all()
    recent_activity = []
    for tx in recent_txs:
        act_type = 'video' if 'Video' in tx.reason else 'quiz'
        
        # Humanize time ago
        diff = datetime.now(timezone.utc) - tx.created_at.replace(tzinfo=timezone.utc)
        if diff.days > 0:
            time_ago = f"{diff.days}d ago"
        elif diff.seconds > 3600:
            time_ago = f"{diff.seconds // 3600}h ago"
        elif diff.seconds > 60:
            time_ago = f"{diff.seconds // 60}m ago"
        else:
            time_ago = "Just now"
            
        recent_activity.append({
            'title': tx.reason,
            'time_ago': time_ago,
            'xp': tx.amount,
            'type': act_type
        })


    return dict(
        rank=rank,
        total_xp_this_week=weekly_aura,
        total_completed_packs=len(completed_packs),
        in_progress_packs=in_progress_packs,
        completed_packs=completed_packs,
        recent_activity=recent_activity,
        streak_at_risk=streak_at_risk,
    )



# ─────────────────────────────────────────────────────────────────────────────
# PWA — serve SW from root so its scope covers the whole app
# ─────────────────────────────────────────────────────────────────────────────
@bp.route('/sw.js')
def service_worker():
    response = make_response(
        send_from_directory(current_app.static_folder, 'sw.js')
    )
    response.headers['Content-Type']  = 'application/javascript'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Service-Worker-Allowed'] = '/'
    return response


import markdown2

@bp.route('/markdown', methods=['POST'])
def render_markdown():
    text = request.get_json().get('text')
    if not text:
        return ""
    # This converts markdown to HTML strings
    return markdown2.markdown(text)
    # This converts markdown to HTML strings
    return markdown2.markdown(text)