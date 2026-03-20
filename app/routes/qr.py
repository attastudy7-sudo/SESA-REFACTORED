import io
from flask import Blueprint, send_file, abort, render_template, current_app, request
from flask_login import login_required
from app.models.school import School
from app.utils.decorators import super_admin_required

qr_bp = Blueprint('qr', __name__)


def _build_join_url(school: School) -> str:
    base = current_app.config.get('APP_BASE_URL') or request.host_url.rstrip('/')
    if school.access_code:
        return f"{base}/join?code={school.access_code}"
    return f"{base}/join"


@qr_bp.route('/<int:school_id>/qr.png')
def school_qr_png(school_id: int):
    import qrcode
    try:
        from qrcode.image.pil import PilImage as ImageFactory
    except ImportError:
        from qrcode.image.pure import PyPNGImage as ImageFactory

    school = School.query.get_or_404(school_id)

    if not school.access_code:
        abort(400)

    join_url = _build_join_url(school)
    box_size = min(max(int(request.args.get('size', 10)), 5), 30)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=4,
    )
    qr.add_data(join_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#1a3a2a", back_color="white", image_factory=ImageFactory)

    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)

    filename = f"SESA_QR_{school.school_name.replace(' ', '_')}.png"
    as_attachment = request.args.get('download', '0') == '1'

    return send_file(buf, mimetype='image/png', as_attachment=as_attachment, download_name=filename)


@qr_bp.route('/<int:school_id>/qr/print')
def school_qr_print(school_id: int):
    school = School.query.get_or_404(school_id)
    join_url = _build_join_url(school)
    qr_url = request.url_root.rstrip('/') + f"/school/{school_id}/qr.png?size=14"
    return render_template('admin/qr_print.html', school=school, join_url=join_url, qr_url=qr_url)


def get_stage_summary():
    from app.extensions import db
    from app.models.test_result import TestResult
    from sqlalchemy import func

    rows = (
        db.session.query(
            func.coalesce(TestResult.stage, TestResult.details, 'Unknown').label('stage'),
            func.count(TestResult.id).label('count'),
        )
        .group_by('stage')
        .all()
    )

    total = sum(r.count for r in rows) or 1
    SEVERITY = {'normal': 0, 'mild': 1, 'elevated': 2, 'moderate': 3, 'clinical': 4}

    result = [
        {'stage': r.stage, 'count': r.count, 'pct': round(r.count / total * 100, 1)}
        for r in rows
    ]
    result.sort(key=lambda x: SEVERITY.get(x['stage'].lower(), 99))
    return result