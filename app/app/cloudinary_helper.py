import cloudinary
import cloudinary.uploader
import cloudinary.api
import os

def init_cloudinary():
    """Initialize Cloudinary with credentials from environment variables."""
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key=os.environ.get('CLOUDINARY_API_KEY'),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET'),
        secure=True
    )

def upload_document(file, folder='documents'):
    """
    Upload a document to Cloudinary.
    Returns a dict with url and public_id on success, None on failure.
    """
    try:
        init_cloudinary()
        result = cloudinary.uploader.upload(
            file,
            folder=f'knowly/{folder}',
            resource_type='auto',  # Handles PDFs, images, docs etc
            use_filename=True,
            unique_filename=True
        )
        return {
            'url': result['secure_url'],
            'public_id': result['public_id'],
            'file_size': result.get('bytes', 0),
        }
    except Exception as e:
        print(f"❌ Cloudinary upload failed: {e}")
        return None

def delete_document(public_id):
    """
    Delete a document from Cloudinary by its public_id.
    """
    try:
        init_cloudinary()
        cloudinary.uploader.destroy(public_id, resource_type='raw')
        return True
    except Exception as e:
        print(f"❌ Cloudinary delete failed: {e}")
        return False