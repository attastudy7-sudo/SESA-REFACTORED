"""
Test scoring service — reads all scoring config from the AssessmentType DB table.
To add a new assessment: insert a row into assessment_type. No code changes needed.
"""

from collections import defaultdict
import logging
logger = logging.getLogger(__name__)


ANSWER_SCORES = {"Never": 0, "Sometimes": 1, "Often": 2, "Always": 3}

STAGE_COLORS = {
    "Normal Stage":   "#2a7f62",
    "Mild Stage":     "#b8860b",
    "Elevated Stage": "#d97706",
    "Clinical Stage": "#b91c1c",
}


def classify_score(test_type: str, score: int, max_score: int = None) -> dict:
    from app.models.assessment_type import AssessmentType
    from app.models.question import Question
    assessment = AssessmentType.query.filter_by(name=test_type).first()
    if not assessment:
        assessment = AssessmentType.query.filter(
            AssessmentType.name.ilike(test_type.strip())
        ).first()
    if not assessment:
        return {"stage": "Unknown", "message": "No result available.", "score_range": "—", "color": "#555"}
    if max_score is None:
        q_count = Question.query.filter_by(test_type=test_type).count()
        max_score = q_count * 3
    pct = round((score / max_score) * 100) if max_score > 0 else 0
    best_match = None
    best_distance = float('inf')
    for r in assessment.scoring_ranges:
        if r["min"] <= pct <= r["max"]:
            return {
                "stage": r["stage"],
                "message": r["message"],
                "score_range": f"{r['min']}% – {r['max']}%",
                "color": STAGE_COLORS.get(r["stage"], "#555"),
            }
        # Track nearest range as fallback for gap/boundary edge cases
        distance = min(abs(pct - r["min"]), abs(pct - r["max"]))
        if distance < best_distance:
            best_distance = distance
            best_match = r
    if best_match:
        logger.warning('classify_score: pct=%s fell outside all ranges for %s — using nearest range %s', pct, test_type, best_match)
        return {
            "stage": best_match["stage"],
            "message": best_match["message"],
            "score_range": f"{best_match['min']}% – {best_match['max']}%",
            "color": STAGE_COLORS.get(best_match["stage"], "#555"),
        }
    return {"stage": "Unknown", "message": "No result available.", "score_range": "—", "color": "#555"}


def get_next_test(current_test_type: str):
    from app.models.assessment_type import AssessmentType
    current = AssessmentType.query.filter_by(name=current_test_type).first()
    if not current:
        return None
    next_type = AssessmentType.query.filter(
        AssessmentType.order > current.order,
        AssessmentType.is_active == True,
    ).order_by(AssessmentType.order).first()
    return next_type.name if next_type else None


def calculate_average_score(results: list) -> dict:
    if not results:
        return {
            "average": 0, "stage": "No assessments yet",
            "message": "Complete an assessment to see your results here.",
            "color": "#6b7280", "percentage": 0,
        }
    percentages = []
    for r in results:
        if r.max_score and r.max_score > 0:
            percentages.append((r.score / r.max_score) * 100)
    if not percentages:
        return {
            "average": 0, "stage": "No assessments yet",
            "message": "Complete an assessment to see your results here.",
            "color": "#6b7280", "percentage": 0,
        }
    avg_percentage = round(sum(percentages) / len(percentages), 1)
    from app.models.assessment_type import AssessmentType
    tests_total = AssessmentType.query.filter_by(is_active=True).count()
    tests_done  = len(set(r.test_type for r in results))
    return {
        "average": avg_percentage,
        "stage": f"{tests_done} of {tests_total} assessments completed",
        "message": "See each assessment result below for your individual stage.",
        "color": "#2a6642", "percentage": avg_percentage,
    }


def get_monthly_averages(results: list) -> list:
    if not results:
        return []
    monthly_data = defaultdict(list)
    for r in results:
        if r.taken_at and r.max_score and r.max_score > 0:
            month_key   = r.taken_at.strftime("%Y-%m")
            month_label = r.taken_at.strftime("%b %Y")
            monthly_data[month_key].append({"percentage": (r.score / r.max_score) * 100, "label": month_label})
    return [
        {"month": k, "label": v[0]["label"], "average": round(sum(d["percentage"] for d in v) / len(v), 1)}
        for k, v in sorted(monthly_data.items())
    ]


def get_school_monthly_averages(test_results: list) -> list:
    return get_monthly_averages(test_results)