"""
AuditLog — immutable record of security and clinical events.
Never update or delete rows from this table.
"""
from datetime import datetime, timezone
from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = 'audit_log'

    id         = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), nullable=False, index=True)
    # e.g. LOGIN, LOGOUT, RESULT_SAVED, CLINICAL_ALERT, STUDENT_DELETED,
    #      COUNSELLOR_NOTE, ADMIN_ACTION, PAYMENT_CONFIRMED

    actor_id   = db.Column(db.Integer, db.ForeignKey('accounts.id', ondelete='SET NULL'), nullable=True, index=True)
    school_id  = db.Column(db.Integer, db.ForeignKey('school.id',   ondelete='SET NULL'), nullable=True, index=True)
    target_id  = db.Column(db.Integer, nullable=True)   # id of the affected row (flexible)
    ip_address = db.Column(db.String(45), nullable=True)
    detail     = db.Column(db.Text, nullable=True)       # JSON string or plain text context
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    def __repr__(self):
        return f'<AuditLog {self.event_type} actor={self.actor_id} at={self.created_at}>'


def audit(event_type, *, actor_id=None, school_id=None,
          target_id=None, ip_address=None, detail=None):
    """
    Helper — write one audit row and flush to the session.
    Call this inside any route that already has a db.session open.
    Does NOT commit — let the surrounding route commit once.

    Usage:
        from app.models.audit_log import audit
        audit('RESULT_SAVED', actor_id=current_user.id,
              school_id=current_user.school_id,
              target_id=result.id, ip_address=request.remote_addr,
              detail=f'test={test_type} stage={stage}')
    """
    row = AuditLog(
        event_type=event_type,
        actor_id=actor_id,
        school_id=school_id,
        target_id=target_id,
        ip_address=ip_address,
        detail=detail,
    )
    db.session.add(row)