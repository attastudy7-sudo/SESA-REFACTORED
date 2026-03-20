import logging
from functools import wraps
from flask import redirect, url_for, flash, session, abort, request
from flask_login import current_user

logger = logging.getLogger(__name__)


def school_login_required(f):
    """Require an active school session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        school_id = session.get('school_id')
        if not school_id:
            flash('Please log in as a school administrator.', 'warning')
            return redirect(url_for('auth.school_login'))
        return f(*args, **kwargs)
    return decorated


def counsellor_required(f):
    """Require is_counsellor flag on the logged-in Accounts user.

    - Not authenticated → redirect to login with a clear message.
    - Authenticated but not a counsellor → 403 (they shouldn't be here at all).
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access the counsellor portal.', 'warning')
            return redirect(url_for('auth.counsellor_login'))
        if not current_user.is_counsellor:
            logger.warning(
                'Unauthorised counsellor access | user=%s ip=%s path=%s',
                current_user.username,
                request.remote_addr,
                request.path,
            )
            abort(403)
        return f(*args, **kwargs)
    return decorated


def super_admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_super_admin:
            logger.warning(
                'Unauthorised admin access attempt | user=%s ip=%s path=%s',
                getattr(current_user, 'username', 'anon'),
                request.remote_addr,
                request.path,
            )
            abort(403)
        return f(*args, **kwargs)
    return decorated