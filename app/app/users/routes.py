    # ...existing imports...

# Settings page route (must be after bp is defined)

import cloudinary.uploader
import json
import math
import re
from flask import render_template, redirect, url_for, flash, request, current_app, session, jsonify
from app.models import User, Post, Bookmark, VideoBookmark, VideoLesson, Programme, Subject, StudyPack, StudyPackVideo
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from sqlalchemy.orm import selectinload, joinedload
from app import db
from app.users import bp
from app.forms import EditProfileForm, SearchForm
from app.utils.turbo import turbo_frame



_TOPIC_ICONS = [
    'atom',
    'flask',
    'compass-drafting',
    'diagram-project',
    'cubes',
    'bezier-curve',
    'wave-square',
    'brain',
]


def _topic_icon(topic_key: str) -> str:
    if not topic_key:
        return 'layer-group'
    return _TOPIC_ICONS[sum(ord(ch) for ch in topic_key) % len(_TOPIC_ICONS)]


def _topic_key_from_text(value: str) -> str:
    text = (value or '').lower().strip()
    text = re.sub(r"\b(notes?|quiz(?:zes)?|cheat\s*sheet|cheatsheet|flashcards?|summary|guide|study\s+guide)\b", '', text)
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text).strip('-')
    return text[:80] or 'general-topic'


def _topic_info_from_post(post: Post):
    meta = {}
    if getattr(post, 'quiz', None) and getattr(post.quiz, 'meta', None):
        try:
            parsed = json.loads(post.quiz.meta)
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            meta = {}

    label = (
        str(meta.get('topic_label') or '').strip()
        or str(meta.get('topic') or '').strip()
        or str(post.title or '').strip()
        or 'General Topic'
    )
    key = str(meta.get('topic_key') or '').strip() or _topic_key_from_text(label)
    return key, label

def _build_topic_cards(posts, like_counts=None, comment_counts=None):
    like_counts = like_counts or {}
    comment_counts = comment_counts or {}
    cards = {}
    for post in posts:
        if not post.subject:
            continue
        topic_key, topic_label = _topic_info_from_post(post)
        card_key = f"{post.subject_id}:{topic_key}"
        if card_key not in cards:
            cards[card_key] = {
                "topic_key": topic_key,
                "topic_label": topic_label,
                "topic_icon": _topic_icon(topic_key),
                "subject": post.subject,
                "latest_at": post.created_at,
                "notes_post_id": None,
                "quiz_post_id": None,
                "cheatsheet_post_id": None,
                "notes_count": 0,
                "quiz_count": 0,
                "cheatsheet_count": 0,
                "total_count": 0,
                "engagement_count": 0,
            }
        card = cards[card_key]
        card["total_count"] += 1
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
    return sorted(cards.values(), key=lambda c: c["latest_at"], reverse=True)


@bp.route('/profile/<username>')
@turbo_frame('main-content', 'frames/profile.html', 'users/profile.html')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    page = request.args.get('page', 1, type=int)
    per_page = 12

    is_own_profile = current_user.is_authenticated and current_user.id == user.id
    if is_own_profile:
        posts = user.posts.order_by(Post.created_at.desc()).all()
    else:
        posts = user.posts.filter_by(status='approved').order_by(Post.created_at.desc()).all()

    topic_cards_list = _build_topic_cards(posts)
    total = len(topic_cards_list)
    pages = max(1, math.ceil(total / per_page)) if total else 1
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    page_items = topic_cards_list[start:start + per_page]

    topic_cards = page_items

    # Fetch saved bookmarks — only shown on own profile, as topic bundles
    saved_topic_cards = []
    if is_own_profile:
        saved_bookmarks = (
            Bookmark.query
            .filter_by(user_id=user.id)
            .options(selectinload(Bookmark.post).selectinload(Post.subject))
            .order_by(Bookmark.created_at.desc())
            .all()
        )
        posts_from_bookmarks = [b.post for b in saved_bookmarks if b.post and b.post.subject]
        saved_topic_cards = _build_topic_cards(posts_from_bookmarks)[:8]

    # Fetch quiz attempts — only shown on own profile
    quiz_attempts = []
    quiz_stats = {'total': 0, 'avg_score': 0, 'perfect': 0}
    if is_own_profile:
        from app.models import QuizAttempt
        quiz_attempts = (
            QuizAttempt.query
            .filter_by(user_id=user.id)
            .order_by(QuizAttempt.created_at.desc())
            .limit(20)
            .all()
        )
        if quiz_attempts:
            total   = len(quiz_attempts)
            avg     = round(sum(a.score_pct for a in quiz_attempts) / total, 1)
            perfect = sum(1 for a in quiz_attempts if a.score_pct >= 100)
            quiz_stats = {'total': total, 'avg_score': avg, 'perfect': perfect}

    from datetime import date

    referral_count = user.referrals.count() if is_own_profile else 0

    return dict(
                           title=f'{user.username}\'s Profile',
                           user=user,
                           topic_cards=topic_cards,
                           total_cards=total,
                           page=page,
                           pages=pages,
                           is_own_profile=is_own_profile,
                           saved_topic_cards=saved_topic_cards,
                           quiz_attempts=quiz_attempts,
                           quiz_stats=quiz_stats,
                           referral_count=referral_count,
                           today=date.today())

@bp.route('/bookmarks')
@login_required
@turbo_frame('main-content', 'frames/bookmarks.html', 'users/bookmarks.html')
def bookmarks():
    page = request.args.get('page', 1, type=int)
    per_page = 12

    # 1. Fetch Study Packs (Video-based)
    # Get user's completed and bookmarked video IDs
    from app.models import VideoCompletion, VideoBookmark, StudyPack, StudyPackVideo, Post, Bookmark
    
    completed_records = VideoCompletion.query.filter_by(user_id=current_user.id).all()
    completed_vid_ids = {vc.video_id for vc in completed_records}
    
    bookmarked_records = VideoBookmark.query.filter_by(user_id=current_user.id).all()
    bookmarked_vid_ids = {vb.video_id for vb in bookmarked_records}
    
    interacted_vid_ids = completed_vid_ids.union(bookmarked_vid_ids)
    
    # Find packs containing these videos
    active_pack_ids = db.session.query(StudyPackVideo.pack_id).filter(
        StudyPackVideo.video_id.in_(list(interacted_vid_ids)) if interacted_vid_ids else db.false()
    ).distinct().all()
    active_pack_ids = [p[0] for p in active_pack_ids]
    
    active_packs_objs = StudyPack.query.options(
        selectinload(StudyPack.videos).joinedload(StudyPackVideo.video),
        joinedload(StudyPack.subject)
    ).filter(StudyPack.id.in_(active_pack_ids)).all()
    
    unified_bundles = []
    
    for pack in active_packs_objs:
        videos = pack.videos
        if not videos:
            continue

        total_vids = len(videos)
        completed_count = sum(1 for spv in videos if spv.video_id in completed_vid_ids)
        progress_pct = int((completed_count / total_vids) * 100) if total_vids > 0 else 0

        # Determine latest activity for sorting
        latest_ts = pack.created_at
        # Check completion timestamps
        pack_vid_ids = [spv.video_id for spv in videos]
        last_vc = VideoCompletion.query.filter(
            VideoCompletion.user_id == current_user.id,
            VideoCompletion.video_id.in_(pack_vid_ids)
        ).order_by(VideoCompletion.created_at.desc()).first()
        if last_vc and last_vc.created_at > latest_ts:
            latest_ts = last_vc.created_at

        # Check bookmark timestamps
        last_vb = VideoBookmark.query.filter(
            VideoBookmark.user_id == current_user.id,
            VideoBookmark.video_id.in_(pack_vid_ids)
        ).order_by(VideoBookmark.created_at.desc()).first()
        if last_vb and last_vb.created_at > latest_ts:
            latest_ts = last_vb.created_at

        # Find first uncompleted video for the "Continue" button
        next_vid_id = None
        sorted_vids = sorted(videos, key=lambda v: v.order_index)
        for spv in sorted_vids:
            if spv.video_id not in completed_vid_ids:
                next_vid_id = spv.video_id
                break

        if next_vid_id is None and sorted_vids:
            next_vid_id = sorted_vids[0].video_id

        # Build a more descriptive title for generic uncategorized packs
        display_title = pack.title
        if pack.title and 'Uncategorized' in pack.title:
            display_title = f"{pack.title} (#{pack.id})"

        unified_bundles.append({
            'type': 'study_pack',
            'id': pack.id,
            'title': display_title,
            'subject_name': pack.subject.name if pack.subject else 'Study Pack',
            'subject': pack.subject,
            'color': pack.subject.color if pack.subject else '#2563eb',
            'video_count': total_vids,
            'resource_count': total_vids,  # For sp-card compatibility
            'completed_count': completed_count,
            'total_count': total_vids,
            'progress_pct': progress_pct,
            'latest_at': latest_ts,
            'url': url_for('main.video_player', video_id=next_vid_id) if next_vid_id else '#',
            'xp': total_vids * 10,
            'first_video_youtube_id': sorted_vids[0].video.youtube_id if sorted_vids and sorted_vids[0].video else None,
        })

    # 1.5 Fetch Post-based Bookmarks (Legacy Topic Bundles)
    saved_bookmarks = (
        Bookmark.query
        .filter_by(user_id=current_user.id)
        .options(selectinload(Bookmark.post).selectinload(Post.subject))
        .order_by(Bookmark.created_at.desc())
        .all()
    )
    posts_from_bookmarks = [b.post for b in saved_bookmarks if b.post and b.post.subject]
    legacy_bundles = _build_topic_cards(posts_from_bookmarks)

    for lb in legacy_bundles:
        unified_bundles.append({
            'type': 'topic_bundle',
            'id': lb['topic_key'],
            'title': lb['topic_label'],
            'subject_name': lb['subject'].name,
            'subject': lb['subject'],
            'color': lb['subject'].color or '#2563eb',
            'video_count': 0,
            'resource_count': lb['total_count'],
            'completed_count': 0,
            'total_count': lb['total_count'],
            'progress_pct': 0,
            'latest_at': lb['latest_at'],
            'url': url_for('main.study_room_topic', subject_slug=lb['subject'].slug, topic_key=lb['topic_key']),
            'xp': lb['total_count'] * 10
        })

    # 2. Sort and Paginate
    sorted_bundles = sorted(
        unified_bundles,
        key=lambda b: (b['latest_at'].timestamp() if b.get('latest_at') else 0),
        reverse=True,
    )
    
    total = len(sorted_bundles)
    pages = max(1, math.ceil(total / per_page)) if total else 1
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    page_items = sorted_bundles[start:start + per_page]

    # 4. Fetch Saved Videos for the other tab
    saved_videos = (
        VideoBookmark.query
        .filter_by(user_id=current_user.id)
        .options(selectinload(VideoBookmark.video))
        .order_by(VideoBookmark.created_at.desc())
        .all()
    )
    saved_video_list = [vb.video for vb in saved_videos if vb.video]

    return dict(
        title='My Stuff',
        topic_cards=page_items, # keeping variable name for compatibility if needed, but it's unified now
        total_cards=total,
        page=page,
        pages=pages,
        has_prev=page > 1,
        has_next=page < pages,
        prev_num=page - 1,
        next_num=page + 1,
        saved_videos=saved_video_list
    )


@bp.route('/<username>/bookmarks')
@login_required
def bookmarks_for_user(username):
    """JSON feed for a user's bookmarks (owner-only)."""
    user = User.query.filter_by(username=username).first_or_404()
    if current_user.id != user.id:
        return jsonify({'bookmarks': []}), 403

    limit = request.args.get('limit', 5, type=int)
    limit = max(1, min(limit, 20))

    rows = (
        Bookmark.query
        .filter_by(user_id=user.id)
        .options(selectinload(Bookmark.post).selectinload(Post.subject))
        .order_by(Bookmark.created_at.desc())
        .limit(limit)
        .all()
    )

    payload = []
    for row in rows:
        post = row.post
        if not post:
            continue
        payload.append({
            'id': post.id,
            'title': post.title,
            'subject': post.subject.name if post.subject else '',
            'icon': post.content_type_icon,
            'color': post.content_type_color,
        })

    return jsonify({'bookmarks': payload})


@bp.route('/save-education', methods=['POST'])
@login_required
def save_education():
    school = request.form.get('school', '').strip()
    programme = request.form.get('programme', '').strip()
    xp_earned = 0
    
    # Award XP for adding school (10 XP) - only if not already set
    if school and not current_user.school:
        current_user.school = school
        xp_earned += 10
    elif school:
        current_user.school = school
    
    # Award XP for adding programme (15 XP) - only if not already set
    if programme and not current_user.programme:
        current_user.programme = programme
        xp_earned += 15
    elif programme:
        current_user.programme = programme
    
    if xp_earned > 0:
        current_user.add_xp(xp_earned, reason='Profile completed')
        flash(f'🎉 You earned {xp_earned} Aura for completing your profile!', 'success')
    
    # Clear the session variable so the overlay won't reappear
    db.session.commit()

    # ── FIRST PACK REDIRECT ──
    # If the user just set their programme, find the first study pack for them
    if programme:
        prog_obj = Programme.query.filter_by(name=programme).first()
        if prog_obj:
            # Find first subject that has at least one study pack
            for sub in prog_obj.subjects:
                pack = StudyPack.query.filter_by(subject_id=sub.id).first()
                if pack and pack.videos:
                    # Get the first video in the pack
                    first_video = sorted(pack.videos, key=lambda v: v.order_index)[0].video
                    if first_video:
                        flash(f"Welcome! We've recommended your first study pack: {pack.title}", "info")
                        return redirect(url_for('main.video_player', video_id=first_video.id))

    return redirect(request.referrer or url_for('main.explore'))


@bp.route('/edit-profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """
    Edit current user's profile.
    """
    form = EditProfileForm()

    if form.validate_on_submit():
        xp_earned = 0
        
        # Award XP for adding bio (5 XP) - only if not already set
        if form.bio.data and not current_user.bio:
            xp_earned += 5
        current_user.bio = form.bio.data
        
        # Award XP for adding school (10 XP) - only if not already set
        if form.school.data and not current_user.school:
            xp_earned += 10
        current_user.school = form.school.data
        
        # Award XP for adding programme (15 XP) - only if not already set
        if form.programme.data and not current_user.programme:
            xp_earned += 15
        current_user.programme = form.programme.data
        
        current_user.nickname = form.nickname.data

        # Handle profile picture upload
        if form.profile_picture.data and form.profile_picture.data.filename:
            file = form.profile_picture.data

            try:
                # Delete old profile picture from Cloudinary if not the default
                if current_user.profile_picture and current_user.profile_picture != 'default.jpg':
                    try:
                        cloudinary.uploader.destroy(
                            current_user.profile_picture,
                            resource_type='image'
                        )
                    except Exception as e:
                        current_app.logger.warning(f"Failed to delete old profile picture: {e}")

                # Upload new profile picture to Cloudinary
                result = cloudinary.uploader.upload(
                    file,
                    folder='knowly/profiles',
                    resource_type='image',
                    use_filename=True,
                    unique_filename=True,
                    transformation=[
                        {'width': 400, 'height': 400, 'crop': 'fill', 'gravity': 'face'}
                    ]
                )

                # Store the public_id so we can delete it later if needed
                current_user.profile_picture = result['secure_url']


            except Exception as e:
                current_app.logger.error(f"Cloudinary profile picture upload failed: {e}")
                flash('Profile picture upload failed. Please try again.', 'danger')
                return redirect(url_for('users.edit_profile'))

        if xp_earned > 0:
            current_user.add_xp(xp_earned, reason='Profile updated')
            flash(f'🎉 You earned {xp_earned} Aura for completing your profile!', 'success')
        else:
            flash('Your profile has been updated!', 'success')
        
        db.session.commit()
        return redirect(url_for('users.profile', username=current_user.username))

    elif request.method == 'GET':
        return redirect(url_for('main.index', settings='profile'))

    return redirect(url_for('main.index'))


@bp.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    """
    Follow a user.
    """
    user = User.query.filter_by(username=username).first_or_404()

    if user == current_user:
        flash('You cannot follow yourself!', 'warning')
        return redirect(url_for('users.profile', username=username))

    if current_user.is_following(user):
        flash('You are already following this user.', 'info')
    else:
        current_user.follow(user)
        db.session.commit()
        flash(f'You are now following {username}!', 'success')
        from app.models import create_notification
        create_notification(
            user_id=user.id,
            message=f'{current_user.username} started following you',
            notification_type='follow',
            link=f'/profile/{current_user.username}',
        )

    return redirect(url_for('users.profile', username=username))


@bp.route('/unfollow/<username>', methods=['POST'])
@login_required
def unfollow(username):
    """
    Unfollow a user.
    """
    user = User.query.filter_by(username=username).first_or_404()

    if user == current_user:
        flash('You cannot unfollow yourself!', 'warning')
        return redirect(url_for('users.profile', username=username))

    if not current_user.is_following(user):
        flash('You are not following this user.', 'info')
    else:
        current_user.unfollow(user)
        db.session.commit()
        flash(f'You have unfollowed {username}.', 'success')

    return redirect(url_for('users.profile', username=username))


@bp.route('/followers/<username>')
@turbo_frame('main-content', 'frames/followers.html', 'users/followers.html')
def followers(username):
    """
    View a user's followers.
    """
    user = User.query.filter_by(username=username).first_or_404()

    page = request.args.get('page', 1, type=int)
    followers = user.followers.paginate(
        page=page,
        per_page=current_app.config['USERS_PER_PAGE'],
        error_out=False
    )

    return dict(
                           title=f'{username}\'s Followers',
                           user=user,
                           followers=followers)


@bp.route('/following/<username>')
@turbo_frame('main-content', 'frames/following.html', 'users/following.html')
def following(username):
    """
    View users that a user is following.
    """
    user = User.query.filter_by(username=username).first_or_404()

    page = request.args.get('page', 1, type=int)
    following = user.following.paginate(
        page=page,
        per_page=current_app.config['USERS_PER_PAGE'],
        error_out=False
    )

    return dict(
                           title=f'{username} is Following',
                           user=user,
                           following=following)


@bp.route('/search')
@turbo_frame('main-content', 'frames/search.html', 'users/search.html')
def search():
    query        = request.args.get('q', '').strip()
    content_type = request.args.get('type', '')
    subject_id   = request.args.get('subject', type=int)

    from app.models import Subject
    subjects = Subject.query.filter_by(is_active=True).order_by(Subject.order, Subject.name).all()

    if not query:
        return dict(
                               title='Search',
                               query='',
                               users=[],
                               topic_cards=[],
                               subjects=subjects,
                               content_type=content_type,
                               subject_id=subject_id)

    like = f'%{query}%'

    # Search users — case-insensitive
    users = User.query.filter(
        db.or_(
            User.username.ilike(like),
            User.nickname.ilike(like)
        )
    ).limit(12).all()

    # Search posts — approved only, case-insensitive, title matches ranked first
    from app.models import Subject
    from sqlalchemy import case as sa_case

    title_match = Post.title.ilike(like)
    desc_match  = Post.description.ilike(like)

    # Also match posts whose subject name contains the query
    subject_name_ids = [
        s.id for s in Subject.query.filter(Subject.name.ilike(like)).all()
    ]

    post_query = Post.query.filter(
        Post.status == 'approved',
        db.or_(
            title_match,
            desc_match,
            Post.subject_id.in_(subject_name_ids) if subject_name_ids else db.false()
        )
    )

    if content_type in ('notes', 'cheatsheet', 'quiz', 'mixed'):
        post_query = post_query.filter(Post.content_type == content_type)

    if subject_id:
        post_query = post_query.filter(Post.subject_id == subject_id)

    # Title matches rank first, then description matches, then subject matches
    relevance = sa_case(
        (title_match, 1),
        (desc_match, 2),
        else_=3
    )
    posts = post_query.order_by(relevance, Post.created_at.desc()).limit(40).all()
    topic_cards = _build_topic_cards(posts)

    return dict(
                           title=f'Results for "{query}"',
                           query=query,
                           users=users,
                           topic_cards=topic_cards,
                           subjects=subjects,
                           content_type=content_type,
                           subject_id=subject_id,
                           total_results=len(users) + len(topic_cards))
                           
@bp.route('/skip-education', methods=['POST'])
@login_required
def skip_education():
    """Mark education onboarding as permanently skipped in the DB."""
    current_user.onboarding_skipped = True
    db.session.commit()
    return '', 204