from flask import Blueprint, render_template, redirect, url_for, flash, session, request, jsonify
from flask_login import login_required, current_user

from app.extensions import db, csrf
from app.models.question import Question
from app.models.test_result import TestResult
from app.forms import FeedbackForm
from app.services.test_service import classify_score, get_next_test, ANSWER_SCORES

test_bp = Blueprint('test', __name__)


@test_bp.route('/<path:test_type>', methods=['GET'])
@login_required
def display_questions(test_type):
    questions = Question.query.filter_by(test_type=test_type).all()
    if not questions:
        flash(f'No questions found for "{test_type}".', 'error')
        return redirect(url_for('main.home'))

    if session.get('current_test') != test_type:
        session['current_test'] = test_type
        session['q_index'] = 0
        session['score'] = 0

    q_index = session['q_index']
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
    )


@test_bp.route('/api/<path:test_type>/next', methods=['POST'])
@csrf.exempt
@login_required
def next_question_api(test_type):
    """JSON API — handles next / back navigation during a test."""
    questions = Question.query.filter_by(test_type=test_type).all()
    question_count = len(questions)

    if not question_count:
        return jsonify({'error': f'No questions for "{test_type}"'}), 404

    if session.get('current_test') != test_type:
        session['current_test'] = test_type
        session['q_index'] = 0
        session['score'] = 0

    q_index = session['q_index']
    data = request.get_json(silent=True) or {}
    answer = data.get('answer')
    action = data.get('action')

    if action == 'back' and q_index > 0:
        session['q_index'] -= 1
        q_index = session['q_index']
        question = questions[q_index]
        return jsonify({
            'question_number': q_index + 1,
            'question_text': question.question_content,
            'progress': round(((q_index + 1) / question_count) * 100, 1),
            'finished': False,
        })

    if answer:
        session['score'] = session.get('score', 0) + ANSWER_SCORES.get(answer, 0)
        session['q_index'] = q_index + 1
        q_index = session['q_index']

    if q_index >= question_count:
        total_score = session.pop('score', 0)
        session.pop('q_index', None)
        session.pop('current_test', None)
        return jsonify({
            'finished': True,
            'redirect': url_for('test.show_results', test_type=test_type, score=total_score),
        })

    question = questions[q_index]
    return jsonify({
        'question_number': q_index + 1,
        'question_text': question.question_content,
        'progress': round(((q_index + 1) / question_count) * 100, 1),
        'finished': False,
    })


@test_bp.route('/result/<path:test_type>/<int:score>')
@login_required
def show_results(test_type, score):
    result = classify_score(test_type, score)
    next_test = get_next_test(test_type)

    questions = Question.query.filter_by(test_type=test_type).all()
    max_score = len(questions) * 3

    form = FeedbackForm(
        test_type=test_type,
        score=score,
        stage=result['stage'],
        message=result['message'],
        max_score=max_score,
    )

    return render_template(
        'test/result.html',
        test_type=test_type,
        score=score,
        max_score=max_score,
        stage=result['stage'],
        message=result['message'],
        score_range=result['score_range'],
        stage_color=result['color'],
        next_test_type=next_test,
        form=form,
    )


@test_bp.route('/submit-result', methods=['POST'])
@login_required
def submit_result():
    form = FeedbackForm()
    if not form.validate_on_submit():
        flash('Could not save result. Please try again.', 'error')
        return redirect(url_for('main.home'))

    test_type = form.test_type.data
    score = int(form.score.data)
    stage = form.stage.data
    max_score = int(form.max_score.data) if form.max_score.data else None

    db.session.add(TestResult(
        test_type=test_type,
        user_id=current_user.id,
        score=score,
        max_score=max_score,
        stage=stage,
        details=stage,
        feedback=form.feedback.data,
    ))
    db.session.commit()
    flash('Your result has been saved.', 'success')

    next_test = get_next_test(test_type)
    if next_test and request.form.get('action') == 'next':
        return redirect(url_for('test.display_questions', test_type=next_test))
    return redirect(url_for('main.home'))