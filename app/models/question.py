from datetime import datetime, timezone
from app.extensions import db


class Question(db.Model):
    __tablename__ = 'question'

    id = db.Column(db.Integer, primary_key=True)
    test_type = db.Column(db.String(100), nullable=False, index=True)
    question_content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<Question {self.id} [{self.test_type}]>'
