"""
report_service.py — Data queries for school performance reports.

Gathers all data needed to generate a weekly, monthly, or yearly
PDF report for a school. All aggregation happens in the DB.
"""
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from app.extensions import db
from app.models.account import Accounts
from app.models.test_result import TestResult


STAGE_ORDER = ['Normal Stage', 'Mild Stage', 'Elevated Stage', 'Clinical Stage']

TEST_TYPES = [
    'Separation Anxiety Disorder',
    'Social Phobia',
    'Generalised Anxiety Disorder',
    'Panic Disorder',
    'Obsessive Compulsive Disorder',
    'Major Depressive Disorder',
]


def get_period_bounds(period: str):
    """Return (start, end, label) for the requested period."""
    now = datetime.now(timezone.utc)

    if period == 'weekly':
        start = now - timedelta(days=7)
        label = f"{start.strftime('%d %b %Y')} – {now.strftime('%d %b %Y')}"
    elif period == 'yearly':
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        label = now.strftime('%Y')
    else:  # monthly (default)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = now.strftime('%B %Y')

    return start, now, label


def get_report_data(school_id: int, period: str) -> dict:
    """
    Return all data needed to render a school report PDF.

    Keys returned:
        period_label        — human-readable period string
        generated_at        — datetime the report was generated
        total_students      — int
        participating       — students who took at least one test in period
        total_assessments   — int
        participation_rate  — percentage of students who participated
        stage_breakdown     — list of {stage, count, pct} across all tests
        by_test_type        — list of {test_type, total, stage_counts}
        at_risk             — list of {name, class_group, test_type, stage, taken_at}
        monthly_trend       — list of {month, label, count, avg_pct}
        class_breakdown     — list of {class_group, total, at_risk_count}
    """
    start, end, period_label = get_period_bounds(period)

    # ── Total students enrolled ───────────────────────────────────────────────
    total_students = (
        db.session.query(func.count(Accounts.id))
        .filter(Accounts.school_id == school_id)
        .scalar() or 0
    )

    # ── Assessments in period ─────────────────────────────────────────────────
    base_q = (
        db.session.query(TestResult)
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(
            Accounts.school_id == school_id,
            TestResult.taken_at >= start,
            TestResult.taken_at <= end,
        )
    )

    total_assessments = base_q.count()

    participating = (
        db.session.query(func.count(func.distinct(TestResult.user_id)))
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(
            Accounts.school_id == school_id,
            TestResult.taken_at >= start,
            TestResult.taken_at <= end,
        )
        .scalar() or 0
    )

    participation_rate = round((participating / total_students) * 100, 1) if total_students else 0

    # ── Stage breakdown across all tests in period ────────────────────────────
    stage_rows = (
        db.session.query(
            func.coalesce(TestResult.stage, 'Unknown').label('stage'),
            func.count(TestResult.id).label('count'),
        )
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(
            Accounts.school_id == school_id,
            TestResult.taken_at >= start,
            TestResult.taken_at <= end,
        )
        .group_by(func.coalesce(TestResult.stage, 'Unknown'))
        .all()
    )

    stage_total = sum(r.count for r in stage_rows) or 1
    stage_counts = {r.stage: r.count for r in stage_rows}
    stage_breakdown = [
        {
            'stage': stage,
            'count': stage_counts.get(stage, 0),
            'pct': round(stage_counts.get(stage, 0) / stage_total * 100, 1),
        }
        for stage in STAGE_ORDER
        if stage_counts.get(stage, 0) > 0
    ]

    # ── Breakdown per test type ───────────────────────────────────────────────
    by_test_type = []
    for test_type in TEST_TYPES:
        rows = (
            db.session.query(
                func.coalesce(TestResult.stage, 'Unknown').label('stage'),
                func.count(TestResult.id).label('count'),
            )
            .join(Accounts, Accounts.id == TestResult.user_id)
            .filter(
                Accounts.school_id == school_id,
                TestResult.test_type == test_type,
                TestResult.taken_at >= start,
                TestResult.taken_at <= end,
            )
            .group_by(func.coalesce(TestResult.stage, 'Unknown'))
            .all()
        )
        if not rows:
            continue
        total = sum(r.count for r in rows)
        by_test_type.append({
            'test_type': test_type,
            'total': total,
            'stage_counts': {r.stage: r.count for r in rows},
        })

    # ── At-risk students (Elevated + Clinical, latest result per test) ────────
    latest_subq = (
        db.session.query(
            TestResult.user_id,
            TestResult.test_type,
            func.max(TestResult.taken_at).label('latest_at'),
        )
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(
            Accounts.school_id == school_id,
            TestResult.taken_at >= start,
            TestResult.taken_at <= end,
        )
        .group_by(TestResult.user_id, TestResult.test_type)
        .subquery()
    )

    at_risk_rows = (
        db.session.query(TestResult, Accounts)
        .join(Accounts, Accounts.id == TestResult.user_id)
        .join(
            latest_subq,
            (latest_subq.c.user_id == TestResult.user_id) &
            (latest_subq.c.test_type == TestResult.test_type) &
            (latest_subq.c.latest_at == TestResult.taken_at),
        )
        .filter(
            Accounts.school_id == school_id,
            TestResult.stage.in_(['Elevated Stage', 'Clinical Stage']),
        )
        .order_by(
            db.case((TestResult.stage == 'Clinical Stage', 0), else_=1),
            Accounts.lname,
            Accounts.fname,
        )
        .all()
    )

    at_risk = [
        {
            'name': acc.full_name,
            'class_group': acc.class_group or '—',
            'test_type': res.test_type,
            'stage': res.stage,
            'taken_at': res.taken_at,
        }
        for res, acc in at_risk_rows
    ]

    # ── Monthly trend (last 6 months regardless of period) ───────────────────
    six_months_ago = datetime.now(timezone.utc) - timedelta(days=180)
    month_expr = func.to_char(TestResult.taken_at, 'YYYY-MM')
    trend_rows = (
        db.session.query(
            month_expr.label('month_key'),
            func.count(TestResult.id).label('count'),
            func.sum(TestResult.score).label('sum_score'),
            func.sum(TestResult.max_score).label('sum_max'),
        )
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(
            Accounts.school_id == school_id,
            TestResult.taken_at >= six_months_ago,
            TestResult.max_score > 0,
        )
        .group_by(month_expr)
        .order_by(month_expr)
        .all()
    )

    monthly_trend = []
    for row in trend_rows:
        if row.month_key and row.sum_max:
            try:
                label = datetime.strptime(row.month_key, '%Y-%m').strftime('%b %Y')
            except ValueError:
                label = row.month_key
            monthly_trend.append({
                'month': row.month_key,
                'label': label,
                'count': row.count,
                'avg_pct': round((row.sum_score / row.sum_max) * 100, 1),
            })

    # ── Class group breakdown ─────────────────────────────────────────────────
    class_rows = (
        db.session.query(
            Accounts.class_group,
            func.count(func.distinct(Accounts.id)).label('total'),
        )
        .filter(
            Accounts.school_id == school_id,
            Accounts.class_group.isnot(None),
        )
        .group_by(Accounts.class_group)
        .order_by(Accounts.class_group)
        .all()
    )

    at_risk_by_class = (
        db.session.query(
            Accounts.class_group,
            func.count(func.distinct(TestResult.user_id)).label('at_risk_count'),
        )
        .join(TestResult, TestResult.user_id == Accounts.id)
        .filter(
            Accounts.school_id == school_id,
            Accounts.class_group.isnot(None),
            TestResult.stage.in_(['Elevated Stage', 'Clinical Stage']),
            TestResult.taken_at >= start,
            TestResult.taken_at <= end,
        )
        .group_by(Accounts.class_group)
        .all()
    )

    at_risk_class_map = {r.class_group: r.at_risk_count for r in at_risk_by_class}

    class_breakdown = [
        {
            'class_group': row.class_group,
            'total': row.total,
            'at_risk_count': at_risk_class_map.get(row.class_group, 0),
        }
        for row in class_rows
    ]

    return {
        'period_label': period_label,
        'period': period,
        'generated_at': datetime.now(timezone.utc),
        'total_students': total_students,
        'participating': participating,
        'total_assessments': total_assessments,
        'participation_rate': participation_rate,
        'stage_breakdown': stage_breakdown,
        'by_test_type': by_test_type,
        'at_risk': at_risk,
        'monthly_trend': monthly_trend,
        'class_breakdown': class_breakdown,
    }