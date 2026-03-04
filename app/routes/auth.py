from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from flask_login import login_user, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.models.account import Accounts
from app.models.school import School
from app.forms import LoginForm, SchoolLoginForm, SignupForm, SchoolSignupForm

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.home'))

    form = LoginForm()
    if form.validate_on_submit():
        user = Accounts.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            if user.is_super_admin:
                return redirect(url_for('admin.dashboard'))
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.home'))
        flash('Invalid username or password. Please try again.', 'error')

    return render_template('auth/login.html', form=form)


@auth_bp.route('/school-login', methods=['GET', 'POST'])
def school_login():
    form = SchoolLoginForm()
    if form.validate_on_submit():
        school = School.query.filter_by(admin_name=form.admin_name.data).first()
        if school and check_password_hash(school.admin_password, form.password.data):
            session.clear()
            session['school_id'] = school.id
            flash(f'Welcome back, {school.admin_name}!', 'success')
            return redirect(url_for('main.school_dashboard', school_id=school.id))
        flash('Invalid administrator name or password.', 'error')

    return render_template('auth/school_login.html', form=form)


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    form = SignupForm()
    if form.validate_on_submit():
        if Accounts.query.filter_by(email=form.email.data).first():
            flash('An account with this email already exists.', 'error')
            return render_template('auth/signup.html', form=form)
        if Accounts.query.filter_by(username=form.username.data).first():
            flash('This username is already taken.', 'error')
            return render_template('auth/signup.html', form=form)

        account = Accounts(
            fname=form.fname.data.strip(),
            lname=form.lname.data.strip(),
            email=form.email.data.strip().lower(),
            username=form.username.data.strip(),
            password=generate_password_hash(form.password.data),
            birthdate=form.birthdate.data,
            gender=form.gender.data,
            level=form.level.data,
        )
        try:
            db.session.add(account)
            db.session.commit()
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception:
            db.session.rollback()
            flash('An error occurred while creating your account. Please try again.', 'error')

    return render_template('auth/signup.html', form=form)


@auth_bp.route('/school-signup', methods=['GET', 'POST'])
def school_signup():
    form = SchoolSignupForm()
    if form.validate_on_submit():
        if School.query.filter_by(school_name=form.school_name.data).first():
            flash('A school with this name is already registered.', 'error')
            return render_template('auth/school_signup.html', form=form)

        school = School(
            school_name=form.school_name.data.strip(),
            admin_name=form.admin_name.data.strip(),
            email=form.email.data.strip().lower() if form.email.data else None,
            admin_password=generate_password_hash(form.admin_password.data),
        )
        try:
            db.session.add(school)
            db.session.commit()
            flash('School registered successfully! Please log in.', 'success')
            return redirect(url_for('auth.school_login'))
        except Exception:
            db.session.rollback()
            flash('An error occurred. Please try again.', 'error')

    return render_template('auth/school_signup.html', form=form)


@auth_bp.route('/logout')
def logout():
    logout_user()
    session.clear()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('main.landing'))
