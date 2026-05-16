from app.utils.emails import _send_brevo_email, _email_shell, _base_url
from flask import current_app

def send_streak_reminder(user):
    """Encourage user to keep their streak alive."""
    subject = f"🔥 Don't lose your {user.current_streak}-day streak!"
    header = f"Keep the fire burning, {user.username}!"
    body = f"""
    <p>Chale, you've worked too hard to let your <strong>{user.current_streak}-day streak</strong> slip away.</p>
    <p>Spend just 5 minutes on Knowly today to keep your momentum and earn more Aura.</p>
    <div style='text-align:center; margin: 30px 0;'>
        <a href='{_base_url()}/dashboard' style='background:#2563eb;color:#fff;padding:12px 24px;border-radius:12px;text-decoration:none;font-weight:bold;'>Resume Learning →</a>
    </div>
    <p>You've got this! 🚀</p>
    """
    html_content = _email_shell(header, body)
    return _send_brevo_email(user.email, subject, html_content)

def send_weekly_digest(user, stats):
    """Summarize weekly activity."""
    subject = "📊 Your Weekly Knowly Digest"
    header = "Weekly Progress Report"
    
    # stats is a dict with: aura_earned, top_subject, packs_in_progress
    packs_html = ""
    if stats.get('packs_in_progress'):
        packs_html = "<ul>"
        for pack in stats['packs_in_progress'][:3]:
            packs_html += f"<li>{pack['title']} ({pack['percent']}% complete)</li>"
        packs_html += "</ul>"
    else:
        packs_html = "<p>No active packs this week. Time to dive back in?</p>"

    body = f"""
    <p>Hi {user.username}, here is a look at your progress over the last 7 days:</p>
    <div style='background:rgba(37, 99, 235, 0.05); padding: 20px; border-radius: 16px; margin: 20px 0;'>
        <p style='margin:0; color:#64748b; font-size:0.9rem;'>Aura Earned</p>
        <p style='margin:0; font-size:1.5rem; font-weight:800; color:#2563eb;'>+{stats.get('aura_earned', 0)} XP</p>
        
        <p style='margin:15px 0 0 0; color:#64748b; font-size:0.9rem;'>Top Subject</p>
        <p style='margin:0; font-size:1.1rem; font-weight:700;'>{stats.get('top_subject') or 'General Studies'}</p>
    </div>
    
    <h3>Active Study Packs</h3>
    {packs_html}
    
    <div style='text-align:center; margin: 30px 0;'>
        <a href='{_base_url()}/dashboard' style='background:#2563eb;color:#fff;padding:12px 24px;border-radius:12px;text-decoration:none;font-weight:bold;'>Go to Dashboard</a>
    </div>
    """
    html_content = _email_shell(header, body)
    return _send_brevo_email(user.email, subject, html_content)

def send_reengagement(user):
    """Re-engage inactive users."""
    subject = "Chale, where you go? 🇬🇭"
    header = "We miss you on Knowly!"
    body = f"""
    <p>Hi {user.username},</p>
    <p>It's been a week since we saw you on the platform. Your subjects are missing you, and some new Study Packs have just landed in your library!</p>
    <p>Don't fall behind. Grab your notes and let's get back to it.</p>
    <div style='text-align:center; margin: 30px 0;'>
        <a href='{_base_url()}/library/all' style='background:#2563eb;color:#fff;padding:12px 24px;border-radius:12px;text-decoration:none;font-weight:bold;'>Explore New Packs →</a>
    </div>
    <p>See you soon!</p>
    """
    html_content = _email_shell(header, body)
    return _send_brevo_email(user.email, subject, html_content)
