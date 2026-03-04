"""
SESA Application Entry Point
Run with: python run.py  (development)
         gunicorn 'run:app' (production)
"""
import os
from app import create_app
from dotenv import load_dotenv
load_dotenv()


app = create_app(os.environ.get('FLASK_ENV', 'development'))

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=True
    )
