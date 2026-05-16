from functools import wraps
from flask import abort
from flask_login import current_user

from .emails import *


def admin_required(f):
    """
    Decorator that requires the current user to be both authenticated
    AND flagged as an admin (user.is_admin == True).

    Usage:
        @bp.route('/admin/something')
        @admin_required
        def some_admin_view():
            ...

    Returns 403 Forbidden for any user who is not an admin.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function