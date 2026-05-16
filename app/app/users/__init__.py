from flask import Blueprint

# Create the users blueprint
bp = Blueprint('users', __name__)

# Import routes at the end to avoid circular imports
from app.users import routes
