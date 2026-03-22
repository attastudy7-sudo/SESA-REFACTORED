from app.services.payment_service import verify_paystack_payment
from app.services.test_service import calculate_average_score, get_monthly_averages, get_school_monthly_averages
from datetime import datetime, timezone
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, session, request, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_, func
from app.extensions import db, csrf, limiter
from app.models.account import Accounts
from app.models.school import School
from app.models.test_result import TestResult
from app.models.question import Question
from flask import send_file
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

    # Query question counts fresh each request.
    # Permanent caching on current_app caused stale counts after admin edits.
    question_counts = {
        row.test_type: row.count
        for row in db.session.query(
            Question.test_type,
            func.count(Question.id).label('count')
        ).group_by(Question.test_type).all()
    }

    tests_meta = [
        {'name': 'Separation Anxiety Disorder',   'key': 'sad',  'count': question_counts.get('Separation Anxiety Disorder',   0), 'icon': '🏠', 'color': 'teal'},
        {'name': 'Social Phobia',                 'key': 'sp',   'count': question_counts.get('Social Phobia',                 0), 'icon': '👥', 'color': 'blue'},
        {'name': 'Generalised Anxiety Disorder',  'key': 'gad',  'count': question_counts.get('Generalised Anxiety Disorder',  0), 'icon': '🌀', 'color': 'purple'},
        {'name': 'Panic Disorder',                'key': 'pd',   'count': question_counts.get('Panic Disorder',                0), 'icon': '💨', 'color': 'orange'},
        {'name': 'Obsessive Compulsive Disorder', 'key': 'ocd',  'count': question_counts.get('Obsessive Compulsive Disorder', 0), 'icon': '🔄', 'color': 'red'},
        {'name': 'Major Depressive Disorder',     'key': 'mdd',  'count': question_counts.get('Major Depressive Disorder',    0), 'icon': '🌧', 'color': 'indigo'},
    ]

    # Cross-test average removed — clinically invalid (tests have different max scores).
    from datetime import datetime, timedelta, timezone
    now = datetime.now()

    this_month_results = [
        r for r in results
        if r.taken_at and r.taken_at.month == now.month and r.taken_at.year == now.year
    ]
    tests_this_month = len(this_month_results)

    # Most recent result per test type — used for per-test stage summary
    latest_by_type = {}
    for r in results:
        if r.test_type not in latest_by_type:
            latest_by_type[r.test_type] = r

    total_assessments_taken = total_tests   # passed to template as total count
    assessments_this_month  = tests_this_month

    recent_results = results[:3]  # 3 most recent for the home table

    return render_template(
        'main/home.html',
        user=user,
        total_tests=total_tests,
        avg_score=total_assessments_taken,
        most_recent=most_recent,
        tests_meta=tests_meta,
        score_change=None,
        prev_avg=assessments_this_month,
        recent_results=recent_results,
        latest_by_type=latest_by_type,
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

    from app.models.account import Accounts as _Acc
    counsellors = _Acc.query.filter_by(school_id=school.id, is_counsellor=True).all()
    
    coverage_counts = {
        tt: db.session.query(func.count(func.distinct(TestResult.user_id)))
            .filter(TestResult.user_id.in_(
                db.session.query(Accounts.id).filter_by(school_id=school_id)
            ))
            .filter(TestResult.test_type == tt)
            .scalar() or 0
        for tt in current_app.config.get('TEST_TYPES', [])
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from flask import jsonify
        return jsonify({
            'stage_counts': stage_counts,
            'coverage_counts': coverage_counts,
            'period': period,
        })

    from app.services.payment_service import is_test_mode
    return render_template(
        'main/school_dashboard.html',
        coverage_counts=coverage_counts,
        school=school,
        counsellors=counsellors,
        total_students=total_students,
        total_results=total_results,
        at_risk_count=at_risk_count,
        stage_counts=stage_counts,
        period=period,
        upload_enabled=school.upload_enabled,
        now=now,
        test_mode=is_test_mode(),
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
    Optional: student_id, class_group, gender, email
    Usernames and passwords are auto-generated.
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

    school_code = _re.sub(r'[^a-z0-9]', '', school.school_name.lower())[:6] or 'sch'

    try:
        df = pd.read_excel(file)
        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

        # ── Required columns check ───────────────────────────────────────────
        required = {'first_name', 'last_name'}
        missing = required - set(df.columns)
        if missing:
            flash(
                f'Missing required columns: {", ".join(sorted(missing))}. '
                f'Required: first_name, last_name. '
                f'Optional: student_id, class_group, gender, email.',
                'error'
            )
            return redirect(url_for('main.school_dashboard', school_id=school_id))

        # ── Row limit ────────────────────────────────────────────────────────
        if len(df) > 1000:
            flash(
                f'File contains {len(df)} rows. Maximum allowed is 1,000 per upload. '
                f'Please split the file and upload in batches.',
                'error'
            )
            return redirect(url_for('main.school_dashboard', school_id=school_id))

        # ── Pre-load existing data into sets for fast in-memory lookup ───────
        existing_usernames = {
            r.username for r in
            Accounts.query.filter_by(school_id=school.id).with_entities(Accounts.username).all()
        }
        existing_emails = {
            r.email for r in
            Accounts.query.filter(Accounts.email.isnot(None)).with_entities(Accounts.email).all()
        }
        existing_names = {
            (r.fname.strip().lower(), r.lname.strip().lower()) for r in
            Accounts.query.filter_by(school_id=school.id).with_entities(Accounts.fname, Accounts.lname).all()
        }

        created    = 0
        skipped    = 0
        duplicates = 0
        warnings   = []

        for i, row in df.iterrows():
            fname = str(row.get('first_name', '')).strip()
            lname = str(row.get('last_name',  '')).strip()

            if not fname or not lname or fname == 'nan' or lname == 'nan':
                skipped += 1
                continue

            if (fname.lower(), lname.lower()) in existing_names:
                duplicates += 1
                continue

            base_uname = _re.sub(r'[^a-z0-9.]', '', f"{fname.lower()}.{lname.lower()}.{school_code}")[:48]
            username = base_uname
            suffix = 1
            while username in existing_usernames:
                username = f"{base_uname}{suffix}"
                suffix += 1
            existing_usernames.add(username)

            student_id_raw = str(row.get('student_id', '')).strip()
            temp_password = student_id_raw if student_id_raw and student_id_raw != 'nan' else username

            email_raw = str(row.get('email', '')).strip()
            email = email_raw.lower() if email_raw and email_raw != 'nan' else None
            if email:
                if email in existing_emails:
                    warnings.append(f'Row {i + 2}: email {email} already exists — saved without email.')
                    email = None
                else:
                    existing_emails.add(email)

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
                school_name=school.school_name,
                gender=gender,
                class_group=class_group,
                school_id=school.id,
            ))
            existing_names.add((fname.lower(), lname.lower()))
            created += 1

        db.session.commit()
        logger.info(
            'Bulk upload | school=%s created=%d skipped=%d duplicates=%d ip=%s',
            school.school_name, created, skipped, duplicates, request.remote_addr,
        )

        msg = f'Successfully created {created} student account(s).'
        if duplicates:
            msg += f' {duplicates} skipped (already exist in this school).'
        if skipped:
            msg += f' {skipped} skipped (missing name).'
        flash(msg, 'success')

        for w in warnings[:5]:
            flash(w, 'warning')
        if len(warnings) > 5:
            flash(f'...and {len(warnings) - 5} more email warning(s). Check your file.', 'warning')

    except Exception as e:
        db.session.rollback()
        logger.error('Bulk upload error | school=%s error=%s', school.school_name, e)
        flash(f'An error occurred while processing the file: {e}', 'error')

    return redirect(url_for('main.school_dashboard', school_id=school_id))


@main_bp.route('/school/<int:school_id>/search-students')
@school_login_required
@limiter.limit("60 per minute")
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
        'class_group': s.class_group,
        'school_name': s.school_name,
    } for s in students])


@main_bp.route('/school/<int:school_id>/pay/verify')
@school_login_required
def verify_payment(school_id):
    """
    Verify a Paystack payment callback and activate the school's upload subscription.

    TEST MODE (PAYSTACK_TEST_MODE=True):
      - The payment_service bypasses the real API and returns a synthetic success.
      - Amount check is skipped so any test-card transaction goes through cleanly.
      - Reference replay guard still runs to keep the code path realistic.
    """
    from app.services.payment_service import is_test_mode

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

        if data['status'] != 'success':
            flash('Payment was not completed successfully.', 'error')
            return redirect(url_for('main.school_dashboard', school_id=school_id))

        # In live mode only: enforce the expected amount
        if not is_test_mode():
            expected_amount = current_app.config.get('SUBSCRIPTION_AMOUNT', 10000)
            if data['amount'] < expected_amount:
                flash('Payment amount insufficient.', 'error')
                return redirect(url_for('main.school_dashboard', school_id=school_id))

        # Guard against reference replay — one reference can only activate once
        # (applies in both modes so we can catch accidental double-submits in testing)
        already_used = School.query.filter_by(paystack_reference=reference).first()
        if already_used and already_used.id != school_id:
            flash('This payment reference has already been used.', 'error')
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

        mode_label = ' [TEST MODE]' if is_test_mode() else ''
        logger.info(
            'Payment confirmed%s | school=%s ref=%s ip=%s',
            mode_label, school.school_name, reference, request.remote_addr,
        )
        flash('Payment confirmed! Student upload is now active.', 'success')

    except Exception as e:
        flash(f'Could not verify payment: {e}', 'error')

    return redirect(url_for('main.school_dashboard', school_id=school_id))


@main_bp.route('/school/<int:school_id>/pay/test-activate', methods=['POST'])
@school_login_required
def test_activate_upload(school_id):
    """
    TEST MODE ONLY — instantly activates upload without touching Paystack.
    Exposed only when PAYSTACK_TEST_MODE=True. Returns 403 in production.

    This lets developers test the full post-activation UX (dashboard unlocks,
    upload form appears, etc.) without completing a Paystack test transaction.
    """
    from app.services.payment_service import is_test_mode
    from datetime import timedelta

    if not is_test_mode():
        from flask import abort
        abort(403)

    school = _get_school_from_session()
    if not school or school.id != school_id:
        flash('Session expired.', 'error')
        return redirect(url_for('auth.school_login'))

    now = datetime.now(timezone.utc)
    school.subscription_paid = True
    school.upload_enabled = True
    school.paystack_reference = f'TEST-{school_id}-{int(now.timestamp())}'
    school.payment_date = now
    school.subscription_expires = now + timedelta(days=365)
    db.session.commit()

    logger.info(
        'TEST activation | school=%s ip=%s',
        school.school_name, request.remote_addr,
    )
    flash('Test activation complete. Upload is now enabled.', 'success')
    return redirect(url_for('main.school_dashboard', school_id=school_id))


@main_bp.route('/school/<int:school_id>/students')
@school_login_required
def school_students(school_id):
    school = _get_school_from_session()
    if current_user.is_authenticated and current_user.is_super_admin:
        school = School.query.get_or_404(school_id)
    elif school and school.id == school_id:
        pass
    else:
        flash('Please log in as a school administrator.', 'warning')
        return redirect(url_for('auth.school_login'))

    accounts_q = (Accounts.query
                  .filter_by(school_id=school.id)
                  .order_by(Accounts.fname))
    total_students = accounts_q.count()
    student_page = request.args.get('student_page', 1, type=int)
    students_pagination = accounts_q.paginate(page=student_page, per_page=25, error_out=False)

    return render_template(
        'main/school_students.html',
        school=school,
        students_pagination=students_pagination,
        total_students=total_students,
    )


@main_bp.route('/school/<int:school_id>/results')
@school_login_required
def school_results(school_id):
    school = _get_school_from_session()
    if current_user.is_authenticated and current_user.is_super_admin:
        school = School.query.get_or_404(school_id)
    elif school and school.id == school_id:
        pass
    else:
        flash('Please log in as a school administrator.', 'warning')
        return redirect(url_for('auth.school_login'))

    results_page = request.args.get('results_page', 1, type=int)
    results_pagination = (
        TestResult.query
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(Accounts.school_id == school.id)
        .order_by(TestResult.taken_at.desc())
        .paginate(page=results_page, per_page=25, error_out=False)
    )
    total_results = (TestResult.query
                     .join(Accounts, Accounts.id == TestResult.user_id)
                     .filter(Accounts.school_id == school.id)
                     .count())

    return render_template(
        'main/school_results.html',
        school=school,
        results_pagination=results_pagination,
        total_results=total_results,
    )


@main_bp.route('/school/<int:school_id>/analytics')
@school_login_required
def school_analytics(school_id):
    """School analytics page showing overall student performance."""
    school = _get_school_from_session()
    if not school or school.id != school_id:
        flash('Please log in as a school administrator.', 'warning')
        return redirect(url_for('auth.school_login'))

    from app.services.analytics_service import get_school_analytics

    analytics = get_school_analytics(school.id)

    return render_template(
        'main/school_analytics.html',
        school=school,
        avg_score=analytics['avg_score'],
        monthly_data=analytics['monthly_data'],
        total_students=analytics['total_students'],
        total_assessments=analytics['total_assessments'],
    )

@main_bp.route('/school/<int:school_id>/report/download')
@school_login_required
def download_report(school_id):
    """Generate and download a PDF performance report for the school."""
    school = _get_school_from_session()
    if not school or school.id != school_id:
        flash('Please log in as a school administrator.', 'warning')
        return redirect(url_for('auth.school_login'))

    period = request.args.get('period', 'monthly')
    if period not in ('weekly', 'monthly', 'yearly'):
        period = 'monthly'

    from app.services.report_service import get_report_data
    from app.services.pdf_service import generate_report_pdf

    data = get_report_data(school_id, period)
    buf = generate_report_pdf(school.school_name, data)

    filename = (
        f"SESA_Report_{school.school_name.replace(' ', '_')}"
        f"_{period}_{data['generated_at'].strftime('%Y%m%d')}.pdf"
    )

    return send_file(
        buf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
    )

# ── Access Code Self-Registration (Group 1) ──────────────────────────────────

@main_bp.route('/join', methods=['GET', 'POST'])
@limiter.limit("20 per hour")
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
                    email=None,  # self-registration via access code — email not required
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
            logger.info('Access code rotated | school_id=%s', school.id)
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
    all_class_groups = sorted([
        row.class_group
        for row in db.session.query(Accounts.class_group)
        .filter(
            Accounts.school_id == school_id,
            Accounts.class_group.isnot(None),
        )
        .distinct()
        .all()
    ])

    return render_template(
        'main/students_at_risk.html',
        school=school,
        pagination=pagination,
        at_risk=pagination.items,
        class_groups=all_class_groups,
        selected_class=selected_class,
    )

@main_bp.route('/school/guide')
@school_login_required
def school_guide():
    return render_template('main/school_guide.html')


# ── SEO: robots.txt ──────────────────────────────────────────────────────────
@main_bp.route('/robots.txt')
def robots_txt():
    from flask import Response
    lines = [
        "User-agent: *",
        "Disallow: /auth/reset-password",
        "Disallow: /auth/logout",
        "Disallow: /home",
        "Disallow: /results",
        "Disallow: /admin",
        "Disallow: /school/",
        "Disallow: /counsellor/",
        "Disallow: /test/",
        "",
        f"Sitemap: {request.url_root.rstrip('/')}/sitemap.xml",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


# ── SEO: sitemap.xml ─────────────────────────────────────────────────────────
@main_bp.route('/sitemap.xml')
def sitemap_xml():
    from flask import Response
    import datetime
    base = request.url_root.rstrip('/')
    today = datetime.date.today().isoformat()
    urls = [
        {"loc": base + "/",                        "priority": "1.0", "changefreq": "monthly"},
        {"loc": base + "/auth/school-signup",      "priority": "0.8", "changefreq": "yearly"},
        {"loc": base + "/auth/login",              "priority": "0.6", "changefreq": "yearly"},
        {"loc": base + "/auth/signup",             "priority": "0.5", "changefreq": "yearly"},
        {"loc": base + "/auth/school-login",       "priority": "0.5", "changefreq": "yearly"},
        {"loc": base + "/auth/counsellor-login",   "priority": "0.4", "changefreq": "yearly"},
        {"loc": base + "/join",                    "priority": "0.5", "changefreq": "yearly"},
    ]
    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml_parts.append(
            f'  <url><loc>{u["loc"]}</loc>'
            f'<lastmod>{today}</lastmod>'
            f'<changefreq>{u["changefreq"]}</changefreq>'
            f'<priority>{u["priority"]}</priority></url>'
        )
    xml_parts.append('</urlset>')
    return Response("\n".join(xml_parts), mimetype="application/xml")
