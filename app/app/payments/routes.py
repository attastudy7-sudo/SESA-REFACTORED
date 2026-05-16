import hmac
import hashlib
import json
import requests
from datetime import datetime, timedelta, timezone
from flask import render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from app import db
from app.payments import bp
from app.models import Purchase, Document, User, Subscription


def _paystack_headers():
    """Return auth headers for Paystack API calls."""
    return {
        'Authorization': f"Bearer {current_app.config['PAYSTACK_SECRET_KEY']}",
        'Content-Type': 'application/json',
    }


@bp.route('/checkout/<int:document_id>')
@login_required
def checkout(document_id):
    """
    Show the checkout page for a paid document.
    Redirects away if the user already has access.
    """
    document = Document.query.get_or_404(document_id)

    # Guard: document must be paid
    if not document.is_paid:
        flash('This document is free — no purchase needed.', 'info')
        # document.post may be None if relationship not set; fall back to index
        post = document.post
        if post:
            return redirect(url_for('posts.view', post_id=post.id))
        return redirect(url_for('main.index'))

    # Guard: user already has access
    if document.has_access(current_user):
        flash('You already have access to this document.', 'info')
        post = document.post
        if post:
            return redirect(url_for('posts.view', post_id=post.id))
        return redirect(url_for('main.index'))

    # Guard: price must be a positive value
    if not document.price or document.price <= 0:
        flash('This document has an invalid price. Please contact support.', 'danger')
        return redirect(url_for('main.index'))

    # Price in pesewas (Paystack uses smallest currency unit; min 100 = GHS 1.00)
    amount_pesewas = int(document.price * 100)

    return render_template(
        'payments/checkout.html',
        title=f'Purchase — {document.original_filename}',
        document=document,
        amount_pesewas=amount_pesewas,
        paystack_public_key=current_app.config['PAYSTACK_PUBLIC_KEY'],
    )


@bp.route('/initiate/<int:document_id>', methods=['POST'])
@login_required
def initiate(document_id):
    """
    Create a Paystack transaction and redirect the user to
    Paystack's hosted payment page.
    """
    document = Document.query.get_or_404(document_id)
    post = document.post

    if not document.is_paid:
        if post:
            return redirect(url_for('posts.view', post_id=post.id))
        return redirect(url_for('main.index'))

    if document.has_access(current_user):
        flash('You already have access to this document.', 'info')
        if post:
            return redirect(url_for('posts.view', post_id=post.id))
        return redirect(url_for('main.index'))

    if not document.price or document.price <= 0:
        flash('This document has an invalid price.', 'danger')
        return redirect(url_for('main.index'))

    amount_pesewas = int(document.price * 100)
    callback_url   = url_for('payments.verify', document_id=document.id, _external=True)

    payload = {
        'email':        current_user.email,
        'amount':       amount_pesewas,
        'currency':     'GHS',
        'callback_url': callback_url,
        'metadata': {
            'user_id':     current_user.id,
            'document_id': document.id,
            'custom_fields': [
                {
                    'display_name': 'Document',
                    'variable_name': 'document_name',
                    'value': document.original_filename,
                },
                {
                    'display_name': 'Buyer',
                    'variable_name': 'buyer_username',
                    'value': current_user.username,
                },
            ],
        },
    }

    try:
        response = requests.post(
            'https://api.paystack.co/transaction/initialize',
            headers=_paystack_headers(),
            json=payload,
            timeout=15,
        )
        data = response.json()

        if data.get('status'):
            return redirect(data['data']['authorization_url'])
        else:
            current_app.logger.error(f"Paystack init failed for doc {document.id}: {data}")
            flash('Payment could not be initiated. Please try again.', 'danger')
            return redirect(url_for('payments.checkout', document_id=document.id))

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Paystack request error: {e}")
        flash('A network error occurred. Please try again.', 'danger')
        return redirect(url_for('payments.checkout', document_id=document.id))


"""
ADD THESE TO: app/payments/routes.py
─────────────────────────────────────
Paste after the existing imports and before (or after) the existing routes.
Also add the Subscription model import once you create it (see models section below).
"""

# ── Add to existing imports at top of routes.py ──────────────────────────────
# from app.models import Document, Purchase, Subscription   ← add Subscription
# from datetime import datetime, timedelta                  ← add this
# (requests, hmac, hashlib, json, flask imports already present)


# ═══════════════════════════════════════════════════════════════════════════════
# PLAN REGISTRY
# Single source of truth for all subscription plans.
# Add more plans here without touching route logic.
# ═══════════════════════════════════════════════════════════════════════════════

PLANS = {
    'semester_unlimited': {
        'name':          'Semester Pass',
        'amount_ghs':    45.00,
        'duration_days': 120,
        'description':   'Unlimited quizzes for a full semester',
        'best_value':    True,
        'per_month_ghs': 11.00,
        'features': [
            'Unlimited quiz attempts',
            'Full answer explanations',
            'Leaderboard access',
            'Priority grading',
        ],
    },
    'monthly_unlimited': {
        'name':          'Monthly Pass',
        'amount_ghs':    18.00,
        'duration_days': 30,
        'description':   'Unlimited quizzes for 30 days',
        'best_value':    False,
        'per_month_ghs': 18.00,
        'features': [
            'Unlimited quiz attempts',
            'Full answer explanations',
            'Leaderboard access',
            'Priority grading',
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE 1 — /checkout  (plan-based, replaces the quiz upgrade url_for target)
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route('/checkout/plan')
@login_required
def plan_checkout():
    """
    Unified checkout entry point.

    Handles two call signatures:
      A) Plan checkout (from quiz upgrade):
           /checkout/plan?plan=monthly_unlimited&amount=20&currency=GHS&source=quiz&post_id=5

      B) Document checkout (existing behaviour, backward-compatible):
           /checkout/<int:document_id>  — kept as separate route below

    Query params (plan checkout):
      plan     : key from PLANS dict
      amount   : display amount in GHS (validated against PLANS; not trusted for billing)
      currency : expected 'GHS'
      source   : where the user came from ('quiz', 'profile', etc.)
      post_id  : optional, used for back-link after payment
    """
    plan_key = request.args.get('plan', '').strip()

    # ── Plan checkout path ────────────────────────────────────────────────────
    if plan_key:
        plan = PLANS.get(plan_key)
        if not plan:
            flash('Unknown subscription plan.', 'danger')
            return redirect(url_for('main.index'))

        # Guard: already subscribed
        if _user_has_active_subscription(current_user):
            flash('You already have an active subscription.', 'info')
            post_id = request.args.get('post_id')
            if post_id:
                return redirect(url_for('posts.view', post_id=post_id))
            return redirect(url_for('main.index'))

        source  = request.args.get('source', 'unknown')
        post_id = request.args.get('post_id')

        amount_pesewas = int(plan['amount_ghs'] * 100)

        return render_template(
                    'payments/checkout.html',
                    title='Upgrade to Unlimited',
                    plan_key=plan_key,
                    plan_name=plan['name'],
                    amount=plan['amount_ghs'],
                    amount_pesewas=amount_pesewas,
                    paystack_public_key=current_app.config['PAYSTACK_PUBLIC_KEY'],
                    verify_url=url_for('payments.subscribe_verify', _external=False),
                    fallback_url=url_for('payments.subscribe_initiate'),
                    next_url=request.args.get('next', ''))


    # ── No plan param → wrong endpoint, send to index ────────────────────────
    flash('No plan selected.', 'warning')
    return redirect(url_for('main.index'))


# ── Keep the original document checkout as its own route ─────────────────────
# (already exists as /checkout/<int:document_id> — no changes needed there)


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE 2 — /subscribe/initiate  (server-side Paystack init for plans)
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route('/subscribe/initiate', methods=['POST'])
@login_required
def subscribe_initiate():
    """
    Create a Paystack transaction for a subscription plan and redirect
    the user to Paystack's hosted payment page (fallback path).
    """
    plan_key = request.form.get('plan_key', '').strip()
    post_id  = request.form.get('post_id', '').strip()
    source   = request.form.get('source', 'unknown')

    plan = PLANS.get(plan_key)
    if not plan:
        flash('Invalid plan.', 'danger')
        return redirect(url_for('main.index'))

    if _user_has_active_subscription(current_user):
        flash('You already have an active subscription.', 'info')
        if post_id:
            return redirect(url_for('posts.view', post_id=post_id))
        return redirect(url_for('main.index'))

    amount_pesewas = int(plan['amount_ghs'] * 100)
    callback_url   = url_for(
        'payments.subscribe_verify',
        plan_key=plan_key,
        post_id=post_id or '',
        _external=True,
    )

    payload = {
            'email':        current_user.email,
            'amount':       amount_pesewas,
            'currency':     'GHS',
            'callback_url': callback_url,
            'metadata': {
                            'user_id':  current_user.id,
                            'plan_key': plan_key,
                            'type':     'subscription',
                            'custom_fields': [
                                {'display_name': 'Plan',  'variable_name': 'plan_name',      'value': plan['name']},
                                {'display_name': 'Buyer', 'variable_name': 'buyer_username', 'value': current_user.username},
                            ],
            }
    }

    try:
        response = requests.post(
            'https://api.paystack.co/transaction/initialize',
            headers=_paystack_headers(),
            json=payload,
            timeout=15,
        )
        data = response.json()

        if data.get('status'):
            return redirect(data['data']['authorization_url'])
        else:
            current_app.logger.error(f"Paystack init failed: {data}")
            flash('Payment could not be initiated. Please try again.', 'danger')
            return redirect(url_for('payments.plan_checkout', plan=plan_key))

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Paystack request error: {e}")
        flash('A network error occurred. Please try again.', 'danger')
        return redirect(url_for('payments.plan_checkout', plan=plan_key))


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTE 3 — /subscribe/verify  (called by Paystack redirect after payment)
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route('/subscribe/verify')
@login_required
def subscribe_verify():
    """
    Paystack redirects here after subscription payment.
    Verifies server-side, records Subscription, grants access.
    """
    reference = request.args.get('reference', '').strip()
    plan_key  = request.args.get('plan_key', '').strip()
    post_id   = request.args.get('post_id', '').strip()

    plan = PLANS.get(plan_key)
    if not plan:
        flash('Unknown plan in callback.', 'danger')
        return redirect(url_for('main.index'))

    if not reference:
        flash('Invalid payment reference.', 'danger')
        return redirect(url_for('payments.plan_checkout', plan=plan_key))

    # Idempotency guard
    existing = Subscription.query.filter_by(transaction_id=reference).first()
    if existing:
        flash('This payment has already been processed.', 'info')
        if post_id:
            return redirect(url_for('posts.view', post_id=post_id))
        return redirect(url_for('main.index'))

    try:
        response = requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers=_paystack_headers(),
            timeout=15,
        )
        data = response.json()

        if not data.get('status'):
            flash('Payment verification failed. Please contact support.', 'danger')
            return redirect(url_for('payments.plan_checkout', plan=plan_key))

        tx              = data['data']
        expected_pesewas = int(plan['amount_ghs'] * 100)

        if tx['status'] == 'success' and tx['amount'] >= expected_pesewas:
            # ── Grant subscription ────────────────────────────────────────────
            now        = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=plan['duration_days'])

            subscription = Subscription(
                user_id=current_user.id,
                plan_key=plan_key,
                plan_name=plan['name'],
                amount_paid=tx['amount'] / 100,
                currency='GHS',
                payment_method=tx.get('channel', 'paystack'),
                transaction_id=reference,
                status='active',
                started_at=now,
                expires_at=expires_at,
            )
            db.session.add(subscription)
            db.session.commit()

            # Optional: send confirmation email
            try:
                from app.utils import send_subscription_activation_email
                send_subscription_activation_email(current_user, plan_key)
            except Exception as email_err:
                current_app.logger.warning(f"Sub confirmation email failed: {email_err}")

            flash(
                f'🎉 Subscription activated! You have unlimited access for {plan["duration_days"]} days.',
                'success'
            )
            if post_id:
                return redirect(url_for('posts.view', post_id=post_id))
            return redirect(url_for('main.index'))

        else:
            # Payment exists but failed / cancelled
            failed_sub = Subscription(
                user_id=current_user.id,
                plan_key=plan_key,
                plan_name=plan['name'],
                amount_paid=0,
                currency='GHS',
                payment_method=tx.get('channel', 'paystack'),
                transaction_id=reference,
                status=tx['status'],
                started_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc),
            )
            db.session.add(failed_sub)
            db.session.commit()

            flash(
                f'Payment was not completed (status: {tx["status"]}). No charge was made.',
                'warning'
            )
            return redirect(url_for('payments.plan_checkout', plan=plan_key))

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Paystack subscribe verify error: {e}")
        flash(
            f'Could not verify payment. Please contact support with reference: {reference}',
            'danger'
        )
        return redirect(url_for('payments.plan_checkout', plan=plan_key))


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOK ADDITION — handle subscription charge.success events
# ═══════════════════════════════════════════════════════════════════════════════
# In your existing webhook() route, add this block inside the
# `if event.get('event') == 'charge.success':` handler,
# AFTER the existing document purchase logic:

"""
        # ── Subscription payment via webhook ──────────────────────────────
        plan_key = metadata.get('plan_key')
        if plan_key and metadata.get('type') == 'subscription':
            plan = PLANS.get(plan_key)
            if plan and not Subscription.query.filter_by(transaction_id=reference).first():
                now = datetime.now(timezone.utc)
                sub = Subscription(
                    user_id=user_id,
                    plan_key=plan_key,
                    plan_name=plan['name'],
                    amount_paid=tx['amount'] / 100,
                    currency='GHS',
                    payment_method=tx.get('channel', 'paystack'),
                    transaction_id=reference,
                    status='active',
                    started_at=now,
                    expires_at=now + timedelta(days=plan['duration_days']),
                )
                db.session.add(sub)
                db.session.commit()
"""


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER — check active subscription (used in routes above + quiz template)
# ═══════════════════════════════════════════════════════════════════════════════

def _user_has_active_subscription(user) -> bool:
    """
    Returns True if the user has a currently active subscription.
    """
    from datetime import datetime
    sub = Subscription.query.filter_by(
        user_id=user.id,
        status='active',
    ).filter(
        Subscription.expires_at > datetime.now(timezone.utc)
    ).first()
    return sub is not None
    

@bp.route('/verify/<int:document_id>')
@login_required
def verify(document_id):
    """
    Paystack redirects here after payment with a ?reference= param.
    We verify the transaction server-side before granting access.
    """
    document  = Document.query.get_or_404(document_id)
    post      = document.post
    reference = request.args.get('reference', '').strip()

    if not reference:
        flash('Invalid payment reference.', 'danger')
        return redirect(url_for('payments.checkout', document_id=document.id))

    # Idempotency: don't process the same reference twice
    existing = Purchase.query.filter_by(transaction_id=reference).first()
    if existing:
        flash('This payment has already been processed.', 'info')
        if post:
            return redirect(url_for('posts.view', post_id=post.id))
        return redirect(url_for('main.index'))

    try:
        response = requests.get(
            f'https://api.paystack.co/transaction/verify/{reference}',
            headers=_paystack_headers(),
            timeout=15,
        )
        data = response.json()

        if not data.get('status'):
            flash('Payment verification failed. Please contact support.', 'danger')
            return redirect(url_for('payments.checkout', document_id=document.id))

        tx = data['data']
        expected_pesewas = int(document.price * 100)

        if tx['status'] == 'success' and tx['amount'] >= expected_pesewas:
            purchase = Purchase(
                user_id=current_user.id,
                document_id=document.id,
                amount_paid=tx['amount'] / 100,
                payment_method=tx.get('channel', 'paystack'),
                transaction_id=reference,
                status='completed',
            )
            db.session.add(purchase)
            db.session.commit()

            # Send purchase confirmation email
            from app.utils import send_purchase_confirmation_email
            send_purchase_confirmation_email(current_user, purchase, document)

            flash(
                f'Payment successful! You now have full access to '
                f'"{document.original_filename}".',
                'success'
            )
            if post:
                return redirect(url_for('posts.view', post_id=post.id))
            return redirect(url_for('main.index'))

        else:
            # Payment exists but wasn't successful
            purchase = Purchase(
                user_id=current_user.id,
                document_id=document.id,
                amount_paid=0,
                payment_method=tx.get('channel', 'paystack'),
                transaction_id=reference,
                status=tx['status'],
            )
            db.session.add(purchase)
            db.session.commit()

            flash(
                f'Payment was not completed (status: {tx["status"]}). '
                f'No charge was made.',
                'warning'
            )
            return redirect(url_for('payments.checkout', document_id=document.id))

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Paystack verify error: {e}")
        flash(
            f'Could not verify payment. Please contact support with your reference: {reference}',
            'danger'
        )
        return redirect(url_for('payments.checkout', document_id=document.id))


@bp.route('/webhook', methods=['POST'])
def webhook():
    """
    Paystack webhook — receives async payment events.
    Set this URL in your Paystack dashboard under Settings → Webhooks.
    """
    paystack_signature = request.headers.get('X-Paystack-Signature', '')
    secret             = current_app.config['PAYSTACK_SECRET_KEY'].encode()
    body               = request.get_data()

    # FIX: was hmac.new() which does not exist — correct call is hmac.new()
    # Python's hmac module: hmac.new(key, msg=None, digestmod='')
    expected_sig = hmac.new(secret, body, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected_sig, paystack_signature):
        current_app.logger.warning('Invalid Paystack webhook signature')
        return jsonify({'status': 'invalid signature'}), 400

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        return jsonify({'status': 'bad json'}), 400

    if event.get('event') == 'charge.success':
            tx        = event['data']
            reference = tx.get('reference')
            metadata  = tx.get('metadata', {})
            user_id   = metadata.get('user_id')

            # ── Subscription payment ──────────────────────────────────────────────
            plan_key = metadata.get('plan_key')
            if plan_key and metadata.get('type') == 'subscription':
                plan = PLANS.get(plan_key)
                if plan and not Subscription.query.filter_by(transaction_id=reference).first():
                    now = datetime.now(timezone.utc)
                    sub = Subscription(
                        user_id=user_id,
                        plan_key=plan_key,
                        plan_name=plan['name'],
                        amount_paid=tx['amount'] / 100,
                        currency='GHS',
                        payment_method=tx.get('channel', 'paystack'),
                        transaction_id=reference,
                        status='active',
                        started_at=now,
                        expires_at=now + timedelta(days=plan['duration_days']),
                    )
                    db.session.add(sub)
                    db.session.commit()
                    current_app.logger.info(
                        f"Webhook: subscription activated plan={plan_key} user={user_id}"
                    )
                return jsonify({'status': 'ok'}), 200

            # ── Document purchase ─────────────────────────────────────────────────
            document_id = metadata.get('document_id')

            if not all([reference, user_id, document_id]):
                return jsonify({'status': 'missing metadata'}), 200

            if Purchase.query.filter_by(transaction_id=reference).first():
                return jsonify({'status': 'already processed'}), 200

            document = db.session.get(Document, document_id)
            if not document:
                return jsonify({'status': 'document not found'}), 200

            purchase = Purchase(
                user_id=user_id,
                document_id=document_id,
                amount_paid=tx['amount'] / 100,
                payment_method=tx.get('channel', 'paystack'),
                transaction_id=reference,
                status='completed',
            )
            db.session.add(purchase)
            db.session.commit()

            from app.utils.emails import send_purchase_confirmation_email
            user = db.session.get(User, user_id)
            send_purchase_confirmation_email(user, purchase, document)

            current_app.logger.info(
                f"Webhook: purchase recorded for doc {document_id} by user {user_id}"
            )
    return jsonify({'status': 'ok'}), 200


@bp.route('/my-purchases')
@login_required
def my_purchases():
    """Show the current user's purchase history."""
    purchases = Purchase.query.filter_by(
        user_id=current_user.id,
        status='completed'
    ).order_by(Purchase.purchased_at.desc()).all()

    return render_template(
        'payments/my_purchases.html',
        title='My Purchases',
        purchases=purchases,
    )

@bp.route('/my-subscription')
@login_required
def my_subscription():
    """Show the current user's active subscription and billing history."""
    from datetime import datetime

    # Active subscription: latest active row that hasn't expired
    active_sub = (
        Subscription.query
        .filter_by(user_id=current_user.id, status='active')
        .filter(Subscription.expires_at > datetime.now(timezone.utc))
        .order_by(Subscription.expires_at.desc())
        .first()
    )

    # Full billing history (all statuses, newest first)
    history = (
        Subscription.query
        .filter_by(user_id=current_user.id)
        .order_by(Subscription.created_at.desc())
        .all()
    )

    return render_template(
        'payments/my_subscription.html',
        title='My Subscription',
        active_sub=active_sub,
        history=history,
        plans=PLANS,
        now=datetime.now(timezone.utc),
    )