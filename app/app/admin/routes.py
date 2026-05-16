from flask import render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import current_user
from app import db
from app.admin import bp
from app.forms import SubjectForm, BulkEmailForm, ProgrammeForm
from app.models import Subject, User, Post, Comment, Document, Programme, GenerationJob, VideoLesson, VideoLesson, VideoLesson, VideoLesson, VideoLesson, VideoLesson, VideoLesson, VideoLesson, VideoLesson, VideoLesson
from app.services.auto_resource_generation import SubjectGap, detect_subject_gaps, generate_topics_for_gap, run_generation_cycle
from app.services.auto_resource_runner import (
    get_log_snapshot,
    get_runner_state,
    start_background_run,
    start_queue_processing,
    stop_active_run,
    summarise_jobs,
)
from app.utils import admin_required
from sqlalchemy import case, func
from datetime import datetime
import re
import os
import threading
import logging


_ALL_CONTENT_TYPES = ['notes', 'quiz', 'cheatsheet']


def _first_programme_for_subject(subject):
    """Return the first linked programme for a subject across lazy-loading styles."""
    programmes_rel = getattr(subject, 'programmes', None)
    if programmes_rel is None:
        return None

    first_fn = getattr(programmes_rel, 'first', None)
    if callable(first_fn):
        return first_fn()

    programmes = list(programmes_rel)
    return programmes[0] if programmes else None


def slugify(text):
    """Convert text to URL-friendly slug."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def _run_background_categorization(app, video_id, video_title, allowed_subjects):
    """Worker function to run categorization in a separate thread."""
    with app.app_context():
        try:
            from app.services.video_categorizer import categorize_video_title
            result = categorize_video_title(video_title, allowed_subjects)
            video = VideoLesson.query.get(video_id)
            if video and isinstance(result, dict):
                video.academic_category = result.get("subject", "Uncategorized")
                video.content_difficulty = result.get("level", "Beginner")
                video.order_index = result.get("sequence", 0)
                db.session.commit()
                logging.info(f"Categorized video {video_id} ('{video_title}') as '{video.academic_category}' level={video.content_difficulty}")
        except Exception as e:
            logging.error(f"Background categorization failed for video {video_id}: {str(e)}")


@bp.route('/')
@admin_required
def dashboard():
    """Admin dashboard with overview statistics."""
    total_users    = User.query.count()
    total_posts    = Post.query.count()
    total_subjects = Subject.query.count()
    total_comments = Comment.query.count()

    pending_count  = Post.query.filter_by(status='pending').count()
    approved_count = Post.query.filter_by(status='approved').count()
    rejected_count = Post.query.filter_by(status='rejected').count()

    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()

    return render_template(
        'admin/dashboard.html',
        title='Admin Dashboard',
        total_users=total_users,
        total_posts=total_posts,
        total_subjects=total_subjects,
        total_comments=total_comments,
        pending_count=pending_count,
        approved_count=approved_count,
        rejected_count=rejected_count,
        recent_users=recent_users,
        recent_posts=recent_posts,
    )


@bp.route('/resource-generation', methods=['GET', 'POST'])
@admin_required
def resource_generation():
    report = None
    runner_state = get_runner_state()

    if request.method == 'POST':
        min_coverage = request.form.get('min_coverage', 3, type=int) or 3
        topics_per_subject = request.form.get('topics_per_subject', 2, type=int) or 2
        max_subjects = request.form.get('max_subjects', 10, type=int)
        max_api_calls = request.form.get('max_api_calls', 50, type=int) or 50
        delay_seconds = request.form.get('delay_seconds', 10, type=int) or 10
        year_filter = request.form.get('year_filter', type=int)
        semester_filter = request.form.get('semester_filter', type=int)
        dry_run = request.form.get('dry_run') == '1'

        content_types = list(_ALL_CONTENT_TYPES)

        programme_slugs = [slug.strip() for slug in request.form.getlist('programme_slugs') if slug.strip()]
        fixed_topics_raw = (request.form.get('fixed_topics') or '').strip()
        fixed_topics = [line.strip() for line in fixed_topics_raw.splitlines() if line.strip()]

        if dry_run:
            report = run_generation_cycle(
                actor=current_user,
                min_coverage=min_coverage,
                topics_per_subject=topics_per_subject,
                content_types=content_types,
                programme_slugs=programme_slugs or None,
                year_filter=year_filter,
                semester_filter=semester_filter,
                fixed_topics=fixed_topics or None,
                max_subjects=max_subjects,
                dry_run=True,
            )
        else:
            ok, payload = start_background_run(
                current_app._get_current_object(),
                actor_id=current_user.id,
                config={
                    'min_coverage': min_coverage,
                    'topics_per_subject': topics_per_subject,
                    'max_subjects': max_subjects,
                    'max_api_calls': max_api_calls,
                    'delay_seconds': delay_seconds,
                    'content_types': content_types,
                    'programme_slugs': programme_slugs or None,
                    'year_filter': year_filter,
                    'semester_filter': semester_filter,
                    'fixed_topics': fixed_topics or None,
                },
            )
            if ok:
                flash(f'Generation run started ({payload}).', 'success')
                return redirect(url_for('admin.resource_generation_jobs'))
            flash(payload, 'warning')
            return redirect(url_for('admin.resource_generation'))

        if report and report.get('failed'):
            flash(
                f"Generation finished with {report['failed']} failure(s). "
                f"Created {report.get('created', 0)} post(s).",
                'warning',
            )
        elif report and dry_run:
            flash(
                f"Dry run complete: {report.get('planned', 0)} generation task(s) planned.",
                'info',
            )

    stats = summarise_jobs()
    recent_jobs = GenerationJob.query.order_by(GenerationJob.updated_at.desc()).limit(15).all()
    runner_state = get_runner_state()
    programmes = Programme.query.filter_by(is_active=True).order_by(Programme.name.asc()).all()
    return render_template(
        'admin/resource_generation.html',
        title='Resource Generation',
        programmes=programmes,
        report=report,
        stats=stats,
        recent_jobs=recent_jobs,
        runner_state=runner_state,
    )


@bp.route('/resource-generation/jobs')
@admin_required
def resource_generation_jobs():
    status_filter = (request.args.get('status') or '').strip().lower()
    query = GenerationJob.query.order_by(GenerationJob.updated_at.desc())
    if status_filter:
        query = query.filter_by(status=status_filter)
    jobs = query.limit(400).all()
    return render_template(
        'admin/resource_generation_jobs.html',
        title='Generation Jobs',
        jobs=jobs,
        status_filter=status_filter,
        stats=summarise_jobs(),
        runner_state=get_runner_state(),
    )


@bp.route('/resource-generation/queue', methods=['POST'])
@admin_required
def process_generation_queue():
    pending_count = GenerationJob.query.filter_by(status='pending').count()
    if pending_count <= 0:
        flash('No pending jobs to process.', 'info')
        return redirect(request.referrer or url_for('admin.resource_generation_jobs'))

    ok, payload = start_queue_processing(
        current_app._get_current_object(),
        actor_id=current_user.id,
        delay_seconds=0,
    )
    if ok:
        flash(f'Queue processor started ({payload}).', 'success')
    else:
        flash(payload, 'warning')
    return redirect(url_for('admin.resource_generation_jobs'))


@bp.route('/resource-generation/runs')
@admin_required
def resource_generation_runs():
    run_rows = (
        db.session.query(
            GenerationJob.run_id,
            func.count(GenerationJob.id).label('total'),
            func.sum(case((GenerationJob.status == 'posted', 1), else_=0)).label('posted'),
            func.sum(case((GenerationJob.status == 'failed', 1), else_=0)).label('failed'),
            func.sum(case((GenerationJob.status == 'pending', 1), else_=0)).label('pending'),
            func.sum(case((GenerationJob.status == 'generating', 1), else_=0)).label('generating'),
            func.max(GenerationJob.updated_at).label('last_updated'),
            func.min(GenerationJob.created_at).label('started_at'),
        )
        .group_by(GenerationJob.run_id)
        .order_by(func.max(GenerationJob.updated_at).desc())
        .all()
    )

    runs = []
    for row in run_rows:
        total = int(row.total or 0)
        posted = int(row.posted or 0)
        failed = int(row.failed or 0)
        pending = int(row.pending or 0)
        generating = int(row.generating or 0)
        completion_pct = int(round((posted + failed) / total * 100)) if total else 0
        runs.append(
            {
                'run_id': row.run_id,
                'total': total,
                'posted': posted,
                'failed': failed,
                'pending': pending,
                'generating': generating,
                'completion_pct': completion_pct,
                'last_updated': row.last_updated,
                'started_at': row.started_at,
            }
        )

    return render_template(
        'admin/resource_generation_runs.html',
        title='Generation Runs',
        runs=runs,
        runner_state=get_runner_state(),
    )


@bp.route('/resource-generation/runs/<string:run_id>')
@admin_required
def resource_generation_run_detail(run_id):
    jobs = (
        GenerationJob.query
        .filter_by(run_id=run_id)
        .order_by(GenerationJob.updated_at.desc(), GenerationJob.id.desc())
        .all()
    )
    if not jobs:
        flash(f'Run {run_id} not found.', 'warning')
        return redirect(url_for('admin.resource_generation_runs'))

    totals = {
        'total': len(jobs),
        'posted': sum(1 for j in jobs if j.status == 'posted'),
        'failed': sum(1 for j in jobs if j.status == 'failed'),
        'pending': sum(1 for j in jobs if j.status == 'pending'),
        'generating': sum(1 for j in jobs if j.status == 'generating'),
        'cancelled': sum(1 for j in jobs if j.status == 'cancelled'),
    }

    subjects_count = len({j.subject_slug for j in jobs if j.subject_slug})
    programmes_count = len({j.programme_slug for j in jobs if j.programme_slug})
    avg_attempts = round(sum(int(j.attempts or 0) for j in jobs) / max(1, len(jobs)), 2)

    failure_topics = [
        {
            'topic': j.topic,
            'subject': j.subject_slug,
            'content_type': j.content_type,
            'error': j.error or '',
        }
        for j in jobs if j.status == 'failed'
    ][:40]

    started_at = min(j.created_at for j in jobs if j.created_at)
    last_updated = max(j.updated_at for j in jobs if j.updated_at)

    analytics = {
        **totals,
        'subjects_count': subjects_count,
        'programmes_count': programmes_count,
        'avg_attempts': avg_attempts,
        'started_at': started_at,
        'last_updated': last_updated,
    }

    return render_template(
        'admin/resource_generation_run_detail.html',
        title=f'Run {run_id}',
        run_id=run_id,
        analytics=analytics,
        jobs=jobs,
        failure_topics=failure_topics,
        runner_state=get_runner_state(),
    )


@bp.route('/resource-generation/manual-job', methods=['GET', 'POST'])
@admin_required
def resource_generation_manual_job():
    subjects = Subject.query.filter_by(is_active=True).order_by(Subject.name.asc()).all()

    if request.method == 'POST':
        subject_id = request.form.get('subject_id', type=int)
        subject_lookup = (request.form.get('subject_lookup') or '').strip()
        topic = (request.form.get('topic') or '').strip()
        level = (request.form.get('level') or 'Intermediate').strip()
        year = request.form.get('year', type=int)
        semester = request.form.get('semester', type=int)

        if not subject_id and subject_lookup:
            exact_match = Subject.query.filter(Subject.name.ilike(subject_lookup)).first()
            if exact_match:
                subject_id = exact_match.id

        if not subject_id or not topic:
            flash('Subject and topic are required.', 'warning')
            return redirect(url_for('admin.resource_generation_manual_job'))

        subject = Subject.query.get(subject_id)
        if not subject:
            flash('Selected subject was not found.', 'warning')
            return redirect(url_for('admin.resource_generation_manual_job'))

        programme = _first_programme_for_subject(subject)
        run_id = f"manual-{current_user.id}-{int(datetime.utcnow().timestamp())}"

        created = 0
        skipped = 0
        for content_type in _ALL_CONTENT_TYPES:
            existing = (
                GenerationJob.query
                .filter_by(subject_id=subject.id, topic=topic, content_type=content_type)
                .filter(GenerationJob.status.in_(['pending', 'generating', 'posted']))
                .first()
            )
            if existing:
                skipped += 1
                continue

            job = GenerationJob(
                run_id=run_id,
                actor_id=current_user.id,
                programme_slug=programme.slug if programme else None,
                programme_name=programme.name if programme else None,
                subject_id=subject.id,
                subject_slug=subject.slug,
                subject_name=subject.name,
                topic=topic,
                content_type=content_type,
                level=level,
                year=year,
                semester=semester,
                status='pending',
                source='manual',
                priority=1,
            )
            db.session.add(job)
            created += 1

        db.session.commit()

        if created == 0:
            flash('No new jobs queued. Matching jobs already exist.', 'info')
        else:
            flash(f'Queued {created} manual job(s). Skipped duplicates: {skipped}.', 'success')
        return redirect(url_for('admin.resource_generation_jobs'))

    return render_template(
        'admin/resource_generation_manual_job.html',
        title='Create Manual Generation Job',
        subjects=subjects,
        runner_state=get_runner_state(),
    )


@bp.route('/resource-generation/generate-for-subject', methods=['GET', 'POST'])
@admin_required
def resource_generation_generate_for_subject():
    subjects = Subject.query.filter_by(is_active=True).order_by(Subject.name.asc()).all()
    programmes = Programme.query.filter_by(is_active=True).order_by(Programme.name.asc()).all()
    preview_topics = None
    form_defaults = {
        'subject_id': None,
        'programme_id': None,
        'level': 'Intermediate',
        'year': None,
        'semester': None,
        'auto_topics': True,
        'topics_per_type': 2,
        'topics_raw': '',
    }

    if request.method == 'POST':
        action = (request.form.get('action') or 'queue').strip().lower()
        subject_id = request.form.get('subject_id', type=int)
        topics_raw = (request.form.get('topics') or '').strip()
        auto_topics = request.form.get('auto_topics') == '1'
        topics_per_type = request.form.get('topics_per_type', type=int) or 2
        topics_per_type = max(1, min(topics_per_type, 6))
        level = (request.form.get('level') or 'Intermediate').strip()
        programme_id = request.form.get('programme_id', type=int)
        year = request.form.get('year', type=int)
        semester = request.form.get('semester', type=int)
        content_types = list(_ALL_CONTENT_TYPES)

        form_defaults = {
            'subject_id': subject_id,
            'programme_id': programme_id,
            'level': level,
            'year': year,
            'semester': semester,
            'auto_topics': auto_topics,
            'topics_per_type': topics_per_type,
            'topics_raw': topics_raw,
        }

        manual_topics = [line.strip() for line in topics_raw.splitlines() if line.strip()]
        if not subject_id:
            flash('Subject is required.', 'warning')
            return redirect(url_for('admin.resource_generation_generate_for_subject'))
        if not auto_topics and not manual_topics:
            flash('Provide at least one topic when auto generation is off.', 'warning')
            return redirect(url_for('admin.resource_generation_generate_for_subject'))

        subject = Subject.query.get(subject_id)
        if not subject:
            flash('Selected subject was not found.', 'warning')
            return redirect(url_for('admin.resource_generation_generate_for_subject'))

        programme = Programme.query.get(programme_id) if programme_id else _first_programme_for_subject(subject)
        run_id = f"subject-{subject.id}-{int(datetime.utcnow().timestamp())}"

        existing_titles = {'notes': [], 'quiz': [], 'cheatsheet': []}
        for post in (
            Post.query
            .filter_by(subject_id=subject.id, status='approved')
            .with_entities(Post.content_type, Post.title)
            .all()
        ):
            if post[0] in existing_titles and post[1]:
                existing_titles[post[0]].append(str(post[1]).strip())

        gap_candidates = detect_subject_gaps(
            min_coverage=1,
            content_types=tuple(content_types),
            programme_slugs=[programme.slug] if programme else None,
            year_filter=year,
            semester_filter=semester,
            max_subjects=500,
        )
        selected_gap = next((gap for gap in gap_candidates if gap.subject_id == subject.id), None)

        if selected_gap is not None:
            selected_gap.existing_titles = existing_titles
            selected_gap.missing_types = content_types
            if year is not None:
                selected_gap.year = year
            if semester is not None:
                selected_gap.semester = semester
            selected_gap.level = level
            if programme and programme.name:
                selected_gap.programme_name = programme.name
        elif auto_topics:
            inferred_programme = programme or _first_programme_for_subject(subject)
            selected_gap = SubjectGap(
                subject_id=subject.id,
                subject_slug=subject.slug,
                subject_name=subject.name,
                programme_name=inferred_programme.name if inferred_programme else "General Programme",
                year=year,
                semester=semester,
                level=level,
                missing_types=list(content_types),
                existing_titles=existing_titles,
            )

        topics_by_type: dict[str, list[str]] = {}
        auto_generated = 0
        for content_type in content_types:
            if auto_topics and selected_gap is not None:
                topics_for_type = generate_topics_for_gap(selected_gap, content_type, topics_per_type)
                auto_generated += len(topics_for_type)
            elif auto_topics:
                topics_for_type = [f"Core Concepts in {subject.name}"][:topics_per_type]
                auto_generated += len(topics_for_type)
            else:
                topics_for_type = manual_topics
            topics_by_type[content_type] = topics_for_type

        if action == 'preview':
            preview_topics = topics_by_type
            return render_template(
                'admin/resource_generation_generate_for_subject.html',
                title='Generate For Subject',
                subjects=subjects,
                programmes=programmes,
                runner_state=get_runner_state(),
                form_defaults=form_defaults,
                preview_topics=preview_topics,
            )

        created = 0
        skipped_duplicates = 0
        for content_type, topics_for_type in topics_by_type.items():
            for topic in topics_for_type:
                existing = (
                    GenerationJob.query
                    .filter_by(subject_id=subject.id, topic=topic, content_type=content_type)
                    .filter(GenerationJob.status.in_(['pending', 'generating', 'posted']))
                    .first()
                )
                if existing:
                    skipped_duplicates += 1
                    continue

                db.session.add(
                    GenerationJob(
                        run_id=run_id,
                        actor_id=current_user.id,
                        programme_slug=programme.slug if programme else None,
                        programme_name=programme.name if programme else None,
                        subject_id=subject.id,
                        subject_slug=subject.slug,
                        subject_name=subject.name,
                        topic=topic,
                        content_type=content_type,
                        level=level,
                        year=year,
                        semester=semester,
                        status='pending',
                        source='auto' if auto_topics else 'manual',
                        priority=1,
                    )
                )
                created += 1

        db.session.commit()
        if created == 0:
            flash('No new jobs queued. Matching jobs may already exist.', 'info')
        else:
            detail = (
                f'Queued {created} job(s) for {subject.name}. '
                f'Auto-topics generated: {auto_generated}. '
                f'Skipped duplicates: {skipped_duplicates}.'
            )
            flash(detail, 'success')
        return redirect(url_for('admin.resource_generation_jobs'))

    return render_template(
        'admin/resource_generation_generate_for_subject.html',
        title='Generate For Subject',
        subjects=subjects,
        programmes=programmes,
        runner_state=get_runner_state(),
        form_defaults=form_defaults,
        preview_topics=preview_topics,
    )


@bp.route('/resource-generation/jobs/<int:job_id>/retry', methods=['POST'])
@admin_required
def retry_generation_job(job_id):
    job = GenerationJob.query.get_or_404(job_id)
    job.status = 'pending'
    job.error = None
    job.attempts = 0
    db.session.commit()
    flash(f'Job #{job.id} re-queued.', 'success')
    return redirect(request.referrer or url_for('admin.resource_generation_jobs'))


@bp.route('/resource-generation/jobs/retry-all', methods=['POST'])
@admin_required
def retry_all_generation_jobs():
    jobs = GenerationJob.query.filter(GenerationJob.status.in_(['failed', 'cancelled'])).all()
    if not jobs:
        flash('No failed or cancelled jobs to requeue.', 'info')
        return redirect(request.referrer or url_for('admin.resource_generation_jobs'))

    for job in jobs:
        job.status = 'pending'
        job.error = None
        job.attempts = 0
    db.session.commit()
    flash(f'Requeued {len(jobs)} job(s).', 'success')
    return redirect(request.referrer or url_for('admin.resource_generation_jobs'))


@bp.route('/resource-generation/jobs/<int:job_id>/cancel', methods=['POST'])
@admin_required
def cancel_generation_job(job_id):
    job = GenerationJob.query.get_or_404(job_id)
    if job.status in {'pending', 'generating'}:
        job.status = 'cancelled'
        db.session.commit()
        flash(f'Job #{job.id} cancelled.', 'info')
    return redirect(request.referrer or url_for('admin.resource_generation_jobs'))


@bp.route('/resource-generation/jobs/<int:job_id>/delete', methods=['POST'])
@admin_required
def delete_generation_job(job_id):
    job = GenerationJob.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    flash(f'Job #{job_id} deleted.', 'success')
    return redirect(request.referrer or url_for('admin.resource_generation_jobs'))


@bp.route('/resource-generation/stop', methods=['POST'])
@admin_required
def stop_generation_run():
    if stop_active_run():
        flash('Stop signal sent to active generation run.', 'warning')
    else:
        flash('No active generation run.', 'info')
    return redirect(request.referrer or url_for('admin.resource_generation'))


@bp.route('/resource-generation/log')
@admin_required
def resource_generation_log():
    return render_template(
        'admin/resource_generation_log.html',
        title='Generation Log',
        runner_state=get_runner_state(),
    )


@bp.route('/resource-generation/log/snapshot')
@admin_required
def resource_generation_log_snapshot():
    return jsonify(get_log_snapshot())


# ============ PROGRAMME MANAGEMENT ============

@bp.route('/programmes')
@admin_required
def programmes():
    programmes = Programme.query.order_by(Programme.order, Programme.name).all()
    return render_template('admin/programmes.html', title='Manage Programmes', programmes=programmes)


@bp.route('/programmes/create', methods=['GET', 'POST'])
@admin_required
def create_programme():
    form = ProgrammeForm()
    if form.validate_on_submit():
        slug = slugify(form.name.data)
        if Programme.query.filter_by(slug=slug).first():
            flash('A programme with this name already exists.', 'danger')
            return redirect(url_for('admin.create_programme'))
        prog = Programme(
            name=form.name.data,
            slug=slug,
            description=form.description.data or None,
            icon=form.icon.data or 'graduation-cap',
            color=form.color.data or '#8b5cf6',
            order=int(form.order.data) if form.order.data else 0,
            is_active=form.is_active.data,
            faculty=form.faculty.data or None,
        )
        db.session.add(prog)
        db.session.commit()
        flash(f'Programme "{prog.name}" created successfully!', 'success')
        return redirect(url_for('admin.programmes'))
    form.is_active.data = True
    existing_faculties = sorted({p.faculty for p in Programme.query.all() if p.faculty})
    return render_template('admin/programme_form.html', title='Create Programme', form=form, programme=None, existing_faculties=existing_faculties)


@bp.route('/programmes/<int:programme_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_programme(programme_id):
    prog = Programme.query.get_or_404(programme_id)
    form = ProgrammeForm()
    if form.validate_on_submit():
        new_slug = slugify(form.name.data)
        if new_slug != prog.slug:
            existing = Programme.query.filter_by(slug=new_slug).first()
            if existing and existing.id != prog.id:
                flash('A programme with this name already exists.', 'danger')
                return redirect(url_for('admin.edit_programme', programme_id=prog.id))
            prog.slug = new_slug
        prog.name        = form.name.data
        prog.description = form.description.data or None
        prog.icon        = form.icon.data or 'graduation-cap'
        prog.color       = form.color.data or '#8b5cf6'
        prog.order       = int(form.order.data) if form.order.data else 0
        prog.is_active   = form.is_active.data
        prog.faculty = form.faculty.data or None
        db.session.commit()
        flash(f'Programme "{prog.name}" updated successfully!', 'success')
        return redirect(url_for('admin.programmes'))
    elif request.method == 'GET':
        form.name.data        = prog.name
        form.description.data = prog.description
        form.icon.data        = prog.icon
        form.color.data       = prog.color
        form.order.data       = str(prog.order)
        form.is_active.data   = prog.is_active
        form.faculty.data = prog.faculty
    existing_faculties = sorted({p.faculty for p in Programme.query.all() if p.faculty})
    return render_template('admin/programme_form.html', title='Edit Programme', form=form, programme=prog, existing_faculties=existing_faculties)


@bp.route('/programmes/<int:programme_id>/delete', methods=['POST'])
@admin_required
def delete_programme(programme_id):
    prog = Programme.query.get_or_404(programme_id)
    for s in prog.subjects.all():
        s.programmes.remove(prog)
    name = prog.name
    db.session.delete(prog)
    db.session.commit()
    flash(f'Programme "{name}" deleted. Its subjects have been unlinked.', 'success')
    return redirect(url_for('admin.programmes'))


@bp.route('/programmes/<int:programme_id>/toggle', methods=['POST'])
@admin_required
def toggle_programme(programme_id):
    prog = Programme.query.get_or_404(programme_id)
    prog.is_active = not prog.is_active
    db.session.commit()
    status = 'activated' if prog.is_active else 'deactivated'
    flash(f'Programme "{prog.name}" {status}.', 'success')
    return redirect(url_for('admin.programmes'))


# ============ SUBJECT MANAGEMENT ============

@bp.route('/subjects')
@admin_required
def subjects():
    subjects = Subject.query.order_by(Subject.order, Subject.name).all()
    return render_template('admin/subjects.html', title='Manage Subjects', subjects=subjects)


@bp.route('/subjects/create', methods=['GET', 'POST'])
@admin_required
def create_subject():
    form = SubjectForm()
    if form.validate_on_submit():
        slug = slugify(form.name.data)
        if Subject.query.filter_by(slug=slug).first():
            flash('A subject with this name already exists.', 'danger')
            return redirect(url_for('admin.create_subject'))
        subject = Subject(
            name=form.name.data,
            slug=slug,
            description=form.description.data,
            icon=form.icon.data or 'book',
            color=form.color.data or '#6366f1',
            order=int(form.order.data) if form.order.data else 0,
            is_active=form.is_active.data,
        )
        db.session.add(subject)
        db.session.commit()
        flash(f'Subject "{subject.name}" created successfully!', 'success')
        return redirect(url_for('admin.subjects'))

    form.is_active.data = True
    return render_template('admin/subject_form.html', title='Create Subject', form=form)


@bp.route('/subjects/<int:subject_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    form = SubjectForm()
    if form.validate_on_submit():
        new_slug = slugify(form.name.data)
        if new_slug != subject.slug:
            existing = Subject.query.filter_by(slug=new_slug).first()
            if existing and existing.id != subject.id:
                flash('A subject with this name already exists.', 'danger')
                return redirect(url_for('admin.edit_subject', subject_id=subject.id))
            subject.slug = new_slug
        subject.name        = form.name.data
        subject.description = form.description.data
        subject.icon        = form.icon.data or 'book'
        subject.color       = form.color.data or '#6366f1'
        subject.order       = int(form.order.data) if form.order.data else 0
        subject.is_active   = form.is_active.data
        db.session.commit()
        flash(f'Subject "{subject.name}" updated successfully!', 'success')
        return redirect(url_for('admin.subjects'))

    elif request.method == 'GET':
        form.name.data        = subject.name
        form.description.data = subject.description
        form.icon.data        = subject.icon
        form.color.data       = subject.color
        form.order.data       = str(subject.order)
        form.is_active.data   = subject.is_active

    all_programmes = Programme.query.order_by(Programme.name).all()
    return render_template('admin/subject_form.html', title='Edit Subject', form=form, subject=subject, all_programmes=all_programmes)

@bp.route('/subjects/<int:subject_id>/add-programme', methods=['POST'])
@admin_required
def add_subject_programme(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    programme_id = request.form.get('add_programme_id', 0, type=int)
    if programme_id:
        programme = Programme.query.get(programme_id)
        if programme and programme not in subject.programmes.all():
            subject.programmes.append(programme)
            db.session.commit()
            flash(f'Subject linked to "{programme.name}".', 'success')
        elif programme in subject.programmes.all():
            flash('Subject is already linked to that programme.', 'warning')
    return redirect(url_for('admin.edit_subject', subject_id=subject_id))


@bp.route('/subjects/<int:subject_id>/remove-programme/<int:programme_id>', methods=['POST'])
@admin_required
def remove_subject_programme(subject_id, programme_id):
    subject = Subject.query.get_or_404(subject_id)
    programme = Programme.query.get_or_404(programme_id)
    if programme in subject.programmes.all():
        subject.programmes.remove(programme)
        db.session.commit()
        flash(f'Subject unlinked from "{programme.name}".', 'success')
    return redirect(url_for('admin.edit_subject', subject_id=subject_id))

@bp.route('/subjects/<int:subject_id>/delete', methods=['POST'])
@admin_required
def delete_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    for post in Post.query.filter_by(subject_id=subject.id).all():
        post.subject_id = None
    name = subject.name
    db.session.delete(subject)
    db.session.commit()
    flash(f'Subject "{name}" deleted successfully.', 'success')
    return redirect(url_for('admin.subjects'))


@bp.route('/subjects/<int:subject_id>/toggle', methods=['POST'])
@admin_required
def toggle_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    subject.is_active = not subject.is_active
    db.session.commit()
    status = 'activated' if subject.is_active else 'deactivated'
    flash(f'Subject "{subject.name}" {status}.', 'success')
    return redirect(url_for('admin.subjects'))


# ============ USER MANAGEMENT ============

@bp.route('/users')
@admin_required
def users():
    page   = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    query  = User.query

    if search:
        query = query.filter(
            db.or_(
                User.username.contains(search),
                User.email.contains(search),
                User.nickname.contains(search)
            )
        )

    users = query.order_by(User.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    return render_template('admin/users.html', title='Manage Users', users=users, search=search)


@bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'warning')
        return redirect(url_for('admin.users'))
    user.is_active = not user.is_active
    db.session.commit()
    status = 'activated' if user.is_active else 'deactivated'
    flash(f'User "{user.username}" has been {status}.', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/users/<int:user_id>/toggle-premium-access', methods=['POST'])
@admin_required
def toggle_premium_access(user_id):
    user = User.query.get_or_404(user_id)
    user.can_access_all_content = not user.can_access_all_content
    db.session.commit()
    status = 'granted' if user.can_access_all_content else 'revoked'
    flash(f'Premium access {status} for user "{user.username}".', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/users/<int:user_id>/set-subscription', methods=['POST'])
@admin_required
def set_subscription(user_id):
    user = User.query.get_or_404(user_id)
    tier = request.form.get('tier', 'free')
    start_date = request.form.get('start_date')
    end_date   = request.form.get('end_date')

    from datetime import datetime
    if start_date:
        user.subscription_start_date = datetime.strptime(start_date, '%Y-%m-%d')
    if end_date:
        user.subscription_end_date = datetime.strptime(end_date, '%Y-%m-%d')

    old_tier = user.subscription_tier
    user.subscription_tier = tier
    db.session.commit()

    if tier != 'free' and old_tier == 'free':
        from app.utils import send_subscription_activation_email
        send_subscription_activation_email(user, tier)

    flash(f'Subscription tier set to {tier} for user "{user.username}".', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'warning')
        return redirect(url_for('admin.users'))

    username = user.username

    if user.profile_picture and user.profile_picture != 'default.jpg':
        if user.profile_picture.startswith('http'):
            try:
                import cloudinary.uploader
                cloudinary.uploader.destroy(user.profile_picture, resource_type='image')
            except Exception as e:
                current_app.logger.warning(f"Failed to delete profile picture from Cloudinary: {e}")

    for post in user.posts:
        if post.document:
            from app.posts.routes import delete_document
            delete_document(post.document)

    db.session.delete(user)
    db.session.commit()
    flash(f'User "{username}" and all their content has been deleted.', 'success')
    return redirect(url_for('admin.users'))


# ============ POST MANAGEMENT ============

@bp.route('/posts')
@admin_required
def posts():
    page           = request.args.get('page', 1, type=int)
    search         = request.args.get('search', '')
    subject_filter = request.args.get('subject', type=int)
    status_filter  = request.args.get('status', '')

    query = Post.query

    if search:
        query = query.filter(
            db.or_(
                Post.title.contains(search),
                Post.description.contains(search)
            )
        )

    if subject_filter:
        query = query.filter_by(subject_id=subject_filter)

    if status_filter in ('pending', 'approved', 'rejected'):
        query = query.filter_by(status=status_filter)

    posts = query.order_by(Post.created_at.desc()).paginate(
        page=page, per_page=20, error_out=False
    )

    subjects = Subject.query.filter_by(is_active=True).order_by(Subject.name).all()

    return render_template(
        'admin/posts.html',
        title='Manage Posts',
        posts=posts,
        subjects=subjects,
        search=search,
        subject_filter=subject_filter,
        status_filter=status_filter,
    )


@bp.route('/posts/<int:post_id>/delete', methods=['POST'])
@admin_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    title   = post.title
    subject = post.subject

    if post.document:
        from app.posts.routes import delete_document
        delete_document(post.document)

    db.session.delete(post)
    db.session.commit()

    if subject:
        subject.update_post_count()

    flash(f'Post "{title}" has been deleted.', 'success')
    return redirect(url_for('admin.posts'))

# ============ POST MODERATION ============

@bp.route('/moderation')
@admin_required
def moderation():
    tab  = request.args.get('tab', 'pending')
    page = request.args.get('page', 1, type=int)

    if tab not in ('pending', 'approved', 'rejected'):
        tab = 'pending'

    posts = Post.query.filter_by(status=tab).order_by(Post.created_at.desc()).paginate(
        page=page, per_page=15, error_out=False
    )

    counts = {
        'pending':  Post.query.filter_by(status='pending').count(),
        'approved': Post.query.filter_by(status='approved').count(),
        'rejected': Post.query.filter_by(status='rejected').count(),
    }

    return render_template(
        'admin/moderation.html',
        title='Post Moderation',
        posts=posts,
        tab=tab,
        counts=counts,
    )


@bp.route('/moderation/<int:post_id>/approve', methods=['POST'])
@admin_required
def approve_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.status           = 'approved'
    post.rejection_reason = None
    db.session.commit()

    # Update subject post count
    if post.subject:
        post.subject.update_post_count()

    from app.posts.routes import on_post_approved
    on_post_approved(post)

    # Award XP to the post author on approval (not at submission time)
    post.author.add_xp(10, reason=f'Post approved: {post.title[:50]}')

    from app.models import create_notification
    create_notification(
        user_id=post.author.id,
        message=f'Your post "{post.title[:60]}" has been approved and is now live!',
        notification_type='post_approved',
        link=f'/posts/{post.id}',
    )

    import threading

    def send_programme_notifications_background(post_id):
        from app import create_app
        app = create_app()
        with app.app_context():
            try:
                from app.models import User, Post
                from app.utils import send_programme_relevant_post_email
                post = db.session.get(Post, post_id)
                if post:
                    users = User.query.filter(
                        User.is_active == True,
                        User.programme.isnot(None),
                        User.programme != '',
                        User.id != post.author.id
                    ).all()
                    post_text = f"{post.title} {post.description} {post.subject.name if post.subject else ''}".lower()
                    matching_users = [
                        u for u in users
                        if any(kw in post_text for kw in u.programme.lower().split() if len(kw) >= 3)
                    ]
                    sent_count = sum(
                        1 for u in matching_users if send_programme_relevant_post_email(u, post)
                    )
                    app.logger.info(f"Sent programme notifications to {sent_count} users for post {post_id}")
            except Exception as e:
                app.logger.error(f"Failed to send programme notifications for post {post_id}: {e}")

    t = threading.Thread(target=send_programme_notifications_background, args=(post.id,))
    t.daemon = True
    t.start()

    flash(f'Post "{post.title}" approved and is now live.', 'success')
    return redirect(request.form.get('next') or url_for('admin.moderation'))


@bp.route('/moderation/<int:post_id>/reject', methods=['POST'])
@admin_required
def reject_post(post_id):
    post = Post.query.get_or_404(post_id)
    reason = request.form.get('reason', '').strip()
    post.status           = 'rejected'
    post.rejection_reason = reason or None
    db.session.commit()

    if post.subject:
        post.subject.update_post_count()

    flash(f'Post "{post.title}" has been rejected.', 'warning')
    return redirect(request.form.get('next') or url_for('admin.moderation'))

# ============ STATISTICS & REPORTS ============

@bp.route('/statistics')
@admin_required
def statistics():
    total_users    = User.query.count()
    active_users   = User.query.filter_by(is_active=True).count()
    inactive_users = total_users - active_users

    total_posts             = Post.query.count()
    posts_with_documents    = Post.query.filter_by(has_document=True).count()
    posts_without_documents = total_posts - posts_with_documents

    from sqlalchemy import func as _func
    counts_q = db.session.query(
        Post.subject_id,
        _func.count(Post.id).label('cnt')
    ).filter_by(status='approved').group_by(Post.subject_id).all()
    counts_map = {row.subject_id: row.cnt for row in counts_q}

    subjects_stats = []
    for subject in Subject.query.all():
        subjects_stats.append({
            'name':       subject.name,
            'post_count': counts_map.get(subject.id, 0),
            'color':      subject.color,
        })

    from app.models import Like
    total_likes    = Like.query.count()
    total_comments = Comment.query.count()

    from sqlalchemy import func
    top_posters = db.session.query(
        User.username,
        User.nickname,
        func.count(Post.id).label('post_count')
    ).join(Post).group_by(User.id).order_by(func.count(Post.id).desc()).limit(10).all()

    return render_template(
        'admin/statistics.html',
        title='Statistics & Analytics',
        total_users=total_users,
        active_users=active_users,
        inactive_users=inactive_users,
        total_posts=total_posts,
        posts_with_documents=posts_with_documents,
        posts_without_documents=posts_without_documents,
        subjects_stats=subjects_stats,
        total_likes=total_likes,
        total_comments=total_comments,
        top_posters=top_posters,
    )

# ============ BULK EMAIL ============

@bp.route('/send-email', methods=['GET', 'POST'])
@admin_required
def send_email():
    import requests

    users       = User.query.filter(User.email.isnot(None)).all()
    total_users = len(users)
    form        = BulkEmailForm()

    if form.validate_on_submit():
        subject    = form.subject.data.strip()
        body       = form.body.data.strip()
        send_to    = form.send_to.data
        selected   = request.form.getlist('selected_emails')
        recipients = [u.email for u in users] if send_to == 'all' else selected

        if not recipients:
            flash('No recipients selected.', 'danger')
            return render_template('admin/send_email.html', users=users, total_users=total_users, form=form)

        sender  = current_app.config.get('MAIL_DEFAULT_SENDER') or current_app.config.get('MAIL_USERNAME')
        api_key = current_app.config.get('BREVO_API_KEY')
        if not api_key:
            flash('BREVO_API_KEY is not configured -- email sending is disabled.', 'danger')
            return render_template('admin/send_email.html', users=users, total_users=total_users, form=form)
        sent    = 0
        failed  = 0

        for email in recipients:
            try:
                response = requests.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={"api-key": api_key, "Content-Type": "application/json"},
                    json={
                        "sender": {"email": sender},
                        "to": [{"email": email}],
                        "subject": subject,
                        "htmlContent": body
                    }
                )
                if response.status_code == 201:
                    sent += 1
                else:
                    current_app.logger.error(f"Brevo error for {email}: {response.text}")
                    failed += 1
            except Exception as e:
                current_app.logger.error(f"Failed to send to {email}: {e}")
                failed += 1

        if sent:
            result = f'Email sent successfully to {sent} user(s).'
            if failed:
                result += f' {failed} failed — check the server logs.'
            flash(result, 'success')
        else:
            flash(f'All {failed} sends failed. Check your Brevo API key and sender address.', 'danger')

        return redirect(url_for('admin.send_email'))

    return render_template('admin/send_email.html', users=users, total_users=total_users, form=form)    

    # ── Video Lessons ─────────────────────────────────────────────────────────────

@bp.route('/videos')
@admin_required
def videos():
    videos = (VideoLesson.query
              .order_by(VideoLesson.created_at.desc())
              .all())
    subjects = Subject.query.filter_by(is_active=True).order_by(Subject.name).all()
    return render_template('admin/videos.html', videos=videos, subjects=subjects)


@bp.route('/videos/add', methods=['POST'])
@admin_required
def add_video():
    from app.services.video_service import get_video_meta
    url        = request.form.get('url', '').strip()
    subject_id = request.form.get('subject_id', type=int)
    xp_reward  = request.form.get('xp_reward', 10, type=int)

    if not url or not subject_id:
        flash('URL and subject are required.', 'danger')
        return redirect(url_for('admin.videos'))

    meta = get_video_meta(url)
    if not meta:
        flash('Could not extract a YouTube ID from that URL.', 'danger')
        return redirect(url_for('admin.videos'))

    # Don't add duplicates per subject
    existing = VideoLesson.query.filter_by(
        youtube_id=meta['youtube_id'], subject_id=subject_id).first()
    if existing:
        flash('That video is already added for this subject.', 'warning')
        return redirect(url_for('admin.videos'))

    video = VideoLesson(
        subject_id = subject_id,
        youtube_id = meta['youtube_id'],
        title      = meta.get('title') or url,
        thumbnail  = meta.get('thumbnail_url'),
        added_by   = current_user.id,
        xp_reward  = xp_reward,
    )
    db.session.add(video)
    db.session.commit()
    flash(f'Video "{video.title}" added.', 'success')

    # ── TRIGGER AI CATEGORISATION ──
    try:
        app = current_app._get_current_object()
        allowed_subjects = [s.name for s in Subject.query.all()]
        thread = threading.Thread(
            target=_run_background_categorization,
            args=(app, video.id, video.title, allowed_subjects)
        )
        thread.start()
    except Exception as e:
        logging.error(f"Failed to start background categorization thread: {str(e)}")

    return redirect(url_for('admin.videos'))


@bp.route('/videos/<int:video_id>/toggle', methods=['POST'])
@admin_required
def toggle_video(video_id):
    video = VideoLesson.query.get_or_404(video_id)
    flash('Toggle feature not available - is_active column was dropped.', 'warning')
    return redirect(url_for('admin.videos'))


@bp.route('/videos/<int:video_id>/delete', methods=['POST'])
@admin_required
def delete_video(video_id):
    video = VideoLesson.query.get_or_404(video_id)
    db.session.delete(video)
    db.session.commit()
    flash('Video deleted.', 'success')
    return redirect(url_for('admin.videos'))