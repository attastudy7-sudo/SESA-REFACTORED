from datetime import datetime, timezone
from flask_login import UserMixin
from app.extensions import db


class Accounts(UserMixin, db.Model):
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    fname = db.Column(db.String(100), nullable=False)
    lname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password = db.Column(db.String(256), nullable=False)
    school_name = db.Column(db.String(200), nullable=True)
    gender = db.Column(db.String(20), nullable=True)
    birthdate = db.Column(db.Date, nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    school_id = db.Column(
        db.Integer,
        db.ForeignKey('school.id', ondelete='CASCADE', name='fk_accounts_school_id'),
        nullable=True,
        index=True
    )

    class_group = db.Column(db.String(50), nullable=True)   # e.g. "Form 2A", "JHS 3B"

    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_counsellor = db.Column(db.Boolean, default=False, server_default='0', nullable=False)

    # Account lockout — incremented on each failed login, reset on success
    failed_attempts = db.Column(db.Integer, default=0, server_default='0', nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)  # NULL = not locked
    phone = db.Column(db.String(20), nullable=True)

    # Consent record — required under Ghana Data Protection Act 2012
    consent_given = db.Column(db.Boolean, default=False, nullable=False, server_default='0')
    consent_given_at = db.Column(db.DateTime, nullable=True)
    consent_version = db.Column(db.String(10), nullable=True)  # e.g. 'v1.0'

    test_results = db.relationship(
        'TestResult',
        backref='account',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    @property
    def full_name(self):
        return f'{self.fname} {self.lname}'

    @property
    def is_super_admin(self):
        return self.is_admin

    @property
    def role(self):
        if self.is_admin:
            return 'superadmin'
        if self.is_counsellor:
            return 'counsellor'
        return 'student'

    def __repr__(self):
        return f'<Account {self.username}>'
    # ── Lockout helpers ──────────────────────────────────────────────────────
    LOCKOUT_THRESHOLD = 5      # failed attempts before lockout
    LOCKOUT_MINUTES   = 15     # minutes locked after threshold reached

    @property
    def is_locked(self):
        """True if the account is currently locked out."""
        if self.locked_until is None:
            return False
        locked_until = self.locked_until
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < locked_until

    def record_failed_login(self):
        """Increment counter; lock account after LOCKOUT_THRESHOLD failures."""
        from datetime import timedelta
        self.failed_attempts = (self.failed_attempts or 0) + 1
        if self.failed_attempts >= self.LOCKOUT_THRESHOLD:
            self.locked_until = datetime.now(timezone.utc) + timedelta(minutes=self.LOCKOUT_MINUTES)

    def record_successful_login(self):
        """Reset counter and clear any lockout on a good login."""
        self.failed_attempts = 0
        self.locked_until = None
        self.last_login = datetime.now(timezone.utc)