import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'change-this-in-production-use-env-var'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Session security ──────────────────────────────────────────────────────
    SESSION_COOKIE_HTTPONLY = True          # JS cannot read the session cookie
    SESSION_COOKIE_SAMESITE = 'Lax'        # CSRF mitigation for top-level nav
    SESSION_COOKIE_SECURE = False           # overridden to True in ProductionConfig
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)  # applies when session.permanent=True

    # ── CSRF ─────────────────────────────────────────────────────────────────
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600             # token valid for 1 hour

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5MB max upload

    ALLOWED_UPLOAD_EXTENSIONS = {'xlsx', 'xls'}

    TEST_TYPES = [
        "Separation Anxiety Disorder",
        "Social Phobia",
        "Generalised Anxiety Disorder",
        "Panic Disorder",
        "Obsessive Compulsive Disorder",
        "Major Depressive Disorder",
    ]

    PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '')
    PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', '')
    SUBSCRIPTION_AMOUNT = int(os.environ.get('SUBSCRIPTION_AMOUNT', 10000))  # in pesewas
    SUBSCRIPTION_CURRENCY = os.environ.get('SUBSCRIPTION_CURRENCY', 'GHS')

class DevelopmentConfig(Config):
    DEBUG = True
    # Use SQLite for local development
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'sesa.db')
    # Or uncomment to use environment variable:
    # SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')

    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'sesa.db')
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True
    # Set RATELIMIT_STORAGE_URI=redis://localhost:6379/0 in your .env
    # Without Redis, rate limits reset independently per gunicorn worker.

    @classmethod
    def init_app(cls, app):
        Config.init_app(app) if hasattr(Config, 'init_app') else None
        secret = app.config.get('SECRET_KEY', '')
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if db_uri.startswith('sqlite') and not os.environ.get('ALLOW_SQLITE_IN_PROD'):
            raise RuntimeError(
                'DATABASE_URL is not set. SQLite must not be used in production '
                'with multiple workers. Set DATABASE_URL to a PostgreSQL connection '
                'string, or set ALLOW_SQLITE_IN_PROD=1 to override (single-process only).'
            )
        if 'change-this' in secret or len(secret) < 24:
            raise RuntimeError(
                'SECRET_KEY is insecure or using the default value. '
                'Set a strong SECRET_KEY environment variable before deploying.'
            )


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_SECURE = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig,
}