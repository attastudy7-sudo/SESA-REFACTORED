"""
Paystack payment verification service.
"""
import requests
from flask import current_app


def verify_paystack_payment(reference: str) -> dict:
    """
    Verify a Paystack payment by reference.
    Returns the data dict from Paystack or raises on failure.
    """
    secret_key = current_app.config['PAYSTACK_SECRET_KEY']
    url = f'https://api.paystack.co/transaction/verify/{reference}'

    response = requests.get(
        url,
        headers={
            'Authorization': f'Bearer {secret_key}',
            'Content-Type': 'application/json',
        },
        timeout=10
    )

    result = response.json()

    if not result.get('status'):
        raise ValueError(result.get('message', 'Paystack verification failed.'))

    return result['data']