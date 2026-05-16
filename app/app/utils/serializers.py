"""
Serializer utilities for converting database models to dictionary format.

Used for API responses and template data formatting.
"""

from app.models import VideoCompletion, UserPackProgress


def format_pack_data(pack, user_id=None):
    """
    Format a StudyPack model into a dictionary for API/template use.
    
    Args:
        pack: StudyPack model instance
        user_id: Optional user ID for user-specific data (completion status, etc.)
    
    Returns:
        Dictionary with pack data and user-specific progress
    """
    # Base pack data
    card = {
        'id': pack.id,
        'title': pack.title,
        'description': getattr(pack, 'description', None) or '',
        'thumbnail_url': getattr(pack, 'thumbnail_url', None),
        'topic_slug': pack.topic_slug,
        'video_count': len(pack.videos) if pack.videos else 0,
        'resource_count': len(pack.resources) if hasattr(pack, 'resources') and pack.resources else 0,
    }
    
    # Add user-specific progress if user_id provided
    if user_id:
        from app.models import VideoCompletion, UserPackProgress
        
        # Check completion status
        completed_videos = VideoCompletion.query.filter_by(user_id=user_id).all()
        completed_video_ids = {vc.video_id for vc in completed_videos}
        
        if pack.videos:
            completed_count = sum(1 for v in pack.videos if v.video_id in completed_video_ids)
            total_count = len(pack.videos)
            progress_pct = int((completed_count / total_count * 100)) if total_count else 0
            
            card.update({
                'completed_count': completed_count,
                'total_count': total_count,
                'progress_pct': progress_pct,
                'user_progress': {
                    'completed_videos': completed_count,
                    'total_videos': total_count,
                    'percentage': progress_pct,
                },
            })
        else:
            card.update({
                'completed_count': 0,
                'total_count': 0,
                'progress_pct': 0,
                'user_progress': {
                    'completed_videos': 0,
                    'total_videos': 0,
                    'percentage': 0,
                },
            })
    else:
        # No user context - set defaults
        total_count = len(pack.videos) if pack.videos else 0
        card.update({
            'completed_count': 0,
            'total_count': total_count,
            'progress_pct': 0,
        })
    
    return card


def update_pack_progress(user_id, video_id):
    """
    Update the progress of a user in a study pack after completing a video.
    
    This function maintains UserPackProgress records to track which users
    have completed videos in which packs.
    
    Args:
        user_id: ID of the user who completed the video
        video_id: ID of the video that was completed
    """
    from app.models import VideoLesson
    
    video = VideoLesson.query.get(video_id)
    if not video or not video.pack_id:
        return
    
    # Check if user already has progress record for this pack
    progress = UserPackProgress.query.filter_by(
        user_id=user_id, 
        pack_id=video.pack_id
    ).first()
    
    if not progress:
        progress = UserPackProgress(user_id=user_id, pack_id=video.pack_id)
        from app import db
        db.session.add(progress)
    
    # Update last_accessed
    from datetime import datetime, timezone
    progress.last_accessed = datetime.now(timezone.utc)
    
    try:
        from app import db
        db.session.commit()
    except Exception as e:
        from app import db
        db.session.rollback()
        print(f"Error updating pack progress: {e}")
