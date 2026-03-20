"""
Counsellor registration and public directory routes.
"""
import logging
from flask import Blueprint, render_template, redirect, url_for, flash, request
from werkzeug.security import generate_password_hash

from app.extensions import db, limiter
from app.models.account import Accounts
from app.models.counsellor_profile import CounsellorProfile
from app.forms import CounsellorSignupForm

counsellor_signup_bp = Blueprint('counsellor_signup', __name__)
logger = logging.getLogger(__name__)


@counsellor_signup_bp.route('/counsellor/apply', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def counsellor_apply():
    """Counsellor self-registration. Account sits as pending until admin verifies."""
    form = CounsellorSignupForm()

    if form.validate_on_submit():
        # ── Duplicate checks ──────────────────────────────────────────────────
        if Accounts.query.filter_by(email=form.email.data.strip().lower()).first():
            form.email.errors.append('An account with this email already exists.')
            return render_template('auth/counsellor_apply.html', form=form)

        if Accounts.query.filter_by(username=form.username.data.strip()).first():
            form.username.errors.append('This username is already taken.')
            return render_template('auth/counsellor_apply.html', form=form)

        try:
            years = int(form.years_experience.data)
        except (ValueError, TypeError):
            form.years_experience.errors.append('Please enter a valid number.')
            return render_template('auth/counsellor_apply.html', form=form)

        try:
            # ── Create base account ───────────────────────────────────────────
            account = Accounts(
                fname=form.fname.data.strip(),
                lname=form.lname.data.strip(),
                email=form.email.data.strip().lower(),
                username=form.username.data.strip(),
                password=generate_password_hash(form.password.data),
                phone=form.phone.data.strip(),
                is_counsellor=True,
            )
            db.session.add(account)
            db.session.flush()  # get account.id before creating profile

            # ── Create counsellor profile ─────────────────────────────────────
            profile = CounsellorProfile(
                account_id=account.id,
                gpc_number=form.gpc_number.data.strip() if form.gpc_number.data else None,
                gacc_number=form.gacc_number.data.strip() if form.gacc_number.data else None,
                ghana_card_number=form.ghana_card_number.data.strip(),
                years_experience=years,
                specialisations=form.specialisations.data.strip(),
                bio=form.bio.data.strip(),
                verification_status='pending',
            )
            db.session.add(profile)
            db.session.commit()

            logger.info(
                'Counsellor application submitted | username=%s ip=%s',
                account.username, request.remote_addr,
            )

            flash(
                'Your application has been submitted successfully. '
                'You will be notified once your credentials have been verified.',
                'success'
            )
            return redirect(url_for('counsellor_signup.counsellor_pending'))

        except Exception as e:
            db.session.rollback()
            logger.error('Counsellor signup error | error=%s', e)
            flash('An error occurred while submitting your application. Please try again.', 'error')

    return render_template('auth/counsellor_apply.html', form=form)


@counsellor_signup_bp.route('/counsellor/pending')
def counsellor_pending():
    """Holding page shown after signup and on login for unverified counsellors."""
    return render_template('auth/counsellor_pending.html')


@counsellor_signup_bp.route('/counsellors')
def counsellor_directory():
    """Public directory of verified counsellors."""
    counsellors = (
        db.session.query(CounsellorProfile, Accounts)
        .join(Accounts, Accounts.id == CounsellorProfile.account_id)
        .filter(CounsellorProfile.verification_status == 'verified')
        .order_by(Accounts.fname)
        .all()
    )
    return render_template('main/counsellor_directory.html', counsellors=counsellors)