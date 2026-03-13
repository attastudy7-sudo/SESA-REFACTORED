"""
SMS notification service for SESA.

Supported providers (set SMS_PROVIDER in .env):
  arkesel       — https://arkesel.com  (recommended for Ghana)
  africastalking — https://africastalking.com

Required env vars (both providers):
  SMS_PROVIDER       = arkesel | africastalking
  SMS_API_KEY        = your API key
  SMS_SENDER_ID      = SESA  (or your registered sender ID)

Africa's Talking only:
  SMS_USERNAME       = your AT username (usually 'sandbox' for dev)
"""
import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

SMS_PROVIDER   = os.environ.get('SMS_PROVIDER', 'arkesel')
SMS_API_KEY    = os.environ.get('SMS_API_KEY', '')
SMS_SENDER_ID  = os.environ.get('SMS_SENDER_ID', 'SESA')
SMS_USERNAME   = os.environ.get('SMS_USERNAME', 'sandbox')  # Africa's Talking only


def send_sms(phone: str, message: str) -> bool:
    """
    Send a single SMS. Returns True on success, False on failure.
    Logs errors but never raises — a failed SMS must never crash a route.

    phone: E.164 format preferred, e.g. '+233201234567'
            Plain local format ('0201234567') is also accepted for Arkesel.
    """
    if not SMS_API_KEY:
        logger.warning('SMS_API_KEY not set — SMS not sent to %s', phone)
        return False

    try:
        if SMS_PROVIDER == 'arkesel':
            return _send_arkesel(phone, message)
        elif SMS_PROVIDER == 'africastalking':
            return _send_africastalking(phone, message)
        else:
            logger.error('Unknown SMS_PROVIDER: %s', SMS_PROVIDER)
            return False
    except Exception as exc:
        logger.error('SMS send failed | phone=%s error=%s', phone, exc)
        return False


def _send_arkesel(phone: str, message: str) -> bool:
    """Arkesel SMS API v2."""
    url = 'https://sms.arkesel.com/api/v2/sms/send'
    payload = {
        'sender': SMS_SENDER_ID,
        'message': message,
        'recipients': [phone],
    }
    resp = requests.post(
        url,
        json=payload,
        headers={'api-key': SMS_API_KEY},
        timeout=10,
    )
    data = resp.json()
    if resp.status_code == 200 and data.get('status') == 'success':
        logger.info('SMS sent via Arkesel | phone=%s', phone)
        return True
    logger.warning('Arkesel SMS failed | phone=%s response=%s', phone, data)
    return False


def _send_africastalking(phone: str, message: str) -> bool:
    """Africa's Talking SMS API."""
    url = 'https://api.africastalking.com/version1/messaging'
    payload = {
        'username': SMS_USERNAME,
        'to':       phone,
        'message':  message,
        'from':     SMS_SENDER_ID,
    }
    resp = requests.post(
        url,
        data=payload,
        headers={
            'apiKey': SMS_API_KEY,
            'Accept': 'application/json',
        },
        timeout=10,
    )
    data = resp.json()
    recipients = data.get('SMSMessageData', {}).get('Recipients', [])
    if recipients and recipients[0].get('status') == 'Success':
        logger.info('SMS sent via Africa\'s Talking | phone=%s', phone)
        return True
    logger.warning('AT SMS failed | phone=%s response=%s', phone, data)
    return False


def send_clinical_alert(counsellor_phone: str, student_name: str,
                        test_type: str, school_name: str) -> bool:
    """
    Pre-built message for a clinical-stage result alert.
    Keep under 160 chars so it fits in one SMS unit.
    """
    message = (
        f'SESA ALERT: {student_name} at {school_name} scored '
        f'Clinical Stage on {test_type}. '
        f'Please follow up as soon as possible.'
    )
    return send_sms(counsellor_phone, message)