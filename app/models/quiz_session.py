"""
QuizSession — server-side quiz progress storage.
Replaces cookie-based session state for in-progress assessments.
One row per student per test type. Upserted on each answer.
Expires after 24 hours to prevent stale rows accumulating.
"""
from datetime import datetime, timezone, timedelta
from app.extensions import db


class QuizSession(db.Model):
    __tablename__ = 'quiz_sessions'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(
        db.Integer,
        db.ForeignKey('accounts.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    test_type  = db.Column(db.String(100), nullable=False, index=True)
    q_index    = db.Column(db.Integer, default=0, nullable=False)
    score      = db.Column(db.Integer, default=0, nullable=False)
    answers    = db.Column(db.Text, default='[]', nullable=False)  # JSON array
    started_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    expires_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc) + timedelta(hours=24),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        db.UniqueConstraint('user_id', 'test_type', name='uq_quiz_user_test'),
    )

    def __repr__(self):
        return f'<QuizSession user={self.user_id} test={self.test_type} q={self.q_index}>'

    @property
    def is_expired(self):
        now = datetime.now(timezone.utc)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now > exp

    @classmethod
    def get_or_create(cls, user_id: int, test_type: str):
        """Return existing live session or a fresh one. Never returns expired."""
        existing = cls.query.filter_by(
            user_id=user_id,
            test_type=test_type,
        ).first()

        if existing and not existing.is_expired:
            return existing, False  # (session, is_new)

        # Delete stale/expired row if present
        if existing:
            db.session.delete(existing)
            db.session.flush()

        fresh = cls(user_id=user_id, test_type=test_type)
        db.session.add(fresh)
        db.session.flush()
        return fresh, True  # (session, is_new)

    @classmethod
    def delete_for(cls, user_id: int, test_type: str):
        """Clean up after a test is completed or abandoned."""
        cls.query.filter_by(user_id=user_id, test_type=test_type).delete()