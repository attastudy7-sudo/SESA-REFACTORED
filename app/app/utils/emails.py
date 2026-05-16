# ─────────────────────────────────────────────────────────────────────────────
# EMAIL VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────
def send_verification_email(user):
  """Send an email verification link to the user."""
  base = _base_url()
  from app.auth.routes import generate_verification_token
  token = generate_verification_token(user)
  verify_url = f"{base}/verify-email?token={token}"
  subject = "Verify your email for knowly"
  html_content = f"""
  <h1>Verify your email</h1>
  <p>Hi {user.nickname or user.username},</p>
  <p>Click the link below to verify your email address and activate your account:</p>
  <p><a href='{verify_url}' style='background:#2563eb;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;'>Verify Email</a></p>
  <p>If you did not sign up, you can ignore this email.</p>
  """
  return _send_brevo_email(user.email, subject, html_content)

# You will need to implement generate_verification_token(user) and a /verify-email route to handle the token.
"""
Email notification service for knowly platform.

Handles automatic email notifications for:
- New user signups (welcome emails)
- Purchase confirmations
- Subscription activations
- Programme-relevant post notifications
- Password resets
"""

import requests
from flask import current_app
from app import db
from app.models import User, Purchase, Document


# ─────────────────────────────────────────────────────────────────────────────
# SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _base_url():
    scheme = current_app.config.get('PREFERRED_URL_SCHEME', 'https')
    host   = current_app.config.get('SERVER_NAME', 'knowly-ly8l.onrender.com')
    return f"{scheme}://{host}"


def _send_brevo_email(to_email, subject, html_content):
    """
    Send an email via the Brevo (Sendinblue) API.

    Returns:
        bool: True if the email was accepted (HTTP 201).
    """
    api_key = current_app.config.get('BREVO_API_KEY')
    if not api_key:
        current_app.logger.error('BREVO_API_KEY not configured')
        return False

    sender = (
        current_app.config.get('MAIL_DEFAULT_SENDER') or
        current_app.config.get('MAIL_USERNAME')
    )
    if not sender:
        current_app.logger.error('MAIL_DEFAULT_SENDER or MAIL_USERNAME not configured')
        return False

    try:
        response = requests.post(
            'https://api.brevo.com/v3/smtp/email',
            headers={'api-key': api_key, 'Content-Type': 'application/json'},
            json={
                'sender': {'name': 'knowly', 'email': sender},
                'to': [{'email': to_email}],
                'subject': subject,
                'htmlContent': html_content,
            },
            timeout=15,
        )
        if response.status_code == 201:
            current_app.logger.info(f'Email sent to {to_email}')
            return True
        current_app.logger.error(f'Brevo error for {to_email}: {response.text}')
        return False
    except Exception as e:
        current_app.logger.error(f'Failed to send email to {to_email}: {e}')
        return False


# ─────────────────────────────────────────────────────────────────────────────
# SHARED EMAIL SHELL  (dark card, blue-to-teal gradient header)
# ─────────────────────────────────────────────────────────────────────────────

def _email_shell(header_html: str, body_html: str) -> str:
    """
    Wrap content in the knowly branded email shell.

    Args:
        header_html: Content placed inside the gradient header card.
        body_html:   Content placed in the body area.
    """
    base = _base_url()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>knowly</title>
<style>
  body, table, td, p, a {{ margin:0; padding:0; border:0; }}
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    background-color: #060d1f;
    color: #f1f5f9;
    -webkit-font-smoothing: antialiased;
  }}
  .outer {{
    width: 100%;
    background-color: #060d1f;
    padding: 32px 16px 48px;
  }}
  .card {{
    max-width: 580px;
    margin: 0 auto;
    background-color: #0f1629;
    border: 1px solid #1e2a45;
    border-radius: 16px;
    overflow: hidden;
  }}
  .card-header {{
    background: linear-gradient(135deg, #2563eb 0%, #06b6d4 100%);
    padding: 28px 28px 24px;
    text-align: center;
  }}
  .brand {{
    display: inline-block;
    margin-bottom: 16px;
    text-decoration: none;
  }}
  .brand img {{
    width: 40px;
    height: 40px;
    border-radius: 10px;
    vertical-align: middle;
    margin-right: 8px;
  }}
  .brand-name {{
    font-size: 20px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: -0.03em;
    vertical-align: middle;
  }}
  .header-title {{
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
    line-height: 1.3;
    margin: 0 0 6px;
  }}
  .header-sub {{
    font-size: 14px;
    color: rgba(255,255,255,0.8);
    margin: 0;
  }}
  .card-body {{
    padding: 28px 28px 24px;
    color: #cbd5e1;
    font-size: 15px;
    line-height: 1.7;
  }}
  .card-body p {{ margin-bottom: 14px; }}
  .card-body p:last-child {{ margin-bottom: 0; }}
  .card-body strong {{ color: #f1f5f9; }}
  .card-body a {{ color: #60a5fa; }}
  .info-box {{
    background: #1a2540;
    border: 1px solid #2e3f66;
    border-radius: 10px;
    padding: 16px 18px;
    margin: 20px 0;
    font-size: 14px;
  }}
  .info-box p {{ margin-bottom: 8px; color: #94a3b8; }}
  .info-box p:last-child {{ margin-bottom: 0; }}
  .info-box strong {{ color: #e2e8f0; }}
  .btn-wrap {{ text-align: center; margin: 24px 0; }}
  .btn {{
    display: inline-block;
    background: linear-gradient(135deg, #2563eb 0%, #06b6d4 100%);
    color: #ffffff !important;
    font-size: 15px;
    font-weight: 700;
    text-decoration: none;
    padding: 14px 32px;
    border-radius: 10px;
    letter-spacing: 0.01em;
  }}
  .warning {{
    background: #2a1e10;
    border: 1px solid #4a3010;
    border-radius: 8px;
    padding: 12px 16px;
    color: #fcd34d;
    font-size: 13px;
    margin-top: 18px;
  }}
  .benefits {{
    background: #1a2540;
    border: 1px solid #2e3f66;
    border-radius: 10px;
    padding: 16px 18px;
    margin: 20px 0;
  }}
  .benefits h3 {{
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #60a5fa;
    margin: 0 0 10px;
  }}
  .benefits ul {{ padding-left: 18px; margin: 0; }}
  .benefits li {{
    color: #cbd5e1;
    font-size: 14px;
    margin-bottom: 7px;
    line-height: 1.5;
  }}
  .card-footer {{
    border-top: 1px solid #1e2a45;
    padding: 16px 28px;
    text-align: center;
    font-size: 12px;
    color: #475569;
    line-height: 1.6;
  }}
  .card-footer a {{ color: #475569; text-decoration: underline; }}
</style>
</head>
<body>
<div class="outer">
  <div class="card">

    <div class="card-header">
      <a href="{base}" class="brand">
        <img src="{base}/static/images/knowly.png" alt="knowly">
        <span class="brand-name">knowly</span>
      </a>
      {header_html}
    </div>

    <div class="card-body">
      {body_html}
    </div>

    <div class="card-footer">
      <p><strong style="color:#64748b;">knowly</strong> — Empowering Students Through Shared Knowledge</p>
      <p style="margin-top:6px;">
        <a href="{base}">Home</a> &nbsp;·&nbsp;
        <a href="{base}/explore">Explore</a> &nbsp;·&nbsp;
        <a href="{base}/library">Library</a>
      </p>
    </div>

  </div>
</div>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# WELCOME EMAIL
# ─────────────────────────────────────────────────────────────────────────────

def send_welcome_email(user):
    """Send a welcome email to a new user."""
    base = _base_url()
    name = user.nickname or user.username

    header = """
      <h1 class="header-title">Welcome to knowly! 👋</h1>
      <p class="header-sub">Your study hub is ready</p>
    """

    body = f"""
      <!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>Welcome to knowly</title>
</head>
<body style="margin:0;padding:0;background:#060d1f;font-family:'Segoe UI',Arial,sans-serif;">

<!-- Preheader -->
<div style="display:none;max-height:0;overflow:hidden;font-size:1px;color:#060d1f;">
  You just joined knowly — your first quiz is waiting. 🎯
</div>

<!-- Outer wrapper -->
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#060d1f;">
  <tr>
    <td align="center" style="padding:32px 16px 48px;">

      <!-- Card -->
      <table width="580" cellpadding="0" cellspacing="0" border="0" style="max-width:580px;width:100%;background:#0f1629;border:1px solid #1e2a45;border-radius:16px;overflow:hidden;">

        <!-- Top accent bar -->
        <tr>
          <td style="height:4px;background:linear-gradient(90deg,#2563eb,#06b6d4);font-size:0;line-height:0;">&nbsp;</td>
        </tr>

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#0d1b3e 0%,#091628 100%);padding:32px 32px 28px;text-align:center;">

            <!-- Logo -->
            <table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto 20px;">
              <tr>
                <td style="vertical-align:middle;padding-right:8px;">
                  <img src="https://knowly-ly8l.onrender.com/static/images/knowly.png"
                       alt="knowly" width="36" height="36"
                       style="display:block;border-radius:8px;">
                </td>
                <td style="vertical-align:middle;">
                  <span style="font-size:22px;font-weight:800;letter-spacing:-0.03em;background:linear-gradient(135deg,#2563eb,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;color:#2563eb;">knowly</span>
                </td>
              </tr>
            </table>

            <!-- Emoji + headline -->
            <p style="margin:0 0 10px;font-size:36px;line-height:1;">🎯</p>
            <h1 style="margin:0 0 8px;font-size:24px;font-weight:800;color:#ffffff;line-height:1.2;letter-spacing:-0.02em;">
              Chale, you don land! Welcome.
            </h1>
            <p style="margin:0;font-size:14px;color:rgba(255,255,255,0.65);line-height:1.5;">
              Your first quiz is waiting — go show yourself 💪
            </p>

          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:28px 32px 8px;">

            <p style="margin:0 0 16px;font-size:15px;color:#cbd5e1;line-height:1.7;">
              Hey <strong style="color:#f1f5f9;">{name}</strong>,
            </p>
            <p style="margin:0 0 16px;font-size:15px;color:#cbd5e1;line-height:1.7;">
              Welcome to knowly — the study platform wey Ghanaian students dey use to pass their exams. Notes, quizzes, past papers — everything dey inside.
            </p>
            <p style="margin:0 0 24px;font-size:15px;color:#cbd5e1;line-height:1.7;">
              The best way to start? <strong style="color:#f1f5f9;">Take your first quiz.</strong> See how you stand, earn your first XP, and make the streak begin. 🔥
            </p>

            <!-- Quiz CTA -->
            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-bottom:28px;">
              <tr>
                <td align="center">
                  <a href="https://knowly-ly8l.onrender.com/index"
                     style="display:inline-block;background:linear-gradient(135deg,#2563eb,#06b6d4);color:#ffffff;font-size:15px;font-weight:700;text-decoration:none;padding:14px 36px;border-radius:10px;letter-spacing:0.01em;">
                    Practice My First Quiz &nbsp;→
                  </a>
                </td>
              </tr>
            </table>

            <!-- Divider -->
            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-bottom:24px;">
              <tr><td style="height:1px;background:linear-gradient(90deg,transparent,#1e2a45,transparent);font-size:0;">&nbsp;</td></tr>
            </table>

            <!-- What else is here -->
            <p style="margin:0 0 14px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:#475569;">While you dey here, check out</p>

            <!-- Feature row 1 -->
            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-bottom:12px;">
              <tr>
                <td width="36" valign="top" style="padding-top:2px;">
                  <div style="width:28px;height:28px;background:rgba(37,99,235,0.15);border-radius:8px;text-align:center;line-height:28px;font-size:14px;">📚</div>
                </td>
                <td style="padding-left:12px;" valign="top">
                  <p style="margin:0 0 2px;font-size:14px;font-weight:700;color:#f1f5f9;">Notes & Cheatsheets</p>
                  <p style="margin:0;font-size:13px;color:#64748b;line-height:1.5;">Exam-focused materials for your exact courses</p>
                </td>
              </tr>
            </table>

            <!-- Feature row 2 -->
            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-bottom:12px;">
              <tr>
                <td width="36" valign="top" style="padding-top:2px;">
                  <div style="width:28px;height:28px;background:rgba(124,58,237,0.15);border-radius:8px;text-align:center;line-height:28px;font-size:14px;">📄</div>
                </td>
                <td style="padding-left:12px;" valign="top">
                  <p style="margin:0 0 2px;font-size:14px;font-weight:700;color:#f1f5f9;">Past Papers</p>
                  <p style="margin:0;font-size:13px;color:#64748b;line-height:1.5;">Practice with real exam questions from your school</p>
                </td>
              </tr>
            </table>

            <!-- Feature row 3 -->
            <table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin-bottom:28px;">
              <tr>
                <td width="36" valign="top" style="padding-top:2px;">
                  <div style="width:28px;height:28px;background:rgba(16,185,129,0.15);border-radius:8px;text-align:center;line-height:28px;font-size:14px;">🤝</div>
                </td>
                <td style="padding-left:12px;" valign="top">
                  <p style="margin:0 0 2px;font-size:14px;font-weight:700;color:#f1f5f9;">Community Uploads</p>
                  <p style="margin:0;font-size:13px;color:#64748b;line-height:1.5;">Share your notes, download others — together e go better</p>
                </td>
              </tr>
            </table>

            <!-- Sign off -->
            <p style="margin:0 0 4px;font-size:15px;color:#cbd5e1;line-height:1.7;">
              We dey root for you. 🙏
            </p>
            <p style="margin:0 0 28px;font-size:15px;color:#cbd5e1;">
              — Alan & the knowly team
            </p>

          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="border-top:1px solid #1e2a45;padding:16px 32px;text-align:center;">
            <p style="margin:0 0 6px;font-size:12px;color:#334155;">
              <strong style="color:#475569;">knowly</strong> — Empowering Students Through Shared Knowledge
            </p>
            <p style="margin:0;font-size:12px;color:#334155;">
              <a href="https://knowly-ly8l.onrender.com" style="color:#475569;text-decoration:underline;">Home</a>
              &nbsp;·&nbsp;
              <a href="https://knowly-ly8l.onrender.com/explore" style="color:#475569;text-decoration:underline;">Explore</a>
              &nbsp;·&nbsp;
              <a href="https://knowly-ly8l.onrender.com/library" style="color:#475569;text-decoration:underline;">Library</a>
            </p>
          </td>
        </tr>

      </table>
      <!-- /Card -->

    </td>
  </tr>
</table>

</body>
</html>"""

    return _send_brevo_email(
        user.email,
        'Welcome to knowly — Your Study Hub is Ready 🎉',
        _email_shell(header, body),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PURCHASE CONFIRMATION
# ─────────────────────────────────────────────────────────────────────────────

def send_purchase_confirmation_email(user, purchase, document):
    """Send a purchase confirmation email."""
    base = _base_url()
    name = user.nickname or user.username

    header = """
      <h1 class="header-title">Purchase Confirmed ✅</h1>
      <p class="header-sub">You now have full access to the document</p>
    """

    body = f"""
      <p>Hi <strong>{name}</strong>,</p>
      <p>Chale, your payment went through successfully. You now get full access
         to the document below.</p>
      <div class="info-box">
        <p><strong>Document:</strong> {document.original_filename}</p>
        <p><strong>Amount Paid:</strong> GHS {purchase.amount_paid:.2f}</p>
        <p><strong>Transaction ID:</strong> {purchase.transaction_id}</p>
        <p><strong>Date:</strong> {purchase.purchased_at.strftime('%d %b %Y, %H:%M UTC')}</p>
      </div>
      <div class="btn-wrap">
        <a href="{base}/payments/my-purchases" class="btn">View My Purchases →</a>
      </div>
      <p>Every purchase you make supports the growth of knowly. You're not just
         buying notes — you're investing in a bigger student community. We truly
         appreciate you for that.</p>
      <p>If you have any questions about your purchase or need help accessing
         the document, reach out to our support team anytime.</p>
      <p>Thank you, and more wins ahead!<br><strong>The knowly Team</strong></p>
    """

    return _send_brevo_email(
        user.email,
        'Purchase Confirmed — knowly',
        _email_shell(header, body),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SUBSCRIPTION ACTIVATION
# ─────────────────────────────────────────────────────────────────────────────

def send_subscription_activation_email(user, tier=None):
    """Send a subscription activation email."""
    base = _base_url()
    name = user.nickname or user.username
    subscription_tier = tier or user.subscription_tier
    tier_label = subscription_tier.capitalize()

    benefits_map = {
        'pro': [
            '✨ Unlimited document downloads',
            '🎯 Unlimited quiz attempts',
            '🚀 Priority support',
            '📊 Advanced analytics',
            '💾 Cloud storage for your documents',
        ],
        'enterprise': [
            '✨ All Pro features',
            '🏢 Team collaboration tools',
            '🔒 Custom security settings',
            '📈 Custom reporting',
            '🎓 Dedicated account manager',
            '⏰ 24/7 priority support',
        ],
    }
    tier_benefits = benefits_map.get(subscription_tier, [])
    benefits_html = ''.join(f'<li>{b}</li>' for b in tier_benefits)

    header = f"""
      <h1 class="header-title">Welcome to knowly {tier_label}! 🚀</h1>
      <p class="header-sub">Your subscription is now active</p>
    """

    body = f"""
      <p>Hi <strong>{name}</strong>,</p>
      <p>Big congratulations! Your <strong>{tier_label}</strong> subscription has
         activated successfully. You now have full access to all premium features
         on knowly.</p>
      <div class="benefits">
        <h3>Your {tier_label} Benefits</h3>
        <ul>{benefits_html}</ul>
      </div>
      <div class="btn-wrap">
        <a href="{base}/explore" class="btn">Start Exploring →</a>
      </div>
      <p>Your subscription stays active until
         <strong>{user.subscription_end_date.strftime('%d %b %Y')}</strong>.
         Make sure to enjoy every benefit that comes with it.</p>
      <p>By upgrading, you join the core group of students pushing knowly forward.
         Your support helps us build better tools, improve quality, and grow the
         community stronger every day. We truly appreciate you for believing in
         the vision.</p>
      <p>If you have any questions, our support team is always here.</p>
      <p>Let's level up!<br><strong>The knowly Team</strong></p>
    """

    return _send_brevo_email(
        user.email,
        f'Subscription Activated — knowly {tier_label}',
        _email_shell(header, body),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PROGRAMME-RELEVANT POST NOTIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def send_programme_relevant_post_email(user, post):
    """Notify a student when a post matching their programme is uploaded."""
    base = _base_url()
    name = user.nickname or user.username
    email_subject = (
        f'New material for {post.subject.name}: {post.title}'
        if post.subject else
        f'New material: {post.title}'
    )
    subject_html      = f'<p><strong>Subject:</strong> {post.subject.name}</p>' if post.subject else ''
    description_html  = f'<p>{post.description}</p>' if post.description else ''

    header = """
      <h1 class="header-title">New Material Just Dropped 📚</h1>
      <p class="header-sub">Relevant to your programme</p>
    """

    body = f"""
      <p>Hi <strong>{name}</strong>,</p>
      <p>Chale, something just dropped — and it matches your programme:
         <strong>{user.programme}</strong>.</p>
      <p>This new material fit be exactly what you need before your next
         class, test, or exams. Don't miss it.</p>
      <div class="info-box">
        <p><strong>{post.title}</strong></p>
        {subject_html}
        {description_html}
      </div>
      <div class="btn-wrap">
        <a href="{base}/posts/{post.id}" class="btn">View Material →</a>
      </div>
      <p>Students in your programme are already checking it out. The earlier
         you see it, the better advantage you get.</p>
      <p>Stay sharp and keep learning!<br><strong>The knowly Team</strong></p>
    """

    return _send_brevo_email(
        user.email,
        email_subject,
        _email_shell(header, body),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PASSWORD RESET
# ─────────────────────────────────────────────────────────────────────────────

def send_password_reset_email(user, reset_url):
    """Send a password reset link to the user."""
    name = user.nickname or user.username

    header = """
      <h1 class="header-title">Password Reset Request 🔑</h1>
      <p class="header-sub">Someone requested a reset for your account</p>
    """

    body = f"""
      <p>Hi <strong>{name}</strong>,</p>
      <p>We received a request to reset your knowly password. Click the button
         below to choose a new one:</p>
      <div class="btn-wrap">
        <a href="{reset_url}" class="btn">Reset My Password →</a>
      </div>
      <p style="font-size:13px; color:#64748b;">
        Or copy and paste this link into your browser:<br>
        <a href="{reset_url}" style="color:#60a5fa; word-break:break-all;">{reset_url}</a>
      </p>
      <div class="warning">
        ⚠️ This link expires in <strong>30 minutes</strong>. If you did not
        request a password reset, you can safely ignore this email — your
        password will not change.
      </div>
    """

    return _send_brevo_email(
        user.email,
        'Reset Your knowly Password',
        _email_shell(header, body),
    )