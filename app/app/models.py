# Imports (ensure db, datetime, timezone are available before models)
from app import db, login_manager
from flask import url_for
from flask_login import UserMixin
from datetime import datetime, timezone, date, timedelta
from werkzeug.security import check_password_hash, generate_password_hash

import urllib.parse
import secrets

# ── Video Engagement Models ─────────────────────────────────────────────





# ...existing code...

# ── Video Engagement Models ─────────────────────────────────────────────
class VideoLike(db.Model):
    __tablename__ = 'video_like'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=False)
    value = db.Column(db.SmallInteger, nullable=False, default=1)  # 1=like, -1=dislike
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user = db.relationship('User', backref='video_likes')
    video = db.relationship('VideoLesson', backref=db.backref('likes', lazy='dynamic', cascade='all, delete-orphan'))
    __table_args__ = (db.UniqueConstraint('user_id', 'video_id', name='unique_video_like'),)

class VideoBookmark(db.Model):
    __tablename__ = 'video_bookmark'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user = db.relationship('User', backref='video_bookmarks')
    video = db.relationship('VideoLesson', backref=db.backref('bookmarks', lazy='dynamic', cascade='all, delete-orphan'))
    __table_args__ = (db.UniqueConstraint('user_id', 'video_id', name='unique_video_bookmark'),)

class VideoComment(db.Model):
    __tablename__ = 'video_comment'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    video_id = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user = db.relationship('User', backref='video_comments')
    video = db.relationship('VideoLesson', backref=db.backref('comments', lazy='dynamic', cascade='all, delete-orphan'))

class VideoView(db.Model):
    __tablename__ = 'video_view'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=True)  # nullable for anonymous
    video_id = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=False)
    viewed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user = db.relationship('User', backref='video_views')
    video = db.relationship('VideoLesson', backref=db.backref('views', lazy='dynamic', cascade='all, delete-orphan'))

@login_manager.user_loader
def load_user(user_id):
    """Required by Flask-Login to load a user from the session."""

    from app import db
    return db.session.get(User, int(user_id))


# Association table for many-to-many follow relationship
followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('profiles.id'), primary_key=True),
    db.Column('followed_id', db.Integer, db.ForeignKey('profiles.id'), primary_key=True)
)


# Palette cycled deterministically by username so each user always gets the same color
_AVATAR_COLORS = [
    "#667eea", "#764ba2", "#f093fb", "#f5576c",
    "#4facfe", "#43e97b", "#fa709a", "#a18cd1",
]


def _initials_avatar_url(username: str, nickname: str | None) -> str:
    """
    Generate a data-URI SVG avatar from the user's initials.
    Requires no files, no CDN, and works in any <img src="">.
    """
    if nickname and nickname.strip():
        parts = nickname.strip().split()
        initials = (parts[0][0] + parts[-1][0]).upper() if len(parts) >= 2 else parts[0][:2].upper()
    else:
        initials = username[:2].upper()

    color = _AVATAR_COLORS[sum(ord(c) for c in username) % len(_AVATAR_COLORS)]

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">'
        f'<circle cx="100" cy="100" r="100" fill="{color}"/>'
        f'<text x="100" y="100" font-family="Inter,Arial,sans-serif" font-size="80" '
        f'font-weight="700" fill="white" text-anchor="middle" '
        f'dominant-baseline="central" letter-spacing="-2">{initials}</text>'
        f'</svg>'
    )
    return f"data:image/svg+xml,{urllib.parse.quote(svg, safe='')}"

class User(UserMixin, db.Model):

    """
    User model - represents a student on the platform.
    Table renamed to 'profiles' to avoid Turso/SQL reserved word conflicts.
    """
    __tablename__ = 'profiles'

    id = db.Column(db.Integer, primary_key=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)

    # Profile identity
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)  # NULL = Google-only account

    # Profile information
    nickname = db.Column(db.String(120), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    profile_picture = db.Column(db.String(500), default='default.jpg', nullable=True)
    school = db.Column(db.String(200), nullable=True)
    programme = db.Column(db.String(200), nullable=True)
    onboarding_skipped = db.Column(db.Boolean, default=False, nullable=False)

    # Account metadata
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=True)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    # Premium access
    can_access_all_content = db.Column(db.Boolean, default=False, nullable=False)

    # Subscription information
    subscription_tier = db.Column(db.String(20), default='free', nullable=False)
    subscription_start_date = db.Column(db.DateTime, nullable=True)
    subscription_end_date = db.Column(db.DateTime, nullable=True)
    free_quiz_attempts = db.Column(db.Integer, default=3, nullable=False)
    free_quiz_attempts_reset_date = db.Column(db.Date, nullable=True)

    # Streak tracking
    last_activity_date = db.Column(db.Date, nullable=True)
    current_streak = db.Column(db.Integer, default=0, nullable=False)
    longest_streak = db.Column(db.Integer, default=0, nullable=False)

    # XP / Level system
    xp_points = db.Column(db.Integer, default=0, nullable=False)

    @property
    def name(self):
        """Convenience property for templates."""
        return self.nickname or self.username

    @property
    def full_name(self):
        return self.nickname

    @full_name.setter
    def full_name(self, value):
        self.nickname = value
    xp_level = db.Column(db.Integer, default=1, nullable=False)
    xp_title = db.Column(db.String(50), nullable=True)

    # Referral system fields (kept for compatibility)
    referred_by_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=True)
    referral_code = db.Column(db.String(12), unique=True, nullable=True, index=True)
    referral_bonus_uploads = db.Column(db.Integer, default=0, nullable=False)
    referral_bonus_expires = db.Column(db.Date, nullable=True)

    # Self-referential relationship for referrals
    referrals = db.relationship('User', backref=db.backref('referrer', remote_side=[id]), lazy='dynamic')

    # Google OAuth profile sync flag
    needs_google_profile_sync = db.Column(db.Boolean, default=False, nullable=False)

    # Aura (virtual currency) system
    aura_balance = db.Column(db.Integer, default=0, nullable=False)

    # Relationships
    # Real-time activity tracking (one-to-one)
    current_activity = db.relationship('UserActivity', backref='user', uselist=False, cascade='all, delete-orphan')
    # Moderation log relationship
    moderation_history = db.relationship('ModerationLog', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    # Posts (adds Post.author backref)
    posts = db.relationship('Post', backref='author', lazy='dynamic', cascade='all, delete-orphan')
    # Comments (adds Comment.author backref)
    comments = db.relationship('Comment', backref='author', lazy='dynamic', cascade='all, delete-orphan')
    # Following/followers
    following = db.relationship(
        'User',
        secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'),
        lazy='dynamic',
        overlaps="followers,following"
    )
    # Subscriptions
    subscriptions = db.relationship(
        'Subscription', back_populates='user',
        lazy='dynamic', cascade='all, delete-orphan',
        order_by='Subscription.created_at.desc()'
    )

    # ── Methods ──────────────────────────────────────────────────────────────────
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def follow(self, user):
        if not self.is_following(user):
            self.following.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.following.remove(user)

    def is_following(self, user):
        return self.following.filter(followers.c.followed_id == user.id).count() > 0

    def followers_count(self):
        return self.followers.count()

    def following_count(self):
        return self.following.count()

    def update_streak(self):
        today = date.today()
        if self.last_activity_date is None:
            self.current_streak = 1
        elif self.last_activity_date == today:
            return
        elif self.last_activity_date == today - timedelta(days=1):
            self.current_streak += 1
        else:
            self.current_streak = 1
        self.last_activity_date = today
        if self.current_streak > self.longest_streak:
            self.longest_streak = self.current_streak
        db.session.commit()

    @property
    def streak_days(self):
        return self.current_streak

    def add_xp(self, points, apply_streak_multiplier=False, reason=None):
        if apply_streak_multiplier and self.current_streak > 0:
            multiplier = 1 + (self.current_streak * 0.05)
            points = round(points * multiplier)
        self.xp_points += points
        self.aura_balance = (self.aura_balance or 0) + points  # keep in sync
        tx = AuraTransaction(
            user_id=self.id,
            amount=points,
            reason=reason or 'Aura earned'
        )
        db.session.add(tx)
        db.session.commit()
    
    def get_level(self):
        if self.xp_points < 1000:
            return 1
        elif self.xp_points < 5000:
            return 2
        elif self.xp_points < 15000:
            return 3
        else:
            return 4
    
    def get_title(self):
        level = self.get_level()
        titles = {1: "Beginner", 2: "Intermediate", 3: "Advanced", 4: "Expert"}
        return titles.get(level, "Novice")
    
    def get_next_level_xp(self):
        levels = [1000, 5000, 15000, 25000]
        for threshold in levels:
            if self.xp_points < threshold:
                return threshold
        return None
    
    def get_current_level_xp(self):
        levels = [0, 1000, 5000, 15000]
        level = self.get_level()
        return levels[level - 1] if level <= len(levels) else levels[-1]
    
    def get_xp_progress(self):
        current = self.get_current_level_xp()
        next_lvl = self.get_next_level_xp()
        if next_lvl is None:
            return 100
        span = next_lvl - current
        earned = self.xp_points - current
        return min(100, int((earned / span) * 100)) if span > 0 else 100

    def free_attempts_left(self):
        today = date.today()
        if self.free_quiz_attempts_reset_date is None:
            self.free_quiz_attempts_reset_date = today + timedelta(days=7)
            return self.free_quiz_attempts
        if self.free_quiz_attempts_reset_date < today:
            self.free_quiz_attempts = 3
            self.free_quiz_attempts_reset_date = today + timedelta(days=7)
        return self.free_quiz_attempts

    FREE_DAILY_POST_LIMIT = 2

    @property
    def daily_post_limit(self) -> int:
        base = self.FREE_DAILY_POST_LIMIT
        if self.is_premium:
            return 9999
        if self.referral_bonus_uploads > 0 and self.referral_bonus_expires:
            from datetime import date
            if self.referral_bonus_expires >= date.today():
                return base + self.referral_bonus_uploads
        return base

    @property
    def daily_uploads_left(self):
        if self.is_premium:
            return None
        today_count = Post.query.filter(
            Post.user_id == self.id,
            db.func.date(Post.created_at) == date.today()
        ).count()
        return max(0, self.daily_post_limit - today_count)

    def use_free_attempt(self):
        if self.is_premium or self.has_active_subscription:
            return True
        if self.free_attempts_left() <= 0:
            return False
        self.free_quiz_attempts -= 1
        db.session.commit()
        return True

    @property
    def is_premium(self):
        return self.subscription_tier != 'free' or self.can_access_all_content

    def get_referral_code(self) -> str:
        """Get or generate a unique referral code for this user."""
        if not self.referral_code:
            import secrets
            while True:
                code = secrets.token_urlsafe(6).upper()[:8]
                if not User.query.filter_by(referral_code=code).first():
                    self.referral_code = code
                    db.session.commit()
                    break
        return self.referral_code

    @property
    def has_active_subscription(self):
        if self.subscription_tier != 'free' and self.subscription_end_date:
            return datetime.now(timezone.utc) < self.subscription_end_date.replace(tzinfo=timezone.utc)
        return False

    @property
    def profile_picture_url(self):
        if not self.profile_picture or self.profile_picture == 'default.jpg':
            return _initials_avatar_url(self.username, self.nickname)
        if self.profile_picture.startswith('http'):
            return self.profile_picture
        return _initials_avatar_url(self.username, self.nickname)

# ── UserActivity Model ─────────────────────────────────────────────
class UserActivity(db.Model):
    __tablename__ = 'user_activities'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False, unique=True, index=True)
    current_post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_heartbeat = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    current_post = db.relationship('Post', backref='active_users')

# ── ModerationLog Model ─────────────────────────────────────────────
class ModerationLog(db.Model):
    __tablename__ = 'moderation_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False, index=True)
    violation_type = db.Column(db.String(32), nullable=False, index=True)  # e.g., NSFW, Gore, Toxicity
    is_permanent = db.Column(db.Boolean, default=False, nullable=False)
    suspension_end = db.Column(db.DateTime, nullable=True)

class WeakTopic(db.Model):
    __tablename__ = 'weak_topic'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False, index=True)
    topic_name = db.Column(db.String(200), nullable=False, index=True)
    fail_count = db.Column(db.Integer, default=1, nullable=False)
    status = db.Column(db.String(32), default='Critical', nullable=False)

    def __repr__(self):
        return f'<WeakTopic {self.topic_name} (user={self.user_id})>'


class Post(db.Model):
    __tablename__ = 'post'
    __table_args__ = (
        db.Index('idx_post_status_created', 'status', 'created_at'),
        db.Index('idx_post_subject_status', 'subject_id', 'status'),
        db.Index('idx_post_user_status',    'user_id', 'status'),
        db.Index('idx_post_content_status', 'content_type', 'status'),
    )
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)   # nullable - threads can be title-only
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=True)
    course_id = db.Column(db.Integer, db.ForeignKey('university_course.id'), nullable=True)
    parent_post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    has_document = db.Column(db.Boolean, default=False)

    # Reddit-style fields
    flair  = db.Column(db.String(30), nullable=True)   # 'discussion','question','resource','tip','rant','announcement'
    score  = db.Column(db.Integer, default=0, nullable=False)  # denormalised upvotes - downvotes

    # Content type for categorizing posts: notes, cheatsheet, quiz, mixed
    content_type = db.Column(db.String(20), default='notes', nullable=False)

    # Optional YouTube video linked to this post
    youtube_id = db.Column(db.String(20), nullable=True)
    is_remix = db.Column(db.Boolean, default=False, nullable=False)
    completion_pct = db.Column(db.Integer, nullable=True)
    remix_count = db.Column(db.Integer, default=0, nullable=False)
    remixes = db.relationship('Post', backref=db.backref('parent', remote_side='Post.id'), lazy='dynamic', cascade='all, delete-orphan', foreign_keys='Post.parent_post_id')
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    status = db.Column(db.String(20), nullable=False, default='pending')
    rejection_reason = db.Column(db.Text, nullable=True)

    # Content difficulty for filtering (Beginner/Intermediate/Advanced)
    content_difficulty = db.Column(db.String(20), nullable=True, index=True)

    # Relationship to UniversityCourse
    course = db.relationship('UniversityCourse', back_populates='study_packs')

    def like_count(self):
        if 'likes' in self.__dict__:
            return len(self.__dict__['likes'])
        return self.likes.count()

    def comment_count(self):
        if 'comments' in self.__dict__:
            return len(self.__dict__['comments'])
        return self.comments.count()

    def is_liked_by(self, user):
        if not user or not user.is_authenticated:
            return False
        return self.likes.filter_by(user_id=user.id).first() is not None

    def is_bookmarked_by(self, user):
        if not user or not user.is_authenticated:
            return False
        from app.models import Bookmark
        return Bookmark.query.filter_by(user_id=user.id, post_id=self.id).first() is not None
# ── UniversityCourse Model ─────────────────────────────────────────────
class UniversityCourse(db.Model):
    __tablename__ = 'university_course'
    id = db.Column(db.Integer, primary_key=True)
    canonical_name = db.Column(db.String(200), nullable=False, index=True)
    course_code = db.Column(db.String(50), nullable=False, index=True)
    university_name = db.Column(db.String(200), nullable=False, index=True)

    # One-to-many: a course can have many study packs (posts)
    study_packs = db.relationship('Post', back_populates='course', lazy='dynamic', cascade='all, delete-orphan')

    def like_count(self):
        # Use pre-loaded collection (selectinload) when available - zero extra queries
        if 'likes' in self.__dict__:
            return len(self.__dict__['likes'])
        return self.likes.count()

    def upvote_count(self):
        return self.votes.filter_by(value=1).count()

    def downvote_count(self):
        return self.votes.filter_by(value=-1).count()

    def vote_by(self, user):
        # Return the user's Vote on this post, or None.
        return self.votes.filter_by(user_id=user.id).first()

    def comment_count(self):
        if 'comments' in self.__dict__:
            return len(self.__dict__['comments'])
        return self.comments.count()

    def is_liked_by(self, user):
        return self.likes.filter_by(user_id=user.id).first() is not None

    def is_bookmarked_by(self, user):
        """Check if this post is bookmarked by the given user."""
        if not user.is_authenticated:
            return False
        return Bookmark.query.filter_by(user_id=user.id, post_id=self.id).first() is not None

    def has_quiz(self):
        """Check if this post has an associated quiz."""
        return hasattr(self, 'quiz') and self.quiz is not None

    @property
    def content_type_color(self):
        """Return color based on content type."""
        colors = {
            'notes': '#2563eb',
            'cheatsheet': '#10b981',
            'quiz': '#7c3aed',
            'mixed': '#f59e0b'
        }
        return colors.get(self.content_type, '#2563eb')

    @property
    def content_type_icon(self):
        """Return icon based on content type."""
        icons = {
            'notes': 'sticky-note',
            'cheatsheet': 'clone',
            'quiz': 'brain',
            'mixed': 'layer-group'
        }
        return icons.get(self.content_type, 'file-alt')

    @property
    def content_type_label(self):
        """Return label based on content type."""
        labels = {
            'notes': 'Notes',
            'cheatsheet': 'Cheatsheet',
            'quiz': 'Quiz',
            'mixed': 'Mixed'
        }
        return labels.get(self.content_type, 'Notes')

    def _quiz_meta_parsed(self):
        """Memoized json.loads for quiz.meta - avoids repeated parsing per request."""
        if self.quiz is None:
            return {}
        if not hasattr(self.quiz, '_meta_parsed'):
            try:
                self.quiz._meta_parsed = json.loads(self.quiz.meta) if self.quiz.meta else {}
            except (ValueError, TypeError):
                self.quiz._meta_parsed = {}
        return self.quiz._meta_parsed

    def _quiz_questions_parsed(self):
        """Memoized json.loads for quiz.questions."""
        if self.quiz is None:
            return []
        if not hasattr(self.quiz, '_questions_parsed'):
            try:
                self.quiz._questions_parsed = json.loads(self.quiz.questions) if self.quiz.questions else []
            except (ValueError, TypeError):
                self.quiz._questions_parsed = []
        return self.quiz._questions_parsed

    @property
    def quiz_card_meta(self):
        """Returns {questions, marks, duration} for quiz post cards."""
        if not self.has_quiz() or not self.quiz.meta:
            return None
        try:
            m = self._quiz_meta_parsed()
            if m.get("document_type") != "quiz":
                return None
            return {
                "questions": m.get("total_questions"),
                "marks":     m.get("total_marks"),
                "duration":  m.get("time_allowed") or m.get("time") or None,
            }
        except (ValueError, KeyError):
            return None

    @property
    def notes_card_meta(self):
        """Returns {read_time} for notes post cards."""
        if not self.has_quiz() or not self.quiz.meta:
            return None
        try:
            m = self._quiz_meta_parsed()
            if m.get("document_type") != "notes":
                return None
            return {
                "read_time": m.get("estimated_read_time"),
            }
        except (ValueError, KeyError):
            return None

    @property
    def cheatsheet_card_meta(self):
        """Returns {formula_count, definition_count} for cheatsheet post cards."""
        if not self.has_quiz() or not self.quiz.questions:
            return None
        try:
            m = self._quiz_meta_parsed()
            if m.get("document_type") != "cheatsheet":
                return None
            sections = self._quiz_questions_parsed()
            formula_count    = sum(
                len(s.get("entries", []))
                for s in sections if s.get("section_type") == "formulas"
            )
            definition_count = sum(
                len(s.get("entries", []))
                for s in sections if s.get("section_type") == "definitions"
            )
            return {
                "formula_count":    formula_count,
                "definition_count": definition_count,
            }
        except (ValueError, KeyError):
            return None

    # ── Flair helpers ──────────────────────────────────────────────────────────
    FLAIRS = {
        'discussion':   {'label': 'Discussion',   'icon': 'comments',         'color': '#6366f1'},
        'question':     {'label': 'Question',     'icon': 'circle-question',  'color': '#3b82f6'},
        'resource':     {'label': 'Resource',     'icon': 'paperclip',        'color': '#10b981'},
        'tip':          {'label': 'Tip',          'icon': 'lightbulb',        'color': '#f59e0b'},
        'rant':         {'label': 'Rant',         'icon': 'fire',             'color': '#ef4444'},
        'announcement': {'label': 'Announcement', 'icon': 'bullhorn',         'color': '#8b5cf6'},
    }

    @property
    def flair_meta(self):
        return self.FLAIRS.get(self.flair) if self.flair else None

    def __repr__(self):
        return f'<Post {self.title}>'




class Comment(db.Model):
    __tablename__ = 'comment'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)  # None = top-level

    replies = db.relationship(
        'Comment',
        backref=db.backref('parent', remote_side='Comment.id'),
        lazy='dynamic',
        cascade='all, delete-orphan',
    )


class Like(db.Model):
    __tablename__ = 'like'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_like'),)


class Vote(db.Model):
    """
    Up/downvote on a post.  value = +1 (upvote) or -1 (downvote).
    Post.score is kept as a denormalised tally updated by the vote route.
    """
    __tablename__ = 'vote'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    post_id    = db.Column(db.Integer, db.ForeignKey('post.id'),     nullable=False)
    value      = db.Column(db.SmallInteger, nullable=False)   # +1 or -1
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = db.relationship('User', backref='votes')
    post = db.relationship('Post', backref=db.backref('votes', lazy='dynamic', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'post_id', name='unique_vote'),
        db.Index('idx_vote_post', 'post_id'),
    )


class Purchase(db.Model):
    __tablename__ = 'purchase'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    document_id = db.Column(db.Integer, db.ForeignKey('document.id'), nullable=False)
    amount_paid = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(50))
    transaction_id = db.Column(db.String(200), unique=True)
    status = db.Column(db.String(50), default='pending')
    purchased_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    document = db.relationship('Document', backref='purchases')


class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    message = db.Column(db.String(300), nullable=False)
    # Notification category/type (e.g., 'AURA_EARNED', 'STREAK_RESTORE', 'REMIX_ALERT')
    notification_type = db.Column(db.String(50), nullable=False, index=True)
    # Actionable URL for notification click-through
    action_url = db.Column(db.String(300), nullable=True)
    # Amount of Aura points earned (if relevant)
    aura_amount = db.Column(db.Integer, nullable=True)
    # Deprecated: use action_url instead
    link = db.Column(db.String(300), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    user = db.relationship('User', backref='notifications')


def create_notification(user_id, message, notification_type, link=None):
    """
    Create and persist a notification for a user.
    Never raises - notification failure must not break the caller.
    """
    try:
        from app import db as _db
        notif = Notification(
            user_id=user_id,
            message=message,
            notification_type=notification_type,
            link=link,
        )
        _db.session.add(notif)
        _db.session.commit()
    except Exception:
        pass

class Document(db.Model):
    __tablename__ = 'document'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(300), nullable=False)
    original_filename = db.Column(db.String(300), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50))
    file_size = db.Column(db.Integer)
    json_sidecar_path = db.Column(db.String(500), nullable=True)
    is_paid = db.Column(db.Boolean, default=False)
    price = db.Column(db.Float, default=0.0)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    download_count = db.Column(db.Integer, default=0)

    post = db.relationship('Post', foreign_keys='Post.document_id', backref='document', uselist=False, overlaps="post_ref")

    def has_access(self, user):
        # Temporary bypass: subscription/purchase constraints are disabled.
        return True
        if getattr(user, 'is_admin', False) or getattr(user, 'can_access_all_content', False):
            return True
        if not self.is_paid:
            return True
        return Purchase.query.filter_by(
            user_id=user.id,
            document_id=self.id,
            status='completed'
        ).first() is not None

    def __repr__(self):
        return f'<Document {self.original_filename}>'

# Association table - subject shared across multiple programmes
subject_programme = db.Table(
    'subject_programme',
    db.Column('subject_id',   db.Integer, db.ForeignKey('subject.id'),   primary_key=True),
    db.Column('programme_id', db.Integer, db.ForeignKey('programme.id'), primary_key=True),
)

class Programme(db.Model):
    """
    Programme model - represents a academic programme/course of study.
    Groups subjects together (e.g., Computer Science, Business Administration).
    """
    __tablename__ = 'programme'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False, index=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    icon = db.Column(db.String(50), default='graduation-cap')
    color = db.Column(db.String(7), default='#8b5cf6')
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    faculty = db.Column(db.String(200), nullable=True, index=True)
    
    # Relationship to subjects via association table
    subjects = db.relationship('Subject', secondary='subject_programme', back_populates='programmes')

    def active_subject_count(self):
        from app.models import Subject
        return Subject.query.filter_by(is_active=True).filter(
            Subject.programmes.any(id=self.id)
        ).count()

    def __repr__(self):
        return f'<Programme {self.name}>'


class Subject(db.Model):
    __tablename__ = 'subject'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    icon = db.Column(db.String(50), default='book')
    color = db.Column(db.String(7), default='#6366f1')
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    post_count = db.Column(db.Integer, default=0)
    
    # Many-to-many relationship to programmes via association table
    programmes = db.relationship('Programme', secondary='subject_programme', back_populates='subjects')
    posts = db.relationship('Post', backref='subject', lazy='dynamic')

    def update_post_count(self):
        self.post_count = self.posts.count()
        db.session.commit()

    def __repr__(self):
        return f'<Subject {self.name}>'


class Bookmark(db.Model):
    """
    Bookmark model - allows users to bookmark posts for later reference.
    """
    __tablename__ = 'bookmark'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Relationships
    user = db.relationship('User', backref='bookmarks')
    post = db.relationship('Post', backref='bookmarks')
    
    # Unique constraint - a user can only bookmark a post once
    __table_args__ = (
        db.UniqueConstraint('user_id', 'post_id', name='unique_bookmark'),
    )

    def __repr__(self):
        return f'<Bookmark user_id={self.user_id} post_id={self.post_id}>'


# ── Helper: format seconds for display ────────────────────────────────────────
def format_time_taken(seconds: int) -> str:
    """
    Convert integer seconds to a human-readable string.
    Returns MM:SS if under 1 hour, HH:MM:SS otherwise.
    """
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class QuizLeaderboard(db.Model):
    __tablename__ = 'quiz_leaderboard'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)

    # Score stored as percentage (0–100, rounded to 2 dp)
    score_pct = db.Column(db.Float, nullable=False)

    earned_marks = db.Column(db.Float, nullable=False)
    xp_earned = db.Column(db.Integer, nullable=False)

    # Server-calculated elapsed seconds; never trusted from frontend
    time_taken = db.Column(db.Integer, nullable=False)   # seconds

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    
    # Public flag - determines if entry is visible on leaderboard
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    
    user = db.relationship('User', backref='leaderboard_entries')
    post = db.relationship('Post', backref=db.backref('leaderboard_entries', cascade='all, delete-orphan'))
    
    __table_args__ = (
        db.UniqueConstraint('post_id', 'user_id', name='unique_leaderboard_entry'),
        db.Index('idx_leaderboard_post_score', 'post_id', 'score_pct', 'time_taken'),
    )

    @property
    def formatted_time(self) -> str:
        return format_time_taken(self.time_taken)

    def __repr__(self):
        return f'<QuizLeaderboard post_id={self.post_id} user_id={self.user_id} score={self.score_pct:.2f}%>'


class QuizData(db.Model):
    __tablename__ = 'quiz_data'
    id          = db.Column(db.Integer, primary_key=True)
    post_id     = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), unique=True, nullable=False)
    questions   = db.Column(db.Text, nullable=False)
    total_marks = db.Column(db.Integer, default=0)
    xp_reward   = db.Column(db.Integer, default=0)
    meta        = db.Column(db.Text)
    created_at  = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    post        = db.relationship('Post', backref=db.backref('quiz', uselist=False, cascade='all, delete-orphan'))


class QuizAttempt(db.Model):
    __tablename__ = 'quiz_attempts'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)

    answers = db.Column(db.Text)

    score_pct = db.Column(db.Float, default=0)  # ONLY percentage field

    earned_marks = db.Column(db.Float, default=0)
    xp_earned = db.Column(db.Integer, default=0)

    timed_out = db.Column(db.Boolean, default=False)

    time_taken = db.Column(db.Integer, default=0)  # seconds, server-calculated

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref='quiz_attempts')
    post = db.relationship('Post', backref=db.backref(
        'quiz_attempts',
        cascade='all, delete-orphan'
    ))


class QuizAssessment(db.Model):
    __tablename__ = 'quiz_assessments'

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey('quiz_attempts.id', ondelete='CASCADE'), nullable=False)
    question_index = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Float, nullable=False)
    feedback = db.Column(db.Text, nullable=True)
    assessed_by = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=True)
    assessed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    attempt = db.relationship('QuizAttempt', backref=db.backref(
        'assessments',
        cascade='all, delete-orphan'
    ))
    assessor = db.relationship('User', backref='assessments')

    __table_args__ = (
        db.UniqueConstraint('attempt_id', 'question_index', name='unique_question_assessment'),
    )

class Subscription(db.Model):
    __tablename__ = 'subscriptions'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False, index=True)
    plan_key       = db.Column(db.String(64),  nullable=False)
    plan_name      = db.Column(db.String(128), nullable=False)
    amount_paid    = db.Column(db.Float,  nullable=False, default=0.0)
    currency       = db.Column(db.String(8),   nullable=False, default='GHS')
    payment_method = db.Column(db.String(64),  nullable=True)
    transaction_id = db.Column(db.String(128), nullable=True, unique=True, index=True)
    status         = db.Column(db.String(32),  nullable=False, default='pending')
    started_at     = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at     = db.Column(db.DateTime, nullable=False)
    created_at     = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', back_populates='subscriptions')

    @property
    def is_active(self):
        return self.status == 'active' and self.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


    def __repr__(self):
        return f'<Subscription {self.plan_key} user={self.user_id} expires={self.expires_at}>'


# Renamed from XpTransaction
class AuraTransaction(db.Model):
    """Logs every Aura (XP) award so students can see their history."""
    __tablename__ = 'aura_transaction'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    amount     = db.Column(db.Integer, nullable=False)
    reason     = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class StudentPastPaper(db.Model):
    """A past exam paper uploaded by a student."""
    __tablename__ = 'student_past_paper'

    id                   = db.Column(db.Integer, primary_key=True)
    user_id              = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    subject_id           = db.Column(db.Integer, db.ForeignKey('subject.id'),  nullable=False)
    subject_slug         = db.Column(db.String(100), nullable=False, index=True)
    filename             = db.Column(db.String(255), nullable=False)
    file_path            = db.Column(db.String(500), nullable=False)

    file_type            = db.Column(db.String(10),  nullable=False)  # pdf | image
    file_size            = db.Column(db.Integer,     nullable=True)
    year                 = db.Column(db.String(10),  nullable=True)
    semester             = db.Column(db.String(20),  nullable=True)
    description          = db.Column(db.String(300), nullable=True)
    status               = db.Column(db.String(20),  default='pending')  # pending|collected|rejected
    xp_awarded           = db.Column(db.Boolean,     default=False)
    collected_at         = db.Column(db.DateTime,    nullable=True)
    uploaded_at          = db.Column(db.DateTime,    default=lambda: datetime.now(timezone.utc), nullable=False)

    user    = db.relationship('User',    backref='past_papers')
    subject = db.relationship('Subject', backref='student_past_papers')

    @property
    def is_cloudinary(self) -> bool:
        """True when the file is stored in Cloudinary (production)."""
        return self.file_path.startswith('https://')

    def to_dict(self) -> dict:
        return {
            'id':           self.id,
            'subject_slug': self.subject_slug,
            'subject_name': self.subject.name if self.subject else self.subject_slug,
            'filename':     self.filename,
            'file_type':    self.file_type,
            'file_size':    self.file_size,
            'year':         self.year,
            'semester':     self.semester,
            'description':  self.description,
            'uploaded_at':  self.uploaded_at.isoformat(),
            'uploader':     self.user.username if self.user else 'unknown',
        }

class NoteCompletion(db.Model):
    """Tracks when a user completes notes in study mode. One row per user/post pair."""
    __tablename__ = 'note_completion'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    post_id    = db.Column(db.Integer, db.ForeignKey('post.id'),     nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_note_completion'),)


class GenerationJob(db.Model):
    """Tracks in-app bulk generation jobs (KnowlyGen-style lifecycle)."""
    __tablename__ = 'generation_job'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(40), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=True, index=True)

    programme_slug = db.Column(db.String(120), nullable=True, index=True)
    programme_name = db.Column(db.String(200), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True, index=True)
    subject_slug = db.Column(db.String(120), nullable=False, index=True)
    subject_name = db.Column(db.String(200), nullable=False)

    topic = db.Column(db.String(300), nullable=False)
    content_type = db.Column(db.String(20), nullable=False, index=True)
    level = db.Column(db.String(20), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    semester = db.Column(db.Integer, nullable=True)

    status = db.Column(db.String(24), nullable=False, default='pending', index=True)
    error = db.Column(db.Text, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    source = db.Column(db.String(20), nullable=False, default='auto')
    priority = db.Column(db.Integer, nullable=False, default=0)

    created_post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    actor = db.relationship('User', foreign_keys=[actor_id], backref='generation_jobs')
    created_post = db.relationship('Post', foreign_keys=[created_post_id], backref='generation_jobs')


# ── VideoLesson Model ─────────────────────────────────────────────
class VideoLesson(db.Model):
    """A YouTube video lesson linked to a subject."""
    __tablename__ = 'video_lesson'

    id         = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True, index=True)
    youtube_id = db.Column(db.String(20), nullable=False)
    title      = db.Column(db.String(300), nullable=False)
    thumbnail  = db.Column(db.String(500), nullable=True)
    order_index = db.Column(db.Integer, nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    # Content difficulty for filtering (Beginner/Intermediate/Advanced)
    content_difficulty = db.Column(db.String(20), nullable=True, index=True)
    # YouTube channel info for creator credit
    channel_name = db.Column(db.String(200), nullable=True)
    channel_id   = db.Column(db.String(50), nullable=True)
    # Background categorization result
    academic_category = db.Column(db.String(100), nullable=True, default='Pending')
    # Normalised search-query slug used to group this video into a StudyPack
    topic_slug      = db.Column(db.String(255), nullable=True, index=True)
    transcript_text = db.Column(db.Text, nullable=True)
    subject = db.relationship('Subject', backref='video_lessons')
    # AI-generated annotations for this video
    annotations = db.relationship('VideoAnnotation', backref='video', cascade='all, delete-orphan')

    @property
    def xp_reward(self):
        return 10

    @property
    @property
    def youtube_url(self):
        return f'https://www.youtube.com/watch?v={self.youtube_id}'

    @property
    def embed_url(self):
        return f'https://www.youtube.com/embed/{self.youtube_id}'

# ── VideoAnnotation Model ─────────────────────────────────────────────
class VideoAnnotation(db.Model):
    __tablename__ = 'video_annotations'

    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=False, index=True)
    timestamp = db.Column(db.Float, nullable=False, index=True)
    annotation_type = db.Column(db.String(50), nullable=False, index=True)  # e.g., 'DIAGRAM_BREAKDOWN', 'FORMULA_STEP'
    content_json = db.Column(db.Text, nullable=False)  # Store JSON (coordinates, LaTeX, etc.)
# ── UserVideoProgress Model ─────────────────────────────────────────────
class UserVideoProgress(db.Model):
    __tablename__ = 'user_video_progress'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False, index=True)
    video_id = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=False, index=True)
    is_completed = db.Column(db.Boolean, default=False, nullable=False)
    last_timestamp = db.Column(db.Float, nullable=True)
    confidence_score = db.Column(db.SmallInteger, nullable=True)  # 0-100 confidence slider

    user = db.relationship('User', foreign_keys=[user_id], backref='video_progress')
    video = db.relationship('VideoLesson', backref='user_progress')

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class VideoCompletion(db.Model):
    """Tracks when a user marks a video as complete. One row per user/video pair."""
    __tablename__ = 'video_completion'

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False)
    video_id        = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=False)
    xp_earned       = db.Column(db.Integer, default=0, nullable=False)
    created_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user  = db.relationship('User', backref=db.backref('video_completions', lazy='dynamic'))
    video = db.relationship('VideoLesson', backref=db.backref('completions', lazy='dynamic'))


    __table_args__ = (
        db.UniqueConstraint('user_id', 'video_id', name='unique_video_completion'),
    )

# ── UserPackProgress Model ─────────────────────────────────────────────────────
class UserPackProgress(db.Model):
    """Caches pack progress to avoid calculating on every page load.
    
    Updated only when a user completes a video in the pack.
    Stores pre-calculated progress_percent so dashboard queries are O(1) instead of O(n).
    """
    __tablename__ = 'user_pack_progress'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'pack_id', name='unique_user_pack_progress'),
    )

    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False, index=True)
    pack_id          = db.Column(db.Integer, db.ForeignKey('study_pack.id'), nullable=False, index=True)
    progress_percent = db.Column(db.Integer, default=0, nullable=False)
    last_video_id    = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=True)
    updated_at       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, onupdate=lambda: datetime.now(timezone.utc))
    created_at       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user       = db.relationship('User', backref=db.backref('pack_progress', lazy='dynamic', cascade='all, delete-orphan'))
    pack       = db.relationship('StudyPack', backref=db.backref('user_progress', lazy='dynamic', cascade='all, delete-orphan'))
    last_video = db.relationship('VideoLesson')

# End of file: ensure no stray triple-quoted strings or syntax errors


# ── StudyPack Model ───────────────────────────────────────────────────────────
class StudyPack(db.Model):
    """A named collection of videos on a topic, shown as a card on search results.

    Auto-generated when a user searches, or manually curated by an admin.
    """
    __tablename__ = 'study_pack'
    __table_args__ = (
        db.Index('idx_study_pack_topic_slug', 'topic_slug'),
    )

    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(200), nullable=False)
    topic_slug = db.Column(db.String(100), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=True)
    is_curated = db.Column(db.Boolean, default=False, nullable=False)
    share_token = db.Column(db.String(16), unique=True, nullable=True)
    view_count = db.Column(db.Integer, default=0, nullable=False)
    source     = db.Column(db.String(20), default='search', nullable=False)
    pack_type  = db.Column(db.String(20), default='quick', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    # order_by uses a lambda so the column reference is resolved after both
    # classes are fully defined — safe regardless of definition order.
    videos  = db.relationship('StudyPackVideo', backref='pack',
                              cascade='all, delete-orphan',
                              order_by=lambda: StudyPackVideo.order_index)
    creator = db.relationship('User', foreign_keys=[created_by], backref='created_study_packs')
    subject = db.relationship('Subject', backref='study_packs')

    @property
    def video_count(self):
        return len(self.videos)

    @property
    def first_video_youtube_id(self):
        if self.videos and self.videos[0].video:
            return self.videos[0].video.youtube_id
        return None

    @property
    def url(self):
        if self.videos:
            return url_for('main.video_player', video_id=self.videos[0].video_id)
        return '#'

    @property
    def type(self):
        return 'study_pack'

    @property
    def color(self):
        return self.subject.color if self.subject else '#6366f1'

    @classmethod
    def generate_share_token(cls):
        """Return an 8-character URL-safe token for shareable pack URLs."""
        return secrets.token_urlsafe(6)

    def __repr__(self):
        return f'<StudyPack {self.title!r}>'


# ── StudyPackVideo Model ──────────────────────────────────────────────────────
class StudyPackVideo(db.Model):
    """Join table recording which videos are in which pack and in what order.

    One row = one video slot in one pack.
    """
    __tablename__ = 'study_pack_video'
    __table_args__ = (
        db.UniqueConstraint('pack_id', 'order_index', name='unique_pack_video_order'),
    )

    id          = db.Column(db.Integer, primary_key=True)
    pack_id     = db.Column(db.Integer, db.ForeignKey('study_pack.id'), nullable=False, index=True)
    video_id    = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=False, index=True)
    order_index = db.Column(db.Integer, nullable=False)
    stage       = db.Column(db.String(20), nullable=True)

    # Relationships
    video = db.relationship('VideoLesson', backref='pack_memberships')

    def __repr__(self):
        return f'<StudyPackVideo pack={self.pack_id} video={self.video_id} order={self.order_index}>'


# ── PackResource Model ────────────────────────────────────────────────────────
class PackResource(db.Model):
    """Stores a generated AI resource attached to a specific video within a pack.

    resource_type values:
      'flashcards'   — JSON list of {front, back} cards, generated from video 1 transcript
      'micro_quiz'   — JSON quiz object (5-10 MCQs), placed at difficulty boundaries
      'notes'        — Full structured notes JSON (pack-level, generated after all videos)
      'cheatsheet'   — Dense formula/definition reference JSON (pack-level)
      'boss_quiz'    — Full 30-question final quiz JSON (pack-level, paid only)

    video_id is NULL for pack-level resources (notes, cheatsheet, boss_quiz).
    video_id is set for per-video resources (flashcards, micro_quiz).

    generation_status values: 'pending', 'generating', 'done', 'failed'
    """
    __tablename__ = 'pack_resource'
    __table_args__ = (
        db.Index('idx_pack_resource_lookup', 'pack_id', 'resource_type', 'video_id'),
    )

    id                = db.Column(db.Integer, primary_key=True)
    pack_id           = db.Column(db.Integer, db.ForeignKey('study_pack.id'), nullable=False, index=True)
    video_id          = db.Column(db.Integer, db.ForeignKey('video_lesson.id'), nullable=True, index=True)
    resource_type     = db.Column(db.String(20), nullable=False)
    content_json      = db.Column(db.Text, nullable=True)       # serialized JSON string
    generation_status = db.Column(db.String(20), default='pending', nullable=False)
    error_message     = db.Column(db.String(500), nullable=True)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow,
                                  onupdate=datetime.utcnow, nullable=False)

    # Relationships
    pack  = db.relationship('StudyPack', backref='resources')
    video = db.relationship('VideoLesson', backref='pack_resources')

    def get_content(self) -> dict | list | None:
        """Deserialize content_json safely."""
        if not self.content_json:
            return None
        try:
            import json
            return json.loads(self.content_json)
        except Exception:
            return None

    def set_content(self, data: dict | list) -> None:
        """Serialize and store content."""
        import json
        self.content_json = json.dumps(data, ensure_ascii=False)

    def __repr__(self):
        return f'<PackResource pack={self.pack_id} type={self.resource_type} video={self.video_id} status={self.generation_status}>'

# ── PackResourceCompletion Model ─────────────────────────────────────────────
class PackResourceCompletion(db.Model):
    """Tracks when a user completes a PackResource (flashcard deck, quiz, etc).

    One row per user per resource. Used to mark checkpoints done in the syllabus
    pane and award XP.
    """
    __tablename__ = 'pack_resource_completion'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'resource_id', name='unique_resource_completion'),
    )

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('profiles.id'), nullable=False, index=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('pack_resource.id'), nullable=False, index=True)
    score       = db.Column(db.Integer, nullable=True)   # for quizzes: number correct
    total       = db.Column(db.Integer, nullable=True)   # for quizzes: total questions
    xp_earned   = db.Column(db.Integer, default=0, nullable=False)
    created_at  = db.Column(db.DateTime,
                            default=lambda: datetime.now(timezone.utc), nullable=False)

    user     = db.relationship('User', backref='resource_completions')
    resource = db.relationship('PackResource', backref='completions')

    def __repr__(self):
        return f'<PackResourceCompletion user={self.user_id} resource={self.resource_id}>'
