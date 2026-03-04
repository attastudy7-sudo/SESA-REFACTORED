from datetime import datetime, timezone
from flask_login import UserMixin
from app.extensions import db


class Accounts(UserMixin, db.Model):
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    fname = db.Column(db.String(100), nullable=False)
    lname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password = db.Column(db.String(256), nullable=False)
    level = db.Column(db.String(50), nullable=True)
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
        return self.id == 1

    def __repr__(self):
        return f'<Account {self.username}>'
