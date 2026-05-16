"""
resource_generator.py — Generates and persists AI study resources for a StudyPack.

Entry point: generate_pack_resources(pack_id, trigger='pack_open')

Generation schedule per pack:
  - video 1 flashcards     → generated immediately on first pack open (all tiers)
  - video 1 micro_quiz     → generated immediately (paid users only; free users see it locked)
  - remaining flashcards   → generated progressively as user completes videos (paid only)
  - micro_quiz checkpoints → placed at difficulty boundaries (paid only)
  - notes + cheatsheet     → generated after all videos in pack are done (paid only)
  - boss_quiz              → generated after notes + cheatsheet are done (paid only)

This module only generates and stores — it does not gate display.
Gating is handled in the study room route and template (Patch 8b/8c).
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Optional

from app import db
from app.models import PackResource, StudyPack, StudyPackVideo, VideoLesson
from app.services.transcript_service import fetch_transcript
from app.services.ai_service import _generate_structured, _FREE_OPENROUTER_MODELS_STRUCTURED

logger = logging.getLogger(__name__)

# ── Flashcard generation ──────────────────────────────────────────────────────

_FLASHCARD_SYSTEM_PROMPT = """You are KnowlyGen, a study card creator.
Generate exactly 8 flashcards from the provided material.
Respond ONLY with valid JSON in this exact shape:
{
  "flashcards": [
    {"front": "Question or term (max 120 chars)", "back": "Answer or definition (max 300 chars)"},
    ...
  ]
}
Rules:
- front should be a concise question or key term
- back should be the direct answer, definition, or key fact
- Cards must be based strictly on the provided material
- Do not number the cards
- Return exactly 8 cards"""

_MICRO_QUIZ_SYSTEM_PROMPT = """You are KnowlyGen, an exam question writer.
Generate exactly 5 multiple-choice questions from the provided material.
Respond ONLY with valid JSON in this exact shape:
{
  "questions": [
    {
      "question": "...",
      "options": [
        {"letter": "A", "text": "..."},
        {"letter": "B", "text": "..."},
        {"letter": "C", "text": "..."},
        {"letter": "D", "text": "..."}
      ],
      "correct_answer": "A",
      "explanation": "Brief explanation of why this answer is correct"
    }
  ],
  "metadata": {"total_questions": 5}
}
Rules:
- Questions must be answerable from the provided material only
- Vary difficulty: 2 easy, 2 medium, 1 hard
- Distractors must be plausible but clearly wrong on reflection"""

_BOSS_QUIZ_SYSTEM_PROMPT = """You are KnowlyGen, a master examiner.
Generate exactly 10 multiple-choice questions covering the FULL scope of the provided material.
Respond ONLY with valid JSON in this exact shape:
{
  "questions": [
    {
      "question": "...",
      "options": [
        {"letter": "A", "text": "..."},
        {"letter": "B", "text": "..."},
        {"letter": "C", "text": "..."},
        {"letter": "D", "text": "..."}
      ],
      "correct_answer": "...",
      "explanation": "..."
    }
  ],
  "metadata": {"total_questions": 10, "is_boss_quiz": true}
}
Rules:
- Questions must synthesize information across the entire lesson material.
- Difficulty: 3 easy, 4 medium, 3 hard.
- Ensure only one clearly correct answer exists."""



def _generate_flashcards(transcript_text: str) -> dict | None:
    """Generate 8 flashcards from transcript text."""
    try:
        result = _generate_structured(
            content=transcript_text,
            doc_type='flashcards',
        )
        # _generate_structured doesn't know 'flashcards' doc_type natively —
        # call OpenRouter/Gemini directly with the custom prompt
        from app.services.ai_service import _generate_via_openrouter, _load_keys
        import os, google.generativeai as genai
        from google.generativeai import types as gtypes

        user_prompt = f"Source Material:\n{transcript_text[:12000]}"

        # Try Gemini first
        keys = _load_keys()
        model_pref = os.environ.get('GEMINI_MODEL_PREFERENCES', 'gemini-2.0-flash-lite').split(',')[0].strip()
        for api_key in keys:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    model_name=model_pref,
                    system_instruction=_FLASHCARD_SYSTEM_PROMPT,
                )
                response = model.generate_content(
                    user_prompt,
                    generation_config=gtypes.GenerationConfig(
                        temperature=0.4,
                        max_output_tokens=2048,
                        response_mime_type='application/json',
                    ),
                    request_options={'timeout': 60},
                )
                data = json.loads(response.text.strip())
                if isinstance(data.get('flashcards'), list) and len(data['flashcards']) > 0:
                    return data
            except Exception as exc:
                logger.warning("Flashcard Gemini generation failed: %s", exc)
                continue

        # Fall back to OpenRouter
        result = _generate_via_openrouter(
            sys_prompt=_FLASHCARD_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            doc_type='flashcards',
            context=transcript_text[:12000],
            model_candidates=_FREE_OPENROUTER_MODELS_STRUCTURED,
        )
        if result and isinstance(result.get('flashcards'), list):
            return result

    except Exception as exc:
        logger.error("Flashcard generation failed entirely: %s", exc)

    return None


def _generate_micro_quiz(transcript_text: str) -> dict | None:
    """Generate a 5-question micro-quiz from transcript text."""
    try:
        from app.services.ai_service import _generate_via_openrouter, _load_keys
        import os, google.generativeai as genai
        from google.generativeai import types as gtypes

        user_prompt = f"Source Material:\n{transcript_text[:12000]}"
        keys = _load_keys()
        model_pref = os.environ.get('GEMINI_MODEL_PREFERENCES', 'gemini-2.0-flash-lite').split(',')[0].strip()

        for api_key in keys:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    model_name=model_pref,
                    system_instruction=_MICRO_QUIZ_SYSTEM_PROMPT,
                )
                response = model.generate_content(
                    user_prompt,
                    generation_config=gtypes.GenerationConfig(
                        temperature=0.4,
                        max_output_tokens=2048,
                        response_mime_type='application/json',
                    ),
                    request_options={'timeout': 60},
                )
                data = json.loads(response.text.strip())
                if isinstance(data.get('questions'), list) and len(data['questions']) > 0:
                    return data
            except Exception as exc:
                logger.warning("Micro-quiz Gemini generation failed: %s", exc)
                continue

        result = _generate_via_openrouter(
            sys_prompt=_MICRO_QUIZ_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            doc_type='quiz',
            context=transcript_text[:12000],
            model_candidates=_FREE_OPENROUTER_MODELS_STRUCTURED,
        )
        if result and isinstance(result.get('questions'), list):
            return result

    except Exception as exc:
        logger.error("Micro-quiz generation failed entirely: %s", exc)

    return None


def _generate_boss_quiz(transcript_text: str) -> dict | None:
    """Generate a 10-question boss quiz from full pack transcripts."""
    try:
        from app.services.ai_service import _generate_via_openrouter, _load_keys
        import os, google.generativeai as genai
        from google.generativeai import types as gtypes

        user_prompt = f"Full Course Material:\n{transcript_text[:24000]}"
        keys = _load_keys()
        model_pref = os.environ.get('GEMINI_MODEL_PREFERENCES', 'gemini-2.0-flash-lite').split(',')[0].strip()

        for api_key in keys:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(
                    model_name=model_pref,
                    system_instruction=_BOSS_QUIZ_SYSTEM_PROMPT,
                )
                response = model.generate_content(
                    user_prompt,
                    generation_config=gtypes.GenerationConfig(
                        temperature=0.5,
                        max_output_tokens=4096,
                        response_mime_type='application/json',
                    ),
                    request_options={'timeout': 90},
                )
                data = json.loads(response.text.strip())
                if isinstance(data.get('questions'), list) and len(data['questions']) > 0:
                    return data
            except Exception as exc:
                logger.warning("Boss quiz Gemini generation failed: %s", exc)
                continue

        result = _generate_via_openrouter(
            sys_prompt=_BOSS_QUIZ_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            doc_type='quiz',
            context=transcript_text[:24000],
            model_candidates=_FREE_OPENROUTER_MODELS_STRUCTURED,
        )
        if result and isinstance(result.get('questions'), list):
            return result

    except Exception as exc:
        logger.error("Boss quiz generation failed entirely: %s", exc)

    return None



# ── Checkpoint placement ──────────────────────────────────────────────────────

def compute_checkpoint_positions(pack_videos: list[StudyPackVideo]) -> dict:
    """
    Given the ordered videos in a pack, return checkpoint positions.

    Returns a dict keyed by order_index of the video *after which* a checkpoint
    should appear:
        {
            3: 'flashcards',   # after video at position 3
            5: 'micro_quiz',   # after video at position 5 (difficulty boundary)
        }

    Strategy: place flashcard checkpoint at Foundation→Practice boundary,
    micro_quiz at Practice→Mastery boundary. If the pack has no difficulty
    spread, fall back to: flashcards after video 3, micro_quiz after video 6.
    """
    if not pack_videos:
        return {}

    stage_order = ['Foundation', 'Practice', 'Mastery']
    positions = {}

    # Find boundary positions
    last_stage = None
    flashcard_pos = None
    micro_quiz_pos = None

    for spv in sorted(pack_videos, key=lambda x: x.order_index):
        stage = (spv.stage or 'Foundation').strip()
        if last_stage and stage != last_stage:
            # Boundary found
            boundary_idx = stage_order.index(stage) if stage in stage_order else 1
            if boundary_idx == 1 and flashcard_pos is None:
                # Foundation → Practice boundary
                flashcard_pos = spv.order_index - 1  # after the last Foundation video
            elif boundary_idx == 2 and micro_quiz_pos is None:
                # Practice → Mastery boundary
                micro_quiz_pos = spv.order_index - 1
        last_stage = stage

    total = len(pack_videos)

    # Fallback positions if no difficulty spread detected
    if flashcard_pos is None:
        flashcard_pos = min(3, total)
    if micro_quiz_pos is None and total > 4:
        micro_quiz_pos = min(total - 1, total)

    if flashcard_pos:
        positions[flashcard_pos] = 'flashcards'
    if micro_quiz_pos and micro_quiz_pos != flashcard_pos:
        positions[micro_quiz_pos] = 'micro_quiz'

    return positions


# ── Main generation orchestrator ─────────────────────────────────────────────

def _get_or_create_resource(pack_id: int, video_id: Optional[int], resource_type: str) -> PackResource:
    """Get existing PackResource or create a new pending one."""
    existing = PackResource.query.filter_by(
        pack_id=pack_id,
        video_id=video_id,
        resource_type=resource_type,
    ).first()
    if existing:
        return existing

    resource = PackResource(
        pack_id=pack_id,
        video_id=video_id,
        resource_type=resource_type,
        generation_status='pending',
    )
    db.session.add(resource)
    db.session.flush()
    return resource


def _generate_and_save_flashcards(pack_id: int, video: VideoLesson, app) -> None:
    """Generate flashcards for a single video and persist to DB. Runs in background thread."""
    with app.app_context():
        resource = _get_or_create_resource(pack_id, video.id, 'flashcards')
        if resource.generation_status == 'done':
            return

        resource.generation_status = 'generating'
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return

        try:
            transcript = fetch_transcript(
                youtube_id=video.youtube_id,
                title=video.title or '',
                channel=video.channel_name or '',
            )
            result = _generate_flashcards(transcript['text'])

            resource = PackResource.query.filter_by(
                pack_id=pack_id, video_id=video.id, resource_type='flashcards'
            ).first()

            if result and resource:
                resource.set_content(result)
                resource.generation_status = 'done'
            elif resource:
                resource.generation_status = 'failed'
                resource.error_message = 'AI returned no valid flashcards'

            db.session.commit()
            logger.info("Flashcards generated for pack=%d video=%d", pack_id, video.id)

        except Exception as exc:
            db.session.rollback()
            logger.error("Flashcard generation error for pack=%d video=%d: %s", pack_id, video.id, exc)
            try:
                resource = PackResource.query.filter_by(
                    pack_id=pack_id, video_id=video.id, resource_type='flashcards'
                ).first()
                if resource:
                    resource.generation_status = 'failed'
                    resource.error_message = str(exc)[:490]
                    db.session.commit()
            except Exception:
                db.session.rollback()


def _generate_micro_quiz_and_save(pack_id: int, video: VideoLesson, app) -> None:
    """Generate a micro-quiz for a single video and persist to DB. Runs in background thread."""
    with app.app_context():
        resource = _get_or_create_resource(pack_id, video.id, 'micro_quiz')
        if resource.generation_status == 'done':
            return

        resource.generation_status = 'generating'
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return

        try:
            transcript = fetch_transcript(
                youtube_id=video.youtube_id,
                title=video.title or '',
                channel=video.channel_name or '',
            )
            result = _generate_micro_quiz(transcript['text'])

            resource = PackResource.query.filter_by(
                pack_id=pack_id, video_id=video.id, resource_type='micro_quiz'
            ).first()

            if result and resource:
                resource.set_content(result)
                resource.generation_status = 'done'
            elif resource:
                resource.generation_status = 'failed'
                resource.error_message = 'AI returned no valid micro-quiz'

            db.session.commit()
            logger.info("Micro-quiz generated for pack=%d video=%d", pack_id, video.id)

        except Exception as exc:
            db.session.rollback()
            logger.error("Micro-quiz generation error for pack=%d video=%d: %s", pack_id, video.id, exc)
            try:
                resource = PackResource.query.filter_by(
                    pack_id=pack_id, video_id=video.id, resource_type='micro_quiz'
                ).first()
                if resource:
                    resource.generation_status = 'failed'
                    resource.error_message = str(exc)[:490]
                    db.session.commit()
            except Exception:
                db.session.rollback()


def _prefetch_transcripts(pack_id: int, app) -> None:
    """Warms the transcript cache for all videos in a pack. Runs in background."""
    with app.app_context():
        pack = StudyPack.query.get(pack_id)
        if not pack: return
        for spv in pack.videos:
            if spv.video and not spv.video.transcript_text:
                try:
                    fetch_transcript(
                        youtube_id=spv.video.youtube_id,
                        title=spv.video.title or '',
                        channel=spv.video.channel_name or '',
                        video_obj=spv.video
                    )
                except Exception as exc:
                    logger.warning("Prefetch failed for video %d: %s", spv.video_id, exc)


def _generate_notes_cheatsheet_and_save(pack_id: int, app) -> None:
    """Generate notes and cheatsheet for the pack. Runs in background."""
    with app.app_context():
        pack = StudyPack.query.get(pack_id)
        if not pack: return

        # Check if already done
        notes_res = _get_or_create_resource(pack_id, None, 'notes')
        sheet_res = _get_or_create_resource(pack_id, None, 'cheatsheet')
        
        if notes_res.generation_status == 'done' and sheet_res.generation_status == 'done':
            # Chain anyway to ensure boss quiz is checked
            _generate_boss_quiz_and_save(pack_id, app)
            return

        notes_res.generation_status = 'generating'
        sheet_res.generation_status = 'generating'
        db.session.commit()

        try:
            # Concatenate all transcripts
            transcripts = []
            for spv in sorted(pack.videos, key=lambda x: x.order_index):
                t = fetch_transcript(spv.video.youtube_id, video_obj=spv.video)
                if t and t.get('text'):
                    transcripts.append(f"--- Video {spv.order_index}: {spv.video.title} ---\n{t['text']}")
            
            full_context = "\n\n".join(transcripts)
            if not full_context:
                raise ValueError("No transcript context available for pack resource generation")

            from app.services.ai_service import generate_academic_bundle
            bundle = generate_academic_bundle(full_context)
            
            if bundle and bundle.get('is_academic'):
                if bundle.get('notes'):
                    notes_res.set_content(bundle['notes'])
                    notes_res.generation_status = 'done'
                if bundle.get('cheatsheet'):
                    sheet_res.set_content(bundle['cheatsheet'])
                    sheet_res.generation_status = 'done'
                db.session.commit()
                logger.info("Notes and cheatsheet generated for pack %d", pack_id)
            else:
                notes_res.generation_status = 'failed'
                sheet_res.generation_status = 'failed'
                db.session.commit()

        except Exception as exc:
            db.session.rollback()
            logger.error("Notes/Cheatsheet generation error for pack %d: %s", pack_id, exc)
            notes_res.generation_status = 'failed'
            sheet_res.generation_status = 'failed'
            db.session.commit()

        # Chain into Boss Quiz
        _generate_boss_quiz_and_save(pack_id, app)


def _generate_boss_quiz_and_save(pack_id: int, app) -> None:
    """Generate the final boss quiz for the pack. Runs in background."""
    with app.app_context():
        resource = _get_or_create_resource(pack_id, None, 'boss_quiz')
        if resource.generation_status == 'done':
            return

        resource.generation_status = 'generating'
        db.session.commit()

        try:
            pack = StudyPack.query.get(pack_id)
            transcripts = []
            for spv in sorted(pack.videos, key=lambda x: x.order_index):
                t = fetch_transcript(spv.video.youtube_id, video_obj=spv.video)
                if t and t.get('text'):
                    transcripts.append(t['text'])
            
            full_context = "\n\n".join(transcripts)
            result = _generate_boss_quiz(full_context)

            if result:
                resource.set_content(result)
                resource.generation_status = 'done'
            else:
                resource.generation_status = 'failed'
            db.session.commit()
            logger.info("Boss quiz generated for pack %d", pack_id)

        except Exception as exc:
            db.session.rollback()
            logger.error("Boss quiz generation error for pack %d: %s", pack_id, exc)
            resource.generation_status = 'failed'
            db.session.commit()



def generate_pack_resources(pack_id: int, trigger: str = 'pack_open') -> dict:
    """
    Main entry point. Called from the study room route when a user opens a pack.

    - Always triggers flashcard generation for video 1 (background thread)
    - Checks what resources already exist and skips re-generation
    - Returns a status dict the route can pass to the template as JSON

    Args:
        pack_id: StudyPack.id
        trigger: 'pack_open' (default) — may be extended for 'video_complete' in 8b

    Returns:
        {
            'triggered': ['flashcards:video_1'],
            'already_done': ['flashcards:video_1'],
            'pending': ['notes', 'cheatsheet'],
        }
    """
    from flask import current_app
    app = current_app._get_current_object()

    pack = StudyPack.query.get(pack_id)
    if not pack:
        return {'error': f'Pack {pack_id} not found'}

    pack_videos = sorted(pack.videos, key=lambda spv: spv.order_index)
    if not pack_videos:
        return {'error': 'Pack has no videos'}

    triggered = []
    already_done = []

    # ── Video 1: flashcards always (all authenticated users) ─────────────────
    first_spv = pack_videos[0]
    first_video = first_spv.video

    if first_video:
        existing = PackResource.query.filter_by(
            pack_id=pack_id,
            video_id=first_video.id,
            resource_type='flashcards',
        ).first()

        if existing and existing.generation_status == 'done':
            already_done.append(f'flashcards:video_{first_spv.order_index}')
        else:
            # Fire generation in background thread
            t = threading.Thread(
                target=_generate_and_save_flashcards,
                args=(pack_id, first_video, app),
                daemon=True,
            )
            t.start()
            triggered.append(f'flashcards:video_{first_spv.order_index}')

    # ── NEW: Warm transcript cache for ALL videos in background ──────────────
    prefetch_t = threading.Thread(
        target=_prefetch_transcripts,
        args=(pack_id, app),
        daemon=True,
    )
    prefetch_t.start()

    # ── Compute and persist checkpoint positions ──────────────────────────────
    checkpoint_positions = compute_checkpoint_positions(pack_videos)

    return {
        'triggered': triggered,
        'already_done': already_done,
        'pending': ['micro_quiz', 'notes', 'cheatsheet', 'boss_quiz'],
        'checkpoint_positions': checkpoint_positions,
        'total_videos': len(pack_videos),
    }

