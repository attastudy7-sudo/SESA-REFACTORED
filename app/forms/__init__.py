"""
WTForms form definitions for SESA.
Centralises validation and CSRF protection.
"""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (StringField, PasswordField, SelectField, BooleanField,
                     DateField, TextAreaField, SubmitField, HiddenField)
from wtforms.validators import (DataRequired, Email, Length, EqualTo,
                                Optional, ValidationError)
                                



GENDER_CHOICES = [
    ('', 'Select gender'),
    ('male', 'Male'),
    ('female', 'Female'),
    ('other', 'Other'),
]

LEVEL_CHOICES = [
    ('', 'Select level'),
    ('jhs', 'JHS (Junior High School)'),
    ('shs', 'SHS (Senior High School)'),
    ('university', 'University / Tertiary'),
]

TEST_TYPE_CHOICES = [
    ('', 'Select test type'),
    ('Separation Anxiety Disorder', 'Separation Anxiety Disorder'),
    ('Social Phobia', 'Social / School Phobia'),
    ('Generalised Anxiety Disorder', 'Generalised Anxiety Disorder'),
    ('Panic Disorder', 'Panic Disorder'),
    ('Obsessive Compulsive Disorder', 'Obsessive Compulsive Disorder'),
    ('Major Depressive Disorder', 'Major Depressive Disorder'),
]


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class SchoolLoginForm(FlaskForm):
    admin_name = StringField('Administrator Name', validators=[DataRequired(), Length(min=2, max=100)])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class SignupForm(FlaskForm):
    fname = StringField('First Name', validators=[DataRequired(), Length(min=2, max=100)])
    lname = StringField('Last Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('password', message='Passwords must match.')]
    )
    birthdate = DateField('Birth Date', validators=[DataRequired()])
    gender = SelectField('Gender', choices=GENDER_CHOICES, validators=[DataRequired()])
    level = SelectField('School Level', choices=LEVEL_CHOICES, validators=[Optional()])
    school_name = StringField('School Name', validators=[Optional()])
    submit = SubmitField('Create Account')
    parental_consent = BooleanField(
        'I confirm that my parent or guardian has consented to my participation and understands that assessment results will be shared with my school\'s pastoral care team.',
        validators=[DataRequired(message='Parental consent is required to create an account.')]
    )


class SchoolSignupForm(FlaskForm):
    school_name = StringField('School Name', validators=[DataRequired(), Length(min=3, max=200)])
    admin_name = StringField('Administrator Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[Optional(), Email(), Length(max=120)])
    phone = StringField('Phone Number', validators=[Optional(), Length(max=20)])
    admin_password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[DataRequired(), EqualTo('admin_password', message='Passwords must match.')]
    )
    submit = SubmitField('Register School')


class EditAccountForm(FlaskForm):
    fname = StringField('First Name', validators=[DataRequired(), Length(min=2, max=100)])
    lname = StringField('Last Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=50)])
    school_name = StringField('School Name', validators=[Optional()])
    birthdate = DateField('Birth Date', validators=[Optional()])
    gender = SelectField('Gender', choices=GENDER_CHOICES, validators=[Optional()])
    level = SelectField('School Level', choices=LEVEL_CHOICES, validators=[Optional()])
    is_admin = BooleanField('Grant Admin Privileges')
    is_counsellor = BooleanField('Assign as School Counsellor')
    phone = StringField('Phone Number (for SMS alerts)', validators=[Optional(), Length(max=20)])
    password = PasswordField('New Password (leave blank to keep current)', validators=[Optional(), Length(min=8)])
    submit = SubmitField('Update Account')


class EditSchoolForm(FlaskForm):
    school_name = StringField('School Name', validators=[DataRequired(), Length(min=3, max=200)])
    email = StringField('Email', validators=[Optional(), Email(), Length(max=120)])
    admin_name = StringField('Administrator Name', validators=[DataRequired(), Length(min=2, max=100)])
    admin_password = PasswordField('New Password (leave blank to keep current)', validators=[Optional(), Length(min=8)])
    submit = SubmitField('Update School')


class QuestionForm(FlaskForm):
    test_type = SelectField('Test Type', choices=TEST_TYPE_CHOICES, validators=[DataRequired()])
    question_content = TextAreaField('Question Content', validators=[DataRequired(), Length(min=10)])
    submit = SubmitField('Save Question')


class FeedbackForm(FlaskForm):
    result_id = HiddenField()
    stage     = HiddenField()
    message   = HiddenField()
    max_score = HiddenField()
    feedback = TextAreaField('How are you feeling?', validators=[Optional(), Length(max=1000)])
    submit = SubmitField('Save & Continue')


class CounsellorLoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=50)])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Sign In')


class PasswordResetForm(FlaskForm):
    school_code = StringField('School Access Code', validators=[DataRequired(), Length(min=6, max=8)])
    username = StringField('Your Username', validators=[DataRequired(), Length(min=3, max=50)])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(
        'Confirm New Password',
        validators=[DataRequired(), EqualTo('new_password', message='Passwords must match.')]
    )
    submit = SubmitField('Reset Password')


class CounsellorSignupForm(FlaskForm):
    # ── Personal details ──────────────────────────────────────────────────────
    fname    = StringField('First Name', validators=[DataRequired(), Length(max=100)])
    lname    = StringField('Last Name',  validators=[DataRequired(), Length(max=100)])
    email    = StringField('Email',      validators=[DataRequired(), Email(), Length(max=120)])
    username = StringField('Username',   validators=[DataRequired(), Length(min=3, max=50)])
    phone    = StringField('Phone Number', validators=[DataRequired(), Length(max=20)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    photo = FileField('Profile Photo', validators=[
    FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Images only — jpg, png, or webp.')
])

    # ── Professional details ──────────────────────────────────────────────────
    gpc_number        = StringField('GPC Registration Number',  validators=[Optional(), Length(max=50)])
    gacc_number       = StringField('GACC Membership Number',   validators=[Optional(), Length(max=50)])
    ghana_card_number = StringField('Ghana Card Number',        validators=[DataRequired(), Length(max=30)])
    years_experience  = StringField('Years of Experience',      validators=[DataRequired()])
    specialisations   = StringField('Specialisations',          validators=[DataRequired(), Length(max=300)])
    bio               = TextAreaField('Professional Bio',       validators=[DataRequired(), Length(min=50, max=1000)])

    # ── Consent ───────────────────────────────────────────────────────────────
    confirm_qualified = BooleanField(
        'I confirm I hold a valid counselling qualification recognised in Ghana',
        validators=[DataRequired()]
    )

    submit = SubmitField('Submit Application')