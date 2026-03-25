"""
cloudinary_service.py — Photo upload for counsellor profiles.
Uploads to Cloudinary and returns a permanent URL.
"""
import os
import logging
import cloudinary
import cloudinary.uploader

logger = logging.getLogger(__name__)

cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
    secure=True,
)


def upload_counsellor_photo(file_storage, username: str) -> str | None:
    """
    Upload a counsellor profile photo to Cloudinary.
    Returns the secure URL or None on failure.
    file_storage: Werkzeug FileStorage object from the form.
    """
    if not all([os.environ.get('CLOUDINARY_CLOUD_NAME'),
                os.environ.get('CLOUDINARY_API_KEY'),
                os.environ.get('CLOUDINARY_API_SECRET')]):
        logger.error('Cloudinary env vars not set — cannot upload counsellor photo')
        return None
    try:
        result = cloudinary.uploader.upload(
            file_storage.stream,
            folder='sesa/counsellors',
            public_id=f'counsellor_{username}',
            overwrite=True,
            transformation=[
                {'width': 400, 'height': 400, 'crop': 'fill', 'gravity': 'face'},
                {'quality': 'auto', 'fetch_format': 'auto'},
            ],
        )
        return result.get('secure_url')
    except Exception as e:
        logger.error('Cloudinary upload failed | user=%s error=%s', username, e)
        return None

def upload_assessment_image(file_storage, assessment_name: str) -> str | None:
    """Upload an assessment type image to Cloudinary."""
    import re
    if not all([os.environ.get('CLOUDINARY_CLOUD_NAME'),
                os.environ.get('CLOUDINARY_API_KEY'),
                os.environ.get('CLOUDINARY_API_SECRET')]):
        logger.error('Cloudinary env vars not set — cannot upload assessment image')
        return None
    slug = re.sub(r'[^a-z0-9]', '_', assessment_name.lower())
    try:
        result = cloudinary.uploader.upload(
            file_storage.stream,
            folder='sesa/assessments',
            public_id=f'assessment_{slug}',
            overwrite=True,
            transformation=[
                {'width': 800, 'height': 320, 'crop': 'fill', 'gravity': 'auto'},
                {'quality': 'auto', 'fetch_format': 'auto'},
            ],
        )
        return result.get('secure_url')
    except Exception as e:
        logger.error('Cloudinary assessment image upload failed | name=%s error=%s', assessment_name, e)
        return None