"""
analytics_service.py — DB-level aggregations for school analytics.

Replaces the pattern of loading all TestResult rows into Python and
computing averages in application code. All heavy lifting happens in
a single query; Python only formats the results for the template.
"""
from sqlalchemy import func
from app.extensions import db
from app.models.account import Accounts
from app.models.test_result import TestResult


def get_school_analytics(school_id: int) -> dict:
    """
    Return all data needed by the school_analytics template.

    Makes two DB queries total regardless of how many results exist:
      1. Aggregate totals (count, avg percentage)
      2. Monthly breakdown (grouped by year-month)

    Returns a dict with keys:
        avg_score        — dict compatible with the existing template
        monthly_data     — list of {month, label, average} dicts
        total_students   — int
        total_assessments — int
    """
    # ── Query 1: totals ───────────────────────────────────────────────────────
    totals = (
        db.session.query(
            func.count(TestResult.id).label('total_assessments'),
            func.count(func.distinct(TestResult.user_id)).label('total_students'),
            func.sum(TestResult.score).label('sum_score'),
            func.sum(TestResult.max_score).label('sum_max'),
        )
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(
            Accounts.school_id == school_id,
            TestResult.max_score > 0,
        )
        .one()
    )

    total_assessments = totals.total_assessments or 0
    total_students = totals.total_students or 0

    if total_assessments == 0 or not totals.sum_max:
        avg_score = {
            'average': 0,
            'stage': 'No assessments yet',
            'message': 'No students have completed an assessment yet.',
            'color': '#6b7280',
            'percentage': 0,
        }
    else:
        avg_pct = round((totals.sum_score / totals.sum_max) * 100, 1)
        avg_score = {
            'average': avg_pct,
            'stage': f'{total_assessments} assessments across {total_students} students',
            'message': 'School-wide average score across all assessments.',
            'color': '#2a6642',
            'percentage': avg_pct,
        }

    # ── Query 2: monthly breakdown ────────────────────────────────────────────
    # Use PostgreSQL's to_char() for year-month grouping.
    # func.strftime() is SQLite-only and will raise UndefinedFunction on Postgres.
    dialect = db.engine.dialect.name
    if dialect == 'postgresql':
        month_expr = func.to_char(TestResult.taken_at, 'YYYY-MM')
    else:
        month_expr = func.strftime('%Y-%m', TestResult.taken_at)
    monthly_rows = (
        db.session.query(
            month_expr.label('month_key'),
            func.sum(TestResult.score).label('sum_score'),
            func.sum(TestResult.max_score).label('sum_max'),
            func.count(TestResult.id).label('count'),
        )
        .join(Accounts, Accounts.id == TestResult.user_id)
        .filter(
            Accounts.school_id == school_id,
            TestResult.max_score > 0,
            TestResult.taken_at.isnot(None),
        )
        .group_by(month_expr)
        .order_by(month_expr)
        .all()
    )

    monthly_data = []
    for row in monthly_rows:
        if row.month_key and row.sum_max:
            avg = round((row.sum_score / row.sum_max) * 100, 1)
            # Format "2026-03" → "Mar 2026" for the chart label
            from datetime import datetime
            try:
                label = datetime.strptime(row.month_key, '%Y-%m').strftime('%b %Y')
            except ValueError:
                label = row.month_key
            monthly_data.append({
                'month': row.month_key,
                'label': label,
                'average': avg,
            })

    return {
        'avg_score': avg_score,
        'monthly_data': monthly_data,
        'total_students': total_students,
        'total_assessments': total_assessments,
    }