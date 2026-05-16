from flask import Blueprint

# Create the posts blueprint
bp = Blueprint('posts', __name__)

# Import routes at the end to avoid circular imports
from app.posts import routes
