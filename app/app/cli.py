import click
from flask.cli import AppGroup
from app.services.campaign_runner import (
    run_streak_campaign,
    run_reengagement_campaign,
    run_weekly_digest_campaign
)

campaigns_bp = AppGroup('campaigns', help='Automated email campaign commands')

@campaigns_bp.command('streak-reminders')
def streak_reminders():
    """Send streak expiry reminders to users active yesterday."""
    click.echo("Running streak campaign...")
    count = run_streak_campaign()
    click.echo(f"Sent {count} streak reminders.")

@campaigns_bp.command('reengagement')
def reengagement():
    """Send re-engagement emails to users inactive for 7 days."""
    click.echo("Running re-engagement campaign...")
    count = run_reengagement_campaign()
    click.echo(f"Sent {count} re-engagement emails.")

@campaigns_bp.command('weekly-digest')
def weekly_digest():
    """Send weekly progress reports to active users."""
    click.echo("Running weekly digest campaign...")
    count = run_weekly_digest_campaign()
    click.echo(f"Sent {count} weekly digests.")
