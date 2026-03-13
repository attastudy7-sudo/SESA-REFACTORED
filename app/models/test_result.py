from datetime import datetime, timezone
from app.extensions import db


class TestResult(db.Model):
    __tablename__ = 'test_results'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('accounts.id', ondelete='CASCADE'), nullable=False, index=True)
    test_type = db.Column(db.String(100), nullable=False, index=True)
    score = db.Column(db.Integer, nullable=False)
    max_score = db.Column(db.Integer, nullable=True)
    stage = db.Column(db.String(50), nullable=True, index=True)  # "Normal Stage", "Mild Stage", etc.
    feedback = db.Column(db.Text, nullable=True)
    details = db.Column(db.Text, nullable=True)           # kept for backward compat
    taken_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        return f'<TestResult user={self.user_id} type={self.test_type} score={self.score}>'

    @property
    def score_percentage(self):
        if self.max_score and self.max_score > 0:
            return round((self.score / self.max_score) * 100)
        return 0
