from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from werkzeug.security import generate_password_hash
from sqlalchemy import func

from app.extensions import db
from app.models.account import Accounts
from app.models.school import School
from app.models.test_result import TestResult
from app.models.question import Question
from app.models.assessment_type import AssessmentType
from app.forms import EditAccountForm, EditSchoolForm, QuestionForm
from app.utils.decorators import super_admin_required
from app.routes.qr import get_stage_summary

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/')
@login_required
@super_admin_required
def dashboard():
    return render_template(
        'admin/dashboard.html',
        results=TestResult.query.order_by(TestResult.taken_at.desc()).limit(200).all(),
        accounts=Accounts.query.order_by(Accounts.created_at.desc()).limit(500).all(),
        total_tests=TestResult.query.count(),
        total_users=Accounts.query.count(),
        total_schools=School.query.count(),
        stage_summary=get_stage_summary(),
        schools=School.query.order_by(School.school_name).all(),
        questions=Question.query.order_by(Question.test_type, Question.order, Question.id).limit(500).all(),
        assessment_types=AssessmentType.query.order_by(AssessmentType.order).all(),
    )


# ── Account management ────────────────────────────────────────────────────────

@admin_bp.route('/accounts/<int:account_id>/edit', methods=['GET', 'POST'])
@login_required
@super_admin_required
def edit_account(account_id):
    account = Accounts.query.get_or_404(account_id)
    form = EditAccountForm(obj=account)
    if form.validate_on_submit():
        account.fname = form.fname.data.strip()
        account.lname = form.lname.data.strip()
        account.email = form.email.data.strip().lower()
        account.username = form.username.data.strip()
        account.school_name = form.school_name.data if hasattr(form, 'school_name') else None
        account.birthdate = form.birthdate.data
        account.gender = form.gender.data
        account.level = form.level.data or None
        account.is_admin = form.is_admin.data
        account.is_counsellor = form.is_counsellor.data
        account.phone = form.phone.data.strip() if form.phone.data else None
        if form.password.data:
            account.password = generate_password_hash(form.password.data)
        db.session.commit()
        flash('Account updated successfully.', 'success')
        return redirect(url_for('admin.dashboard') + '#all_accounts')
    return render_template('admin/edit_account.html', form=form, account=account)


@admin_bp.route('/accounts/<int:account_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_account(account_id):
    account = Accounts.query.get_or_404(account_id)
    db.session.delete(account)
    db.session.commit()
    flash(f'Account "{account.username}" deleted.', 'success')
    return redirect(url_for('admin.dashboard') + '#all_accounts')


# ── School management ─────────────────────────────────────────────────────────

@admin_bp.route('/schools/<int:school_id>/edit', methods=['GET', 'POST'])
@login_required
@super_admin_required
def edit_school(school_id):
    school = School.query.get_or_404(school_id)
    form = EditSchoolForm(obj=school)
    if form.validate_on_submit():
        school.school_name = form.school_name.data.strip()
        school.email = form.email.data.strip().lower() if form.email.data else None
        school.admin_name = form.admin_name.data.strip()
        if form.admin_password.data:
            school.admin_password = generate_password_hash(form.admin_password.data)
        db.session.commit()
        flash('School updated successfully.', 'success')
        return redirect(url_for('admin.dashboard') + '#all_schools')
    return render_template('admin/edit_school.html', form=form, school=school)


@admin_bp.route('/schools/<int:school_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_school(school_id):
    school = School.query.get_or_404(school_id)
    db.session.delete(school)
    db.session.commit()
    flash(f'School "{school.school_name}" deleted.', 'success')
    return redirect(url_for('admin.dashboard') + '#all_schools')


@admin_bp.route('/schools/<int:school_id>/toggle-upload', methods=['POST'])
@login_required
@super_admin_required
def toggle_upload(school_id):
    school = School.query.get_or_404(school_id)
    school.upload_enabled = not school.upload_enabled
    db.session.commit()
    state = 'enabled' if school.upload_enabled else 'disabled'
    flash(f'Upload access for "{school.school_name}" is now {state}.', 'success')
    return redirect(url_for('admin.dashboard') + '#all_schools')


# ── Question management ───────────────────────────────────────────────────────

@admin_bp.route('/questions/add', methods=['GET', 'POST'])
@login_required
@super_admin_required
def add_question():
    if request.method == 'POST':
        test_type = request.form.get('test_type', '').strip()
        content = request.form.get('question_content', '').strip()
        if test_type and len(content) >= 10:
            db.session.add(Question(
                test_type=test_type,
                question_content=content,
                order=Question.query.filter_by(test_type=test_type).count(),
            ))
            db.session.commit()
            flash('Question added successfully.', 'success')
            return redirect(url_for('admin.dashboard') + '#question_database')
        flash('Please fill in all fields correctly.', 'error')
        return redirect(url_for('admin.dashboard') + '#question_database')
    return redirect(url_for('admin.dashboard') + '#question_database')


@admin_bp.route('/questions/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
@super_admin_required
def edit_question(question_id):
    question = Question.query.get_or_404(question_id)
    form = QuestionForm(obj=question)
    if form.validate_on_submit():
        question.test_type = form.test_type.data
        question.question_content = form.question_content.data.strip()
        db.session.commit()
        flash('Question updated successfully.', 'success')
        return redirect(url_for('admin.dashboard') + '#question_database')
    return render_template('admin/question_form.html', form=form, title='Edit Question', question=question)


@admin_bp.route('/questions/<int:question_id>/json')
@login_required
@super_admin_required
def question_json(question_id):
    from flask import jsonify
    question = Question.query.get_or_404(question_id)
    return jsonify({'id': question.id, 'test_type': question.test_type, 'question_content': question.question_content})


@admin_bp.route('/questions/<int:question_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_question(question_id):
    question = Question.query.get_or_404(question_id)
    db.session.delete(question)
    db.session.commit()
    flash('Question deleted successfully.', 'success')
    return redirect(url_for('admin.dashboard') + '#question_database')


# ── Assessment type management ────────────────────────────────────────────────

@admin_bp.route('/assessment-types/add', methods=['POST'])
@login_required
@super_admin_required
def add_assessment_type():
    import json
    name           = request.form.get('name', '').strip()
    display_name   = request.form.get('display_name', '').strip()
    description    = request.form.get('description', '').strip()
    icon           = request.form.get('icon', '🧠').strip()
    color          = request.form.get('color', 'green').strip()
    order          = int(request.form.get('order', 0))
    scoring_ranges_raw = request.form.get('scoring_ranges', '[]').strip()

    if not name or not display_name:
        flash('Name and display name are required.', 'error')
        return redirect(url_for('admin.dashboard') + '#assessment_types')
    if AssessmentType.query.filter_by(name=name).first():
        flash(f'Assessment type "{name}" already exists.', 'error')
        return redirect(url_for('admin.dashboard') + '#assessment_types')
    try:
        scoring_ranges = json.loads(scoring_ranges_raw)
    except (ValueError, TypeError):
        flash('Invalid scoring ranges JSON.', 'error')
        return redirect(url_for('admin.dashboard') + '#assessment_types')

    image_url = None
    image_file = request.files.get('image')
    if image_file and image_file.filename:
        from app.services.cloudinary_service import upload_assessment_image
        image_url = upload_assessment_image(image_file, name)

    db.session.add(AssessmentType(
        name=name, display_name=display_name, description=description,
        icon=icon, color=color, order=order, scoring_ranges=scoring_ranges,
        image_url=image_url,
    ))
    db.session.commit()
    flash(f'Assessment type "{display_name}" added.', 'success')
    from urllib.parse import quote
    return redirect(url_for('admin.dashboard') + f'?add_questions_for={quote(display_name)}#assessment_types')


@admin_bp.route('/assessment-types/<int:type_id>/toggle', methods=['POST'])
@login_required
@super_admin_required
def toggle_assessment_type(type_id):
    at = AssessmentType.query.get_or_404(type_id)
    at.is_active = not at.is_active
    db.session.commit()
    state = 'activated' if at.is_active else 'deactivated'
    flash(f'"{at.display_name}" {state}.', 'success')
    return redirect(url_for('admin.dashboard') + '#assessment_types')

@admin_bp.route('/assessment-types/<int:type_id>/edit', methods=['POST'])
@login_required
@super_admin_required
def edit_assessment_type(type_id):
    import json
    at = AssessmentType.query.get_or_404(type_id)
    at.name           = request.form.get('name', '').strip()
    at.display_name   = request.form.get('display_name', '').strip()
    at.description    = request.form.get('description', '').strip() or None
    at.icon           = request.form.get('icon', '').strip() or None
    at.color          = request.form.get('color', 'green').strip()
    at.order          = int(request.form.get('order', 0))
    try:
        at.scoring_ranges = json.loads(request.form.get('scoring_ranges', '[]'))
    except (ValueError, TypeError):
        flash('Invalid scoring ranges JSON.', 'error')
        return redirect(url_for('admin.dashboard') + '#assessment_types')
    image_file = request.files.get('image')
    if image_file and image_file.filename:
        from app.services.cloudinary_service import upload_assessment_image
        new_url = upload_assessment_image(image_file, at.name)
        if new_url:
            at.image_url = new_url
    db.session.commit()
    flash(f'"{at.display_name}" updated successfully.', 'success')
    return redirect(url_for('admin.dashboard') + '#assessment_types')

@admin_bp.route('/assessment-types/<int:type_id>/delete', methods=['POST'])
@login_required
@super_admin_required
def delete_assessment_type(type_id):
    at = AssessmentType.query.get_or_404(type_id)
    name = at.display_name
    db.session.delete(at)
    db.session.commit()
    flash(f'Assessment type "{name}" deleted.', 'success')
    return redirect(url_for('admin.dashboard') + '#assessment_types')
# ── Counsellor verification ───────────────────────────────────────────────────

@admin_bp.route('/counsellors')
@login_required
@super_admin_required
def counsellor_applications():
    """List all counsellor applications grouped by status."""
    from app.models.counsellor_profile import CounsellorProfile
    pending = (
        db.session.query(CounsellorProfile, Accounts)
        .join(Accounts, Accounts.id == CounsellorProfile.account_id)
        .filter(CounsellorProfile.verification_status == 'pending')
        .order_by(CounsellorProfile.submitted_at.asc())
        .all()
    )
    verified = (
        db.session.query(CounsellorProfile, Accounts)
        .join(Accounts, Accounts.id == CounsellorProfile.account_id)
        .filter(CounsellorProfile.verification_status == 'verified')
        .order_by(CounsellorProfile.verified_at.desc())
        .all()
    )
    rejected = (
        db.session.query(CounsellorProfile, Accounts)
        .join(Accounts, Accounts.id == CounsellorProfile.account_id)
        .filter(CounsellorProfile.verification_status == 'rejected')
        .order_by(CounsellorProfile.submitted_at.desc())
        .all()
    )
    return render_template(
        'admin/counsellor_applications.html',
        pending=pending,
        verified=verified,
        rejected=rejected,
    )


@admin_bp.route('/counsellors/<int:profile_id>/verify', methods=['POST'])
@login_required
@super_admin_required
def verify_counsellor(profile_id):
    """Approve or reject a counsellor application."""
    from app.models.counsellor_profile import CounsellorProfile
    from datetime import datetime, timezone
    profile = CounsellorProfile.query.get_or_404(profile_id)
    action = request.form.get('action')

    if action == 'approve':
        profile.verification_status = 'verified'
        profile.verified_at = datetime.now(timezone.utc)
        profile.rejection_reason = None
        db.session.commit()
        flash('Counsellor approved successfully.', 'success')

    elif action == 'reject':
        reason = request.form.get('rejection_reason', '').strip()
        profile.verification_status = 'rejected'
        profile.rejection_reason = reason or 'Your application did not meet our verification requirements.'
        db.session.commit()
        flash('Counsellor application rejected.', 'warning')

    return redirect(url_for('admin.counsellor_applications'))