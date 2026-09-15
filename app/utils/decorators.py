import logging
from functools import wraps
from flask import redirect, url_for, flash, session, abort, request
from flask_login import current_user
from app.models.school import School
from app.models.account import Accounts


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


def subscription_required(f):
    """Block access to paywalled features if the school's subscription is not active."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.is_authenticated and current_user.is_super_admin:
            return f(*args, **kwargs)
        school_id = session.get('school_id')
        if not school_id:
            flash('Please log in as a school administrator.', 'warning')
            return redirect(url_for('auth.school_login'))
        school = School.query.get(school_id)
        if not school or not school.subscription_active:
            flash('This feature requires an active subscription. Please complete your payment to continue.', 'warning')
            return redirect(url_for('main.school_dashboard', school_id=school_id))
        return f(*args, **kwargs)
    return decorated


def student_subscription_required(f):
    """Block students of an unpaid/lapsed school from the student app.

    Place BELOW @login_required so the user is authenticated when this runs.
    Accounts without a school (legacy/admin) are not subject to school billing.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.is_super_admin:
            return f(*args, **kwargs)
        school = School.query.get(current_user.school_id) if current_user.school_id else None
        if school is None or school.subscription_active:
            return f(*args, **kwargs)
        logger.warning(
            'Student blocked: subscription inactive | user=%s school=%s ip=%s path=%s',
            current_user.username, school.school_name, request.remote_addr, request.path,
        )
        from flask_login import logout_user
        logout_user()
        flash("Your school's subscription is not active yet. Please contact your school administrator.", 'warning')
        return redirect(url_for('auth.login'))
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