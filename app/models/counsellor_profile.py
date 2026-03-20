"""
CounsellorProfile — professional details for counsellor accounts.

Linked one-to-one with Accounts. Created at signup, activated by
super admin after credential verification.

Verification flow:
    signup → status='pending' → admin reviews → status='verified' or 'rejected'
    A verified counsellor can log in and access their dashboard.
    A pending/rejected counsellor sees a holding page after login.
"""
import os
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from app.extensions import db


def _get_fernet():
    key = os.environ.get('PHI_ENCRYPTION_KEY', '')
    if not key:
        return None
    return Fernet(key.encode())


class CounsellorProfile(db.Model):
    __tablename__ = 'counsellor_profiles'

    id = db.Column(db.Integer, primary_key=True)

    # ── Link to base account ──────────────────────────────────────────────────
    account_id = db.Column(
        db.Integer,
        db.ForeignKey('accounts.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        index=True,
    )
    account = db.relationship('Accounts', backref=db.backref('counsellor_profile', uselist=False))

    # ── Professional credentials ──────────────────────────────────────────────
    gpc_number    = db.Column(db.String(50),  nullable=True)   # Ghana Psychology Council
    gacc_number   = db.Column(db.String(50),  nullable=True)   # Ghana Assoc. of Certified Counsellors
    _ghana_card_encrypted = db.Column('ghana_card_number', db.String(500), nullable=True)  # National ID — encrypted

    @property
    def ghana_card_number(self):
        if not self._ghana_card_encrypted:
            return None
        f = _get_fernet()
        if not f:
            return self._ghana_card_encrypted
        try:
            return f.decrypt(self._ghana_card_encrypted.encode()).decode()
        except Exception:
            return self._ghana_card_encrypted

    @ghana_card_number.setter
    def ghana_card_number(self, value):
        if not value:
            self._ghana_card_encrypted = None
            return
        f = _get_fernet()
        if not f:
            self._ghana_card_encrypted = value
            return
        self._ghana_card_encrypted = f.encrypt(value.encode()).decode()

    specialisations = db.Column(db.String(300), nullable=True)  # comma-separated
    bio             = db.Column(db.Text,         nullable=True)
    years_experience = db.Column(db.Integer,     nullable=True)

    # ── Photo ─────────────────────────────────────────────────────────────────
    # Stores a Cloudinary URL (or empty until Cloudinary is integrated)
    photo_url = db.Column(db.String(500), nullable=True)

    # ── Verification ─────────────────────────────────────────────────────────
    verification_status = db.Column(
        db.String(20),
        default='pending',
        nullable=False,
        index=True,
    )  # 'pending' | 'verified' | 'rejected'

    rejection_reason = db.Column(db.Text, nullable=True)
    submitted_at     = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    verified_at = db.Column(db.DateTime, nullable=True)

    # ── Subscription ─────────────────────────────────────────────────────────
    subscription_paid      = db.Column(db.Boolean,  default=False,  nullable=False)
    subscription_expires   = db.Column(db.DateTime, nullable=True)
    paystack_reference     = db.Column(db.String(100), nullable=True)
    payment_date           = db.Column(db.DateTime,    nullable=True)

    def __repr__(self):
        return f'<CounsellorProfile account={self.account_id} status={self.verification_status}>'

    # ── Convenience properties ────────────────────────────────────────────────
    @property
    def is_verified(self):
        return self.verification_status == 'verified'

    @property
    def is_pending(self):
        return self.verification_status == 'pending'

    @property
    def is_rejected(self):
        return self.verification_status == 'rejected'

    @property
    def subscription_active(self):
        if not self.subscription_paid:
            return False
        if self.subscription_expires is None:
            return True
        return datetime.now(timezone.utc) < self.subscription_expires.replace(tzinfo=timezone.utc)

    @property
    def specialisations_list(self):
        """Return specialisations as a Python list."""
        if not self.specialisations:
            return []
        return [s.strip() for s in self.specialisations.split(',') if s.strip()]