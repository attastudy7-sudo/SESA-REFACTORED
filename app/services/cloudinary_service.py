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
    try:
        result = cloudinary.uploader.upload(
            file_storage,
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