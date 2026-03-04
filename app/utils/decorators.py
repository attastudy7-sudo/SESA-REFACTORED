from functools import wraps
from flask import g, redirect, url_for, flash, session, abort
from flask_login import current_user


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


def super_admin_required(f):
    """Require the super-admin account (id == 1)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_super_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated
