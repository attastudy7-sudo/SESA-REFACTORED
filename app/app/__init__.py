from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from config import Config
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import mistune


# Initialize extensions (no app yet)
db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
limiter = None  # Will be initialized in create_app


def register_error_handlers(app):
    from flask import render_template

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('errors/403.html'), 403

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return render_template('errors/500.html'), 500


def register_template_context(app):
    @app.context_processor
    def inject_template_defaults():
        from app.models import Programme
        active_programmes = Programme.query.filter_by(is_active=True).order_by(Programme.name).all()
        return dict(
            active_programmes=active_programmes,
            show_suggestions=False,
            suggested_users={'same_school': [], 'same_programme': [], 'random': []}
        )


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Fix HTTPS behind Render's proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # ── Extensions ────────────────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    csrf.init_app(app)
    Migrate(app, db, render_as_batch=True)

    # ── Compression (gzip all HTML/CSS/JS responses) ──────────────────────────
    from flask_compress import Compress
    Compress(app)

    # ── Static file caching ───────────────────────────────────────────────────
    @app.after_request
    def add_cache_headers(response):
        if '/static/' in request.path:
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response
    
    # ── Redis Cache & Rate Limiter ─────────────────────────────────────────
    import redis
    redis_url = app.config.get('REDIS_URL', 'redis://localhost:6379/0')
    redis_available = False
    try:
        redis_client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1)
        redis_client.ping()
        app.extensions['redis'] = redis_client
        redis_available = True
        if not app.config.get('IS_DEVELOPMENT'):
            print("Redis cache connected")
    except Exception:
        app.extensions['redis'] = None
        # Only print in non-development or if explicitly requested
        if not app.config.get('IS_DEVELOPMENT'):
             print("Note: Redis unavailable. Continuing without caching.")

    # Initialize rate limiter with fallback
    global limiter
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    
    storage_uri = redis_url if redis_available else "memory://"
    
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        storage_uri=storage_uri,
        default_limits=["200 per day", "500 per hour"],
        strategy="fixed-window"
    )

    # ── Cloudinary ────────────────────────────────────────────────────────────
    import cloudinary
    cloudinary.config(
        cloud_name=app.config['CLOUDINARY_CLOUD_NAME'],
        api_key=app.config['CLOUDINARY_API_KEY'],
        api_secret=app.config['CLOUDINARY_API_SECRET'],
        secure=True
    )



    # ── Login manager ─────────────────────────────────────────────────────────
    login_manager.login_view = 'main.join'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    # ── Blueprints ────────────────────────────────────────────────────────────
    # IMPORTANT: register auth FIRST so url_for('auth.signup') / url_for('auth.login')
    # are available when the main blueprint's redirect routes are built.

    # 1. Auth blueprint — must come before main so its endpoints exist
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # 2. Google OAuth blueprint — registered after auth so imports resolve cleanly
    from app.auth.routes import create_google_blueprint
    google_bp = create_google_blueprint()
    app.register_blueprint(google_bp, url_prefix='/login')

    # Wire up the oauth_authorized signal AFTER both blueprints are registered
    from flask_dance.consumer import oauth_authorized
    from flask import redirect, url_for, flash

    @oauth_authorized.connect_via(google_bp)
    def google_logged_in(blueprint, token):
        if not token:
            flash('Failed to log in with Google.', 'danger')
            return redirect(url_for('auth.login'))

        resp = blueprint.session.get('/oauth2/v2/userinfo')
        if not resp.ok:
            flash('Failed to fetch user info from Google.', 'danger')
            return redirect(url_for('auth.login'))

        info           = resp.json()
        google_email   = info.get('email')
        google_name    = info.get('name', '')
        google_picture = info.get('picture')

        if not google_email:
            flash('Could not retrieve your email from Google.', 'danger')
            return redirect(url_for('auth.login'))

        from app.auth.routes import _get_or_create_google_user
        from flask_login import login_user
        from flask import session as flask_session
        user, created = _get_or_create_google_user(google_email, google_name, google_picture)
        login_user(user, remember=True)

        if created:
            flash(f'Welcome to knowly, {user.username}! Account created via Google.', 'success')
        else:
            flash(f'Welcome back, {user.username}!', 'success')

        # Redirect to saved next page or home — returning a Response
        # stops Flask-Dance from doing its own redirect (which causes 404)
        next_url = flask_session.pop('next_after_google', None) or url_for('main.index')
        return redirect(next_url)

    # 3. Remaining blueprints
    from app.posts import bp as posts_bp
    app.register_blueprint(posts_bp, url_prefix='/posts')

    from app.users import bp as users_bp
    app.register_blueprint(users_bp, url_prefix='/users')

    from app.payments import bp as payments_bp
    app.register_blueprint(payments_bp, url_prefix='/payments')

    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    from app.quiz import bp as quiz_bp
    # Registered at / because quiz routes (e.g. /<post_id>/quiz/start) do not
    # conflict with main routes. This preserves existing internal URL structures.
    app.register_blueprint(quiz_bp, url_prefix='/')

    # 4. Main blueprint last — its /signup and /login redirects call
    #    url_for('auth.signup') / url_for('auth.login'), which must already exist
    from app import routes
    app.register_blueprint(routes.bp)

    from app.internal import routes as internal_routes
    app.register_blueprint(internal_routes.bp)
    # The internal blueprint uses X-Internal-Key header auth (not CSRF tokens).
    # Exempt it so KnowlyGen can call POST/PATCH endpoints without a CSRF token.
    csrf.exempt(internal_routes.bp)

    from app.past_papers import routes as past_papers_routes
    app.register_blueprint(past_papers_routes.bp, url_prefix='/past-papers')

    from app.services.ai_service import warn_if_gemini_keys_invalid
    warn_if_gemini_keys_invalid()

    # ── CLI Commands ──────────────────────────────────────────────────────────
    from app.cli import campaigns_bp
    app.cli.add_command(campaigns_bp)


    # ── Database ──────────────────────────────────────────────────────────────
    # db.create_all() only in development; production uses `flask db upgrade`
    if app.config.get('IS_DEVELOPMENT', True):
        with app.app_context():
            try:
                db.create_all()
            except Exception as e:
                print(f"Database init skipped: {e}")

    # Add custom JSON filter
    @app.template_filter('from_json')
    def from_json_filter(value):
        import json
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    import re as _re

    def _safe_markdown(text):
        if not text:
            return ''
        math_blocks = []
        def _stash(m):
            idx = len(math_blocks)
            math_blocks.append(m.group(0))
            return f'\x00MATH{idx}\x00'
        text = _re.sub(r'\$\$.+?\$\$', _stash, text, flags=_re.DOTALL)
        text = _re.sub(r'\\\[.+?\\\]', _stash, text, flags=_re.DOTALL)
        text = _re.sub(r'\$[^\$\n]+?\$', _stash, text)
        text = _re.sub(r'\\\(.+?\\\)', _stash, text, flags=_re.DOTALL)
        text = mistune.html(text)
        for i, block in enumerate(math_blocks):
            text = text.replace(f'\x00MATH{i}\x00', block)
        return text

    app.jinja_env.filters['markdown'] = _safe_markdown
    app.jinja_env.filters['fromjson'] = json.loads

    def _strip_course_code(text):
        if not text:
            return text
        # Handle "CS102 - Discrete Maths"
        if ' - ' in text:
            return text.split(' - ', 1)[1].strip()
        # Handle "CS102: Discrete Maths"
        if ':' in text:
            return text.split(':', 1)[1].strip()
        # Handle "CS102 – Discrete Maths" (en-dash)
        if ' – ' in text:
            return text.split(' – ', 1)[1].strip()
        return text
    app.jinja_env.filters['strip_course_code'] = _strip_course_code

    register_error_handlers(app)
    register_template_context(app)
    return app


# Import models so SQLAlchemy knows about them
from app import models
from app.models import Subject

import logging
logging.basicConfig(level=logging.INFO)