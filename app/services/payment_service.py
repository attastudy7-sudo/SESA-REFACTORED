"""
Paystack payment verification service.

TEST MODE
---------
Set PAYSTACK_TEST_MODE=True in your config (or env var PAYSTACK_TEST_MODE=1)
to bypass the real Paystack API entirely. Any reference string will be
treated as a successful payment for the configured amount. This lets you
click through the full payment flow locally without hitting real servers.
"""
import requests
from flask import current_app


def is_test_mode() -> bool:
    """Return True when running in Paystack test mode."""
    return bool(current_app.config.get('PAYSTACK_TEST_MODE', False))


def verify_paystack_payment(reference: str) -> dict:
    """
    Verify a Paystack payment by reference.

    In TEST MODE: returns a synthetic success payload immediately so the
    full activation code path runs without any network call.

    In LIVE MODE: hits the real Paystack verify endpoint.

    Returns the data dict from Paystack (real or synthetic) or raises on failure.
    """
    if is_test_mode():
        # Synthetic success — mirrors the shape Paystack actually returns
        amount = current_app.config.get('SUBSCRIPTION_AMOUNT', 10000)
        currency = current_app.config.get('SUBSCRIPTION_CURRENCY', 'GHS')
        return {
            'status': 'success',
            'reference': reference,
            'amount': amount,
            'currency': currency,
            'channel': 'test_bypass',
            'paid_at': None,
            'customer': {'email': 'test@sesa.local'},
            '_test_mode': True,
        }

    secret_key = current_app.config['PAYSTACK_SECRET_KEY']
    url = f'https://api.paystack.co/transaction/verify/{reference}'

    response = requests.get(
        url,
        headers={
            'Authorization': f'Bearer {secret_key}',
            'Content-Type': 'application/json',
        },
        timeout=10,
    )

    result = response.json()

    if not result.get('status'):
        raise ValueError(result.get('message', 'Paystack verification failed.'))

    return result['data']
