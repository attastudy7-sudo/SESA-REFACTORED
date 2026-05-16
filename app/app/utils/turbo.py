from functools import wraps
from flask import request, render_template

def turbo_frame(frame_id, frame_template, full_template):
    """
    Returns frame_template when request comes from a Turbo Frame with matching id.
    Returns full_template otherwise (direct URL visit, browser back, etc).
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            context = f(*args, **kwargs)
            if isinstance(context, dict):
                if request.headers.get('Turbo-Frame') == frame_id:
                    return render_template(frame_template, **context)
                return render_template(full_template, **context)
            return context  # redirect or Response passed through unchanged
        return wrapped
    return decorator
