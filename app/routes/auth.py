import logging
from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from flask_login import login_user, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, limiter
from app.models.account import Accounts
from app.models.school import School
from app.models.audit_log import audit
from app.forms import LoginForm, SchoolLoginForm, SignupForm, SchoolSignupForm, PasswordResetForm

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

_LOCKED_MSG = (
    'This account has been temporarily locked after too many failed attempts. '
    'Please try again in 15 minutes.'
)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        user = Accounts.query.filter_by(username=username).first()

        if user and user.is_locked:
            logger.warning('Login blocked — locked | user=%s ip=%s', username, request.remote_addr)
            audit('LOGIN_BLOCKED', actor_id=user.id, school_id=user.school_id,
                  ip_address=request.remote_addr, detail='Account locked')
            db.session.commit()
            flash(_LOCKED_MSG, 'error')
            return render_template('auth/login.html', form=form)

        if user and check_password_hash(user.password, form.password.data):
            user.record_successful_login()
            login_user(user)
            session.permanent = True
            audit('LOGIN_SUCCESS', actor_id=user.id, school_id=user.school_id,
                  ip_address=request.remote_addr)
            db.session.commit()
            logger.info('Login | user=%s ip=%s', user.username, request.remote_addr)

            if user.is_super_admin:
                return redirect(url_for('admin.dashboard'))
            if user.is_counsellor:
                return redirect(url_for('counsellor.dashboard'))
            next_page = request.args.get('next')
            if next_page:
                from urllib.parse import urlparse
                parsed = urlparse(next_page)
                if parsed.scheme or parsed.netloc:
                    next_page = None  # reject absolute URLs — open redirect protection
            return redirect(next_page or url_for('main.home'))

        # Failed attempt
        if user:
            user.record_failed_login()
            remaining = max(0, user.LOCKOUT_THRESHOLD - user.failed_attempts)
            audit('LOGIN_FAILED', actor_id=user.id, school_id=user.school_id,
                  ip_address=request.remote_addr,
                  detail=f'Attempt {user.failed_attempts}/{user.LOCKOUT_THRESHOLD}')
            db.session.commit()
            logger.warning('Failed login | user=%s attempt=%s ip=%s',
                           username, user.failed_attempts, request.remote_addr)

            if user.is_locked:
                flash(_LOCKED_MSG, 'error')
            elif remaining <= 2:
                flash(
                    f'Invalid password. {remaining} attempt{"s" if remaining != 1 else ""} '
                    f'remaining before your account is temporarily locked.',
                    'error',
                )
            else:
                flash('Invalid username or password. Please try again.', 'error')
        else:
            logger.warning('Failed login — unknown user | username=%s ip=%s',
                           username, request.remote_addr)
            flash('Invalid username or password. Please try again.', 'error')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/school-login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def school_login():
    form = SchoolLoginForm()
    if form.validate_on_submit():
        admin_name = form.admin_name.data.strip()
        school = School.query.filter_by(admin_name=admin_name).first()

        if school and school.is_locked:
            logger.warning('School login blocked — locked | school=%s ip=%s',
                           admin_name, request.remote_addr)
            flash(_LOCKED_MSG, 'error')
            return render_template('auth/school_login.html', form=form)

        if school and check_password_hash(school.admin_password, form.password.data):
            school.record_successful_login()
            session.clear()
            session['school_id'] = school.id
            session.permanent = True
            db.session.commit()
            logger.info('School login | school=%s ip=%s', school.school_name, request.remote_addr)
            flash(f'Welcome back, {school.admin_name}!', 'success')
            return redirect(url_for('main.school_dashboard', school_id=school.id))

        # Failed attempt
        if school:
            school.record_failed_login()
            remaining = max(0, school.LOCKOUT_THRESHOLD - school.failed_attempts)
            db.session.commit()
            logger.warning('Failed school login | school=%s attempt=%s ip=%s',
                           admin_name, school.failed_attempts, request.remote_addr)

            if school.is_locked:
                flash(_LOCKED_MSG, 'error')
            elif remaining <= 2:
                flash(
                    f'Invalid password. {remaining} attempt{"s" if remaining != 1 else ""} '
                    f'remaining before this account is temporarily locked.',
                    'error',
                )
            else:
                flash('Invalid administrator name or password.', 'error')
        else:
            flash('Invalid administrator name or password.', 'error')

    return render_template('auth/school_login.html', form=form)


@auth_bp.route('/signup', methods=['GET', 'POST'])
@limiter.limit("20 per hour")
def signup():
    form = SignupForm()
    if form.validate_on_submit():
        if Accounts.query.filter_by(email=form.email.data).first():
            flash('An account with this email already exists.', 'error')
            return render_template('auth/signup.html', form=form)
        if Accounts.query.filter_by(username=form.username.data).first():
            flash('This username is already taken.', 'error')
            return render_template('auth/signup.html', form=form)

        account = Accounts(
            fname=form.fname.data.strip(),
            lname=form.lname.data.strip(),
            email=form.email.data.strip().lower(),
            username=form.username.data.strip(),
            password=generate_password_hash(form.password.data),
            birthdate=form.birthdate.data,
            gender=form.gender.data,
            school_name=None,
        )
        try:
            db.session.add(account)
            db.session.commit()
            logger.info('New account | username=%s ip=%s', account.username, request.remote_addr)
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception:
            db.session.rollback()
            flash('An error occurred while creating your account. Please try again.', 'error')

    return render_template('auth/signup.html', form=form)


@auth_bp.route('/school-signup', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def school_signup():
    form = SchoolSignupForm()
    if form.validate_on_submit():
        if School.query.filter_by(school_name=form.school_name.data).first():
            form.school_name.errors.append('A school with this name is already registered.')
            return render_template('auth/school_signup.html', form=form)

        school = School(
            school_name=form.school_name.data.strip(),
            admin_name=form.admin_name.data.strip(),
            email=form.email.data.strip().lower() if form.email.data else None,
            phone=form.phone.data.strip() if form.phone.data else None,
            admin_password=generate_password_hash(form.admin_password.data),
        )
        try:
            db.session.add(school)
            db.session.commit()
            logger.info('New school | school=%s ip=%s', school.school_name, request.remote_addr)
            flash('School registered successfully! Please log in.', 'success')
            return redirect(url_for('auth.school_login'))
        except Exception:
            db.session.rollback()
            flash('An error occurred. Please try again.', 'error')

    return render_template('auth/school_signup.html', form=form)


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit("10 per hour")
def reset_password():
    """Password reset via school access code + username — no email required."""
    form = PasswordResetForm()
    if form.validate_on_submit():
        code = form.school_code.data.strip().upper()
        username = form.username.data.strip()

        school = School.query.filter_by(access_code=code).first()
        account = Accounts.query.filter_by(username=username, school_id=school.id).first() if school else None

        if not school or not account:
            flash('Invalid school code or username. Please check your details and try again.', 'error')
            return render_template('auth/reset_password.html', form=form)

        account.password = generate_password_hash(form.new_password.data)
        account.failed_attempts = 0
        account.locked_until = None
        db.session.commit()
        logger.info('Password reset | user=%s school=%s ip=%s',
                    account.username, school.school_name, request.remote_addr)
        flash('Password reset successfully. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', form=form)


@auth_bp.route('/logout')
def logout():
    username = getattr(current_user, 'username', None)
    logout_user()
    session.clear()
    if username:
        logger.info('Logout | user=%s ip=%s', username, request.remote_addr)
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('main.landing'))