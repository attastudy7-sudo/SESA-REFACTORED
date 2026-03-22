from app.extensions import db


class AssessmentType(db.Model):
    __tablename__ = 'assessment_type'

    id             = db.Column(db.Integer, primary_key=True)
    name           = db.Column(db.String(100), unique=True, nullable=False)
    display_name   = db.Column(db.String(100), nullable=False)
    description    = db.Column(db.Text, nullable=True)
    icon           = db.Column(db.String(10),  nullable=True)
    color          = db.Column(db.String(20),  nullable=True)
    order          = db.Column(db.Integer,     default=0, nullable=False)
    is_active      = db.Column(db.Boolean,     default=True, nullable=False)
    scoring_ranges = db.Column(db.JSON,        nullable=False)
    image_url      = db.Column(db.String(500), nullable=True)

    def __repr__(self):
        return f'<AssessmentType {self.name}>'