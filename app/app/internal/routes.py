"""
internal/routes.py — Internal API routes for KnowlyGen integration.
All routes require the X-Internal-Key header to match INTERNAL_API_KEY in .env.
These routes are not accessible to regular users.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
import hmac
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from sqlalchemy import func

from app import db
from app.models import Programme, Subject, Post, Like, UserActivity

bp = Blueprint("internal", __name__, url_prefix="/internal")


# ── Auth decorator ────────────────────────────────────────────────────────────

def internal_key_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-Internal-Key", "").strip()
        expected = os.getenv("INTERNAL_API_KEY", "").strip()
        if not key or not expected or not hmac.compare_digest(key, expected):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/ping")
@internal_key_required
def ping():
    """Health check — confirms the key is valid and the app is reachable."""
    return jsonify({"status": "ok"})


@bp.route("/programmes")
@internal_key_required
def internal_programmes():
    """
    Returns all active programmes as JSON.
    Replaces HTML scraping of /library.
    """
    programmes = Programme.query.order_by(Programme.name).all()
    return jsonify({
        "programmes": [
            {
                "id":   p.id,
                "slug": p.slug,
                "name": p.name,
            }
            for p in programmes
        ]
    })


@bp.route("/subjects/<programme_slug>")
@internal_key_required
def internal_subjects(programme_slug: str):
    """
    Returns all subjects for a programme as JSON.
    Replaces HTML scraping of /library/programme/<slug>.
    """
    programme = Programme.query.filter_by(slug=programme_slug).first()
    if not programme:
        return jsonify({"error": f"Programme '{programme_slug}' not found"}), 404

    subjects = Subject.query.filter(
        Subject.is_active == True,
        Subject.programmes.any(Programme.id == programme.id)
    ).order_by(Subject.name).all()
    return jsonify({
        "programme": {"id": programme.id, "slug": programme.slug, "name": programme.name},
        "subjects": [
            {
                "id":   s.id,
                "slug": s.slug,
                "name": s.name,
            }
            for s in subjects
        ]
    })


@bp.route("/coverage/<subject_slug>")
@internal_key_required
def internal_coverage(subject_slug: str):
    """
    Returns post counts by content_type for a subject, plus engagement data.
    Replaces HTML scraping of /library/subject/<slug>.
    """
    subject = Subject.query.filter_by(slug=subject_slug).first()
    if not subject:
        return jsonify({"error": f"Subject '{subject_slug}' not found"}), 404

    # Count approved posts by content type
    approved = Post.query.filter_by(
        subject_id=subject.id,
        status='approved',
    )
    counts = dict(
        approved.with_entities(
            Post.content_type,
            func.count(Post.id),
        ).group_by(Post.content_type).all()
    )

    # Engagement: count posts that have at least one like
    liked_post_ids = (
        db.session.query(Like.post_id)
        .join(Post, Post.id == Like.post_id)
        .filter(Post.subject_id == subject.id)
        .distinct()
        .count()
    )

    return jsonify({
        "subject_id":      subject.id,
        "subject_name":    subject.name,
        "notes":           counts.get("notes",      0),
        "quiz":            counts.get("quiz",       0),
        "cheatsheet":      counts.get("cheatsheet", 0),
        "total":           sum(counts.values()),
        "engagement_zero": liked_post_ids == 0,
    })

@bp.route("/titles/<subject_slug>")
@internal_key_required
def internal_titles(subject_slug: str):
    """
    Returns existing approved post titles grouped by content_type for a subject.
    Used by KnowlyGen to avoid generating duplicate topics per content type.
    """
    subject = Subject.query.filter_by(slug=subject_slug).first()
    if not subject:
        return jsonify({"notes": [], "quiz": [], "cheatsheet": []}), 200

    rows = (
        Post.query
        .filter_by(subject_id=subject.id, status='approved')
        .with_entities(Post.content_type, Post.title)
        .all()
    )

    result = {"notes": [], "quiz": [], "cheatsheet": []}
    for content_type, title in rows:
        if content_type in result:
            result[content_type].append(title)

    return jsonify(result)


@bp.route("/subjects-search")
@internal_key_required
def subjects_search():
    """
    Search all subjects by name or slug query.
    ?q=calculus  — returns up to 40 matching subjects with programme info.
    """
    q = request.args.get("q", "").strip().lower()

    query = Subject.query.filter(Subject.is_active == True)
    if q:
        query = query.filter(
            db.or_(
                Subject.name.ilike(f"%{q}%"),
                Subject.slug.ilike(f"%{q}%"),
            )
        )
    results = query.order_by(Subject.name).limit(40).all()

    return jsonify({
        "subjects": [
            {
                "id":             s.id,
                "slug":           s.slug,
                "name":           s.name,
                "programme":      s.programmes.first().name if s.programmes.first() else None,
                "programme_slug": s.programmes.first().slug if s.programmes.first() else None,
            }
            for s in results
        ]
    })


@bp.route("/subjects-by-id/<int:programme_id>")
def subjects_by_id(programme_id: int):
    """
    Public endpoint (no internal key required) — used by the student
    upload form to load subjects for a selected programme.
    """
    programme = Programme.query.get_or_404(programme_id)
    subjects  = programme.subjects.filter_by(is_active=True).order_by(Subject.name).all()
    return jsonify({
        "subjects": [{"id": s.id, "slug": s.slug, "name": s.name}
                     for s in subjects]
    })

@bp.route("/student-papers")
@internal_key_required
def student_papers():
    """
    Returns all uncollected student past papers.
    KnowlyGen polls this at the start of every run.
    """
    from app.models import StudentPastPaper
    papers = (StudentPastPaper.query
              .filter_by(status='pending')
              .order_by(StudentPastPaper.uploaded_at.asc())
              .all())
    return jsonify({"papers": [p.to_dict() for p in papers]})


@bp.route("/student-papers/<int:paper_id>/file")
@internal_key_required
def student_paper_file(paper_id: int):
    """
    Serve the paper file to KnowlyGen.

    Production (Cloudinary): issues a redirect to the Cloudinary URL — no disk
    access required, so this works regardless of Render's ephemeral filesystem.

    Local dev: streams the file directly from the local filesystem path stored
    in paper.file_path (absolute path on the dev machine).
    """
    from app.models import StudentPastPaper
    paper = StudentPastPaper.query.get_or_404(paper_id)

    if paper.is_cloudinary:
        # Redirect KnowlyGen straight to the Cloudinary CDN URL.
        # The X-Internal-Key header is not forwarded, which is fine — the
        # Cloudinary URL is already authenticated via a signed path or public.
        from flask import redirect as _redirect
        return _redirect(paper.file_path)

    # Local dev fallback: stream from disk.
    if not Path(paper.file_path).exists():
        return jsonify({"error": "File not found on disk"}), 404
    return send_file(paper.file_path, as_attachment=True,
                     download_name=paper.filename)


@bp.route("/student-papers/<int:paper_id>/collected", methods=["PATCH"])
@internal_key_required
def mark_collected(paper_id: int):
    """KnowlyGen calls this after successfully downloading a paper."""
    from app.models import StudentPastPaper
    paper = StudentPastPaper.query.get_or_404(paper_id)
    paper.status       = 'collected'
    paper.collected_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"status": "collected"})


@bp.route("/create-subject", methods=["POST"])
@internal_key_required
def create_subject():
    """
    Create a new subject under an existing programme.
    Body (JSON):
        {
            "programme_slug": "ma",
            "name":           "MA203 – Vector Calculus",
            "slug":           "ma203"          # optional — auto-derived if omitted
        }
    Returns:
        { "id": <int>, "slug": "ma203", "name": "MA203 – Vector Calculus", "created": true }
    or if the slug already exists:
        { "id": <int>, "slug": "ma203", "name": "...", "created": false }
    """
    import re as _re

    data            = request.get_json(force=True, silent=True) or {}
    programme_slug  = (data.get("programme_slug") or "").strip()
    name            = (data.get("name") or "").strip()
    slug            = (data.get("slug") or "").strip()

    if not programme_slug or not name:
        return jsonify({"error": "programme_slug and name are required"}), 400

    programme = Programme.query.filter_by(slug=programme_slug).first()
    if not programme:
        return jsonify({"error": f"Programme '{programme_slug}' not found"}), 404

    # Derive slug from name if not provided
    if not slug:
        slug = _re.sub(r"[^a-z0-9-]", "", name.lower().replace(" ", "-").replace("–", "-"))
        slug = _re.sub(r"-+", "-", slug).strip("-")

    # Return existing subject if slug already taken
    existing = Subject.query.filter_by(slug=slug).first()
    if existing:
        return jsonify({
            "id":      existing.id,
            "slug":    existing.slug,
            "name":    existing.name,
            "created": False,
        })

    subject = Subject(
        name      = name,
        slug      = slug,
        is_active = True,
    )
    subject.programmes.append(programme)
    db.session.add(subject)
    db.session.commit()

    return jsonify({
        "id":      subject.id,
        "slug":    subject.slug,
        "name":    subject.name,
        "created": True,
    }), 201

@bp.route("/subject/<subject_slug>/add-programme", methods=["POST"])
@internal_key_required
def add_subject_programme(subject_slug: str):
    """
    Link a subject to an additional programme.
    Body (JSON): { "programme_slug": "bsc-cs" }
    Called by KnowlyGen after uploading a post with shared_programmes set.
    """
    data = request.get_json(force=True, silent=True) or {}
    programme_slug = (data.get("programme_slug") or "").strip()

    if not programme_slug:
        return jsonify({"error": "programme_slug is required"}), 400

    subject = Subject.query.filter_by(slug=subject_slug).first()
    if not subject:
        return jsonify({"error": f"Subject '{subject_slug}' not found"}), 404

    programme = Programme.query.filter_by(slug=programme_slug).first()
    if not programme:
        return jsonify({"error": f"Programme '{programme_slug}' not found"}), 404

    if programme in subject.programmes.all():
        return jsonify({"message": "already linked", "subject": subject_slug, "programme": programme_slug}), 200

    subject.programmes.append(programme)
    db.session.commit()

    return jsonify({"message": "linked", "subject": subject_slug, "programme": programme_slug}), 200


# ── Ghost Mode: Active users studying a post ────────────────────────────────

@bp.route("/active-users/<int:post_id>")
@internal_key_required
def get_active_users(post_id):
    """
    Returns count of users currently studying a specific post.
    Uses UserActivity to track active sessions - "Ghost Mode" feature.
    """
    # Consider users active if they have a heartbeat within last 5 minutes
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    
    count = UserActivity.query.filter(
        UserActivity.current_post_id == post_id,
        UserActivity.is_active == True,
        UserActivity.last_heartbeat >= cutoff
    ).count()
    
    return jsonify({
        "post_id": post_id,
        "active_count": count,
        "message": f"{count} student{'s' if count != 1 else ''} studying this now"
    })