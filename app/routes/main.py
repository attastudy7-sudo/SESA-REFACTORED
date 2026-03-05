from app.services.payment_service import verify_paystack_payment
from app.services.test_service import calculate_average_score, get_monthly_averages, get_school_monthly_averages
from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, session, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_
from collections import Counter
from app.extensions import db
from app.models.account import Accounts
from app.models.school import School
from app.models.test_result import TestResult
from app.models.question import Question
from app.utils.decorators import school_login_required

main_bp = Blueprint('main', __name__)


def _get_school_from_session():
    """Return School from session or None."""
    school_id = session.get('school_id')
    return School.query.get(school_id) if school_id else None


@main_bp.route('/')
def landing():
    return render_template('main/landing.html')


@main_bp.route('/home')
@login_required
def home():
    user = current_user
    results = user.test_results.order_by(TestResult.taken_at.desc()).all()
    total_tests = len(results)
    most_recent = results[0] if results else None

    def q_count(test_type):
        return Question.query.filter_by(test_type=test_type).count()

    tests_meta = [
        {'name': 'Separation Anxiety Disorder',   'key': 'sad',  'count': q_count('Separation Anxiety Disorder'),   'icon': '🏠', 'color': 'teal'},
        {'name': 'Social Phobia',                 'key': 'sp',   'count': q_count('Social Phobia'),                 'icon': '👥', 'color': 'blue'},
        {'name': 'Generalised Anxiety Disorder',  'key': 'gad',  'count': q_count('Generalised Anxiety Disorder'),  'icon': '🌀', 'color': 'purple'},
        {'name': 'Panic Disorder',                'key': 'pd',   'count': q_count('Panic Disorder'),                'icon': '💨', 'color': 'orange'},
        {'name': 'Obsessive Compulsive Disorder', 'key': 'ocd',  'count': q_count('Obsessive Compulsive Disorder'), 'icon': '🔄', 'color': 'red'},
        {'name': 'Major Depressive Disorder',     'key': 'mdd',  'count': q_count('Major Depressive Disorder'),     'icon': '🌧', 'color': 'indigo'},
    ]

    avg_score = round(sum(r.score for r in results) / total_tests, 1) if total_tests else 0

    # Calculate previous month's average for comparison
    from datetime import datetime, timedelta
    now = datetime.now()
    first_of_this_month = now.replace(day=1)
    first_of_last_month = (first_of_this_month - timedelta(days=1)).replace(day=1)
    
    last_month_results = [r for r in results if r.taken_at and first_of_last_month <= r.taken_at < first_of_this_month]
    prev_avg = round(sum(r.score for r in last_month_results) / len(last_month_results), 1) if last_month_results else None
    
    # Determine arrow direction
    # Green arrow up = average dropped (improved in mental health context where lower is better)
    # Red arrow down = average went up (worse in mental health context)
    score_change = None
    if prev_avg is not None and total_tests > len(last_month_results):
        score_change = avg_score - prev_avg  # positive = went up, negative = went down

    return render_template(
        'main/home.html',
        user=user,
        total_tests=total_tests,
        avg_score=avg_score,
        most_recent=most_recent,
        tests_meta=tests_meta,
        score_change=score_change,
        prev_avg=prev_avg,
    )


@main_bp.route('/results')
@login_required
def results():
    user = current_user
    all_results = user.test_results.order_by(TestResult.taken_at.desc()).all()
    
    # Calculate average score
    avg_data = calculate_average_score(all_results)
    monthly_data = get_monthly_averages(all_results)
    
    return render_template(
        'main/results.html',
        user=user,
        results=all_results,
        avg_score=avg_data,
        monthly_data=monthly_data,
    )


@main_bp.route('/school/<int:school_id>')
def school_dashboard(school_id):
    school = _get_school_from_session()
    # Allow super-admin OR the school itself
    if current_user.is_authenticated and current_user.is_super_admin:
        school = School.query.get_or_404(school_id)
    elif school and school.id == school_id:
        pass  # already loaded
    else:
        flash('Please log in as a school administrator.', 'warning')
        return redirect(url_for('auth.school_login'))

    accounts = Accounts.query.filter_by(school_id=school.id).order_by(Accounts.fname).all()
    results = (TestResult.query
               .join(Accounts)
               .filter(Accounts.school_id == school.id)
               .order_by(TestResult.taken_at.desc())
               .all())

    now = datetime.now(timezone.utc)
    stage_counter = Counter(
        (r.stage or r.details or 'Unknown').strip().title()
        for r in results
        if r.taken_at and r.taken_at.month == now.month and r.taken_at.year == now.year
    )

    return render_template(
        'main/school_dashboard.html',
        school=school,
        accounts=accounts,
        results=results,
        stage_counts=stage_counter,
        upload_enabled=school.upload_enabled,
        now=now,
        paystack_public_key=current_app.config.get('PAYSTACK_PUBLIC_KEY', ''),
        subscription_amount=current_app.config.get('SUBSCRIPTION_AMOUNT', 10000),
        subscription_currency=current_app.config.get('SUBSCRIPTION_CURRENCY', 'GHS'),
    )


@main_bp.route('/school/<int:school_id>/upload-students', methods=['POST'])
@school_login_required
def upload_students(school_id):
    from werkzeug.security import generate_password_hash
    import pandas as pd, os
    from flask import current_app

    school = _get_school_from_session()
    if not school or school.id != school_id:
        flash('Not authorised.', 'error')
        return redirect(url_for('auth.school_login'))

    if not school.upload_enabled:
        flash('Upload is not enabled. Please complete the subscription payment to activate student upload.', 'warning')
        return redirect(url_for('main.school_dashboard', school_id=school_id))

    file = request.files.get('file')
    if not file or file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('main.school_dashboard', school_id=school_id))

    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in current_app.config.get('ALLOWED_UPLOAD_EXTENSIONS', {'xlsx', 'xls'}):
        flash('Invalid file type. Please upload an Excel file (.xlsx or .xls).', 'error')
        return redirect(url_for('main.school_dashboard', school_id=school_id))

    try:
        df = pd.read_excel(file)
        df.columns = [c.strip().lower() for c in df.columns]
        required = ['first name', 'last name', 'email', 'username', 'password', 'birthdate', 'gender', 'level']
        missing = [c for c in required if c not in df.columns]
        if missing:
            flash(f'Missing columns: {", ".join(missing)}', 'error')
            return redirect(url_for('main.school_dashboard', school_id=school_id))

        created, skipped = 0, 0
        for _, row in df.iterrows():
            level = str(row['level']).strip().lower()
            if level not in ('primaryschool', 'middleschool', 'highschool', 'university'):
                skipped += 1
                continue
            if Accounts.query.filter_by(email=str(row['email']).strip()).first():
                continue
            birthdate = None
            if not pd.isna(row['birthdate']):
                try:
                    birthdate = pd.to_datetime(row['birthdate']).date()
                except Exception:
                    pass
            db.session.add(Accounts(
                fname=str(row['first name']).strip(),
                lname=str(row['last name']).strip(),
                email=str(row['email']).strip().lower(),
                username=str(row['username']).strip(),
                password=generate_password_hash(str(row['password'])),
                level=level,
                gender=str(row.get('gender', '')).strip(),
                birthdate=birthdate,
                school_id=school.id,
            ))
            created += 1

        db.session.commit()
        msg = f'Successfully created {created} student account(s).'
        if skipped:
            msg += f' {skipped} row(s) skipped due to invalid education level.'
        flash(msg, 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'An error occurred while processing the file: {e}', 'error')

    return redirect(url_for('main.school_dashboard', school_id=school_id))


@main_bp.route('/school/<int:school_id>/search-students')
def search_students(school_id):
    """AJAX student search for school dashboard."""
    school = _get_school_from_session()
    is_admin = current_user.is_authenticated and current_user.is_super_admin
    if not is_admin and (not school or school.id != school_id):
        return jsonify([])

    q = request.args.get('query', '').strip()
    if not q:
        return jsonify([])

    like = f'%{q}%'
    students = Accounts.query.filter(
        Accounts.school_id == school_id,
        or_(
            Accounts.fname.ilike(like),
            Accounts.lname.ilike(like),
            Accounts.username.ilike(like),
            Accounts.email.ilike(like),
        )
    ).limit(20).all()

    return jsonify([{
        'id': s.id,
        'fname': s.fname,
        'lname': s.lname,
        'username': s.username,
        'email': s.email,
    } for s in students])


@main_bp.route('/school/<int:school_id>/pay/verify')
@school_login_required
def verify_payment(school_id):

    school = _get_school_from_session()
    if not school or school.id != school_id:
        flash('Session expired. Please log in again.', 'error')
        return redirect(url_for('auth.school_login'))

    reference = request.args.get('reference', '').strip()
    if not reference:
        flash('No payment reference found. Please try again.', 'error')
        return redirect(url_for('main.school_dashboard', school_id=school_id))

    try:
        data = verify_paystack_payment(reference)

        expected_amount = current_app.config['SUBSCRIPTION_AMOUNT']

        if data['status'] != 'success':
            flash('Payment was not completed successfully.', 'error')
            return redirect(url_for('main.school_dashboard', school_id=school_id))

        if data['amount'] < expected_amount:
            flash('Payment amount insufficient.', 'error')
            return redirect(url_for('main.school_dashboard', school_id=school_id))

        # ✅ Activate upload
        school.subscription_paid = True
        school.upload_enabled = True
        school.paystack_reference = reference
        school.payment_date = datetime.now(timezone.utc)
        db.session.commit()

        flash('Payment confirmed! Upload is now enabled.', 'success')

    except Exception as e:
        flash(f'Could not verify payment: {e}', 'error')

    # ✅ IMPORTANT: redirect instead of render
    return redirect(url_for('main.school_dashboard', school_id=school_id))


@main_bp.route('/school/<int:school_id>/analytics')
@school_login_required
def school_analytics(school_id):
    """School analytics page showing overall student performance."""
    school = _get_school_from_session()
    if not school or school.id != school_id:
        flash('Please log in as a school administrator.', 'warning')
        return redirect(url_for('auth.school_login'))

    # Get all test results for this school
    results = (TestResult.query
               .join(Accounts)
               .filter(Accounts.school_id == school.id)
               .order_by(TestResult.taken_at.desc())
               .all())
    
    # Calculate school average
    avg_data = calculate_average_score(results)
    monthly_data = get_school_monthly_averages(results)
    
    return render_template(
        'main/school_analytics.html',
        school=school,
        avg_score=avg_data,
        monthly_data=monthly_data,
        total_students=len(set(r.user_id for r in results)),
        total_assessments=len(results),
    )
