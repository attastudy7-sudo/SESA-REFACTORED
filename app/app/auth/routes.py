# ─────────────────────────────────────────────────────────────────────────────
# AUTH ROUTES — authentication, signup, login, password reset, Google OAuth
# ─────────────────────────────────────────────────────────────────────────────

# Standard library
import os
import re
import hmac
import hashlib
import urllib.parse

# Flask & extensions
from flask import current_app, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, current_user
from flask_wtf.csrf import validate_csrf, CSRFError
from flask_dance.contrib.google import make_google_blueprint
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# Application
from app import limiter, db, csrf
from app.auth import bp          # Blueprint MUST be imported before @bp.route decorators
from app.models import User
from app.forms import LoginForm, SignupForm


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL VERIFICATION TOKEN GENERATION
# ─────────────────────────────────────────────────────────────────────────────

def generate_verification_token(user):
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return s.dumps({'user_id': user.id, 'email': user.email})


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/verify-email')
def verify_email():
    token = request.args.get('token')
    if not token:
        flash('Invalid or missing verification token.', 'danger')
        return redirect(url_for('main.index'))
    s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        data = s.loads(token, max_age=60*60*24*3)  # 3 days expiry
    except SignatureExpired:
        flash('Verification link expired. Please request a new one.', 'danger')
        return redirect(url_for('main.index'))
    except BadSignature:
        flash('Invalid verification token.', 'danger')
        return redirect(url_for('main.index'))
    user = User.query.filter_by(id=data.get('user_id'), email=data.get('email')).first()
    if not user:
        flash('User not found.', 'danger')
    elif user.email_verified:
        flash('Email already verified. Please log in.', 'info')
    else:
        user.email_verified = True
        db.session.commit()
        flash('Email verified! You can now log in.', 'success')
    return redirect(url_for('main.index', login=1))


# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE OAUTH BLUEPRINT FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def create_google_blueprint():
    """
    Called in the app factory (app/__init__.py):

        google_bp = create_google_blueprint()
        app.register_blueprint(google_bp, url_prefix='/login')

    The OAuth callback lands at /login/google/authorized (handled by
    Flask-Dance). The oauth_authorized signal in __init__.py then
    logs the user in — there is NO separate /google/callback route.

    Add these URIs in Google Cloud Console:
        Local:      http://localhost:5000/login/google/authorized
        Production: https://your-domain.onrender.com/login/google/authorized

    Required env vars:
        GOOGLE_OAUTH_CLIENT_ID
        GOOGLE_OAUTH_CLIENT_SECRET
    """
    return make_google_blueprint(
        client_id=os.environ.get('GOOGLE_OAUTH_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET'),
        scope=[
            'openid',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile',
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — find user by username OR email
# ─────────────────────────────────────────────────────────────────────────────

def _find_user_by_login(identifier: str):
    """
    Accept either a username or email in the login field.
    If the identifier contains '@' we try email first, then username.
    """
    identifier = identifier.strip()
    if '@' in identifier:
        user = User.query.filter_by(email=identifier).first()
        if user:
            return user
    return User.query.filter_by(username=identifier).first()


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — create or fetch a Google OAuth user
# ─────────────────────────────────────────────────────────────────────────────

def _get_or_create_google_user(google_email: str, google_name: str, google_picture: str = None):
    """
    Find an existing account by Google email, or create a new one.

    Username is derived from the email prefix; a numeric suffix is appended
    if the base username is already taken.

    Google-created accounts have password_hash=None and can only log in
    via Google unless a password is set separately.
    """
    user = User.query.filter_by(email=google_email).first()
    if user:
        # One-time profile sync for existing Google users
        if user.needs_google_profile_sync:
            if google_name:
                user.nickname = google_name
            if google_picture:
                user.profile_picture = google_picture
            user.email_verified = True
            user.needs_google_profile_sync = False
            db.session.commit()
        return user, False

    base_username = google_email.split('@')[0].replace('.', '_').lower()
    username = base_username
    counter  = 1
    while User.query.filter_by(username=username).first():
        username = f"{base_username}{counter}"
        counter += 1

    user = User(
        username        = username,
        email           = google_email,
        nickname        = google_name or username,
        profile_picture = google_picture or 'default.jpg',
    )
    user.password_hash = None   # Google-only account — no password
    user.email_verified = True  # Google ensures email is verified

    db.session.add(user)
    db.session.commit()

    from app.utils import send_welcome_email
    send_welcome_email(user)

    return user, True


# ─────────────────────────────────────────────────────────────────────────────
# LOGIN — accepts username OR email
# ─────────────────────────────────────────────────────────────────────────────

@csrf.exempt
@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    # Process login request
    username_or_email = request.form.get('username')
    password = request.form.get('password')
    
    if request.method == 'POST':
        if not username_or_email or not password:
            flash('Please enter both username/email and password.', 'danger')
            return redirect(url_for('main.index', login=1))
            
        user = _find_user_by_login(username_or_email)
        if user and user.password_hash is None:
            flash('This account uses Google sign-in. Use the "Sign in with Google" button, or add a password in your account settings.', 'info')
            return redirect(url_for('main.index', login=1))

        if user is None or not user.check_password(password):
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('main.index', login=1))

        if user.password_hash is not None and not user.email_verified:
            flash('Please verify your email address before logging in. Check your inbox for a verification link.', 'warning')
            return redirect(url_for('main.index', login=1))

        login_user(user, remember=True)
        next_page = request.args.get('next')
        # Only allow safe local redirects
        if next_page:
            parsed = urllib.parse.urlparse(next_page)
            if parsed.scheme or parsed.netloc or not parsed.path.startswith('/'):
                next_page = url_for('main.index')
        else:
            next_page = url_for('main.index')
        return redirect(next_page)
        
    return redirect(url_for('main.index', login=1))


# ─────────────────────────────────────────────────────────────────────────────
# SIGNUP
# ─────────────────────────────────────────────────────────────────────────────

@csrf.exempt
@bp.route('/signup', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    # GET request: redirect to index with signup modal
    if request.method == 'GET':
        return redirect(url_for('main.index', signup=1))
        
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        password2 = request.form.get('password2', '')
        nickname = request.form.get('nickname', '').strip()
        username = request.form.get('username', '').strip()

        # Validation
        if not all([email, password, password2]):
            msg = 'All fields are required.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {"success": False, "message": msg}, 400
            flash(msg, 'danger')
            return redirect(url_for('main.index', signup=1))

        # Optional: username and nickname validation
        if username:
            if not re.match(r'^[A-Za-z0-9_]{3,32}$', username):
                msg = 'Username must be 3-32 characters, alphanumeric or underscore.'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return {"success": False, "message": msg}, 400
                flash(msg, 'danger')
                return redirect(url_for('main.index', signup=1))
            if User.query.filter_by(username=username).first():
                msg = 'Username is already taken.'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return {"success": False, "message": msg}, 400
                flash(msg, 'danger')
                return redirect(url_for('main.index', signup=1))

        if '@' not in email or '.' not in email:
            msg = 'Please enter a valid email address.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {"success": False, "message": msg}, 400
            flash(msg, 'danger')
            return redirect(url_for('main.index', signup=1))

        # Password policy: 8+ chars, 1 uppercase, 1 digit, 1 symbol
        pw_errors = []
        if len(password) < 8:
            pw_errors.append('at least 8 characters')
        if not re.search(r'[A-Z]', password):
            pw_errors.append('an uppercase letter')
        if not re.search(r'\d', password):
            pw_errors.append('a digit')
        if not re.search(r'[^A-Za-z0-9]', password):
            pw_errors.append('a symbol')
        if pw_errors:
            msg = 'Password must contain ' + ', '.join(pw_errors) + '.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {"success": False, "message": msg}, 400
            flash(msg, 'danger')
            return redirect(url_for('main.index', signup=1))

        if password != password2:
            msg = 'Passwords do not match.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {"success": False, "message": msg}, 400
            flash(msg, 'danger')
            return redirect(url_for('main.index', signup=1))

        # Check if email is taken (prevent enumeration)
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            msg = 'Check your inbox for next steps.'
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return {"success": True, "message": msg}
            flash(msg, 'info')
            return redirect(url_for('main.index', signup=1))

        # Use provided username or generate from email, handle race condition
        from sqlalchemy.exc import IntegrityError
        base_username = email.split('@')[0].replace('.', '_').lower()
        if not username:
            username = base_username
            counter = 1
        else:
            counter = 1
        user = None
        while True:
            try:
                if User.query.filter_by(username=username).first():
                    username = f"{base_username}{counter}"
                    counter += 1
                    continue
                user = User(username=username, email=email, nickname=nickname)
                user.set_password(password)
                # Auto-verify email if override is enabled
                if current_app.config.get('SKIP_EMAIL_VERIFICATION', False):
                    user.email_verified = True
                else:
                    user.email_verified = False
                db.session.add(user)
                db.session.commit()
                break
            except IntegrityError:
                db.session.rollback()
                username = f"{base_username}{counter}"
                counter += 1

        # Send verification email unless skipping in dev
        if user.password_hash is not None:
            if current_app.config.get('SKIP_EMAIL_VERIFICATION', False):
                login_user(user, remember=True)
                msg = 'Account created! Email verification skipped in development.'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return {"success": True, "message": msg, "redirect": url_for('main.index')}
                flash(msg, 'success')
                return redirect(url_for('main.index'))
            else:
                from app.utils.emails import send_verification_email
                send_verification_email(user)
                msg = 'Account created! Please check your email to verify your address.'
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return {"success": True, "message": msg}
                flash(msg, 'info')
                return redirect(url_for('main.index', login=1))

        # OAuth-only path not reachable here


# ─────────────────────────────────────────────────────────────────────────====
# GOOGLE — initiate OAuth flow
# Saves the 'next' param in session so it survives the OAuth redirect.
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/google/login')
def google_login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    next_page = request.args.get('next')
    if next_page and next_page.startswith('/'):
        session['next_after_google'] = next_page

    return redirect(url_for('google.login'))


# ─────────────────────────────────────────────────────────────────────────────
# LOGOUT
# ─────────────────────────────────────────────────────────────────────────────

@bp.route('/logout', methods=['POST'])
def logout():
    try:
        validate_csrf(request.form.get('csrf_token'))
    except CSRFError:
        flash('Invalid CSRF token.', 'danger')
        return redirect(url_for('main.index'))
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))


# ─────────────────────────────────────────────────────────────────────────────
# PASSWORD RESET — request
# ─────────────────────────────────────────────────────────────────────────────

@csrf.exempt
@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    return redirect(url_for('main.index', signup=0))


# ─────────────────────────────────────────────────────────────────────────────
# PASSWORD RESET — confirm token and set new password
# ─────────────────────────────────────────────────────────────────────────────

@csrf.exempt
@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    import time
    from app.forms import PasswordResetForm

    # Validate token format
    try:
        user_id_str, expires_str, provided_token = token.split('.')
        user_id = int(user_id_str)
        expires = int(expires_str)
    except (ValueError, AttributeError):
        flash('This reset link is invalid.', 'danger')
        return redirect(url_for('auth.reset_password_request'))

    if int(time.time()) > expires:
        flash('This reset link has expired. Please request a new one.', 'warning')
        return redirect(url_for('auth.reset_password_request'))

    user = db.session.get(User, user_id)
    if not user or user.password_hash is None:
        flash('This reset link is invalid.', 'danger')
        return redirect(url_for('auth.reset_password_request'))

    secret = current_app.config.get('PASSWORD_RESET_SECRET', current_app.config['SECRET_KEY']).encode()
    payload = f'{user.id}:{user.password_hash[:10]}:{expires}'
    expected = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, provided_token):
        flash('This reset link is invalid or has already been used.', 'danger')
        return redirect(url_for('auth.reset_password_request'))

    form = PasswordResetForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been reset. Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html',
                           title='Set New Password', form=form, token=token)
