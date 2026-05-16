from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from flask import Flask
from sqlalchemy import func

from app import db
from app.models import GenerationJob, Subject, User
from app.services.auto_resource_generation import detect_subject_gaps, generate_topics_for_gap
from app.services.resource_generation import (
    build_validated_bundle_from_text,
    get_taxonomy_context_for_ai,
    save_generated_selection,
)


_LOCK = threading.Lock()
_STOP = threading.Event()
_IS_RUNNING = False
_ACTIVE_RUN_ID: str | None = None
_LOG_TOTAL = 0
_LOG_BUFFER: list[str] = []
_MAX_LOG = 800


def _emit(message: str) -> None:
    global _LOG_TOTAL
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    line = f"[{stamp}] {message}"
    with _LOCK:
        _LOG_BUFFER.append(line)
        if len(_LOG_BUFFER) > _MAX_LOG:
            del _LOG_BUFFER[:-_MAX_LOG]
        _LOG_TOTAL += 1


def get_runner_state() -> dict[str, Any]:
    with _LOCK:
        return {
            "running": _IS_RUNNING,
            "run_id": _ACTIVE_RUN_ID,
            "log_total": _LOG_TOTAL,
        }


def get_log_snapshot() -> dict[str, Any]:
    with _LOCK:
        return {
            "running": _IS_RUNNING,
            "run_id": _ACTIVE_RUN_ID,
            "log_total": _LOG_TOTAL,
            "lines": list(_LOG_BUFFER),
        }


def stop_active_run() -> bool:
    with _LOCK:
        running = _IS_RUNNING
    if running:
        _STOP.set()
        _emit("Stop requested by admin.")
        return True
    return False


def start_background_run(app: Flask, *, actor_id: int, config: dict[str, Any]) -> tuple[bool, str]:
    global _IS_RUNNING, _ACTIVE_RUN_ID, _LOG_TOTAL

    with _LOCK:
        if _IS_RUNNING:
            return False, "A run is already in progress."
        _IS_RUNNING = True
        _STOP.clear()
        _ACTIVE_RUN_ID = uuid.uuid4().hex[:12]
        _LOG_TOTAL = 0
        _LOG_BUFFER.clear()
        run_id = _ACTIVE_RUN_ID

    thread = threading.Thread(
        target=_run_worker,
        args=(app, actor_id, run_id, config),
        daemon=True,
        name=f"generation-run-{run_id}",
    )
    thread.start()
    return True, run_id


def start_queue_processing(app: Flask, *, actor_id: int, delay_seconds: float = 0) -> tuple[bool, str]:
    global _IS_RUNNING, _ACTIVE_RUN_ID, _LOG_TOTAL

    with _LOCK:
        if _IS_RUNNING:
            return False, "A run is already in progress."
        _IS_RUNNING = True
        _STOP.clear()
        _ACTIVE_RUN_ID = f"queue-{uuid.uuid4().hex[:12]}"
        _LOG_TOTAL = 0
        _LOG_BUFFER.clear()
        run_id = _ACTIVE_RUN_ID

    thread = threading.Thread(
        target=_queue_worker,
        args=(app, actor_id, run_id, delay_seconds),
        daemon=True,
        name=f"generation-queue-{run_id}",
    )
    thread.start()
    return True, run_id


def _build_metadata(subject_name: str, programme_name: str | None, topic: str) -> dict[str, Any]:
    return {
        "title": f"{topic} - {subject_name}",
        "description": f"Auto-generated study material for {subject_name}.",
        "subject_hint": subject_name,
        "programme_hint": programme_name or "",
        "subject_match_basis": "existing",
        "programme_match_basis": "existing",
        "matched_subject_name": subject_name,
        "matched_programme_name": programme_name or "",
        "flair": "academic",
    }


def _publish_generation_job(
    job: GenerationJob,
    actor: User | None,
    taxonomy_context: dict | None = None,
) -> bool:
    if not actor:
        job.status = "failed"
        job.error = "No actor available for generation job"
        db.session.commit()
        return False

    try:
        source_text = (
            f"Subject: {job.subject_name}\n"
            f"Programme: {job.programme_name or ''}\n"
            f"Level: {job.level or 'Intermediate'}\n"
            f"Topic: {job.topic}\n"
            f"Target format: {job.content_type}\n\n"
            "Generate rigorous university-level study material for revision."
        )
        generation_result = build_validated_bundle_from_text(
            source_text,
            taxonomy_context=taxonomy_context,
        )
        if not generation_result.get("ok"):
            raise RuntimeError(str(generation_result.get("error") or "Invalid bundle response"))

        bundle = generation_result.get("bundle")
        if not isinstance(bundle, dict):
            raise RuntimeError("Invalid bundle response")
        if bundle.get("is_academic") is False:
            raise RuntimeError("AI marked generated content as non-academic")

        payload = bundle.get(job.content_type)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Bundle missing {job.content_type} payload")

        metadata = {
            **_build_metadata(job.subject_name, job.programme_name, job.topic),
            **dict(bundle.get("metadata") or {}),
        }
        metadata.setdefault("title", f"{job.topic} - {job.subject_name}")

        bundle_for_save = dict(bundle)
        bundle_for_save["metadata"] = metadata
        post, error = save_generated_selection(
            selection_type=job.content_type,
            content=payload,
            metadata=metadata,
            user=actor,
            subject_id=job.subject_id,
            bundle=bundle_for_save,
        )
        if error or not post:
            raise RuntimeError(error or "Failed to save generated content")

        job.status = "posted"
        job.created_post_id = post.id
        db.session.commit()
        return True
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)[:700]
        db.session.commit()
        return False


def _run_worker(app: Flask, actor_id: int, run_id: str, config: dict[str, Any]) -> None:
    global _IS_RUNNING, _ACTIVE_RUN_ID

    try:
        with app.app_context():
            _emit(f"Run {run_id} started.")

            actor = db.session.get(User, actor_id)
            if not actor:
                _emit("Actor not found; stopping run.")
                return

            taxonomy_context = get_taxonomy_context_for_ai()

            content_types = [ct for ct in config.get("content_types", ["notes", "quiz", "cheatsheet"]) if ct in {"notes", "quiz", "cheatsheet"}]
            if not content_types:
                content_types = ["notes", "quiz", "cheatsheet"]

            min_coverage = int(config.get("min_coverage", 3) or 3)
            topics_per_subject = int(config.get("topics_per_subject", 2) or 2)
            max_subjects = int(config.get("max_subjects", 10) or 10)
            max_api_calls = int(config.get("max_api_calls", 50) or 50)
            delay_seconds = float(config.get("delay_seconds", 10) or 10)
            programme_slugs = config.get("programme_slugs") or None
            year_filter = config.get("year_filter")
            semester_filter = config.get("semester_filter")
            fixed_topics = [str(topic).strip() for topic in (config.get("fixed_topics") or []) if str(topic).strip()]

            _emit("Detecting subject gaps...")
            gaps = detect_subject_gaps(
                min_coverage=max(1, min_coverage),
                content_types=tuple(content_types),
                programme_slugs=programme_slugs,
                year_filter=int(year_filter) if year_filter else None,
                semester_filter=int(semester_filter) if semester_filter else None,
                max_subjects=max_subjects,
            )
            _emit(f"Gap detection complete. {len(gaps)} subject(s) matched.")

            created_jobs = 0
            for gap in gaps:
                if _STOP.is_set():
                    break
                for content_type in gap.missing_types:
                    topics = fixed_topics or generate_topics_for_gap(gap, content_type, topics_per_subject)
                    existing_lower = {title.lower() for title in gap.existing_titles.get(content_type, [])}
                    for topic in topics:
                        if topic.lower() in existing_lower:
                            continue
                        exists = GenerationJob.query.filter_by(
                            subject_slug=gap.subject_slug,
                            topic=topic,
                            content_type=content_type,
                        ).filter(GenerationJob.status.in_(["pending", "generating", "posted"])).first()
                        if exists:
                            continue

                        job = GenerationJob(
                            run_id=run_id,
                            actor_id=actor.id,
                            programme_slug=(gap.programme_name or "").lower().replace(" ", "-"),
                            programme_name=gap.programme_name,
                            subject_id=gap.subject_id,
                            subject_slug=gap.subject_slug,
                            subject_name=gap.subject_name,
                            topic=topic,
                            content_type=content_type,
                            level=gap.level,
                            year=gap.year,
                            semester=gap.semester,
                            status="pending",
                            source="manual" if fixed_topics else "auto",
                            priority=1 if fixed_topics else 0,
                        )
                        db.session.add(job)
                        created_jobs += 1
            db.session.commit()
            _emit(f"Queued {created_jobs} job(s).")

            api_calls = 0
            while not _STOP.is_set() and api_calls < max_api_calls:
                job = (
                    GenerationJob.query
                    .filter_by(run_id=run_id, status="pending")
                    .order_by(GenerationJob.priority.desc(), GenerationJob.created_at.asc())
                    .first()
                )
                if not job:
                    break

                job.status = "generating"
                job.attempts = int(job.attempts or 0) + 1
                job.error = None
                db.session.commit()

                _emit(f"Generating {job.content_type} for {job.subject_slug} -> {job.topic}")
                if _publish_generation_job(job, actor, taxonomy_context=taxonomy_context):
                    _emit(f"Posted job {job.id} as post {job.created_post_id}.")
                else:
                    _emit(f"Job {job.id} failed: {job.error}")

                api_calls += 1
                if delay_seconds > 0 and not _STOP.is_set():
                    time.sleep(delay_seconds)

            remaining = GenerationJob.query.filter_by(run_id=run_id, status="pending").count()
            if _STOP.is_set() and remaining:
                _emit(f"Run stopped by admin. {remaining} pending job(s) left queued.")
            elif api_calls >= max_api_calls and remaining:
                _emit(f"Run reached max API calls ({max_api_calls}). {remaining} pending job(s) left queued.")
            else:
                _emit("Run completed.")

    finally:
        with _LOCK:
            _IS_RUNNING = False
            _ACTIVE_RUN_ID = None
        _STOP.clear()


def _queue_worker(app: Flask, actor_id: int, run_id: str, delay_seconds: float) -> None:
    global _IS_RUNNING, _ACTIVE_RUN_ID

    try:
        with app.app_context():
            _emit(f"Queue processor {run_id} started.")

            fallback_actor = db.session.get(User, actor_id)
            if not fallback_actor:
                _emit("Actor not found; stopping queue processor.")
                return

            taxonomy_context = get_taxonomy_context_for_ai()

            processed = 0
            while not _STOP.is_set():
                job = (
                    GenerationJob.query
                    .filter_by(status="pending")
                    .order_by(GenerationJob.priority.desc(), GenerationJob.created_at.asc())
                    .first()
                )
                if not job:
                    break

                job.status = "generating"
                job.attempts = int(job.attempts or 0) + 1
                job.error = None
                db.session.commit()

                actor = job.actor or fallback_actor
                _emit(f"Processing queued job {job.id}: {job.content_type} for {job.subject_slug} -> {job.topic}")
                if _publish_generation_job(job, actor, taxonomy_context=taxonomy_context):
                    processed += 1
                    _emit(f"Posted job {job.id} as post {job.created_post_id}.")
                else:
                    _emit(f"Job {job.id} failed: {job.error}")

                if delay_seconds > 0 and not _STOP.is_set():
                    time.sleep(delay_seconds)

            remaining = GenerationJob.query.filter_by(status="pending").count()
            if _STOP.is_set() and remaining:
                _emit(f"Queue processor stopped. {remaining} pending job(s) left queued.")
            else:
                _emit(f"Queue processor completed. {processed} job(s) processed.")

    finally:
        with _LOCK:
            _IS_RUNNING = False
            _ACTIVE_RUN_ID = None
        _STOP.clear()


def summarise_jobs(*, run_id: str | None = None) -> dict[str, int]:
    query = GenerationJob.query
    if run_id:
        query = query.filter_by(run_id=run_id)

    rows = dict(query.with_entities(GenerationJob.status, func.count(GenerationJob.id)).group_by(GenerationJob.status).all())
    return {
        "pending": int(rows.get("pending", 0) or 0),
        "generating": int(rows.get("generating", 0) or 0),
        "posted": int(rows.get("posted", 0) or 0),
        "failed": int(rows.get("failed", 0) or 0),
        "cancelled": int(rows.get("cancelled", 0) or 0),
    }
