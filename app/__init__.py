"""
Application factory for SESA.
"""
import os
import logging
import click
from flask import Flask, render_template, send_from_directory, Response
from flask.cli import with_appcontext

from config import config
from app.extensions import db, migrate, login_manager, csrf, limiter


def create_app(config_name: str = None) -> Flask:
    """Create and configure the Flask application."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'default')

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config[config_name])

    # Ensure instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    # Configure structured logging
    _configure_logging(app)

    # Initialize extensions
    _init_extensions(app)

    # Register blueprints
    _register_blueprints(app)

    # Register PWA routes
    _register_pwa_routes(app)

    # Register error handlers
    _register_error_handlers(app)

    # Register CLI commands
    _register_cli(app)

    # Security response headers
    _register_security_headers(app)

    return app


def _configure_logging(app: Flask) -> None:
    """Set up structured logging."""
    log_level = logging.DEBUG if app.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(levelname)s %(name)s — %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    # Silence noisy third-party loggers in production
    if not app.debug:
        logging.getLogger('werkzeug').setLevel(logging.WARNING)


def _init_extensions(app: Flask) -> None:
    """Initialize Flask extensions."""

    # ── Neon / serverless Postgres pool settings ───────────────────────────────
    # Neon drops idle connections — these settings prevent stale connection errors
    app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {}).update({
        "pool_pre_ping": True,   # test connection before using it
        "pool_recycle":  300,    # recycle connections every 5 minutes
        "pool_size":     5,      # max persistent connections
        "max_overflow":  2,      # extra connections under load
    })

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    from app.models.account import Accounts
    from app.models.quiz_session import QuizSession  # noqa: F401
    from app.models.counsellor_profile import CounsellorProfile  # noqa: F401

    @login_manager.user_loader
    def load_user(user_id: str):
        return Accounts.query.get(int(user_id))


def _register_blueprints(app: Flask) -> None:
    """Register all application blueprints."""
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.test import test_bp
    from app.routes.admin import admin_bp
    from app.routes.counsellor import counsellor_bp
    from app.routes.qr import qr_bp
    from app.routes.counsellor_signup import counsellor_signup_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp, url_prefix='/')
    app.register_blueprint(test_bp, url_prefix='/test')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(counsellor_bp, url_prefix='/counsellor')
    app.register_blueprint(qr_bp, url_prefix='/school')
    app.register_blueprint(counsellor_signup_bp)



def _register_pwa_routes(app: Flask) -> None:
    """Register PWA-specific routes for manifest and service worker."""

    @app.route('/static/manifest.json')
    def manifest():
        """Serve manifest.json with proper MIME type."""
        return send_from_directory(
            app.static_folder,
            'manifest.json',
            mimetype='application/manifest+json'
        )

    @app.route('/static/sw.js')
    def service_worker():
        """Serve service worker with proper MIME type."""
        return send_from_directory(
            app.static_folder,
            'sw.js',
            mimetype='application/javascript'
        )

    @app.route('/offline')
    def offline():
        """Dedicated offline fallback page served by the service worker."""
        return render_template('errors/offline.html'), 200


def _register_error_handlers(app: Flask) -> None:
    """Register custom error pages."""
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403


def _register_security_headers(app: Flask) -> None:
    """Set security response headers on every response."""
    from flask import request as _req
    from flask import session as _sess

    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if not app.debug:
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains'
            )
        if response.status_code == 200:
            is_static = _req.path.startswith('/static/')
            is_public = _req.path in (
                '/', '/offline', '/auth/login', '/auth/signup',
                '/auth/school-login', '/auth/school-signup',
            )
            if not is_static and not is_public:
                response.headers['Cache-Control'] = (
                    'no-store, no-cache, must-revalidate, max-age=0'
                )
                response.headers['Pragma'] = 'no-cache'
        return response


def _register_cli(app: Flask) -> None:
    """Register CLI commands."""
    @app.cli.command('init-db')
    @with_appcontext
    def init_db():
        """Initialize the database."""
        db.create_all()
        click.echo('Database initialized.')

    @app.cli.command('import-students')
    @click.argument('school_id')
    @click.argument('excel_path')
    @with_appcontext
    def import_students(school_id, excel_path):
        """Import student accounts from an Excel file."""
        import pandas as pd
        from werkzeug.security import generate_password_hash
        from app.models.account import Accounts
        from datetime import datetime

        try:
            df = pd.read_excel(excel_path, engine='openpyxl')
            df.columns = [c.strip().lower() for c in df.columns]

            expected = {'first name', 'last name', 'email', 'username', 'password', 'gender', 'birthdate'}
            missing = expected - set(df.columns)
            if missing:
                click.echo(f'Missing columns: {missing}')
                return

            count = 0
            for _, row in df.iterrows():
                if Accounts.query.filter_by(email=row['email']).first():
                    continue
                acc = Accounts(
                    fname=row['first name'],
                    lname=row['last name'],
                    email=row['email'],
                    username=row['username'],
                    password=generate_password_hash(str(row['password'])),
                    school_name=None,
                    gender=row.get('gender', ''),
                    birthdate=pd.to_datetime(row['birthdate']).date() if not pd.isna(row['birthdate']) else None,
                    school_id=int(school_id)
                )
                db.session.add(acc)
                count += 1

            db.session.commit()
            click.echo(f'Imported {count} students for school {school_id}.')
        except Exception as e:
            click.echo(f'Error: {e}')

