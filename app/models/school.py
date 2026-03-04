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

    accounts = db.relationship(
        'Accounts',
        backref='school',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<School {self.school_name}>'

    @property
    def student_count(self):
        return self.accounts.count()