from datetime import datetime, timezone
from app.extensions import db


class SchoolClass(db.Model):
    __tablename__ = 'school_class'
    __table_args__ = (
        db.UniqueConstraint('school_id', 'name', name='uq_school_class_school_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(
        db.Integer,
        db.ForeignKey('school.id', ondelete='CASCADE', name='fk_school_class_school_id'),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(100), nullable=False)   # e.g. "Form 2A", "JHS 3B"
    level = db.Column(db.String(20), nullable=True)     # jhs | shs | university
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    accounts = db.relationship(
        'Accounts',
        backref='school_class',
        lazy='dynamic',
    )

    def __repr__(self):
        return f'<SchoolClass {self.name} school={self.school_id}>'

    @property
    def student_count(self):
        return self.accounts.count()
