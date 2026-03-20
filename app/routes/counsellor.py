"""
Counsellor portal — view flagged students, add notes, mark as contacted,
view full student history.
Access: logged-in Accounts with is_counsellor=True.
"""
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy import func

from app.extensions import db
from app.models.account import Accounts
from app.models.test_result import TestResult
from app.models.audit_log import audit, AuditLog
from app.utils.decorators import counsellor_required

counsellor_bp = Blueprint('counsellor', __name__)
logger = logging.getLogger(__name__)


@counsellor_bp.route('/dashboard')
@login_required
@counsellor_required
def dashboard():
    """Show all Elevated + Clinical students in the counsellor's school."""
    if current_user.counsellor_profile and not current_user.counsellor_profile.is_verified:
        return redirect(url_for('counsellor_signup.counsellor_pending'))

    school_id = current_user.school_id
    selected_class = request.args.get('class_group', '').strip()
    page = request.args.get('page', 1, type=int)

    # Subquery: latest taken_at per student per test type
    latest_subq = (
        db.session.query(
            TestResult.user_id,
            TestResult.test_type,
            func.max(TestResult.taken_at).label('latest_at'),
        )
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(Accounts.school_id == school_id)
        .group_by(TestResult.user_id, TestResult.test_type)
        .subquery()
    )

    at_risk_q = (
        db.session.query(TestResult, Accounts)
        .join(Accounts, Accounts.id == TestResult.user_id)
        .join(
            latest_subq,
            (latest_subq.c.user_id == TestResult.user_id) &
            (latest_subq.c.test_type == TestResult.test_type) &
            (latest_subq.c.latest_at == TestResult.taken_at),
        )
        .filter(
            Accounts.school_id == school_id,
            TestResult.stage.in_(['Elevated Stage', 'Clinical Stage']),
        )
    )

    if selected_class:
        at_risk_q = at_risk_q.filter(Accounts.class_group == selected_class)

    at_risk_q = at_risk_q.order_by(
        db.case((TestResult.stage == 'Clinical Stage', 0), else_=1),
        TestResult.taken_at.desc(),
    )

    pagination = at_risk_q.paginate(page=page, per_page=20, error_out=False)

    # All class groups in this school for the filter dropdown
    class_groups = sorted([
        row.class_group
        for row in db.session.query(Accounts.class_group)
        .filter(
            Accounts.school_id == school_id,
            Accounts.class_group.isnot(None),
        )
        .distinct()
        .all()
    ])

    # IDs of students already contacted (from audit log) — for badge display
    contacted_ids = {
        row.target_id
        for row in db.session.query(AuditLog.target_id)
        .filter(
            AuditLog.event_type == 'STUDENT_CONTACTED',
            AuditLog.school_id == school_id,
            AuditLog.target_id.isnot(None),
        )
        .distinct()
        .all()
    }

    return render_template(
        'counsellor/dashboard.html',
        at_risk=pagination.items,
        pagination=pagination,
        counsellor=current_user,
        class_groups=class_groups,
        selected_class=selected_class,
        contacted_ids=contacted_ids,
    )


@counsellor_bp.route('/student/<int:student_id>')
@login_required
@counsellor_required
def student_history(student_id):
    """Full assessment history for a single student."""
    student = Accounts.query.get_or_404(student_id)

    # Scope check — must be same school
    if student.school_id != current_user.school_id:
        flash('Access denied.', 'error')
        return redirect(url_for('counsellor.dashboard'))

    results = (
        TestResult.query
        .filter_by(user_id=student.id)
        .order_by(TestResult.taken_at.desc())
        .all()
    )

    # Counsellor notes for this student from audit log
    notes = (
        AuditLog.query
        .filter_by(event_type='COUNSELLOR_NOTE', target_id=student_id, school_id=current_user.school_id)
        .order_by(AuditLog.created_at.desc())
        .all()
    )

    contact_log = (
        AuditLog.query
        .filter_by(event_type='STUDENT_CONTACTED', target_id=student_id, school_id=current_user.school_id)
        .order_by(AuditLog.created_at.desc())
        .all()
    )

    return render_template(
        'counsellor/student_history.html',
        student=student,
        results=results,
        notes=notes,
        contact_log=contact_log,
        counsellor=current_user,
    )


@counsellor_bp.route('/note/<int:student_id>', methods=['POST'])
@login_required
@counsellor_required
def add_note(student_id):
    """Save a private counsellor note for a student."""
    student = Accounts.query.get_or_404(student_id)

    if student.school_id != current_user.school_id:
        flash('Access denied.', 'error')
        return redirect(url_for('counsellor.dashboard'))

    note_text = request.form.get('note', '').strip()
    if not note_text:
        flash('Note cannot be empty.', 'error')
        return redirect(url_for('counsellor.student_history', student_id=student_id))

    audit(
        'COUNSELLOR_NOTE',
        actor_id=current_user.id,
        school_id=current_user.school_id,
        target_id=student_id,
        ip_address=request.remote_addr,
        detail=note_text[:500],
    )
    db.session.commit()

    logger.info(
        'Counsellor note added | counsellor=%s student=%s',
        current_user.username, student.username,
    )
    flash(f'Note saved for {student.full_name}.', 'success')

    # Return to wherever the request came from
    next_url = request.form.get('next', '')
    if next_url:
        from urllib.parse import urlparse
        parsed = urlparse(next_url)
        if parsed.scheme or parsed.netloc:
            next_url = ''
    return redirect(next_url or url_for('counsellor.student_history', student_id=student_id))


@counsellor_bp.route('/mark-contacted/<int:student_id>', methods=['POST'])
@login_required
@counsellor_required
def mark_contacted(student_id):
    """Record that a counsellor has reached out to a student."""
    student = Accounts.query.get_or_404(student_id)

    if student.school_id != current_user.school_id:
        flash('Access denied.', 'error')
        return redirect(url_for('counsellor.dashboard'))

    audit(
        'STUDENT_CONTACTED',
        actor_id=current_user.id,
        school_id=current_user.school_id,
        target_id=student_id,
        ip_address=request.remote_addr,
        detail=f'Counsellor {current_user.full_name} marked {student.full_name} as contacted.',
    )
    db.session.commit()

    flash(f'{student.full_name} marked as contacted.', 'success')
    next_url = request.form.get('next', '')
    if next_url:
        from urllib.parse import urlparse
        parsed = urlparse(next_url)
        if parsed.scheme or parsed.netloc:
            next_url = ''
    return redirect(next_url or url_for('counsellor.dashboard'))