import os
import secrets
from datetime import timedelta
basedir = os.path.abspath(os.path.dirname(__file__))

_SECRET_KEY_FROM_ENV = os.environ.get('SECRET_KEY', '')


class Config:
    """Base configuration."""
    SECRET_KEY = _SECRET_KEY_FROM_ENV or secrets.token_hex(32)
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
    COUNSELLOR_PHOTO_UPLOAD_FOLDER = 'app/static/uploads/counsellors'
    ALLOWED_PHOTO_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
    MAX_PHOTO_SIZE = 2 * 1024 * 1024  # 2MB

    TEST_TYPES = [
        "Separation Anxiety Disorder",
        "Social Phobia",
        "Generalised Anxiety Disorder",
        "Panic Disorder",
        "Obsessive Compulsive Disorder",
        "Major Depressive Disorder",
    ]

    APP_BASE_URL = os.environ.get('APP_BASE_URL', '')
    PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '')
    PAYSTACK_PUBLIC_KEY = os.environ.get('PAYSTACK_PUBLIC_KEY', '')
    SUBSCRIPTION_AMOUNT = int(os.environ.get('SUBSCRIPTION_AMOUNT', 10000))  # in pesewas
    SUBSCRIPTION_CURRENCY = os.environ.get('SUBSCRIPTION_CURRENCY', 'GHS')

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'sesa.db')

    SESSION_COOKIE_SECURE = False

    # Bypass real Paystack API — any reference = instant success.
    # Set to False when testing with real Paystack test cards.
    PAYSTACK_TEST_MODE = True


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'sesa.db')
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True
    # Set RATELIMIT_STORAGE_URI=redis://localhost:6379/0 in your .env
    # Without Redis, rate limits reset independently per gunicorn worker.

    # ── Database connection pool ──────────────────────────────────────────────
    # Neon (and other serverless Postgres providers) close idle connections
    # after ~300s. pool_pre_ping tests the connection before every query and
    # silently reconnects if it is dead — prevents the SSL 500 on first request.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'pool_timeout': 20,
        'pool_size': 5,
        'max_overflow': 2,
    }

    @classmethod
    def init_app(cls, app):
        Config.init_app(app) if hasattr(Config, 'init_app') else None
        if not _SECRET_KEY_FROM_ENV:
            raise RuntimeError(
                'SECRET_KEY environment variable is not set. '
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        if len(_SECRET_KEY_FROM_ENV) < 32:
            raise RuntimeError(
                'SECRET_KEY is too short (minimum 32 characters). '
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
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