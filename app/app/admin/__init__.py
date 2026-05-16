from flask import Blueprint

# Create the admin blueprint
bp = Blueprint('admin', __name__)

# Import routes at the end to avoid circular imports
from app.admin import routes
