"""
Flask extensions — initialized here, registered in app factory.
This avoids circular imports throughout the project.
"""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
import os as _os

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri=_os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'),
)

# Configure login manager
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'
