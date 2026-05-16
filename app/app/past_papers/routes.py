"""
past_papers/routes.py — Student past paper upload feature.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from flask import (Blueprint, current_app, flash,
                   redirect, render_template, request, url_for)
from flask_login import current_user, login_required

from app import db
from app.models import StudentPastPaper, Subject, Programme, AuraTransaction

bp = Blueprint('past_papers', __name__)

ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
MAX_FILE_SIZE      = 20 * 1024 * 1024
XP_REWARD          = 50


def _allowed(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def _award_xp(user, amount: int, reason: str) -> None:
    streak_bonus = ""
    if user.current_streak > 0:
        streak_bonus = f" (+{user.current_streak} day streak bonus)"
    user.add_xp(amount, apply_streak_multiplier=True, reason=reason + streak_bonus)


@bp.route('/')
@login_required
def index():
    # ── Filter params ─────────────────────────────────────────────────────────
    sel_programme = request.args.get('programme', type=int)
    sel_subject   = request.args.get('subject',   type=int)
    sel_year      = request.args.get('year',       '').strip()
    sel_semester  = request.args.get('semester',   '').strip()
    page          = request.args.get('page', 1, type=int)

    # ── Community archive query ───────────────────────────────────────────────
    q = (StudentPastPaper.query
         .filter_by(status='collected')          # only approved papers
         .join(StudentPastPaper.subject))

    if sel_subject:
        q = q.filter(StudentPastPaper.subject_id == sel_subject)
    elif sel_programme:
        from app.models import Subject as Subj, programme_subjects
        subj_ids = (db.session.query(Subj.id)
                    .join(programme_subjects,
                          programme_subjects.c.subject_id == Subj.id)
                    .filter(programme_subjects.c.programme_id == sel_programme)
                    .subquery())
        q = q.filter(StudentPastPaper.subject_id.in_(subj_ids))

    if sel_year:
        q = q.filter(StudentPastPaper.year == sel_year)
    if sel_semester:
        q = q.filter(StudentPastPaper.semester == sel_semester)

    papers = (q.order_by(StudentPastPaper.year.desc().nullslast(),
                         StudentPastPaper.uploaded_at.desc())
               .paginate(page=page, per_page=20, error_out=False))

    # ── Sidebar data ──────────────────────────────────────────────────────────
    programmes  = Programme.query.order_by(Programme.name).all()
    subjects    = []
    if sel_programme:
        from app.models import Subject as Subj, programme_subjects
        subjects = (Subj.query
                    .join(programme_subjects,
                          programme_subjects.c.subject_id == Subj.id)
                    .filter(programme_subjects.c.programme_id == sel_programme)
                    .order_by(Subj.name).all())

    # Available years for the year filter (from real data)
    years = (db.session.query(StudentPastPaper.year)
             .filter(StudentPastPaper.status == 'collected',
                     StudentPastPaper.year.isnot(None))
             .distinct()
             .order_by(StudentPastPaper.year.desc())
             .all())
    years = [r[0] for r in years]

    # ── My uploads (collapsed section at bottom) ──────────────────────────────
    my_papers = (StudentPastPaper.query
                 .filter_by(user_id=current_user.id)
                 .order_by(StudentPastPaper.uploaded_at.desc())
                 .limit(10).all())

    # ── Stats ─────────────────────────────────────────────────────────────────
    total_count = StudentPastPaper.query.filter_by(status='collected').count()

    return render_template(
        'past_papers/index.html',
        papers=papers,
        programmes=programmes,
        subjects=subjects,
        years=years,
        my_papers=my_papers,
        xp_reward=XP_REWARD,
        sel_programme=sel_programme,
        sel_subject=sel_subject,
        sel_year=sel_year,
        sel_semester=sel_semester,
        total_count=total_count,
    )


@bp.route('/upload', methods=['POST'])
@login_required
def upload():
    subject_slug = request.form.get('subject_slug', '').strip()
    year         = request.form.get('year', '').strip()
    semester     = request.form.get('semester', '').strip()
    description  = request.form.get('description', '').strip()
    file         = request.files.get('file')
    redirect_to  = request.form.get('redirect_to', 'past_papers.index')

    if not subject_slug:
        flash('Please select a subject.', 'danger')
        return redirect(url_for(redirect_to))

    subject = Subject.query.filter_by(slug=subject_slug).first()
    if not subject:
        flash('Subject not found.', 'danger')
        return redirect(url_for(redirect_to))

    if not file or not file.filename:
        flash('No file selected.', 'danger')
        return redirect(url_for(redirect_to))

    if not _allowed(file.filename):
        flash('Only PDF and image files (JPG, PNG) are allowed.', 'danger')
        return redirect(url_for(redirect_to))

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        flash('File too large — maximum size is 20 MB.', 'danger')
        return redirect(url_for(redirect_to))

    suffix = Path(file.filename).suffix.lower()
    ftype  = 'pdf' if suffix == '.pdf' else 'image'

    # ── Upload to Cloudinary ──────────────────────────────────────────────────
    try:
        import cloudinary.uploader
        result = cloudinary.uploader.upload(
            file,
            folder='knowly/past_papers',
            resource_type='auto',
            use_filename=False,
            unique_filename=True,
        )
        file_path = result['secure_url']
    except Exception as exc:
        current_app.logger.error("Past paper Cloudinary upload failed: %s", exc)
        flash('File upload failed — please try again.', 'danger')
        return redirect(url_for(redirect_to))

    paper = StudentPastPaper(
        user_id      = current_user.id,
        subject_id   = subject.id,
        subject_slug = subject_slug,
        filename     = file.filename,
        file_path    = file_path,
        file_type    = ftype,
        file_size    = size,
        year         = year or None,
        semester     = semester or None,
        description  = description or None,
        status       = 'pending',
    )
    db.session.add(paper)
    _award_xp(current_user, XP_REWARD, f'Uploaded past paper for {subject.name}')
    paper.xp_awarded = True
    db.session.commit()

    flash(f'Past paper uploaded successfully! You earned {XP_REWARD} Aura 🎉', 'success')
    return (redirect(url_for(redirect_to, slug=subject_slug))
            if redirect_to != 'past_papers.index'
            else redirect(url_for('past_papers.index')))