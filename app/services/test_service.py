"""
Test scoring service — all scoring ranges and classification logic.
Isolated from routes for easy testing and maintenance.
"""

SCORING_RANGES = {
    "Separation Anxiety Disorder": [
        {"min": 0,  "max": 5,  "stage": "Normal Stage",   "message": "You're managing separation anxiety well. You cope comfortably with school and daily life."},
        {"min": 6,  "max": 10, "stage": "Mild Stage",     "message": "Some signs of separation anxiety are beginning to show, but they are still manageable with the right support."},
        {"min": 11, "max": 16, "stage": "Elevated Stage", "message": "Separation anxiety is starting to affect your school life. Speaking with a trusted adult or counsellor may help."},
        {"min": 17, "max": 21, "stage": "Clinical Stage", "message": "Separation anxiety appears to be severe and significantly impacting your daily life. Professional help including counselling or medical support is recommended."},
    ],
    "Social Phobia": [
        {"min": 0,  "max": 6,  "stage": "Normal Stage",   "message": "You feel comfortable in social situations most days. You're managing any fear of being judged or embarrassed very well."},
        {"min": 7,  "max": 13, "stage": "Mild Stage",     "message": "Some signs of social phobia are beginning to show. These are still manageable, and talking to someone you trust can help."},
        {"min": 14, "max": 20, "stage": "Elevated Stage", "message": "Social phobia is becoming more serious and may be affecting your school life. A counsellor can help you develop coping strategies."},
        {"min": 21, "max": 27, "stage": "Clinical Stage", "message": "Social phobia appears severe and is making school life very difficult. Professional help including counselling and possible medical support is strongly recommended."},
    ],
    "Generalised Anxiety Disorder": [
        {"min": 0,  "max": 4,  "stage": "Normal Stage",   "message": "You feel okay most days and are managing your worries well. Keep up the healthy habits."},
        {"min": 5,  "max": 9,  "stage": "Mild Stage",     "message": "Some signs of constant worrying are showing, but they are still manageable with the right help and support."},
        {"min": 10, "max": 13, "stage": "Elevated Stage", "message": "Constant worry is becoming more serious and may be affecting your school life and relationships. Speaking to a counsellor is advisable."},
        {"min": 14, "max": 18, "stage": "Clinical Stage", "message": "Generalised anxiety appears severe, making school life very difficult. Professional help including counselling and medical intervention is recommended."},
    ],
    "Panic Disorder": [
        {"min": 0,  "max": 6,  "stage": "Normal Stage",   "message": "You are managing sudden fear or panic well. You cope effectively with school and social life."},
        {"min": 7,  "max": 13, "stage": "Mild Stage",     "message": "Some signs of panic disorder are beginning to show, but they are still manageable. Talking to a trusted adult can help."},
        {"min": 14, "max": 20, "stage": "Elevated Stage", "message": "Sudden fear attacks are becoming more serious and may be affecting your school life. A counsellor can help."},
        {"min": 21, "max": 27, "stage": "Clinical Stage", "message": "Panic disorder appears severe and is making school life very difficult. Professional help including counselling and possible medical support is strongly recommended."},
    ],
    "Obsessive Compulsive Disorder": [
        {"min": 0,  "max": 4,  "stage": "Normal Stage",   "message": "You have little to no symptoms of uncontrollable thoughts and are coping well with school life."},
        {"min": 5,  "max": 9,  "stage": "Mild Stage",     "message": "Some signs of repetitive thoughts or behaviours are showing. These are still manageable with the right support."},
        {"min": 10, "max": 13, "stage": "Elevated Stage", "message": "Uncontrollable thoughts are becoming more serious and may be affecting your school life and relationships."},
        {"min": 14, "max": 18, "stage": "Clinical Stage", "message": "OCD appears severe and is making school life very difficult. Professional help including counselling and medical intervention is strongly recommended."},
    ],
    "Major Depressive Disorder": [
        {"min": 0,  "max": 7,  "stage": "Normal Stage",   "message": "You feel okay most days with little to no symptoms of deep sadness or loss of interest in life."},
        {"min": 8,  "max": 15, "stage": "Mild Stage",     "message": "Some symptoms of deep sadness or loss of interest are showing, but they are still manageable. Talking to someone you trust can help."},
        {"min": 16, "max": 22, "stage": "Elevated Stage", "message": "Feelings of sadness or loss of interest are becoming more serious and may be affecting your school life. Speaking to a counsellor is advisable."},
        {"min": 23, "max": 30, "stage": "Clinical Stage", "message": "Major depression appears severe and is making school and social life very difficult. Professional help including counselling and medical intervention is strongly recommended."},
    ],
}

TEST_ORDER = [
    "Separation Anxiety Disorder",
    "Social Phobia",
    "Generalised Anxiety Disorder",
    "Panic Disorder",
    "Obsessive Compulsive Disorder",
    "Major Depressive Disorder",
]

ANSWER_SCORES = {"Never": 0, "Sometimes": 1, "Often": 2, "Always": 3}

STAGE_COLORS = {
    "Normal Stage":   "#2a7f62",
    "Mild Stage":     "#b8860b",
    "Elevated Stage": "#d97706",
    "Clinical Stage": "#b91c1c",
}


def classify_score(test_type: str, score: int) -> dict:
    """Return stage and message for a given test type and score."""
    ranges = SCORING_RANGES.get(test_type, [])
    for r in ranges:
        if r["min"] <= score <= r["max"]:
            return {
                "stage": r["stage"],
                "message": r["message"],
                "score_range": f"{r['min']} – {r['max']}",
                "color": STAGE_COLORS.get(r["stage"], "#555"),
            }
    return {"stage": "Unknown", "message": "No result available.", "score_range": "—", "color": "#555"}


def get_next_test(current_test_type: str):
    """Return the next test type in order, or None if last."""
    try:
        idx = TEST_ORDER.index(current_test_type)
        return TEST_ORDER[idx + 1]
    except (ValueError, IndexError):
        return None
