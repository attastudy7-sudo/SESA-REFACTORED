from datetime import datetime, timedelta, timezone
from app import db
from app.models import User, AuraTransaction, VideoCompletion, StudyPack, StudyPackVideo
from app.services.email_campaigns import send_streak_reminder, send_weekly_digest, send_reengagement
from sqlalchemy import func

def run_streak_campaign():
    """
    Find users whose streak is about to expire.
    Condition: last_activity_date was exactly yesterday.
    """
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    # Users whose last activity was yesterday and have a streak > 0
    users = User.query.filter(
        User.last_activity_date == yesterday,
        User.current_streak > 0
    ).all()
    
    count = 0
    for user in users:
        try:
            if send_streak_reminder(user):
                count += 1
        except Exception:
            continue
    return count

def run_reengagement_campaign():
    """
    Find users inactive for exactly 7 days.
    """
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date()
    users = User.query.filter(
        User.last_activity_date == seven_days_ago
    ).all()
    
    count = 0
    for user in users:
        try:
            if send_reengagement(user):
                count += 1
        except Exception:
            continue
    return count

def run_weekly_digest_campaign():
    """
    Send weekly digest to all active users (those who had any activity in the last 7 days).
    """
    seven_days_ago_dt = datetime.utcnow() - timedelta(days=7)
    seven_days_ago_date = seven_days_ago_dt.date()
    
    # Target users who had activity in the last 7 days
    users = User.query.filter(User.last_activity_date >= seven_days_ago_date).all()
    
    count = 0
    for user in users:
        try:
            # Calculate stats for the user
            aura_earned = db.session.query(func.sum(AuraTransaction.amount)).filter(
                AuraTransaction.user_id == user.id,
                AuraTransaction.created_at >= seven_days_ago_dt
            ).scalar() or 0
            
            if aura_earned == 0:
                # Skip users with no progress this week
                continue
                
            # Top subject (by video completions this week)
            top_sub_row = VideoCompletion.query.filter(
                VideoCompletion.user_id == user.id,
                VideoCompletion.created_at >= seven_days_ago_dt
            ).first() 
            
            top_subject = "General Studies"
            if top_sub_row and top_sub_row.video and top_sub_row.video.subject:
                top_subject = top_sub_row.video.subject.name

            # Packs in progress
            completed_vid_ids = {vc.video_id for vc in VideoCompletion.query.filter_by(user_id=user.id).all()}
            active_pack_ids = db.session.query(StudyPackVideo.pack_id).filter(
                StudyPackVideo.video_id.in_(completed_vid_ids)
            ).distinct().all()
            active_pack_ids = [p[0] for p in active_pack_ids]
            
            active_packs = StudyPack.query.filter(StudyPack.id.in_(active_pack_ids)).all()
            packs_in_progress = []
            for pack in active_packs:
                videos = pack.videos
                if not videos: continue
                comp_count = sum(1 for spv in videos if spv.video_id in completed_vid_ids)
                if 0 < comp_count < len(videos):
                    packs_in_progress.append({
                        'title': pack.title,
                        'percent': int((comp_count / len(videos)) * 100)
                    })
            
            stats = {
                'aura_earned': aura_earned,
                'top_subject': top_subject,
                'packs_in_progress': packs_in_progress
            }
            
            if send_weekly_digest(user, stats):
                count += 1
        except Exception:
            continue
            
    return count
