from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
import logging

from app.extensions import db, csrf
from app.models.question import Question
from app.models.test_result import TestResult
from app.models.account import Accounts
from app.models.quiz_session import QuizSession
from app.forms import FeedbackForm
from app.services.test_service import classify_score, get_next_test, ANSWER_SCORES
from app.services.sms_service import send_clinical_alert
from app.models.audit_log import audit

test_bp = Blueprint('test', __name__)
logger = logging.getLogger(__name__)
MHAP_HELPLINE = '0800 111 222'  # Ghana Mental Health Authority helpline


@test_bp.route('/<path:test_type>', methods=['GET'])
@login_required
def display_questions(test_type):
    questions = Question.query.filter_by(test_type=test_type).order_by(Question.order, Question.id).all()
    if not questions:
        flash(f'No questions found for "{test_type}".', 'error')
        return redirect(url_for('main.home'))

    # 7-day cooldown — prevent score gaming and rumination
    from datetime import datetime, timedelta, timezone
    cooldown_days = 7
    cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
    recent = TestResult.query.filter(
        TestResult.user_id == current_user.id,
        TestResult.test_type == test_type,
        TestResult.taken_at >= cutoff,
    ).order_by(TestResult.taken_at.desc()).first()
    if recent:
        taken_at = recent.taken_at
        if taken_at.tzinfo is None:
            taken_at = taken_at.replace(tzinfo=timezone.utc)
        days_ago = (datetime.now(timezone.utc) - taken_at).days
        days_left = cooldown_days - days_ago
        flash(
            f'You completed this assessment {days_ago} day(s) ago. '
            f'Please wait {days_left} more day(s) before retaking it.',
            'warning'
        )
        return redirect(url_for('main.home'))

    # Get or create a DB-backed quiz session (replaces cookie session)
    quiz_session, _ = QuizSession.get_or_create(current_user.id, test_type)
    db.session.commit()

    q_index = quiz_session.q_index
    question = questions[q_index]
    question_count = len(questions)
    progress = round(((q_index + 1) / question_count) * 100, 1)

    return render_template(
        'test/test.html',
        question=question,
        curr_question=q_index + 1,
        question_count=question_count,
        test_type=test_type,
        progress=progress,
        is_assessment=True,
    )


@test_bp.route('/api/<path:test_type>/next', methods=['POST'])
@csrf.exempt
@login_required
def next_question_api(test_type):
    """JSON API — handles next / back navigation during a test."""
    questions = Question.query.filter_by(test_type=test_type).order_by(Question.order, Question.id).all()
    question_count = len(questions)

    if not question_count:
        return jsonify({'error': f'No questions for "{test_type}"'}), 404

    # Load DB-backed quiz session
    quiz_session = QuizSession.query.filter_by(
        user_id=current_user.id,
        test_type=test_type,
    ).first()

    if not quiz_session or quiz_session.is_expired:
        # Session gone or expired — restart from scratch
        if quiz_session:
            db.session.delete(quiz_session)
            db.session.flush()
        quiz_session = QuizSession(user_id=current_user.id, test_type=test_type)
        db.session.add(quiz_session)
        db.session.flush()

    q_index = quiz_session.q_index
    data = request.get_json(silent=True) or {}
    answer = data.get('answer')
    action = data.get('action')

    if action == 'back' and q_index > 0:
        quiz_session.q_index -= 1
        db.session.commit()
        q_index = quiz_session.q_index
        question = questions[q_index]
        return jsonify({
            'question_number': q_index + 1,
            'question_text': question.question_content,
            'progress': round(((q_index + 1) / question_count) * 100, 1),
            'finished': False,
        })

    if answer:
        quiz_session.score = quiz_session.score + ANSWER_SCORES.get(answer, 0)
        quiz_session.q_index = q_index + 1
        db.session.commit()
        q_index = quiz_session.q_index

    if q_index >= question_count:
        total_score = quiz_session.score

        # Clean up the in-progress session row
        QuizSession.delete_for(current_user.id, test_type)

        # Save result to DB — score never travels through the URL
        max_score = question_count * 3
        if max_score == 0:
            logger.error('max_score is 0 for test_type=%s — aborting result save', test_type)
            return jsonify({'error': 'Assessment configuration error. Please contact support.'}), 500
        result_data = classify_score(test_type, total_score, max_score)

        result_obj = TestResult(
            test_type=test_type,
            user_id=current_user.id,
            score=total_score,
            max_score=max_score,
            stage=result_data['stage'],
        )
        db.session.add(result_obj)
        db.session.flush()

        _fire_clinical_alerts(result_obj, result_data['stage'])

        audit(
            'RESULT_SAVED',
            actor_id=current_user.id,
            school_id=current_user.school_id,
            target_id=result_obj.id,
            ip_address=request.remote_addr,
            detail=f'Completed {test_type} assessment',
        )
        db.session.commit()

        return jsonify({
            'finished': True,
            'redirect': url_for('test.show_results', result_id=result_obj.id),
        })

    question = questions[q_index]
    return jsonify({
        'question_number': q_index + 1,
        'question_text': question.question_content,
        'progress': round(((q_index + 1) / question_count) * 100, 1),
        'finished': False,
    })


@test_bp.route('/result/<int:result_id>')
@login_required
def show_results(result_id):
    """Score is never in the URL. Load the persisted row and verify ownership."""
    result_obj = TestResult.query.filter_by(
        id=result_id, user_id=current_user.id
    ).first_or_404()

    result = classify_score(result_obj.test_type, result_obj.score, result_obj.max_score)
    next_test = get_next_test(result_obj.test_type)

    from datetime import datetime, timedelta, timezone
    from app.models.assessment_type import AssessmentType
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=now.weekday())  # Monday
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    total_assessments = AssessmentType.query.filter_by(is_active=True).count()
    completed_this_week = (TestResult.query
        .filter(
            TestResult.user_id == current_user.id,
            TestResult.taken_at >= week_start,
        )
        .with_entities(TestResult.test_type)
        .distinct()
        .count())
    days_until_reset = 7 - now.weekday()  # days until Monday

    counsellor = None
    if current_user.school_id:
        counsellor = Accounts.query.filter_by(
            school_id=current_user.school_id,
            is_counsellor=True,
        ).first()

    form = FeedbackForm(
        result_id=result_id,
        stage=result['stage'],
        message=result['message'],
        max_score=result_obj.max_score,
    )

    return render_template(
        'test/result.html',
        result_obj=result_obj,
        test_type=result_obj.test_type,
        score=result_obj.score,
        max_score=result_obj.max_score,
        stage=result['stage'],
        message=result['message'],
        score_range=result['score_range'],
        stage_color=result['color'],
        next_test_type=next_test,
        form=form,
        counsellor=counsellor,
        mhap_helpline=MHAP_HELPLINE,
        completed_this_week=completed_this_week,
        total_assessments=total_assessments,
        days_until_reset=days_until_reset,
    )


@test_bp.route('/submit-feedback', methods=['POST'])
@login_required
def submit_feedback():
    """Attach optional free-text feedback to an already-saved result."""
    form = FeedbackForm()
    if not form.validate_on_submit():
        flash('Could not save feedback. Please try again.', 'error')
        return redirect(url_for('main.home'))

    try:
        result_id = int(form.result_id.data)
    except (TypeError, ValueError):
        flash('Invalid result reference.', 'error')
        return redirect(url_for('main.home'))

    result_obj = TestResult.query.filter_by(
        id=result_id, user_id=current_user.id
    ).first_or_404()

    if form.feedback.data:
        result_obj.feedback = form.feedback.data
        db.session.commit()

    flash('Your result has been saved.', 'success')

    next_test = get_next_test(result_obj.test_type)
    if next_test and request.form.get('action') == 'next':
        return redirect(url_for('test.display_questions', test_type=next_test))
    return redirect(url_for('main.home'))


# ── Internal helper ───────────────────────────────────────────────────────────

def _fire_clinical_alerts(result_obj, stage):
    """SMS all counsellors at the student's school when a Clinical result is saved."""
    if 'clinical' not in stage.lower():
        logger.info('Result saved | result_id=%s school_id=%s',
                    result_obj.id, current_user.school_id)
        return

    logger.warning('Clinical stage recorded | result_id=%s school_id=%s',
                   result_obj.id, current_user.school_id)

    if not current_user.school_id:
        return

    counsellors = Accounts.query.filter_by(
        school_id=current_user.school_id,
        is_counsellor=True,
    ).all()
    import threading
    for counsellor in counsellors:
        if counsellor.phone:
            t = threading.Thread(
                target=send_clinical_alert,
                kwargs={
                    'counsellor_phone': counsellor.phone,
                    'student_id': current_user.id,
                    'school_name': (
                        current_user.school.school_name
                        if current_user.school else 'your school'
                    ),
                },
                daemon=True,
            )
            t.start()