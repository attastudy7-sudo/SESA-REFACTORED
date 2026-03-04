import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'change-this-in-production-use-env-var'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    WTF_CSRF_ENABLED = True
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
    # SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        # 'sqlite:///' + os.path.join(basedir, 'sesa_dev.db')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')

    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'sesa.db')
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_SSL_STRICT = True


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
