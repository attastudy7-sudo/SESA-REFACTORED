from app.services.payment_service import verify_paystack_payment
from app.services.test_service import calculate_average_score, get_monthly_averages, get_school_monthly_averages
from datetime import datetime, timezone
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, session, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, func
from app.extensions import db, csrf
from app.models.account import Accounts
from app.models.school import School
from app.models.test_result import TestResult
from app.models.question import Question
from app.utils.decorators import school_login_required

main_bp = Blueprint('main', __name__)
logger = logging.getLogger(__name__)


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

    now = datetime.now(timezone.utc)

    # ── Paginated student list ──────────────────────────────────────────────
    student_page = request.args.get('student_page', 1, type=int)
    accounts_q = (Accounts.query
                  .filter_by(school_id=school.id)
                  .order_by(Accounts.fname))
    students_pagination = accounts_q.paginate(page=student_page, per_page=20, error_out=False)

    # Scalar counts for stat cards — no full table load
    total_students = accounts_q.count()
    total_results = (TestResult.query
                     .join(Accounts, Accounts.id == TestResult.user_id)
                     .filter(Accounts.school_id == school.id)
                     .count())
    at_risk_count = (TestResult.query
                     .join(Accounts, Accounts.id == TestResult.user_id)
                     .filter(
                         Accounts.school_id == school.id,
                         TestResult.stage.in_(['Elevated Stage', 'Clinical Stage']),
                     )
                     .count())

    # ── Stage distribution — configurable period ────────────────────────────
    # period = 'month' | 'term' | 'year' | 'all'
    period = request.args.get('period', 'month')
    stage_q = (
        db.session.query(
            func.coalesce(TestResult.stage, 'Unknown').label('stage'),
            func.count(TestResult.id).label('count'),
        )
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(Accounts.school_id == school.id)
    )
    if period == 'month':
        stage_q = stage_q.filter(
            func.extract('month', TestResult.taken_at) == now.month,
            func.extract('year',  TestResult.taken_at) == now.year,
        )
    elif period == 'term':
        # Ghanaian school terms: Jan–Apr, May–Aug, Sep–Dec
        term_start_month = ((now.month - 1) // 4) * 4 + 1
        term_start = datetime(now.year, term_start_month, 1, tzinfo=timezone.utc)
        stage_q = stage_q.filter(TestResult.taken_at >= term_start)
    elif period == 'year':
        stage_q = stage_q.filter(
            func.extract('year', TestResult.taken_at) == now.year,
        )
    # 'all' — no date filter

    stage_rows = stage_q.group_by(func.coalesce(TestResult.stage, 'Unknown')).all()
    stage_counts = {row.stage.strip().title(): row.count for row in stage_rows}

    # ── Paginated recent results ────────────────────────────────────────────
    results_page = request.args.get('results_page', 1, type=int)
    results_pagination = (
        TestResult.query
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(Accounts.school_id == school.id)
        .order_by(TestResult.taken_at.desc())
        .paginate(page=results_page, per_page=20, error_out=False)
    )

    return render_template(
        'main/school_dashboard.html',
        school=school,
        students_pagination=students_pagination,
        results_pagination=results_pagination,
        total_students=total_students,
        total_results=total_results,
        at_risk_count=at_risk_count,
        stage_counts=stage_counts,
        period=period,
        upload_enabled=school.upload_enabled,
        now=now,
        paystack_public_key=current_app.config.get('PAYSTACK_PUBLIC_KEY', ''),
        subscription_amount=current_app.config.get('SUBSCRIPTION_AMOUNT', 10000),
        subscription_currency=current_app.config.get('SUBSCRIPTION_CURRENCY', 'GHS'),
    )


@main_bp.route('/school/<int:school_id>/upload-students', methods=['POST'])
@school_login_required
def upload_students(school_id):
    """
    Bulk upload students from Excel.
    Required columns: first_name, last_name
    Optional: student_id, class_group, level, gender, email
    Usernames and passwords are auto-generated — no longer required.
    """
    import re as _re
    import pandas as pd
    from werkzeug.security import generate_password_hash

    school = _get_school_from_session()
    if not school or school.id != school_id:
        flash('Not authorised.', 'error')
        return redirect(url_for('auth.school_login'))

    if not school.upload_enabled:
        flash('Upload is not enabled. Please complete the subscription payment.', 'warning')
        return redirect(url_for('main.school_dashboard', school_id=school_id))

    file = request.files.get('file')
    if not file or file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('main.school_dashboard', school_id=school_id))

    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in current_app.config.get('ALLOWED_UPLOAD_EXTENSIONS', {'xlsx', 'xls'}):
        flash('Invalid file type. Please upload an Excel file (.xlsx or .xls).', 'error')
        return redirect(url_for('main.school_dashboard', school_id=school_id))

    # Short school code for auto-generated usernames
    school_code = _re.sub(r'[^a-z0-9]', '', school.school_name.lower())[:6] or 'sch'

    try:
        df = pd.read_excel(file)
        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

        required = {'first_name', 'last_name'}
        missing = required - set(df.columns)
        if missing:
            flash(
                f'Missing required columns: {", ".join(sorted(missing))}. '
                f'Required: first_name, last_name. '
                f'Optional: student_id, class_group, level, gender, email.',
                'error'
            )
            return redirect(url_for('main.school_dashboard', school_id=school_id))

        created, skipped = 0, 0
        for _, row in df.iterrows():
            fname = str(row.get('first_name', '')).strip()
            lname = str(row.get('last_name', '')).strip()
            if not fname or not lname or fname == 'nan' or lname == 'nan':
                skipped += 1
                continue

            # Auto-generate unique username
            base_uname = _re.sub(r'[^a-z0-9.]', '', f"{fname.lower()}.{lname.lower()}.{school_code}")[:48]
            username = base_uname
            suffix = 1
            while Accounts.query.filter_by(username=username).first():
                username = f"{base_uname}{suffix}"
                suffix += 1

            # student_id or username as temporary password
            student_id = str(row.get('student_id', '')).strip()
            temp_password = student_id if student_id and student_id != 'nan' else username

            # Optional email
            email_raw = str(row.get('email', '')).strip()
            email = email_raw.lower() if email_raw and email_raw != 'nan' else None
            if email and Accounts.query.filter_by(email=email).first():
                email = None

            level_raw = str(row.get('level', '')).strip().lower()
            level = level_raw if level_raw in ('primaryschool', 'middleschool', 'highschool', 'university') else None

            cg_raw = str(row.get('class_group', row.get('class', ''))).strip()
            class_group = cg_raw if cg_raw and cg_raw != 'nan' else None

            gender_raw = str(row.get('gender', '')).strip().lower()
            gender = gender_raw if gender_raw in ('male', 'female', 'other') else None

            db.session.add(Accounts(
                fname=fname,
                lname=lname,
                email=email,
                username=username,
                password=generate_password_hash(temp_password),
                level=level,
                gender=gender,
                class_group=class_group,
                school_id=school.id,
            ))
            created += 1

        db.session.commit()
        logger.info(
            'Bulk upload | school=%s created=%d skipped=%d ip=%s',
            school.school_name, created, skipped, request.remote_addr,
        )
        msg = f'Successfully created {created} student account(s).'
        if skipped:
            msg += f' {skipped} row(s) skipped (missing name).'
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

        # ✅ Activate upload — subscription valid for 365 days
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        school.subscription_paid = True
        school.upload_enabled = True
        school.paystack_reference = reference
        school.payment_date = now
        school.subscription_expires = now + timedelta(days=365)
        db.session.commit()
        logger.info(
            'Payment confirmed | school=%s ref=%s ip=%s',
            school.school_name, reference, request.remote_addr,
        )
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


# ── Access Code Self-Registration (Group 1) ──────────────────────────────────

@main_bp.route('/join', methods=['GET', 'POST'])
def join_with_code():
    """Student self-registration via 6-digit school access code."""
    from werkzeug.security import generate_password_hash
    import re

    error = None
    school = None
    code = request.args.get('code', '').strip().upper()

    if code:
        school = School.query.filter_by(access_code=code).first()
        if not school:
            error = 'Invalid access code. Please check with your school administrator.'

    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        school = School.query.filter_by(access_code=code).first()

        if not school:
            error = 'Invalid access code.'
        else:
            fname = request.form.get('fname', '').strip()
            lname = request.form.get('lname', '').strip()
            password = request.form.get('password', '')
            class_group = request.form.get('class_group', '').strip() or None

            if not fname or not lname or not password:
                error = 'Please fill in all required fields.'
            elif len(password) < 6:
                error = 'Password must be at least 6 characters.'
            else:
                school_code = re.sub(r'[^a-z0-9]', '', school.school_name.lower())[:6] or 'sch'
                base_uname = re.sub(r'[^a-z0-9.]', '', f"{fname.lower()}.{lname.lower()}.{school_code}")[:48]
                username = base_uname
                suffix = 1
                while Accounts.query.filter_by(username=username).first():
                    username = f"{base_uname}{suffix}"
                    suffix += 1

                account = Accounts(
                    fname=fname,
                    lname=lname,
                    username=username,
                    password=generate_password_hash(password),
                    class_group=class_group,
                    school_id=school.id,
                )
                try:
                    db.session.add(account)
                    db.session.commit()
                    logger.info(
                        'Access-code registration | school=%s username=%s ip=%s',
                        school.school_name, username, request.remote_addr,
                    )
                    from flask_login import login_user
                    login_user(account)
                    flash(f'Welcome to SESA, {fname}! Your username is @{username}.', 'success')
                    return redirect(url_for('main.home'))
                except Exception as e:
                    db.session.rollback()
                    error = 'An error occurred. Please try again.'

    return render_template('auth/join.html', school=school, code=code, error=error)


@main_bp.route('/school/<int:school_id>/generate-access-code', methods=['POST'])
@school_login_required
def generate_access_code(school_id):
    """Generate a new 6-digit access code for the school."""
    import secrets
    school = _get_school_from_session()
    if not school or school.id != school_id:
        flash('Not authorised.', 'error')
        return redirect(url_for('auth.school_login'))

    # Generate a unique 6-char alphanumeric code
    for _ in range(10):
        code = secrets.token_hex(3).upper()  # 6 hex chars
        if not School.query.filter_by(access_code=code).first():
            school.access_code = code
            db.session.commit()
            logger.info('Access code generated | school=%s code=%s', school.school_name, code)
            flash(f'New access code generated: {code}', 'success')
            break
    else:
        flash('Could not generate a unique code. Please try again.', 'error')

    return redirect(url_for('main.school_dashboard', school_id=school_id))


@main_bp.route('/school/<int:school_id>/students-at-risk')
@school_login_required
def students_at_risk(school_id):
    """Students at Elevated or Clinical stage (Group 3 — #1 feature for principals)."""
    school = _get_school_from_session()
    if not school or school.id != school_id:
        flash('Please log in as a school administrator.', 'warning')
        return redirect(url_for('auth.school_login'))

    # Class-group filter (applied in SQL, not Python)
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

    # Apply class-group filter at the SQL level
    if selected_class:
        at_risk_q = at_risk_q.filter(Accounts.class_group == selected_class)

    at_risk_q = at_risk_q.order_by(
        db.case((TestResult.stage == 'Clinical Stage', 0), else_=1),
        TestResult.taken_at.desc(),
    )

    pagination = at_risk_q.paginate(page=page, per_page=25, error_out=False)

    # All class groups for this school (for the filter dropdown)
    all_class_groups = sorted({
        a.class_group
        for a in Accounts.query.filter(
            Accounts.school_id == school_id,
            Accounts.class_group.isnot(None),
        ).with_entities(Accounts.class_group).all()
        if a.class_group
    })

    return render_template(
        'main/students_at_risk.html',
        school=school,
        pagination=pagination,
        at_risk=pagination.items,
        class_groups=all_class_groups,
        selected_class=selected_class,
    )

