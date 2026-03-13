from datetime import datetime, timezone
from app.extensions import db


class School(db.Model):
    __tablename__ = 'school'

    id = db.Column(db.Integer, primary_key=True)
    school_name = db.Column(db.String(200), nullable=False, unique=True)
    admin_name = db.Column(db.String(100), nullable=False)
    admin_password = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    subscription_paid = db.Column(db.Boolean, default=False)
    upload_enabled = db.Column(db.Boolean, default=False)
    paystack_reference = db.Column(db.String(100), nullable=True)
    payment_date = db.Column(db.DateTime, nullable=True)
    subscription_expires = db.Column(db.DateTime, nullable=True, index=True)

    accounts = db.relationship(
        'Accounts',
        backref='school',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    # Self-registration fields (Group 1 — access code + QR onboarding)
    access_code = db.Column(db.String(8), nullable=True, unique=True, index=True)
    qr_token = db.Column(db.String(64), nullable=True, unique=True, index=True)

    # School admin lockout
    failed_attempts = db.Column(db.Integer, default=0, server_default='0', nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f'<School {self.school_name}>'

    @property
    def student_count(self):
        return self.accounts.count()

    @property
    def subscription_active(self):
        """True if paid and not yet expired."""
        if not self.subscription_paid:
            return False
        if self.subscription_expires is None:
            return True   # legacy rows with no expiry date — treat as active
        return datetime.now(timezone.utc) < self.subscription_expires

    @property
    def subscription_days_remaining(self):
        """Integer days left, or None if no expiry set."""
        if not self.subscription_expires:
            return None
        delta = self.subscription_expires - datetime.now(timezone.utc)
        return max(delta.days, 0)

    # ── Lockout helpers ──────────────────────────────────────────────────────
    LOCKOUT_THRESHOLD = 5
    LOCKOUT_MINUTES   = 15

    @property
    def is_locked(self):
        if self.locked_until is None:
            return False
        return datetime.now(timezone.utc) < self.locked_until

    def record_failed_login(self):
        from datetime import timedelta
        self.failed_attempts = (self.failed_attempts or 0) + 1
        if self.failed_attempts >= self.LOCKOUT_THRESHOLD:
            self.locked_until = datetime.now(timezone.utc) + timedelta(minutes=self.LOCKOUT_MINUTES)

    def record_successful_login(self):
        self.failed_attempts = 0
        self.locked_until = None