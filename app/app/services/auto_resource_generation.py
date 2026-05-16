from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func

from app import db
from app.models import Like, Post, Programme, Subject, User
from app.services.resource_generation import build_validated_bundle_from_text, save_generated_selection

logger = logging.getLogger(__name__)

_CONTENT_TYPES = ("notes", "quiz", "cheatsheet")


@dataclass
class SubjectGap:
    subject_id: int
    subject_slug: str
    subject_name: str
    programme_name: str
    year: int | None
    semester: int | None
    level: str
    missing_types: list[str]
    gap_reasons: dict[str, str] = field(default_factory=dict)
    current: dict[str, int] = field(default_factory=dict)
    existing_titles: dict[str, list[str]] = field(default_factory=lambda: {"notes": [], "quiz": [], "cheatsheet": []})


def _infer_year_semester(subject_slug: str) -> tuple[int | None, int | None]:
    match = re.search(r"[a-z]+(\d)(\d)\d", (subject_slug or "").lower())
    if not match:
        return None, None
    year = int(match.group(1))
    sem_digit = int(match.group(2))
    semester = 1 if sem_digit <= 1 else 2
    return year, semester


def _infer_level(year: int | None) -> str:
    return {
        1: "Beginner",
        2: "Elementary",
        3: "Intermediate",
        4: "Advanced",
    }.get(year or 0, "Intermediate")


def _taxonomy_context(subject_limit: int = 350, programme_limit: int = 160) -> dict[str, list[str]]:
    subjects = [
        row.name
        for row in Subject.query.filter_by(is_active=True)
        .order_by(Subject.name.asc())
        .limit(subject_limit)
        .all()
    ]
    programmes = [
        row.name
        for row in Programme.query.filter_by(is_active=True)
        .order_by(Programme.name.asc())
        .limit(programme_limit)
        .all()
    ]
    faculties = sorted(
        {
            (row.faculty or "").strip()
            for row in Programme.query.filter_by(is_active=True).all()
            if (row.faculty or "").strip()
        }
    )
    return {
        "subjects": subjects,
        "programmes": programmes,
        "faculties": faculties,
    }


def detect_subject_gaps(
    *,
    min_coverage: int = 3,
    content_types: tuple[str, ...] = _CONTENT_TYPES,
    programme_slugs: list[str] | None = None,
    year_filter: int | None = None,
    semester_filter: int | None = None,
    max_subjects: int | None = None,
) -> list[SubjectGap]:
    programmes_query = Programme.query.filter_by(is_active=True).order_by(Programme.name.asc())
    if programme_slugs:
        programmes_query = programmes_query.filter(Programme.slug.in_(programme_slugs))

    programmes = programmes_query.all()
    visited_subject_ids: set[int] = set()
    gaps: list[SubjectGap] = []

    for programme in programmes:
        subjects = (
            programme.subjects.filter_by(is_active=True)
            .order_by(Subject.name.asc())
            .all()
        )
        for subject in subjects:
            if subject.id in visited_subject_ids:
                continue
            visited_subject_ids.add(subject.id)

            counts = dict(
                db.session.query(Post.content_type, func.count(Post.id))
                .filter(
                    Post.subject_id == subject.id,
                    Post.status == "approved",
                )
                .group_by(Post.content_type)
                .all()
            )
            existing_titles = {"notes": [], "quiz": [], "cheatsheet": []}
            for row in (
                Post.query.filter_by(subject_id=subject.id, status="approved")
                .with_entities(Post.content_type, Post.title)
                .all()
            ):
                if row[0] in existing_titles and row[1]:
                    existing_titles[row[0]].append(str(row[1]).strip())

            liked_post_count = (
                db.session.query(Like.post_id)
                .join(Post, Post.id == Like.post_id)
                .filter(Post.subject_id == subject.id)
                .distinct()
                .count()
            )
            engagement_zero = liked_post_count == 0

            year, semester = _infer_year_semester(subject.slug)
            if year_filter and year != year_filter:
                continue
            if semester_filter and semester != semester_filter:
                continue
            missing: list[str] = []
            reasons: dict[str, str] = {}
            for content_type in content_types:
                count = int(counts.get(content_type, 0) or 0)
                if count < min_coverage:
                    missing.append(content_type)
                    reasons[content_type] = "below_threshold"
                elif engagement_zero and count > 0:
                    missing.append(content_type)
                    reasons[content_type] = "zero_engagement"

            if missing:
                gaps.append(
                    SubjectGap(
                        subject_id=subject.id,
                        subject_slug=subject.slug,
                        subject_name=subject.name,
                        programme_name=programme.name,
                        year=year,
                        semester=semester,
                        level=_infer_level(year),
                        missing_types=missing,
                        gap_reasons=reasons,
                        current={ct: int(counts.get(ct, 0) or 0) for ct in _CONTENT_TYPES},
                        existing_titles=existing_titles,
                    )
                )

            if max_subjects and len(gaps) >= max_subjects:
                return gaps

    return gaps


def _load_gemini_keys() -> list[str]:
    keys: list[str] = []
    single = os.environ.get("GEMINI_API_KEY")
    if single:
        keys.append(single)
    for index in range(1, 20):
        key = os.environ.get(f"GEMINI_API_KEY_{index}")
        if key:
            keys.append(key)
    return keys


def _extract_json_array(raw: str) -> list[str]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    data = json.loads(text)
    if not isinstance(data, list):
        return []
    normalized = []
    seen: set[str] = set()
    for item in data:
        val = str(item or "").strip()
        if not val:
            continue
        key = val.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(val)
    return normalized


def _fallback_topics(subject_name: str, n: int) -> list[str]:
    base = (subject_name or "General Studies").strip()
    subject_lower = base.lower()

    if "abstract algebra" in subject_lower:
        seeds = [
            "Proof by Mathematical Induction",
            "Indexed Collections of Sets",
            "Equivalence Relations and Partitions",
            "Group Homomorphisms and Isomorphisms",
            "Normal Subgroups and Quotient Groups",
            "Rings, Ideals, and Factor Rings",
        ]
        return seeds[: max(1, n)]

    if "data structure" in subject_lower or "algorithm" in subject_lower:
        seeds = [
            "Time and Space Complexity Analysis",
            "Recurrence Relations and Master Method",
            "Hash Tables and Collision Resolution",
            "Binary Search Trees and AVL Rotations",
            "Graph Traversal: BFS and DFS",
            "Shortest Path Algorithms: Dijkstra and Bellman-Ford",
        ]
        return seeds[: max(1, n)]

    templates = [
        f"Fundamental Principles of {base}",
        f"Problem Solving in {base}",
        f"Applied Methods in {base}",
        f"Core Theories of {base}",
        f"Analytical Techniques in {base}",
        f"Exam Focus Areas in {base}",
    ]
    return templates[: max(1, n)]


def _is_vague_topic(topic: str) -> bool:
    text = (topic or "").strip().lower()
    if not text:
        return True
    banned_exact = {
        "introduction",
        "overview",
        "fundamentals",
        "basics",
        "revision",
        "practice",
        "exam prep",
        "study guide",
        "topic",
    }
    if text in banned_exact:
        return True
    if text.endswith(" topic") or text.startswith("topic "):
        return True
    if re.search(r"\btopic\s*\d+\b", text):
        return True
    generic_markers = ("introduction to", "overview of", "basics of", "general concepts")
    return any(marker in text for marker in generic_markers)


def _clean_topic(topic: str) -> str:
    cleaned = " ".join(str(topic or "").replace("\n", " ").split())
    cleaned = cleaned.strip("-:;,. ")
    return cleaned[:96].strip()


def _finalize_topics(raw_topics: list[str], existing_titles: list[str], n: int, subject_name: str) -> list[str]:
    blocked = {title.lower() for title in existing_titles}
    seen: set[str] = set()
    chosen: list[str] = []

    for raw in raw_topics:
        topic = _clean_topic(raw)
        if not topic:
            continue
        key = topic.lower()
        if key in seen or key in blocked:
            continue
        if _is_vague_topic(topic):
            continue
        seen.add(key)
        chosen.append(topic)
        if len(chosen) >= n:
            return chosen

    for fallback in _fallback_topics(subject_name, n * 2):
        topic = _clean_topic(fallback)
        key = topic.lower()
        if key in seen or key in blocked:
            continue
        seen.add(key)
        chosen.append(topic)
        if len(chosen) >= n:
            break

    return chosen[:n]


def generate_topics_for_gap(gap: SubjectGap, content_type: str, n: int) -> list[str]:
    n = max(1, min(int(n or 1), 6))
    keys = _load_gemini_keys()
    existing_titles = [title for title in gap.existing_titles.get(content_type, []) if title]

    if not keys:
        return _finalize_topics(_fallback_topics(gap.subject_name, n), existing_titles, n, gap.subject_name)

    exemplars = _fallback_topics(gap.subject_name, min(4, n + 1))
    prompt = (
        "You are an expert university curriculum designer for West African programmes. "
        "Return only a valid JSON array of strings and nothing else.\n\n"
        f"Generate exactly {n} high-quality topic names for:\n"
        f"Subject: {gap.subject_name} ({gap.subject_slug.upper()})\n"
        f"Programme: {gap.programme_name}\n"
        f"Level: {gap.level}\n"
        f"Year: {gap.year or '?'} Semester: {gap.semester or '?'}\n"
        f"Content type target: {content_type}\n"
        "Each topic should be concise (3-10 words), non-overlapping, and useful for exam revision.\n"
        "Use concrete concept names, formulas, methods, or named frameworks.\n"
        "Avoid vague labels like Introduction, Overview, Basics, Fundamentals, Topic 1, Revision."
    )
    if exemplars:
        prompt += "\nUse specificity similar to these example concept names:\n"
        prompt += "\n".join(f"- {item}" for item in exemplars)
    if existing_titles:
        prompt += "\nDo not generate any topic that matches these existing titles:\n"
        prompt += "\n".join(f"- {title}" for title in existing_titles)

    model_name = (
        os.environ.get("GEMINI_TOPIC_MODEL")
        or os.environ.get("GEMINI_MODEL_PREFERENCES", "gemini-2.0-flash-lite").split(",")[0].strip()
        or "gemini-2.0-flash-lite"
    )

    try:
        import google.generativeai as genai
        from google.generativeai import types
    except Exception:
        logger.warning("google-generativeai unavailable for topic generation; using fallback topics.")
        topics = _fallback_topics(gap.subject_name, n)
        blocked = {title.lower() for title in existing_titles}
        return [topic for topic in topics if topic.lower() not in blocked][:n]

    last_error = ""
    for api_key in keys:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction="Return only valid JSON array output.",
            )
            response = model.generate_content(
                prompt,
                generation_config=types.GenerationConfig(
                    temperature=0.4,
                    max_output_tokens=512,
                    response_mime_type="application/json",
                ),
                request_options={"timeout": 20},
            )
            topics = _extract_json_array(response.text or "")
            if not topics:
                continue

            filtered = _finalize_topics(topics, existing_titles, n, gap.subject_name)
            if filtered:
                return filtered
        except Exception as exc:
            last_error = str(exc)
            continue

    if last_error:
        logger.warning("Topic generation fallback for %s/%s: %s", gap.subject_slug, content_type, last_error)

    return _finalize_topics(_fallback_topics(gap.subject_name, n), existing_titles, n, gap.subject_name)


def _build_topic_source_text(gap: SubjectGap, topic: str, content_type: str) -> str:
    return (
        f"Subject: {gap.subject_name}\n"
        f"Programme: {gap.programme_name}\n"
        f"Level: {gap.level}\n"
        f"Topic: {topic}\n"
        f"Target format: {content_type}\n\n"
        "Generate rigorous university-level study material that can be used for revision. "
        "Assume a West African undergraduate curriculum and include exam-relevant depth."
    )

def _expand_topic_to_brief(gap: SubjectGap, topic: str, content_type: str) -> str:
    """
    Ask Gemini to write a ~400-word content brief for the topic before passing
    it to bundle generation.  This gives the AI real substance to work from
    instead of a 5-line stub, producing better quiz questions and notes.
    Falls back to the original stub if the expansion call fails.
    """
    stub = _build_topic_source_text(gap, topic, content_type)

    try:
        import google.generativeai as genai
        from google.generativeai import types as gtypes
    except Exception:
        return stub

    keys = []
    single = os.environ.get("GEMINI_API_KEY")
    if single:
        keys.append(single)
    for i in range(1, 20):
        k = os.environ.get(f"GEMINI_API_KEY_{i}")
        if k:
            keys.append(k)
    if not keys:
        return stub

    model_name = (
        os.environ.get("GEMINI_MODEL_PREFERENCES", "gemini-2.0-flash-lite")
        .split(",")[0]
        .strip()
        or "gemini-2.0-flash-lite"
    )

    prompt = (
        f"Write a detailed ~400-word academic brief on the following topic "
        f"suitable for university-level study material.\n\n"
        f"Subject: {gap.subject_name}\n"
        f"Programme: {gap.programme_name}\n"
        f"Level: {gap.level}\n"
        f"Topic: {topic}\n\n"
        f"Cover key concepts, definitions, formulas where relevant, and typical exam angles. "
        f"Assume a West African undergraduate curriculum."
    )

    for api_key in keys:
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name=model_name)
            response = model.generate_content(
                prompt,
                generation_config=gtypes.GenerationConfig(
                    temperature=0.5,
                    max_output_tokens=700,
                ),
                request_options={"timeout": 30},
            )
            brief = (response.text or "").strip()
            if len(brief) > 100:
                return (
                    f"Subject: {gap.subject_name}\n"
                    f"Programme: {gap.programme_name}\n"
                    f"Level: {gap.level}\n"
                    f"Topic: {topic}\n\n"
                    f"{brief}"
                )
        except Exception as exc:
            logger.warning("Topic brief expansion failed for %s/%s: %s", gap.subject_slug, topic, exc)
            continue

    return stub

def _normalized_metadata(bundle: dict[str, Any], gap: SubjectGap) -> dict[str, Any]:
    metadata = dict(bundle.get("metadata") or {})
    metadata["subject_hint"] = gap.subject_name
    metadata["programme_hint"] = gap.programme_name
    metadata["subject_match_basis"] = "existing"
    metadata["programme_match_basis"] = "existing"
    metadata["matched_subject_name"] = gap.subject_name
    metadata["matched_programme_name"] = gap.programme_name
    metadata.setdefault("title", f"{gap.subject_name} Study Resource")
    metadata.setdefault("description", f"Auto-generated study material for {gap.subject_name}.")
    metadata.setdefault("flair", "academic")
    return metadata


def run_generation_cycle(
    *,
    actor: User,
    min_coverage: int = 3,
    topics_per_subject: int = 2,
    content_types: list[str] | None = None,
    programme_slugs: list[str] | None = None,
    year_filter: int | None = None,
    semester_filter: int | None = None,
    fixed_topics: list[str] | None = None,
    max_subjects: int | None = 10,
    dry_run: bool = True,
) -> dict[str, Any]:
    selected_types = [ct for ct in (content_types or list(_CONTENT_TYPES)) if ct in _CONTENT_TYPES]
    if not selected_types:
        selected_types = ["notes", "quiz", "cheatsheet"]

    gaps = detect_subject_gaps(
        min_coverage=max(1, int(min_coverage or 1)),
        content_types=tuple(selected_types),
        programme_slugs=programme_slugs,
        year_filter=year_filter,
        semester_filter=semester_filter,
        max_subjects=max_subjects,
    )
    taxonomy_context = _taxonomy_context()
    cleaned_fixed_topics = [str(topic).strip() for topic in (fixed_topics or []) if str(topic).strip()]

    planned = 0
    created = 0
    failures: list[dict[str, str]] = []

    for gap in gaps:
        for content_type in gap.missing_types:
            topics = cleaned_fixed_topics or generate_topics_for_gap(gap, content_type, topics_per_subject)
            existing_lower = {title.lower() for title in gap.existing_titles.get(content_type, [])}

            for topic in topics:
                if topic.lower() in existing_lower:
                    continue
                planned += 1

                if dry_run:
                    continue

                source_text = _expand_topic_to_brief(gap, topic, content_type)
                generation_result = build_validated_bundle_from_text(
                    source_text,
                    taxonomy_context=taxonomy_context,
                )

                if not generation_result.get("ok"):
                    failures.append(
                        {
                            "subject": gap.subject_slug,
                            "topic": topic,
                            "content_type": content_type,
                            "error": str(generation_result.get("error") or "Invalid AI response"),
                        }
                    )
                    continue

                bundle = generation_result.get("bundle")
                if not isinstance(bundle, dict):
                    failures.append(
                        {
                            "subject": gap.subject_slug,
                            "topic": topic,
                            "content_type": content_type,
                            "error": "Invalid AI response",
                        }
                    )
                    continue

                if bundle.get("is_academic") is False:
                    failures.append(
                        {
                            "subject": gap.subject_slug,
                            "topic": topic,
                            "content_type": content_type,
                            "error": "AI marked topic as non-academic.",
                        }
                    )
                    continue

                payload = bundle.get(content_type)
                if not isinstance(payload, dict):
                    failures.append(
                        {
                            "subject": gap.subject_slug,
                            "topic": topic,
                            "content_type": content_type,
                            "error": f"Bundle missing {content_type} payload.",
                        }
                    )
                    continue

                metadata = _normalized_metadata(bundle, gap)
                metadata["title"] = f"{topic} - {gap.subject_name}"

                bundle_for_save = dict(bundle)
                bundle_for_save["metadata"] = metadata

                post, error = save_generated_selection(
                    selection_type=content_type,
                    content=payload,
                    metadata=metadata,
                    user=actor,
                    subject_id=gap.subject_id,
                    bundle=bundle_for_save,
                )

                if error or not post:
                    failures.append(
                        {
                            "subject": gap.subject_slug,
                            "topic": topic,
                            "content_type": content_type,
                            "error": error or "Failed to save post.",
                        }
                    )
                    continue

                created += 1

    db.session.expire_all()

    return {
        "dry_run": bool(dry_run),
        "gap_subjects": len(gaps),
        "planned": planned,
        "created": created,
        "failed": len(failures),
        "content_types": selected_types,
        "fixed_topics": cleaned_fixed_topics,
        "year_filter": year_filter,
        "semester_filter": semester_filter,
        "errors": failures[:60],
    }
