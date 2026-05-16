from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, PasswordField, BooleanField, SubmitField, TextAreaField, SelectField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError, Optional
from app.models import User



class LoginForm(FlaskForm):
    """Form for user login."""
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Log In')


class SignupForm(FlaskForm):
    """Form for user registration."""
    username = StringField('Username', validators=[
        DataRequired(),
        Length(min=3, max=80, message='Username must be between 3 and 80 characters')
    ])
    email = StringField('Email', validators=[DataRequired(), Email()])
    nickname = StringField('Nickname', validators=[
        DataRequired(),
        Length(min=2, max=120)
    ])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=6, message='Password must be at least 6 characters')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Sign Up')
    
    def validate_username(self, username):
        """Check if username already exists."""
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Username already taken. Please choose a different one.')
    
    def validate_email(self, email):
        """Check if email already exists."""
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email already registered. Please use a different one.')


class EditProfileForm(FlaskForm):
    """Form for editing user profile."""
    nickname = StringField('Nickname', validators=[Length(max=120)])
    bio = TextAreaField('Bio', validators=[Length(max=500)])
    profile_picture = FileField('Profile Picture', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')
    ])
    submit = SubmitField('Update Profile')
    school = StringField('School / University', validators=[Optional(), Length(max=200)])      # add this
    programme = StringField('Programme / Course of Study', validators=[Optional(), Length(max=200)])  # add this


class CreatePostForm(FlaskForm):
    """Form for creating / editing a post."""

    title = StringField('Title', validators=[
        DataRequired(),
        Length(min=3, max=200, message='Title must be between 3 and 200 characters')
    ])
    description = TextAreaField('Description', validators=[
        Optional(),
        Length(max=5000, message='Description too long')
    ])
    subject = SelectField('Subject/Category', coerce=int, validators=[Optional()])

    # Flair — Reddit-style post type tag
    flair = SelectField(
        'Flair',
        choices=[
            ('',             'No flair'),
            ('discussion',   'Discussion'),
            ('question',     'Question'),
            ('resource',     'Resource'),
            ('tip',          'Tip'),
            ('rant',         'Rant'),
            ('announcement', 'Announcement'),
        ],
        default='',
        validators=[Optional()],
    )

    # Content type — display label only, tells the user what they're getting
    content_type = SelectField(
        'Content Type',
        choices=[
            ('notes',      'Notes'),
            ('cheatsheet', 'Cheatsheet'),
            ('quiz',       'Quiz'),
            ('flashcards', 'Flashcards'),
        ],
        default='notes',
        validators=[DataRequired()],
    )

    # Content difficulty — Beginner/Intermediate/Advanced
    content_difficulty = SelectField(
        'Difficulty Level',
        choices=[
            ('',        'Not specified'),
            ('Beginner',      'Beginner'),
            ('Intermediate', 'Intermediate'),
            ('Advanced',      'Advanced'),
        ],
        default='',
        validators=[Optional()],
    )

    document = FileField('Upload Document (Optional)', validators=[
        FileAllowed(['pdf', 'docx', 'pptx', 'txt', 'doc', 'ppt'],
                   'Only PDF, DOCX, PPTX, and TXT files allowed!')
    ])
    json_sidecar = FileField('Upload Quiz JSON Sidecar (Optional)', validators=[
        FileAllowed(['json'], 'Only JSON files allowed!')
    ])
    is_paid = BooleanField('Paid Document (Future Feature)')
    price   = StringField('Price (Future Feature)', validators=[Optional()])
    submit  = SubmitField('Create Post')


class CommentForm(FlaskForm):
    """Form for adding a comment."""
    content = TextAreaField('Comment', validators=[
        DataRequired(),
        Length(min=1, max=500, message='Comment must be between 1 and 500 characters')
    ])
    submit = SubmitField('Post Comment')


class SearchForm(FlaskForm):
    """Form for searching users and documents."""
    query = StringField('Search', validators=[DataRequired()])
    submit = SubmitField('Search')


class SubjectForm(FlaskForm):
    """Form for creating/editing subjects (admin only)."""
    name = StringField('Subject Name', validators=[
        DataRequired(),
        Length(min=2, max=100, message='Name must be between 2 and 100 characters')
    ])
    description = TextAreaField('Description', validators=[
        Length(max=500, message='Description too long')
    ])
    icon = StringField('Icon (Font Awesome)', validators=[
        Length(max=50)
    ])
    color = StringField('Color (Hex)', validators=[
        Length(min=7, max=7, message='Must be a valid hex color (e.g., #6366f1)')
    ])
    order = StringField('Display Order', validators=[Optional()])
    is_active = BooleanField('Active')
    submit = SubmitField('Save Subject')


class ProgrammeForm(FlaskForm):
    """Form for creating/editing programmes (admin only)."""
    name = StringField('Programme Name', validators=[
        DataRequired(),
        Length(min=2, max=200, message='Name must be between 2 and 200 characters')
    ])
    description = TextAreaField('Description', validators=[
        Length(max=1000, message='Description too long')
    ])
    icon = StringField('Icon (Font Awesome)', validators=[
        Length(max=50)
    ])
    color = StringField('Color (Hex)', validators=[
        Length(min=7, max=7, message='Must be a valid hex color (e.g., #8b5cf6)')
    ])
    order = StringField('Display Order', validators=[Optional()])
    is_active = BooleanField('Active')
    faculty = StringField('Faculty', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Save Programme')

class BulkEmailForm(FlaskForm):
    """Form for sending bulk emails to users."""
    subject = StringField('Subject', validators=[DataRequired()])
    body = TextAreaField('Message', validators=[DataRequired()])
    send_to = SelectField('Send To', choices=[('all', 'All Users'), ('selected', 'Selected Users')], default='all')
    selected_emails = StringField('Selected Emails')
    submit = SubmitField('Send Email')

class PasswordResetRequestForm(FlaskForm):
    """Request a password reset link by email."""
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Link')


class PasswordResetForm(FlaskForm):
    """Set a new password using a valid reset token."""
    password = PasswordField('New Password', validators=[
        DataRequired(),
        Length(min=6, message='Password must be at least 6 characters')
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Reset Password')