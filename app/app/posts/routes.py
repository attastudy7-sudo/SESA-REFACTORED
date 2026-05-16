# Import Blueprint before using @bp.route
from app.posts import bp
# Import Flask-Login decorators and current_user before using them
from flask_login import login_required, current_user
from app.services.cheatsheet_pdf_renderer import generate_cheatsheet_pdf
# ── Cheatsheet/Notes PDF Download ─────────────────────────────────────────────

@bp.route('/<int:post_id>/download_cheatsheet_pdf')
@login_required
def download_cheatsheet_pdf(post_id):
    post = Post.query.get_or_404(post_id)
    if post.content_type not in ("cheatsheet", "notes"):
        flash("PDF download only available for notes and cheatsheets.", "warning")
        return redirect(url_for('posts.view', post_id=post.id))
    # Only allow for free or purchased/premium
    if not post.is_free and not current_user.is_premium:
        from app.models import Purchase
        if not Purchase.query.filter_by(user_id=current_user.id, document_id=post.document_id).first():
            flash('Purchase this post to download it.', 'warning')
            return redirect(url_for('payments.checkout', document_id=post.document_id))
    # Get the JSON sidecar
    doc = None
    if post.document and post.document.json_sidecar_path:
        import json
        try:
            with open(post.document.json_sidecar_path, encoding="utf-8") as f:
                doc = json.load(f)
        except Exception:
            flash("Could not load cheatsheet data for PDF.", "danger")
            return redirect(url_for('posts.view', post_id=post.id))
    if not doc:
        flash("No cheatsheet/notes data found for PDF export.", "danger")
        return redirect(url_for('posts.view', post_id=post.id))
    # Generate PDF
    import tempfile
    tmp_pdf = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    pdf_path = generate_cheatsheet_pdf(doc, tmp_pdf.name)
    if not pdf_path:
        flash("PDF generation failed. Please try again later.", "danger")
        return redirect(url_for('posts.view', post_id=post.id))
    tmp_pdf.close()
    return send_from_directory(os.path.dirname(pdf_path), os.path.basename(pdf_path), as_attachment=True, download_name=f"{post.title or 'cheatsheet'}.pdf")
import hashlib
import hmac
import json
import re
from datetime import date
import shutil
import tempfile
import time
import urllib.parse
import os
import uuid
from difflib import SequenceMatcher
from pathlib import Path

import requests as req

from flask import (
    Response, render_template, redirect, stream_with_context,
    url_for, flash, request, current_app, jsonify, send_from_directory,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import psutil

from app import db
from app.posts import bp
from app.forms import CreatePostForm, CommentForm
from app.models import Post, Document, Comment, Like, Subject, Bookmark, Programme
from app.services.ai_service import generate_metadata, generate_academic_bundle
from app.services.document_service import extract_text_from_file
from app.services.resource_generation import analyze_uploaded_resource, save_generated_selection


# ── Rate Limiter ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute;1000/hour"])

def _is_local() -> bool:
    """True when running in local development mode (no Cloudinary keys set)."""
    return not bool(current_app.config.get('CLOUDINARY_CLOUD_NAME'))


def _local_upload_folder() -> str:
    """Absolute path to the local uploads folder. Created if it doesn't exist."""
    folder = os.path.join(current_app.root_path, 'static', 'uploads', 'documents')
    os.makedirs(folder, exist_ok=True)
    return folder


# ── Helpers ───────────────────────────────────────────────────────────────────

def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def _slugify(text: str) -> str:
    text = (text or '').lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def _ensure_unique_slug(model, base_slug: str) -> str:
    slug = base_slug or 'untitled'
    i = 2
    while model.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{i}"
        i += 1
    return slug


def _resolve_or_create_programme(programme_hint: str | None, faculty_hint: str | None) -> Programme:
    programme_name = (programme_hint or '').strip() or 'General Studies'
    faculty_name = (faculty_hint or '').strip() or 'General'

    exact = Programme.query.filter(Programme.name.ilike(programme_name)).first()
    if exact:
        if faculty_name and not exact.faculty:
            exact.faculty = faculty_name
        return exact

    candidates = Programme.query.all()
    best = None
    best_score = 0.0
    for programme in candidates:
        score = SequenceMatcher(None, programme.name.lower(), programme_name.lower()).ratio()
        if score > best_score:
            best_score, best = score, programme
    if best and best_score >= 0.88:
        if faculty_name and not best.faculty:
            best.faculty = faculty_name
        return best

    base_slug = _slugify(programme_name) or 'general-studies'
    programme = Programme(
        name=programme_name,
        slug=_ensure_unique_slug(Programme, base_slug),
        description=f"AI-generated programme for {programme_name}",
        icon='graduation-cap',
        color='#8b5cf6',
        order=999,
        is_active=True,
        faculty=faculty_name,
    )
    db.session.add(programme)
    db.session.flush()
    return programme


def _resolve_or_create_subject(meta: dict, content_payload: dict) -> Subject:
    subject_hint = (meta.get('subject_hint') or '').strip() or 'General Studies'
    programme_hint = (meta.get('programme_hint') or '').strip()
    faculty_hint = (meta.get('faculty_hint') or '').strip()

    exact = Subject.query.filter(Subject.name.ilike(subject_hint)).first()
    chosen = exact
    if not chosen:
        best = None
        best_score = 0.0
        for subject in Subject.query.all():
            score = SequenceMatcher(None, subject.name.lower(), subject_hint.lower()).ratio()
            if score > best_score:
                best_score, best = score, subject
        if best and best_score >= 0.86:
            chosen = best

    if chosen:
        if programme_hint or faculty_hint:
            target_programme = _resolve_or_create_programme(programme_hint, faculty_hint)
            already_linked = chosen.programmes.filter_by(id=target_programme.id).first() is not None
            if not already_linked:
                chosen.programmes.append(target_programme)
        return chosen

    base_slug = _slugify(subject_hint) or 'general-studies'
    subject = Subject(
        name=subject_hint,
        slug=_ensure_unique_slug(Subject, base_slug),
        description=(meta.get('description') or 'AI-generated study subject'),
        icon='book',
        color='#6366f1',
        order=999,
        is_active=True,
    )
    db.session.add(subject)
    db.session.flush()

    programme = _resolve_or_create_programme(programme_hint, faculty_hint)
    subject.programmes.append(programme)
    return subject


def _pricing_allowed() -> bool:
    if current_app.config.get('ALLOW_ALL_PRICING'):
        return True
    return current_user.is_authenticated and current_user.is_admin


def _apply_pricing(document, form):
    if _pricing_allowed() and form.is_paid.data:
        try:
            price = float(form.price.data) if form.price.data else 0.0
        except (ValueError, TypeError):
            price = 0.0
        document.is_paid = True
        document.price   = round(price, 2)
    else:
        document.is_paid = False
        document.price   = 0.0


# ── Storage: upload ───────────────────────────────────────────────────────────

def upload_document(file, form, json_file=None):
    if _is_local():
        return _upload_local(file, form, json_file)
    return _upload_cloudinary(file, form, json_file)


def _upload_local(file, form, json_file=None):
    try:
        file_ext          = file.filename.rsplit('.', 1)[1].lower()
        original_filename = secure_filename(file.filename)
        unique_name       = f"{uuid.uuid4().hex}.{file_ext}"
        upload_folder     = _local_upload_folder()
        save_path         = os.path.join(upload_folder, unique_name)

        file.save(save_path)
        file_size = os.path.getsize(save_path)
        file_url  = f"/static/uploads/documents/{unique_name}"

        document = Document(
            filename=unique_name,
            original_filename=original_filename,
            file_path=file_url,
            file_type=file_ext,
            file_size=file_size,
            is_paid=False,
            price=0.0,
        )

        if json_file and json_file.filename:
            json_ext = 'json'
            json_unique_name = f"{uuid.uuid4().hex}.{json_ext}"
            json_save_path = os.path.join(upload_folder, json_unique_name)
            json_file.save(json_save_path)
            document.json_sidecar_path = f"/static/uploads/documents/{json_unique_name}"

        _apply_pricing(document, form)
        return document

    except Exception as e:
        current_app.logger.error(f"Local upload failed: {e}")
        flash('File upload failed. Please try again.', 'danger')
        return None


def _upload_cloudinary(file, form, json_file=None):
    try:
        import cloudinary.uploader
        file_ext          = file.filename.rsplit('.', 1)[1].lower()
        original_filename = secure_filename(file.filename)

        result = cloudinary.uploader.upload(
            file,
            folder='knowly/documents',
            resource_type='auto',
            type='upload',
            use_filename=True,
            unique_filename=True,
            format=file_ext,
            access_control=[{"access_type": "anonymous"}],
        )

        document = Document(
            filename=result['public_id'],
            original_filename=original_filename,
            file_path=result['secure_url'],
            file_type=file_ext,
            file_size=result.get('bytes', 0),
            is_paid=False,
            price=0.0,
        )

        if json_file and json_file.filename:
            json_result = cloudinary.uploader.upload(
                json_file,
                folder='knowly/documents',
                resource_type='raw',
                type='upload',
                use_filename=True,
                unique_filename=True,
                format='json',
            )
            document.json_sidecar_path = json_result['secure_url']

        _apply_pricing(document, form)
        return document

    except Exception as e:
        current_app.logger.error(f"Cloudinary upload failed: {e}")
        flash('File upload failed. Please try again.', 'danger')
        return None


# ── Storage: delete ───────────────────────────────────────────────────────────

def delete_document(document):
    if _is_local():
        _delete_local(document)
    else:
        _delete_cloudinary(document)


def _delete_local(document):
    try:
        upload_folder = _local_upload_folder()
        file_path     = os.path.join(upload_folder, document.filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        if document.json_sidecar_path:
            json_filename = os.path.basename(document.json_sidecar_path)
            json_path = os.path.join(upload_folder, json_filename)
            if os.path.exists(json_path):
                os.remove(json_path)
    except Exception as e:
        current_app.logger.warning(f"Failed to delete local file '{document.filename}': {e}")


def _cloudinary_public_id_from_url(url: str) -> str:
    """
    Extract the public_id from a Cloudinary secure_url.
    e.g. https://res.cloudinary.com/<cloud>/raw/upload/v123/<public_id>.json
    For raw files the public_id includes the file extension.
    """
    parsed = urllib.parse.urlparse(url)
    parts = parsed.path.split('/')
    # Find the version segment (starts with 'v' followed by digits)
    for i, part in enumerate(parts):
        if part.startswith('v') and part[1:].isdigit():
            return '/'.join(parts[i + 1:])
    # Fallback: take everything after /upload/
    try:
        upload_idx = parts.index('upload')
        return '/'.join(parts[upload_idx + 1:])
    except ValueError:
        return parsed.path.lstrip('/')


def _delete_cloudinary(document):
    try:
        import cloudinary.uploader
        # PDFs uploaded with resource_type='auto' are stored as 'raw' on Cloudinary
        resource_type = (
            'image' if document.file_type in {'png', 'jpg', 'jpeg', 'gif', 'webp'}
            else 'raw'
        )
        cloudinary.uploader.destroy(document.filename, resource_type=resource_type)

        if document.json_sidecar_path:
            json_public_id = _cloudinary_public_id_from_url(document.json_sidecar_path)
            cloudinary.uploader.destroy(json_public_id, resource_type='raw')

    except Exception as e:
        current_app.logger.warning(f"Failed to delete Cloudinary file '{document.filename}': {e}")


# ── Storage: stream / serve ───────────────────────────────────────────────────

def _signed_proxy_token(document_id: int, expires: int, secret: bytes) -> str:
    return hmac.new(secret, f'{document_id}:{expires}'.encode(), hashlib.sha256).hexdigest()


def _stream_document(document, as_attachment: bool = False):
    if _is_local():
        return _stream_local(document, as_attachment)
    return _stream_cloudinary(document, as_attachment)


def _read_sidecar_bytes(sidecar_path: str) -> bytes:
    if sidecar_path.startswith("http://") or sidecar_path.startswith("https://"):
        resp = req.get(sidecar_path, timeout=20)
        resp.raise_for_status()
        return resp.content

    abs_sidecar_path = sidecar_path
    if not os.path.isabs(abs_sidecar_path):
        abs_sidecar_path = os.path.join(
            current_app.root_path,
            "static",
            "uploads",
            "documents",
            os.path.basename(sidecar_path),
        )
    with open(abs_sidecar_path, "rb") as f:
        return f.read()






def _stream_local(document, as_attachment: bool = False):
    try:
        upload_folder = _local_upload_folder()
        file_path     = os.path.join(upload_folder, document.filename)
        if not os.path.exists(file_path):
            current_app.logger.error(f"Local file not found: {file_path}")
            return None, None
        ext_mime = {
            'pdf':  'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'doc':  'application/msword',
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'ppt':  'application/vnd.ms-powerpoint',
            'txt':  'text/plain',
            'png':  'image/png',
            'jpg':  'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif':  'image/gif',
        }
        content_type = ext_mime.get(document.file_type.lower(), 'application/octet-stream')
        def generate():
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):
                    yield chunk
        headers = {}
        if as_attachment:
            safe_name = urllib.parse.quote(document.original_filename or 'download')
            headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{safe_name}"
        headers['Content-Length'] = str(os.path.getsize(file_path))
        return (
            stream_with_context(generate()),
            dict(status=200, content_type=content_type, headers=headers),
        )
    except Exception as e:
        current_app.logger.error(f"Local file serve failed: {e}")
        return None, None


def _stream_cloudinary(document, as_attachment: bool = False):
    try:
        upstream = req.get(document.file_path, stream=True, timeout=20)
        upstream.raise_for_status()
    except Exception as e:
        current_app.logger.error(
            f"Cloudinary fetch failed for document {document.id} ({document.file_path}): {e}"
        )
        return None, None
    content_type = upstream.headers.get('Content-Type', 'application/octet-stream')
    headers = {}
    if as_attachment:
        safe_name = urllib.parse.quote(document.original_filename or 'download')
        headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{safe_name}"
    if 'Content-Length' in upstream.headers:
        headers['Content-Length'] = upstream.headers['Content-Length']
    return (
        stream_with_context(upstream.iter_content(chunk_size=8192)),
        dict(status=200, content_type=content_type, headers=headers),
    )


# ── Quiz helpers ──────────────────────────────────────────────────────────────

def on_post_approved(post) -> None:
    """
    Call this from admin/routes.py after setting post.status = 'approved'.
    Re-reads the stored JSON sidecar, re-validates, and updates QuizData.
    Failure is logged but never blocks the approval.
    """
    if not post.document or not post.document.json_sidecar_path:
        return
    try:
        from app.services.quiz_service import quiz_from_sidecar
        quiz = quiz_from_sidecar(post)
        if quiz:
            current_app.logger.info(
                "Quiz (re-)attached to approved post %s: %d questions, %d marks.",
                post.id, len(json.loads(quiz.questions)), quiz.total_marks
            )
        else:
            current_app.logger.info(
                "Post %s approved — no valid quiz sidecar found.", post.id
            )
    except Exception as exc:
        current_app.logger.warning(
            "Quiz attachment failed for post %s during approval: %s", post.id, exc
        )


def _try_attach_quiz(post, json_bytes: bytes) -> None:
    """
    Validate json_bytes and attach a quiz to post.
    Flashes a user-facing message for both success and failure.
    Never raises.
    """
    try:
        from app.services.quiz_service import validate_and_attach_quiz
        quiz_data, error = validate_and_attach_quiz(post, json_bytes)
        if quiz_data:
            flash(
                f'Quiz attached successfully! '
                f'({quiz_data.total_marks} marks, '
                f'{len(json.loads(quiz_data.questions))} questions)',
                'success'
            )
        else:
            flash(
                f'Your post was submitted but the quiz JSON was rejected: {error} '
                f'The post will be published without a quiz.',
                'warning'
            )
    except Exception as exc:
        current_app.logger.exception(
            "Unexpected error attaching quiz to post %s.", post.id
        )
        flash(
            'Your post was submitted, but the quiz could not be processed '
            'due to an unexpected error.',
            'warning'
        )



@bp.route('/generate-metadata', methods=['POST'])
@login_required
@limiter.limit("10/minute;100/hour")
def api_generate_metadata():
    """AJAX endpoint to generate post metadata via AI."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        content = data.get('content', '')
        mode = data.get('mode', 'text')

        if not content or len(content.strip()) < 3:
            return jsonify({"error": "Content too short to generate metadata."}), 400

        result = generate_metadata(content, mode)
        # Validate output
        if not isinstance(result, dict) or not result.get("title"):
            current_app.logger.error(f"AI metadata output invalid: {result}")
            return jsonify({"error": "AI failed to generate valid metadata. Please try again later."}), 500
        return jsonify(result)
    except Exception as exc:
        current_app.logger.exception(f"AI metadata generation failed: {exc}")
        return jsonify({"error": "AI service error. Please try again later."}), 500


# ── Post CRUD ─────────────────────────────────────────────────────────────────
@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    # Legacy route — redirect to the new library view
    return redirect(url_for('main.library_all_videos'))

    form = CreatePostForm()
    subjects = Subject.query.filter_by(is_active=True).order_by(Subject.order, Subject.name).all()
    form.subject.choices = [(0, 'Select a subject (optional)')] + [(s.id, s.name) for s in subjects]

    # --- Video context support ---
    from_video = request.args.get('from_video')
    video_context = None
    if from_video:
        # Optionally, fetch more context from the video (e.g., transcript, topic, etc.)
        from app.models import VideoLesson
        video = VideoLesson.query.get(from_video)
        if video:
            video_context = {
                'id': video.id,
                'title': video.title,
                'transcript': getattr(video, 'transcript', None),
                'topic': getattr(video, 'topic', None),
                'subject_id': getattr(video, 'subject_id', None),
            }

    if form.validate_on_submit():
        # ── Daily upload limit for free users ────────────────────────────────
        if not current_user.is_premium:
            today_count = Post.query.filter(
                Post.user_id == current_user.id,
                db.func.date(Post.created_at) == date.today()
            ).count()
            if today_count >= current_user.daily_post_limit:
                flash(
                    f'You\'ve used all {current_user.daily_post_limit} uploads for today. '
                    f'Refer a friend to get bonus uploads, or upgrade for unlimited.',
                    'warning'
                )
                return redirect(url_for('posts.create'))

        # ── Determine content_type ────────────────────────────────────────────
        content_type = getattr(form, 'content_type', None)
        content_type = content_type.data if content_type else 'notes'
        from app.routes import VALID_CONTENT_TYPES
        if content_type not in VALID_CONTENT_TYPES:
            content_type = 'notes'

        # Always generate metadata/title via AI, never from uploaded file
        ai_metadata = None
        try:
            # Use the main content field for AI title generation
            ai_metadata = generate_metadata(form.description.data or '', mode=content_type)
        except Exception as exc:
            current_app.logger.error(f"AI metadata generation failed during post creation: {exc}")
        ai_title = (ai_metadata.get('title') if isinstance(ai_metadata, dict) else None) or 'Untitled AI Post'

        post = Post(
            title=ai_title,
            description=form.description.data,
            author=current_user,
            status='approved',
            content_type=content_type,
            flair=form.flair.data or None,
            content_difficulty=form.content_difficulty.data or None,
        )
        db.session.add(post)

        if form.subject.data and form.subject.data != 0:
            post.subject_id = form.subject.data
            subject = db.session.get(Subject, form.subject.data)
            if subject:
                subject.post_count = subject.posts.count() + 1

        json_bytes = None

        if form.document.data and form.document.data.filename:
            file = form.document.data
            if allowed_file(file.filename, current_app.config['ALLOWED_DOCUMENT_EXTENSIONS']):
                json_file = (
                    form.json_sidecar.data
                    if hasattr(form, 'json_sidecar')
                    and form.json_sidecar.data
                    and form.json_sidecar.data.filename
                    else None
                )
                if json_file:
                    json_bytes = json_file.read()
                    json_file.seek(0)
                document = upload_document(file, form, json_file)
                if document:
                    db.session.add(document)
                    db.session.flush()
                    if post not in db.session:
                        db.session.add(post)
                    post.has_document = True
                    post.document_id  = document.id

                    # ── Auto-promote to 'quiz' if a valid quiz sidecar is present
                    if json_bytes:
                        from app.services.quiz_service import validate_and_attach_quiz
                        quiz_data, _ = validate_and_attach_quiz(post, json_bytes)
                        db.session.refresh(post)
                        if quiz_data:
                            try:
                                import json as _j
                                _dt = _j.loads(json_bytes).get("document_type", "quiz")
                                post.content_type = _dt if _dt in ("quiz", "notes", "cheatsheet") else "quiz"
                            except Exception:
                                post.content_type = 'quiz'

        db.session.add(post)
        db.session.commit()

        current_user.update_streak()

        is_generated = request.form.get('source') == 'generated'
        if is_generated and not current_user.is_admin:
            current_app.logger.error(
                "KnowlyGen upload rejected: source=generated but "
                "current_user.id=%s is not admin (is_admin=%s).",
                current_user.id, current_user.is_admin
            )
            db.session.delete(post)
            db.session.commit()
            from flask import abort
            abort(403)

        on_post_approved(post)
        flash('Your post has been published successfully!', 'success')
        return redirect(url_for('posts.view', post_id=post.id))

    return render_template(
        'posts/create.html',
        title='Create Post',
        form=form,
        show_pricing=_pricing_allowed(),
        from_video=from_video,
        video_context=video_context,
    )


@bp.route('/<int:post_id>')
def view(post_id):
    post = Post.query.get_or_404(post_id)

    if post.status != 'approved':
        if not current_user.is_authenticated or current_user.id != post.user_id:
            flash('This post is not available.', 'warning')
            return redirect(url_for('main.index'))

    comment_form = CommentForm()
    page = request.args.get('page', 1, type=int)
    comments = post.comments.order_by(Comment.created_at.desc()).paginate(
        page=page,
        per_page=current_app.config['COMMENTS_PER_PAGE'],
        error_out=False
    )

    from app.models import QuizData, QuizLeaderboard

    quiz_data = None
    has_quiz  = False
    structured_content = None
    structured_type    = None
    leaderboard_entries = []
    user_entry          = None
    total_participants  = 0
    meta               = {}   # always defined; populated below if quiz_data exists

    import json as _json
    quiz_data = QuizData.query.filter_by(post_id=post.id).first()

    if quiz_data:
        meta     = _json.loads(quiz_data.meta) if quiz_data.meta else {}
        doc_type = meta.get("document_type", "") or post.content_type or ""

        if doc_type in ("notes", "cheatsheet"):
            _loaded = _json.loads(quiz_data.questions)
            current_app.logger.debug(
                "Post %s: doc_type=%r, questions type=%s",
                post.id, doc_type, type(_loaded).__name__,
            )
            if isinstance(_loaded, list):
                structured_content = _loaded
                structured_type    = doc_type
            else:
                # questions field contains a bad value (e.g. an old error string).
                # Re-process from sidecar if available so it self-heals.
                current_app.logger.warning(
                    "Post %s quiz_data.questions is not a list (%s) — re-processing sidecar.",
                    post.id, type(_loaded).__name__
                )
                if post.document and post.document.json_sidecar_path:
                    try:
                        from app.services.quiz_service import quiz_from_sidecar
                        quiz_data = quiz_from_sidecar(post)
                        if quiz_data:
                            meta               = _json.loads(quiz_data.meta) if quiz_data.meta else {}
                            structured_content = _json.loads(quiz_data.questions)
                            structured_type    = meta.get("document_type") or post.content_type
                        else:
                            structured_type = doc_type
                    except Exception:
                        current_app.logger.exception("Re-processing sidecar failed for post %s", post.id)
                        structured_type = doc_type
                else:
                    structured_type = doc_type
        elif doc_type == "quiz" or not doc_type:
            has_quiz = True
    else:
        # No QuizData row yet. For notes/cheatsheet posts that have a JSON sidecar
        # (e.g. approved before the pipeline ran, or uploaded directly), attempt to
        # lazily process and attach the sidecar now so content renders immediately.
        if post.content_type in ("notes", "cheatsheet") and post.document and post.document.json_sidecar_path:
            try:
                from app.services.quiz_service import quiz_from_sidecar
                quiz_data = quiz_from_sidecar(post)
                if quiz_data:
                    meta               = _json.loads(quiz_data.meta) if quiz_data.meta else {}
                    structured_content = _json.loads(quiz_data.questions)
                    structured_type    = meta.get("document_type") or post.content_type
                else:
                    current_app.logger.warning(
                        "Lazy sidecar processing returned None for post %s — "
                        "check quiz_service logs for validation errors.",
                        post.id
                    )
                    structured_type = post.content_type
            except Exception:
                current_app.logger.exception("Lazy sidecar processing failed for post %s", post.id)
                structured_type = post.content_type
        elif post.content_type in ("notes", "cheatsheet"):
            structured_type = post.content_type
        elif post.content_type == "quiz":
            has_quiz = True

    if has_quiz:
        leaderboard_entries = (
            QuizLeaderboard.query
            .filter_by(post_id=post.id, is_public=True)
            .order_by(
                QuizLeaderboard.score_pct.desc(),
                QuizLeaderboard.time_taken.asc(),
                QuizLeaderboard.created_at.asc()
            )
            .limit(10)
            .all()
        )
        total_participants = QuizLeaderboard.query.filter_by(post_id=post.id, is_public=True).count()

        if current_user.is_authenticated:
            from app.models import QuizAttempt
            user_entry = (
                QuizAttempt.query
                .filter_by(post_id=post.id, user_id=current_user.id)
                .order_by(
                    QuizAttempt.score_pct.desc(),
                    QuizAttempt.time_taken.asc()
                )
                .first()
            )


    # ── Pick the right template ───────────────────────────────────────────────
    _template_map = {
        'notes':      'posts/view_notes.html',
        'cheatsheet': 'posts/view_cheatsheet.html',
        'quiz':       'posts/view_quiz.html',
    }
    # has_quiz is True when doc_type is "quiz" or empty — map those to view_quiz
    if has_quiz:
        template = 'posts/view_quiz.html'
    else:
        # Only use structured templates when parsed structured content is available.
        # Otherwise, fall back to the generic post view so document preview still works.
        if structured_type in _template_map and structured_content:
            template = _template_map[structured_type]
        else:
            template = 'posts/view.html'

    # meta is always a dict (initialised to {} above; populated from quiz_data.meta when present).
    # quiz_meta is therefore safe to pass to every template regardless of whether quiz_data exists.
    quiz_meta = meta
    # Hoist nested metadata fields to the top level so templates can read them flat
    _nested = quiz_meta.get('metadata', {})
    if _nested:
        quiz_meta = {**quiz_meta, **_nested}


    # Fetch suggested videos for the quiz's subject (and topic if available)
    suggested_videos = []
    if post.subject_id:
        # Try to get topic key from quiz meta or post
        topic_key = None
        if quiz_meta.get('topic_key'):
            topic_key = quiz_meta['topic_key']
        else:
            # fallback: try from post title
            from app.routes import _topic_key_from_text
            topic_key = _topic_key_from_text(post.title)
        # Use the same logic as topic_bundle
        from app.models import Subject
        subject = Subject.query.get(post.subject_id)
        if subject:
            suggested_videos = subject.video_lessons.order_by('created_at').limit(5).all()

    return render_template(
        template,
        title=post.title,
        post=post,
        comment_form=comment_form,
        comments=comments,
        has_quiz=has_quiz,
        quiz_data=quiz_data,
        quiz_meta=quiz_meta,
        structured_content=structured_content,
        structured_type=structured_type,
        leaderboard_entries=leaderboard_entries,
        user_entry=user_entry,
        total_participants=total_participants,
        suggested_videos=suggested_videos,
    )

@bp.route('/<int:post_id>/delete', methods=['POST'])
@login_required
def delete(post_id):
    post = Post.query.get_or_404(post_id)

    if post.author != current_user:
        flash('You cannot delete this post.', 'danger')
        return redirect(url_for('posts.view', post_id=post.id))

    if post.document:
        delete_document(post.document)

    db.session.delete(post)
    db.session.commit()
    flash('Your post has been deleted.', 'success')
    return redirect(url_for('main.index'))


# ── Social actions ────────────────────────────────────────────────────────────

@bp.route('/<int:post_id>/like', methods=['POST'])
@login_required
def like(post_id):
    post = Post.query.get_or_404(post_id)
    existing_like = Like.query.filter_by(user_id=current_user.id, post_id=post.id).first()

    if existing_like:
        db.session.delete(existing_like)
        db.session.commit()
        liked = False
    else:
        db.session.add(Like(user_id=current_user.id, post_id=post.id))
        db.session.commit()
        current_user.update_streak()
        current_user.add_xp(2, apply_streak_multiplier=True, reason='Liked a post')
        liked = True
        # Notify post author (skip self-likes)
        if post.author.id != current_user.id:
            from app.models import create_notification
            create_notification(
                user_id=post.author.id,
                message=f'{current_user.username} liked your post "{post.title[:60]}"',
                notification_type='like',
                link=f'/posts/{post.id}',
            )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'liked': liked,
            'like_count': post.like_count()
        })

    flash('Post liked!' if liked else 'Post unliked.', 'success' if liked else 'info')
    return redirect(request.referrer or url_for('main.index'))


@bp.route('/<int:post_id>/vote', methods=['POST'])
@login_required
def vote(post_id):
    """Up/downvote a post. Body: JSON {value: 1 or -1}."""
    from app.models import Vote
    post = Post.query.get_or_404(post_id)

    data  = request.get_json(silent=True) or {}
    value = data.get('value')
    if value not in (1, -1):
        return jsonify({'error': 'value must be 1 or -1'}), 400

    existing = Vote.query.filter_by(user_id=current_user.id, post_id=post.id).first()

    if existing:
        if existing.value == value:
            # Same vote → undo (toggle off)
            post.score -= existing.value
            db.session.delete(existing)
            user_vote = 0
        else:
            # Switching direction
            post.score += (value - existing.value)
            existing.value = value
            user_vote = value
    else:
        db.session.add(Vote(
            user_id=current_user.id,
            post_id=post.id,
            value=value,
            created_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc)
        ))
        post.score += value
        user_vote = value

    db.session.commit()

    return jsonify({
        'score':     post.score,
        'user_vote': user_vote,
    })

@bp.route('/<int:post_id>/complete-notes', methods=['POST'])
@login_required
def complete_notes(post_id):
    """Award XP when a user finishes reading notes in study mode. Once per post."""
    from app.models import NoteCompletion
    post = Post.query.get_or_404(post_id)

    # Only award XP for notes posts
    if post.content_type != 'notes':
        return jsonify({'status': 'ignored'}), 200

    # Check if already completed
    existing = NoteCompletion.query.filter_by(
        user_id=current_user.id, post_id=post_id
    ).first()

    if existing:
        return jsonify({'status': 'already_completed', 'xp': 0}), 200

    # First completion — award XP
    XP_REWARD = 15
    db.session.add(NoteCompletion(user_id=current_user.id, post_id=post_id))
    current_user.add_xp(XP_REWARD, apply_streak_multiplier=True, reason=f'Notes: {post.title[:50]}')
    current_user.update_streak()
    db.session.commit()

    return jsonify({'status': 'completed', 'xp': XP_REWARD}), 200

@bp.route('/<int:post_id>/bookmark', methods=['POST'])
@login_required
def bookmark(post_id):
    post = Post.query.get_or_404(post_id)
    existing = Bookmark.query.filter_by(user_id=current_user.id, post_id=post.id).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        bookmarked = False
    else:
        db.session.add(Bookmark(user_id=current_user.id, post_id=post.id))
        db.session.commit()
        bookmarked = True

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'bookmarked': bookmarked})

    flash('Post saved!' if bookmarked else 'Bookmark removed.', 'success' if bookmarked else 'info')
    return redirect(request.referrer or url_for('main.index'))

@bp.route('/<int:post_id>/comment', methods=['POST'])
@login_required
def comment(post_id):
    post = Post.query.get_or_404(post_id)
    form = CommentForm()

    if form.validate_on_submit():
        db.session.add(Comment(
            content=form.content.data,
            author=current_user,
            post=post,
        ))
        db.session.commit()
        current_user.update_streak()
        current_user.add_xp(5, apply_streak_multiplier=True, reason=f'Comment: {post.title[:50]}')
        flash('Your comment has been posted!', 'success')
        # Notify post author (skip self-comments)
        if post.author.id != current_user.id:
            from app.models import create_notification
            create_notification(
                user_id=post.author.id,
                message=f'{current_user.username} commented on your post "{post.title[:60]}"',
                notification_type='comment',
                link=f'/posts/{post.id}',
            )

    return redirect(url_for('posts.view', post_id=post.id))


# ── Document routes ───────────────────────────────────────────────────────────



@bp.route('/document/<int:document_id>/preview')
@login_required
def preview_document(document_id):
    document = Document.query.get_or_404(document_id)

    # Temporary bypass: subscription/purchase constraints are disabled.

    previewable = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp',
                   'docx', 'pptx', 'doc', 'ppt', 'xlsx', 'xls'}
    ext = document.file_type.lower()

    if ext not in previewable:
        return jsonify({'error': 'not_previewable'}), 400

    if ext in {'png', 'jpg', 'jpeg', 'gif', 'webp'}:
        return jsonify({'type': 'image', 'url': document.file_path}), 200

    expires = int(time.time()) + 300
    secret  = current_app.config['SECRET_KEY'].encode()
    token   = _signed_proxy_token(document_id, expires, secret)

    proxy_url = url_for(
        'posts.proxy_document',
        document_id=document.id,
        token=token,
        expires=expires,
        _external=True,
    )

    if _is_local():
        return jsonify({'type': 'local', 'url': document.file_path}), 200

    viewer_url = (
        'https://docs.google.com/viewer?embedded=true&url='
        + urllib.parse.quote(proxy_url, safe='')
    )
    return jsonify({'type': 'gdocs', 'viewer_url': viewer_url}), 200


@bp.route('/document/<int:document_id>/proxy')
def proxy_document(document_id):
    token   = request.args.get('token', '')
    expires = request.args.get('expires', '')

    try:
        exp_ts = int(expires)
    except (ValueError, TypeError):
        return 'Bad request', 400

    if int(time.time()) > exp_ts:
        return 'Preview link expired — please click Preview again', 410

    secret   = current_app.config['SECRET_KEY'].encode()
    expected = _signed_proxy_token(document_id, exp_ts, secret)
    if not hmac.compare_digest(expected, token):
        return 'Forbidden', 403

    document = Document.query.get_or_404(document_id)

    body, kwargs = _stream_document(document, as_attachment=False)
    if body is None:
        return 'Could not fetch file from storage', 502

    return Response(body, **kwargs)






@bp.route('/document/<int:document_id>/download')
@login_required
def download_document(document_id):
    from app.models import Document, Purchase
    document = Document.query.get_or_404(document_id)
    post = document.post
    if not post.is_free and not current_user.is_premium:
        if not Purchase.query.filter_by(user_id=current_user.id, document_id=document.id).first():
            flash('Purchase this post to download it.', 'warning')
            return redirect(url_for('payments.checkout', document_id=document.id))
    return _stream_document(document, as_attachment=True)


@bp.route('/analyze-upload', methods=['POST'])
@login_required
@limiter.limit("5/minute;50/hour")
def analyze_upload():
    """
    AJAX endpoint: extract text from uploaded file and generate quiz/notes/cheatsheet.
    Adds error handling, validation, resource logging, and user feedback.
    """
    if 'document' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['document']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    temp_dir = os.path.join(current_app.root_path, 'temp_uploads')
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{uuid.uuid4().hex}_{secure_filename(file.filename)}")
    file.save(temp_path)

    try:
        # Monitor resource usage before AI call
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss
        cpu_before = process.cpu_percent(interval=0.1)

        result = analyze_uploaded_resource(temp_path)
        text = result.get("text", "")

        # Monitor resource usage after AI call
        mem_after = process.memory_info().rss
        cpu_after = process.cpu_percent(interval=0.1)
        current_app.logger.info(f"AI analyze_upload resource usage: mem {mem_before}->{mem_after} bytes, cpu {cpu_before}->{cpu_after}%")

        if not result.get("ok"):
            current_app.logger.warning("Upload analysis failed: %s", result.get("error"))
            return jsonify({
                "ai_available": False,
                "message": "AI generation unavailable at the moment.",
                "reason": str(result.get("error")),
                "extracted_text": text[:2000],
                "text_length": len(text)
            })

        bundle = result["bundle"]

        # Validate and sanitize AI output
        missing = [
            k for k in ['metadata', 'quiz', 'notes', 'cheatsheet']
            if k not in bundle or not isinstance(bundle.get(k), dict)
        ]
        if missing:
            current_app.logger.warning("AI bundle structure missing keys: %s", missing)
            return jsonify({
                "ai_available": False,
                "message": "AI returned incomplete content.",
                "missing_keys": missing,
                "extracted_text": text[:2000],
                "text_length": len(text)
            })

        # Fallback: if output is not valid, return safe error
        if bundle.get('is_academic') is False:
            return jsonify({"ai_available": True, **bundle})

        # Check if any component silently failed
        quiz = bundle.get('quiz', {})
        if isinstance(quiz, dict) and quiz.get('_generation_failed'):
            current_app.logger.warning("Quiz generation failed for all providers, returning partial bundle.")
            bundle['quiz'] = None
            bundle['quiz_failed'] = True

        return jsonify({"ai_available": True, **bundle})

    except Exception as exc:
        current_app.logger.exception(f"AI analysis failed: {exc}")
        return jsonify({
            "ai_available": False,
            "message": "AI analysis failed. Please try again later.",
            "reason": str(exc),
            "extracted_text": text[:2000] if 'text' in locals() else None
        }), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


# ── AI Health Check Endpoint ────────────────────────────────────────────────
@bp.route('/ai-health', methods=['GET'])
def ai_health():
    """Health check endpoint for AI service."""
    try:
        # Simple check: can we call generate_metadata with a trivial prompt?
        result = generate_metadata("health check", mode="text")
        if isinstance(result, dict) and result.get("title"):
            return jsonify({"ok": True, "ai": "available"})
        return jsonify({"ok": False, "ai": "unavailable", "detail": str(result)})
    except Exception as exc:
        current_app.logger.exception(f"AI health check failed: {exc}")
        return jsonify({"ok": False, "ai": "error", "detail": str(exc)}), 500


@bp.route('/save-selection', methods=['POST'])
@login_required
def save_selection():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    selection_type = data.get('type')
    content = data.get('content')
    meta = data.get('metadata', {})
    bundle = data.get('bundle', {})
    content_difficulty = data.get('content_difficulty', '')

    if not selection_type or not content:
        return jsonify({"error": "Incomplete selection data"}), 400

    try:
        post, error = save_generated_selection(
            selection_type=selection_type,
            content=content,
            metadata=meta,
            user=current_user,
            subject_id=meta.get('subject_id'),
            bundle=bundle,
            content_difficulty=content_difficulty,
        )
        if error or not post:
            raise RuntimeError(error or 'Failed to save generated selection')

        return jsonify({
            "success": True,
            "post_id": post.id,
            "redirect_url": url_for('posts.view', post_id=post.id)
        })
    except Exception as exc:
        current_app.logger.error("Save selection failed: %s", exc)
        return jsonify({"error": str(exc)}), 500