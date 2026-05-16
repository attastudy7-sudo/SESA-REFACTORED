"""
transcript_service.py — Fetches YouTube video transcripts for AI generation.

Tries youtube-transcript-api first. Falls back to a title-based description
string if captions are unavailable, so generation never hard-fails.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

try:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    _TRANSCRIPT_API_AVAILABLE = True
except ImportError:
    _TRANSCRIPT_API_AVAILABLE = False
    logger.warning("youtube-transcript-api not installed. Run: pip install youtube-transcript-api")


def fetch_transcript(youtube_id: str, title: str = '', channel: str = '', video_obj=None) -> dict:
    """
    Fetch a transcript for a YouTube video.

    Returns:
        {
            'text': str,           # full transcript or fallback description
            'source': str,         # 'transcript' | 'fallback'
            'word_count': int,
            'language': str,       # e.g. 'en', or '' for fallback
        }
    """
    # ── Cache Check ──────────────────────────────────────────────────────────
    if video_obj and getattr(video_obj, 'transcript_text', None):
        text = video_obj.transcript_text
        return {
            'text': text,
            'source': 'cache',
            'word_count': len(text.split()),
            'language': 'en', # assume en for cached
        }

    if _TRANSCRIPT_API_AVAILABLE:
        try:
            # Prefer English; accept auto-generated captions
            transcript_list = YouTubeTranscriptApi.list_transcripts(youtube_id)
            transcript = None

            # Try manually created English first
            try:
                transcript = transcript_list.find_manually_created_transcript(['en', 'en-US', 'en-GB'])
            except Exception:
                pass

            # Fall back to auto-generated English
            if transcript is None:
                try:
                    transcript = transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])
                except Exception:
                    pass

            # Fall back to any available language
            if transcript is None:
                try:
                    transcript = next(iter(transcript_list))
                except Exception:
                    pass

            if transcript is not None:
                snippets = transcript.fetch()
                text = ' '.join(s['text'] for s in snippets if s.get('text'))
                text = text.strip()
                if text:
                    # ── Save to Cache ────────────────────────────────────────
                    if video_obj:
                        try:
                            from app import db
                            # Re-query video_obj to ensure it's in the current session
                            # if it was passed across threads/contexts
                            model_video = video_obj
                            if not db.session.object_session(model_video):
                                from app.models import VideoLesson
                                model_video = db.session.get(VideoLesson, video_obj.id)
                            
                            if model_video:
                                model_video.transcript_text = text
                                db.session.commit()
                                logger.info("Transcript cached in DB for video_id=%d", model_video.id)
                        except Exception as cache_exc:
                            logger.warning("Failed to cache transcript in DB: %s", cache_exc)

                    return {
                        'text': text,
                        'source': 'transcript',
                        'word_count': len(text.split()),
                        'language': getattr(transcript, 'language_code', 'en'),
                    }

        except (NoTranscriptFound, TranscriptsDisabled):
            logger.info("No captions available for %s — using title fallback.", youtube_id)
        except Exception as exc:
            logger.warning("Transcript fetch failed for %s: %s", youtube_id, exc)

    # Fallback: build a description from title + channel so AI generation
    # still runs but with less context
    fallback_parts = []
    if title:
        fallback_parts.append(f"Video title: {title}")
    if channel:
        fallback_parts.append(f"Channel: {channel}")
    fallback_parts.append(
        "This is an educational video. Generate study resources based on the topic implied by the title."
    )
    fallback_text = '\n'.join(fallback_parts)

    return {
        'text': fallback_text,
        'source': 'fallback',
        'word_count': len(fallback_text.split()),
        'language': '',
    }

