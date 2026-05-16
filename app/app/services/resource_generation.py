from __future__ import annotations

import copy
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher

from flask import current_app

from app import db
from app.models import Bookmark, Document, Post, Programme, QuizData, Subject
from app.services.ai_service import generate_academic_bundle
from app.services.document_service import extract_text_from_file
from app.services.quiz_service import DocumentValidationError, normalise_quiz_to_flat_questions, validate_document

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: object, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback
    
def _latexify_math_text(value: object) -> str:
    text = _clean_text(value)
    if not text:
        return text

    # Normalize alternate math delimiters into $...$ / $$...$$
    text = text.replace("\\[", "$$").replace("\\]", "$$")
    text = text.replace("\\(", "$").replace("\\)", "$")

    # If model emits bare LaTeX commands, ensure delimiters are present.
    has_latex_command = bool(re.search(r"\\[A-Za-z]+", text))
    has_math_delimiter = "$" in text
    if has_latex_command and not has_math_delimiter:
        text = f"${text}$"

    return text


def _safe_explanation(text: object) -> str:
    candidate = _latexify_math_text(text)
    if len(candidate.split()) >= 10:
        return candidate
    return "This answer follows directly from the source material and reinforces the core concept."


def _normalize_note_block(block: object) -> dict | None:
    if isinstance(block, str):
        text = _latexify_math_text(block)
        return {"block_type": "paragraph", "text": text} if text else None
    if not isinstance(block, dict):
        return None

    block_type = _clean_text(block.get("block_type"), "paragraph")
    if block_type not in {
        "paragraph", "definition", "theorem", "proof", "note", "formula",
        "example", "worked_example", "list", "table", "diagram_placeholder",
    }:
        block_type = "paragraph"

    normalized: dict = {"block_type": block_type}
    label = _clean_text(block.get("label"))
    if label:
        normalized["label"] = label

    text = _latexify_math_text(block.get("text") or block.get("content") or block.get("body") or block.get("summary"))
    if text:
        normalized["text"] = text

    if block_type in {"worked_example", "proof"}:
        steps = block.get("steps") if isinstance(block.get("steps"), list) else []
        normalized["steps"] = [_latexify_math_text(step) for step in steps if _clean_text(step)]

    if block_type == "list":
        items = block.get("items") if isinstance(block.get("items"), list) else []
        normalized["items"] = [_latexify_math_text(item) for item in items if _clean_text(item)]

    if block_type == "table":
        headers = block.get("headers") if isinstance(block.get("headers"), list) else []
        rows = block.get("rows") if isinstance(block.get("rows"), list) else []
        normalized["headers"] = [_latexify_math_text(item) for item in headers if _clean_text(item)]
        normalized["rows"] = [
            [_latexify_math_text(cell) for cell in row if _clean_text(cell)]
            for row in rows
            if isinstance(row, list)
        ]

    caption = _clean_text(block.get("caption"))
    if caption:
        normalized["caption"] = caption

    return normalized


def _normalize_notes_section(section: object, index: int) -> dict | None:
    if not isinstance(section, dict):
        return None

    raw_content = section.get("content") if isinstance(section.get("content"), list) else []
    if not raw_content:
        raw_content = section.get("blocks") if isinstance(section.get("blocks"), list) else []
    if not raw_content:
        raw_content = section.get("entries") if isinstance(section.get("entries"), list) else []

    content = [_normalize_note_block(block) for block in raw_content]
    content = [block for block in content if block]

    if not content:
        fallback_text = _latexify_math_text(section.get("text") or section.get("content") or section.get("summary") or "Review this section carefully.")
        content = [{"block_type": "paragraph", "text": fallback_text}]

    while len(content) < 3:
        content.append({"block_type": "note", "text": "Expand this section with examples, formulas, or a short summary."})

    section_type = _clean_text(section.get("section_type"), "concepts")
    if section_type not in {"overview", "concepts", "theory", "examples", "worked_examples", "mistakes", "revision", "custom"}:
        section_type = "concepts"

    return {
        "section_number": int(section.get("section_number") or index),
        "section_title": _clean_text(section.get("section_title") or section.get("title") or section.get("heading") or section.get("topic"), f"Section {index}"),
        "section_type": section_type,
        "content": content,
    }


def _normalize_cheatsheet_entry(entry: object) -> dict | None:
    if isinstance(entry, str):
        content = _latexify_math_text(entry)
        return {"label": "Key Point", "content": content} if content else None
    if not isinstance(entry, dict):
        return None

    label = _clean_text(entry.get("label") or entry.get("title") or entry.get("name"), "Key Point")
    content = _latexify_math_text(entry.get("content") or entry.get("formula") or entry.get("text") or entry.get("fact") or entry.get("summary") or "")
    normalized = {"label": label, "content": content or "Review this key point."}
    notes = _clean_text(entry.get("notes"))
    example = _clean_text(entry.get("example"))
    if notes:
        normalized["notes"] = notes
    if example:
        normalized["example"] = example
    return normalized


def _normalize_cheatsheet_section(section: object, index: int) -> dict | None:
    if not isinstance(section, dict):
        return None

    raw_entries = section.get("entries") if isinstance(section.get("entries"), list) else []
    if not raw_entries:
        raw_entries = section.get("content") if isinstance(section.get("content"), list) else []

    entries = [_normalize_cheatsheet_entry(entry) for entry in raw_entries]
    entries = [entry for entry in entries if entry]

    if not entries:
        fallback = _latexify_math_text(section.get("content") or section.get("fact") or section.get("summary") or "Review this key item.")
        entries = [{"label": "Definition", "content": fallback}]

    while len(entries) < 4:
        entries.append({"label": "Application", "content": "Apply this concept using a simple practice example."})

    section_type = _clean_text(section.get("section_type"), "formulas")
    if section_type not in {"formulas", "definitions", "rules", "examples", "summary_table", "steps"}:
        section_type = "formulas"

    return {
        "section_title": _clean_text(section.get("section_title") or section.get("title") or section.get("heading") or section.get("topic"), f"Cheatsheet Section {index}"),
        "section_type": section_type,
        "entries": entries,
    }


def _mcq_options(raw_options: object) -> list[dict]:
    options: list[str] = []
    if isinstance(raw_options, list):
        for opt in raw_options:
            if isinstance(opt, dict):
                options.append(_clean_text(opt.get("text"), "Option"))
            else:
                options.append(_clean_text(opt, "Option"))

    while len(options) < 4:
        options.append(f"Option {len(options) + 1}")

    return [
        {"letter": "A", "text": options[0]},
        {"letter": "B", "text": options[1]},
        {"letter": "C", "text": options[2]},
        {"letter": "D", "text": options[3]},
    ]


def _pick_mcq_answer(raw_answer: object, options: list[dict]) -> str:
    answer_text = _clean_text(raw_answer).upper()
    if answer_text in {"A", "B", "C", "D"}:
        return answer_text

    for item in options:
        if _clean_text(item.get("text")).lower() == _clean_text(raw_answer).lower():
            return item.get("letter", "A")
    return "A"


def _fallback_mcq_options(stem: str, raw_answer: object) -> list[dict]:
    answer_text = _clean_text(raw_answer, "Correct answer")
    distractor_seed = _clean_text(stem, "Question")[:40] or "Question"
    return [
        {"letter": "A", "text": answer_text},
        {"letter": "B", "text": f"Not {answer_text}" if answer_text else f"{distractor_seed} option B"},
        {"letter": "C", "text": f"{distractor_seed} option C"},
        {"letter": "D", "text": f"{distractor_seed} option D"},
    ]


def _to_quiz_sidecar_document(payload: dict, metadata: dict) -> dict:
    raw_questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
    raw_questions = raw_questions[:30]

    mcq_questions = []

    for q in raw_questions:
        if not isinstance(q, dict):
            continue

        stem = _latexify_math_text(q.get("question") or q.get("question_text") or "Review this concept from the source material.")
        marks = 1
        explanation = _safe_explanation(q.get("explanation"))
        raw_options = q.get("options") if isinstance(q.get("options"), list) else []
        options = _mcq_options(raw_options) if len(raw_options) >= 4 else _fallback_mcq_options(stem, q.get("correct_answer") or q.get("answer"))

        mcq_questions.append(
            {
                "question_text": stem,
                "marks": marks,
                "options": options,
                "correct_answer": _pick_mcq_answer(q.get("correct_answer") or q.get("answer"), options),
                "explanation": explanation,
            }
        )

    while len(mcq_questions) < 30:
        question_number = len(mcq_questions) + 1
        stem = f"Question {question_number}: Review the core concept from this study material."
        options = _fallback_mcq_options(stem, "A")
        mcq_questions.append(
            {
                "question_text": stem,
                "marks": 1,
                "options": options,
                "correct_answer": "A",
                "explanation": "This question reinforces the key idea drawn from the source material.",
            }
        )

    sections = []
    section_letter_index = 0

    def add_section(section_title: str, question_type: str, rows: list[dict]) -> None:
        nonlocal section_letter_index
        if not rows:
            return
        section_letter = chr(65 + section_letter_index)
        section_letter_index += 1
        questions = []
        section_marks = 0
        for idx, row in enumerate(rows, start=1):
            question = {"question_number": idx, **row}
            questions.append(question)
            if question_type == "problem_solving":
                section_marks += sum(sp.get("marks", 0) for sp in question.get("subparts", []))
            else:
                section_marks += int(question.get("marks") or 0)

        marks_per_q = section_marks / max(1, len(questions))
        sections.append(
            {
                "section_letter": section_letter,
                "section_title": section_title,
                "question_type": question_type,
                "questions_count": len(questions),
                "marks_per_question": marks_per_q,
                "total_section_marks": section_marks,
                "questions": questions,
            }
        )

    add_section("Multiple Choice", "multiple_choice", mcq_questions)

    if not sections:
        add_section(
            "Multiple Choice",
            "multiple_choice",
            [{"question_text": "Explain the main idea from this source.", "marks": 1, "options": _fallback_mcq_options("Explain the main idea from this source.", "A"), "correct_answer": "A", "explanation": _safe_explanation("")}],
        )

    total_questions = sum(section.get("questions_count", 0) for section in sections)
    total_marks = sum(section.get("total_section_marks", 0) for section in sections)

    return {
        "schema_version": "1.0",
        "document_type": "quiz",
        "generated_at": _now_iso(),
        "title": _clean_text(metadata.get("title"), "Untitled Study Material"),
        "course": _clean_text(metadata.get("subject_hint"), "General Studies"),
        "level": "Intermediate",
        "type": "Self-Assessment Quiz",
        "instructions": ["Read each question carefully and choose the best answer."],
        "metadata": {
            "time": _clean_text((payload.get("metadata") or {}).get("time") if isinstance(payload.get("metadata"), dict) else "30 minutes", "30 minutes"),
            "total_marks": max(1, total_marks),
            "total_questions": 30,
        },
        "sections": sections,
    }


def _to_notes_sidecar_document(payload: dict, metadata: dict) -> dict:
    raw_sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    if not raw_sections:
        raw_sections = [{"title": "Overview", "content": "Review the source material and summarise the key points."}]

    sections = []
    for idx, section in enumerate(raw_sections, start=1):
        normalized_section = _normalize_notes_section(section, idx)
        if normalized_section:
            sections.append(normalized_section)

    raw_summary = payload.get("summary") if isinstance(payload.get("summary"), list) else []
    summary = [_clean_text(item) for item in raw_summary if _clean_text(item)]
    while len(summary) < 5:
        summary.append("Review the section content and reinforce the core idea for retention.")

    payload_meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    return {
        "schema_version": "1.0",
        "document_type": "notes",
        "generated_at": _now_iso(),
        "title": _clean_text(metadata.get("title"), "Untitled Study Material"),
        "course": _clean_text(metadata.get("subject_hint"), "General Studies"),
        "level": "Intermediate",
        "metadata": {
            "estimated_read_time": _clean_text(payload_meta.get("estimated_read_time"), "10 minutes"),
            "focus_areas": _clean_text(payload_meta.get("focus_areas")),
            "prerequisites": _clean_text(payload_meta.get("prerequisites")),
        },
        "sections": sections,
        "summary": summary,
    }


def _to_cheatsheet_sidecar_document(payload: dict, metadata: dict) -> dict:
    raw_sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    if not raw_sections:
        raw_sections = [{"title": "Core Concepts", "content": "Summarise the key formula or definition."}]

    sections = []
    for idx, section in enumerate(raw_sections, start=1):
        normalized_section = _normalize_cheatsheet_section(section, idx)
        if normalized_section:
            sections.append(normalized_section)

    payload_meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    topics = payload_meta.get("topics") if isinstance(payload_meta.get("topics"), list) else []

    return {
        "schema_version": "1.0",
        "document_type": "cheatsheet",
        "generated_at": _now_iso(),
        "title": _clean_text(metadata.get("title"), "Untitled Study Material"),
        "course": _clean_text(metadata.get("subject_hint"), "General Studies"),
        "level": "Intermediate",
        "metadata": {
            "purpose": _clean_text(payload_meta.get("purpose"), "Rapid revision and recall"),
            "exam_context": _clean_text(payload_meta.get("exam_context")),
            "topics": [_clean_text(topic) for topic in topics if _clean_text(topic)],
        },
        "sections": sections,
    }


def _build_sidecar_document(content_type: str, payload: dict, metadata: dict) -> dict:
    if content_type == "quiz":
        return _to_quiz_sidecar_document(payload, metadata)
    if content_type == "notes":
        return _to_notes_sidecar_document(payload, metadata)
    return _to_cheatsheet_sidecar_document(payload, metadata)


def _retry_safe_payload(content_type: str, payload: object) -> dict:
    if content_type == "quiz":
        return _sanitize_quiz(payload)
    if content_type == "notes":
        return _sanitize_notes(payload)
    return _sanitize_cheatsheet(payload)


def _build_and_validate_sidecar_with_retry(
    content_type: str,
    payload: dict,
    metadata: dict,
    max_attempts: int = 2,
) -> dict:
    """
    Validate generated sidecar and automatically retry once with a sanitised
    payload if the first validation pass fails.
    """
    last_error = None
    working_payload: dict = copy.deepcopy(payload) if isinstance(payload, dict) else {}

    for attempt in range(1, max_attempts + 1):
        sidecar_doc = _build_sidecar_document(content_type, working_payload, metadata)
        try:
            validated = validate_document(copy.deepcopy(sidecar_doc))
            if attempt > 1:
                logger.info(
                    "Recovered %s sidecar validation on retry %d/%d",
                    content_type,
                    attempt,
                    max_attempts,
                )
            return validated
        except (DocumentValidationError, ValueError) as exc:
            last_error = exc
            logger.warning(
                "%s sidecar validation failed on attempt %d/%d: %s",
                content_type,
                attempt,
                max_attempts,
                exc,
            )
            if attempt < max_attempts:
                working_payload = _retry_safe_payload(content_type, working_payload)

    raise RuntimeError(
        f"Generated {content_type} sidecar failed validation after {max_attempts} attempts: {last_error}"
    ) from last_error


def _save_sidecar_and_attach_document(post: Post, content_type: str, sidecar_doc: dict) -> Document:
    upload_folder = os.path.join(current_app.root_path, "static", "uploads", "documents")
    os.makedirs(upload_folder, exist_ok=True)

    json_filename = f"{uuid.uuid4().hex}.json"
    abs_json_path = os.path.join(upload_folder, json_filename)
    sidecar_url = f"/static/uploads/documents/{json_filename}"

    payload = json.dumps(sidecar_doc, ensure_ascii=True, indent=2)
    with open(abs_json_path, "w", encoding="utf-8") as fh:
        fh.write(payload)

    document = Document(
        filename=json_filename,
        original_filename=f"generated-{content_type}.json",
        file_path=sidecar_url,
        file_type="json",
        file_size=len(payload.encode("utf-8")),
        json_sidecar_path=sidecar_url,
        is_paid=False,
        price=0.0,
    )
    db.session.add(document)
    db.session.flush()

    post.document_id = document.id
    post.has_document = True
    return document


def _quizdata_from_validated_document(
    validated_doc: dict,
    metadata: dict,
    content_type: str,
    selection_type: str,
    subject_id: int | None,
) -> QuizData:
    doc_type = validated_doc.get("document_type", content_type)

    if doc_type == "quiz":
        questions_to_store = normalise_quiz_to_flat_questions(validated_doc)
        total_marks = int(validated_doc.get("metadata", {}).get("total_marks") or 0)
    elif doc_type == "notes":
        questions_to_store = [
            {
                "section_number": s.get("section_number"),
                "section_title": s.get("section_title"),
                "section_type": s.get("section_type", ""),
                "content": s.get("content", []),
            }
            for s in validated_doc.get("sections", [])
        ]
        total_marks = 0
    else:
        questions_to_store = [
            {
                "section_title": s.get("section_title"),
                "section_type": s.get("section_type", ""),
                "entries": s.get("entries", []),
            }
            for s in validated_doc.get("sections", [])
        ]
        total_marks = 0

    meta_dict = {
        "document_type": doc_type,
        "title": validated_doc.get("title", ""),
        "description": metadata.get("description", ""),
        "subject_hint": metadata.get("subject_hint", ""),
        "programme_hint": metadata.get("programme_hint", ""),
        "faculty_hint": metadata.get("faculty_hint", ""),
        "topic_label": metadata.get("topic_label", ""),
        "topic_key": metadata.get("topic_key", ""),
        "flair": metadata.get("flair", "academic"),
        "schema_version": validated_doc.get("schema_version", ""),
        "course": validated_doc.get("course", ""),
        "level": validated_doc.get("level", ""),
        "document_hash": validated_doc.get("document_hash", ""),
        "generated_at": validated_doc.get("generated_at", ""),
    }
    if subject_id is not None:
        meta_dict["subject_id"] = subject_id

    if doc_type == "quiz":
        vmeta = validated_doc.get("metadata", {})
        meta_dict.update(
            {
                "type": validated_doc.get("type", ""),
                "instructions": validated_doc.get("instructions", []),
                "total_questions": vmeta.get("total_questions", 0),
                "total_marks": vmeta.get("total_marks", total_marks),
                "time": vmeta.get("time", ""),
                "time_allowed": vmeta.get("time_allowed", ""),
            }
        )
    elif doc_type == "notes":
        vmeta = validated_doc.get("metadata", {})
        meta_dict.update(
            {
                "estimated_read_time": vmeta.get("estimated_read_time", ""),
                "focus_areas": vmeta.get("focus_areas", ""),
                "prerequisites": vmeta.get("prerequisites", ""),
                "summary": validated_doc.get("summary", []),
            }
        )
    elif doc_type == "cheatsheet":
        vmeta = validated_doc.get("metadata", {})
        meta_dict.update(
            {
                "purpose": vmeta.get("purpose", ""),
                "exam_context": vmeta.get("exam_context", ""),
                "topics": vmeta.get("topics", []),
            }
        )

    return QuizData(
        questions=json.dumps(questions_to_store),
        meta=json.dumps(meta_dict),
        total_marks=total_marks,
        xp_reward=20 if content_type == selection_type else 10,
    )


def _normalize_post_flair(value: object) -> str:
    raw = str(value or "").strip().lower()
    allowed = {"academic", "casual", "visual", "interactive"}
    if raw in allowed:
        return raw
    if any(token in raw for token in ("question", "quiz", "exam", "test")):
        return "interactive"
    if any(token in raw for token in ("diagram", "chart", "visual")):
        return "visual"
    if any(token in raw for token in ("chat", "discussion", "casual")):
        return "casual"
    return "academic"


def _build_quizdata_payload(content_type: str, payload: dict, metadata: dict) -> tuple[list, dict, int]:
    payload_meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    if content_type == "quiz":
        questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
        total_marks = payload_meta.get("total_marks")
        if not isinstance(total_marks, int):
            total_marks = 0
            for item in questions:
                if isinstance(item, dict) and isinstance(item.get("marks"), (int, float)):
                    total_marks += int(item.get("marks") or 0)
        meta = {
            "document_type": "quiz",
            "title": metadata.get("title", ""),
            "description": metadata.get("description", ""),
            "subject_hint": metadata.get("subject_hint", ""),
            "programme_hint": metadata.get("programme_hint", ""),
            "faculty_hint": metadata.get("faculty_hint", ""),
            "flair": metadata.get("flair", "academic"),
            "total_questions": len(questions),
            "total_marks": total_marks,
            "time": payload_meta.get("time", ""),
            "time_allowed": payload_meta.get("time_allowed", ""),
        }
        return questions, meta, total_marks

    if content_type == "notes":
        sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
        meta = {
            "document_type": "notes",
            "title": metadata.get("title", ""),
            "description": metadata.get("description", ""),
            "subject_hint": metadata.get("subject_hint", ""),
            "programme_hint": metadata.get("programme_hint", ""),
            "faculty_hint": metadata.get("faculty_hint", ""),
            "flair": metadata.get("flair", "academic"),
            "estimated_read_time": payload_meta.get("estimated_read_time", ""),
            "focus_areas": payload_meta.get("focus_areas", ""),
            "prerequisites": payload_meta.get("prerequisites", ""),
            "summary": payload.get("summary", []),
        }
        return sections, meta, 0

    sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    meta = {
        "document_type": "cheatsheet",
        "title": metadata.get("title", ""),
        "description": metadata.get("description", ""),
        "subject_hint": metadata.get("subject_hint", ""),
        "programme_hint": metadata.get("programme_hint", ""),
        "faculty_hint": metadata.get("faculty_hint", ""),
        "flair": metadata.get("flair", "academic"),
        "purpose": payload_meta.get("purpose", ""),
        "exam_context": payload_meta.get("exam_context", ""),
        "topics": payload_meta.get("topics", []),
    }
    return sections, meta, 0


def _slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")


_GENERIC_TOPIC_TOKENS = {
    "study material", "study pack", "untitled", "notes", "quiz", "cheatsheet",
    "summary", "guide", "document", "chapter", "unit", "module", "general topic",
}


def _clean_concept_phrase(value: object) -> str:
    phrase = str(value or "").strip()
    if not phrase:
        return ""
    phrase = re.sub(r"\.(pdf|docx|pptx|ppt|txt)$", "", phrase, flags=re.IGNORECASE)
    phrase = re.sub(r"[_\-|]+", " ", phrase)
    phrase = re.sub(r"\s+", " ", phrase).strip(" :,-")
    return phrase


def _extract_concept_candidates_from_text(text: str, limit: int = 12) -> list[str]:
    if not text:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def _push(raw: object) -> None:
        phrase = _clean_concept_phrase(raw)
        if len(phrase) < 4 or len(phrase) > 80:
            return
        lower = phrase.lower()
        if lower in seen:
            return
        if any(tok in lower for tok in _GENERIC_TOPIC_TOKENS):
            return
        if re.fullmatch(r"[\W_]+", phrase):
            return
        seen.add(lower)
        candidates.append(phrase)

    # Capture probable headings from early lines.
    lines = [ln.strip() for ln in text.splitlines() if ln and ln.strip()]
    for line in lines[:140]:
        if re.search(r"[A-Za-z]", line) and not re.search(r"[.;!?]", line):
            if 4 <= len(line) <= 80:
                _push(line)

    # Capture noun-like title phrases from full text.
    for match in re.finditer(r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){1,6})\b", text):
        _push(match.group(1))

    # Capture common educational phrase patterns.
    for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9]+(?:\s+(?:of|and|for|in|with|to)\s+[A-Za-z0-9]+){1,4})\b", text):
        _push(match.group(1))

    return candidates[:limit]


def _build_concept_extraction_guidance(text: str) -> str:
    hints = _extract_concept_candidates_from_text(text, limit=8)
    guidance = (
        "Topic extraction rule:\n"
        "- Infer one clear MAIN topic and 4-8 SUBTOPICS from the source content itself.\n"
        "- Build quiz, notes, and cheatsheet around those inferred concepts.\n"
        "- Do not anchor generation to the upload filename or a generic title.\n"
        "- In metadata, set topic/focus fields to concept-driven values."
    )
    if hints:
        guidance += "\nLikely concept anchors from the source:\n- " + "\n- ".join(hints)
    return guidance


def _infer_main_topic_and_subtopics(text: str, bundle: dict) -> tuple[str, list[str]]:
    metadata = bundle.get("metadata") if isinstance(bundle.get("metadata"), dict) else {}
    notes = bundle.get("notes") if isinstance(bundle.get("notes"), dict) else {}
    cheatsheet = bundle.get("cheatsheet") if isinstance(bundle.get("cheatsheet"), dict) else {}

    candidates: list[str] = []

    for key in (
        "topic", "main_topic", "subject_topic", "focus_topic", "title",
        "topic_label", "key_topic",
    ):
        value = _clean_concept_phrase(metadata.get(key))
        if value:
            candidates.append(value)

    sections = notes.get("sections") if isinstance(notes.get("sections"), list) else []
    for section in sections[:8]:
        if isinstance(section, dict):
            title = _clean_concept_phrase(section.get("section_title") or section.get("title"))
            if title:
                candidates.append(title)

    cheat_sections = cheatsheet.get("sections") if isinstance(cheatsheet.get("sections"), list) else []
    for section in cheat_sections[:8]:
        if isinstance(section, dict):
            title = _clean_concept_phrase(section.get("section_title") or section.get("title"))
            if title:
                candidates.append(title)

    extracted = _extract_concept_candidates_from_text(text, limit=12)
    candidates.extend(extracted)

    ordered: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        lower = item.lower()
        if not item or lower in seen:
            continue
        seen.add(lower)
        ordered.append(item)

    if not ordered:
        return "General Topic", []

    def _is_generic(phrase: str) -> bool:
        lower = phrase.lower()
        return any(tok in lower for tok in _GENERIC_TOPIC_TOKENS)

    main_topic = next((item for item in ordered if not _is_generic(item)), ordered[0])
    subtopics = [
        item for item in ordered
        if item.lower() != main_topic.lower()
        and SequenceMatcher(None, item.lower(), main_topic.lower()).ratio() < 0.86
        and not _is_generic(item)
    ][:8]

    return main_topic, subtopics


def _build_dynamic_title(main_topic: str, subtopics: list[str]) -> str:
    if not subtopics:
        return f"{main_topic} - Exam-Focused Study Pack"
    suffix = ", ".join(subtopics[:2])
    title = f"{main_topic}: {suffix}"
    if len(title) > 100:
        title = f"{main_topic} - Concept Study Pack"
    return title


def _apply_concept_topic_metadata(bundle: dict, source_text: str) -> None:
    if not isinstance(bundle, dict):
        return
    metadata = bundle.get("metadata") if isinstance(bundle.get("metadata"), dict) else {}
    bundle["metadata"] = metadata

    main_topic, subtopics = _infer_main_topic_and_subtopics(source_text, bundle)
    metadata["main_topic"] = main_topic
    metadata["topic"] = main_topic
    metadata["focus_topic"] = main_topic
    metadata["subtopics"] = subtopics
    metadata["extracted_topics"] = [main_topic, *subtopics][:10]

    existing_title = _clean_concept_phrase(metadata.get("title"))
    if not existing_title or SequenceMatcher(None, existing_title.lower(), main_topic.lower()).ratio() < 0.55:
        metadata["title"] = _build_dynamic_title(main_topic, subtopics)

    if not str(metadata.get("description") or "").strip():
        if subtopics:
            metadata["description"] = f"Covers {main_topic} with focus on {', '.join(subtopics[:3])}."
        else:
            metadata["description"] = f"Covers key concepts and exam practice for {main_topic}."

def _derive_topic_label(metadata: dict, fallback_title: str) -> str:
    """
    Build a stable, user-facing topic label from AI metadata/title.
    This powers subject -> topic grouping for newly generated posts.
    """
    candidate = (
        str((metadata or {}).get("main_topic") or "").strip()
        or str((metadata or {}).get("topic") or "").strip()
        or str((metadata or {}).get("subject_topic") or "").strip()
        or str((metadata or {}).get("focus_topic") or "").strip()
        or str((metadata or {}).get("topic_label") or "").strip()
        or str(fallback_title or "").strip()
    )
    if not candidate:
        return "General Topic"

    # Remove common content-type suffixes to keep one topic across formats.
    candidate = re.sub(
        r"\b(notes?|quiz(?:zes)?|cheat\s*sheet|cheatsheet|flashcards?|summary|guide|study\s+guide)\b",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s*[-:|]\s*$", "", candidate).strip()
    return candidate or "General Topic"

def _topic_key_from_label(label: str) -> str:
    base = _slugify(label)[:80]
    return base or "general-topic"

def _ensure_unique_slug(model, base_slug: str) -> str:
    slug = base_slug or "untitled"
    index = 2
    while model.query.filter_by(slug=slug).first():
        slug = f"{base_slug}-{index}"
        index += 1
    return slug


def _resolve_or_create_programme(
    programme_hint: str | None,
    faculty_hint: str | None,
    *,
    force_new: bool = False,
    preferred_name: str | None = None,
) -> Programme:
    programme_name = (preferred_name or programme_hint or "").strip() or "General Studies"
    faculty_name = (faculty_hint or "").strip() or "General"

    exact = Programme.query.filter(Programme.name.ilike(programme_name)).first()
    if exact:
        if faculty_name and not exact.faculty:
            exact.faculty = faculty_name
        return exact

    if not force_new:
        best_match = None
        best_score = 0.0
        for programme in Programme.query.all():
            score = SequenceMatcher(None, programme.name.lower(), programme_name.lower()).ratio()
            if score > best_score:
                best_score = score
                best_match = programme

        if best_match and best_score >= 0.88:
            if faculty_name and not best_match.faculty:
                best_match.faculty = faculty_name
            return best_match

    base_slug = _slugify(programme_name) or "general-studies"
    programme = Programme(
        name=programme_name,
        slug=_ensure_unique_slug(Programme, base_slug),
        description=f"AI-generated programme for {programme_name}",
        icon="graduation-cap",
        color="#8b5cf6",
        order=999,
        is_active=True,
        faculty=faculty_name,
    )
    db.session.add(programme)
    db.session.flush()
    return programme


def _resolve_or_create_subject(meta: dict, content_payload: dict) -> Subject:
    subject_hint = (
        (meta.get("matched_subject_name") or "").strip()
        or (meta.get("subject_hint") or "").strip()
        or "General Studies"
    )
    programme_hint = (meta.get("programme_hint") or "").strip()
    matched_programme_name = (meta.get("matched_programme_name") or "").strip()
    faculty_hint = (meta.get("faculty_hint") or "").strip()
    subject_force_new = str(meta.get("subject_match_basis") or "").strip().lower() == "new"
    programme_force_new = str(meta.get("programme_match_basis") or "").strip().lower() == "new"

    exact = Subject.query.filter(Subject.name.ilike(subject_hint)).first()
    chosen = exact

    if not chosen and not subject_force_new:
        best_match = None
        best_score = 0.0
        for subject in Subject.query.all():
            score = SequenceMatcher(None, subject.name.lower(), subject_hint.lower()).ratio()
            if score > best_score:
                best_score = score
                best_match = subject
        if best_match and best_score >= 0.86:
            chosen = best_match

    if chosen:
        if programme_hint or faculty_hint:
            target_programme = _resolve_or_create_programme(
                programme_hint,
                faculty_hint,
                force_new=programme_force_new,
                preferred_name=matched_programme_name,
            )
            if not chosen.programmes.filter_by(id=target_programme.id).first():
                chosen.programmes.append(target_programme)
        return chosen

    base_slug = _slugify(subject_hint) or "general-studies"
    subject = Subject(
        name=subject_hint,
        slug=_ensure_unique_slug(Subject, base_slug),
        description=meta.get("description") or "AI-generated study subject",
        icon="book",
        color="#6366f1",
        order=999,
        is_active=True,
    )
    db.session.add(subject)
    db.session.flush()

    programme = _resolve_or_create_programme(
        programme_hint,
        faculty_hint,
        force_new=programme_force_new,
        preferred_name=matched_programme_name,
    )
    subject.programmes.append(programme)
    return subject


def _taxonomy_context_for_ai(subject_limit: int = 350, programme_limit: int = 160) -> dict:
    subjects = [
        row.name
        for row in Subject.query.filter_by(is_active=True)
        .order_by(Subject.name.asc())
        .limit(subject_limit)
        .all()
    ]

    programmes = Programme.query.filter_by(is_active=True).order_by(Programme.name.asc()).limit(programme_limit).all()
    programme_names = [row.name for row in programmes]
    faculties = sorted({(row.faculty or "").strip() for row in programmes if (row.faculty or "").strip()})

    return {
        "subjects": subjects,
        "programmes": programme_names,
        "faculties": faculties,
    }


def get_taxonomy_context_for_ai(subject_limit: int = 350, programme_limit: int = 160) -> dict:
    """Public wrapper so other services can reuse taxonomy context safely."""
    return _taxonomy_context_for_ai(subject_limit=subject_limit, programme_limit=programme_limit)


def _validate_taxonomy_selection(metadata: dict, taxonomy_context: dict) -> tuple[bool, dict, str | None]:
    if not isinstance(metadata, dict):
        return False, {}, "Bundle metadata is missing or invalid."

    normalized = dict(metadata)
    subject_map = {name.lower(): name for name in taxonomy_context.get("subjects", []) if isinstance(name, str)}
    programme_map = {name.lower(): name for name in taxonomy_context.get("programmes", []) if isinstance(name, str)}

    subject_basis = str(normalized.get("subject_match_basis") or "new").strip().lower()
    programme_basis = str(normalized.get("programme_match_basis") or "new").strip().lower()

    matched_subject = str(normalized.get("matched_subject_name") or "").strip()
    matched_programme = str(normalized.get("matched_programme_name") or "").strip()

    if subject_basis == "existing":
        canonical = subject_map.get(matched_subject.lower())
        if not canonical:
            return False, normalized, "subject marked existing but matched_subject_name is not an exact DB name"
        normalized["matched_subject_name"] = canonical
        normalized["subject_hint"] = canonical
    else:
        normalized["matched_subject_name"] = ""

    if programme_basis == "existing":
        canonical = programme_map.get(matched_programme.lower())
        if not canonical:
            return False, normalized, "programme marked existing but matched_programme_name is not an exact DB name"
        normalized["matched_programme_name"] = canonical
        normalized["programme_hint"] = canonical
    else:
        normalized["matched_programme_name"] = ""

    return True, normalized, None


def _validate_bundle_content_quality(bundle: dict) -> tuple[bool, str | None]:
    if not isinstance(bundle, dict):
        return False, "Bundle payload is invalid."

    metadata = bundle.get("metadata") if isinstance(bundle.get("metadata"), dict) else {}
    title = str(metadata.get("title") or "").strip()
    description = str(metadata.get("description") or "").strip()
    subject_hint = str(metadata.get("subject_hint") or "").strip()

    if not title or not description or not subject_hint:
        return False, "metadata missing required fields (title/description/subject_hint)"

    quiz = bundle.get("quiz") if isinstance(bundle.get("quiz"), dict) else {}
    notes = bundle.get("notes") if isinstance(bundle.get("notes"), dict) else {}
    cheatsheet = bundle.get("cheatsheet") if isinstance(bundle.get("cheatsheet"), dict) else {}

    quiz_questions = quiz.get("questions") if isinstance(quiz.get("questions"), list) else []
    note_sections = notes.get("sections") if isinstance(notes.get("sections"), list) else []
    cheat_sections = cheatsheet.get("sections") if isinstance(cheatsheet.get("sections"), list) else []

    if not quiz_questions:
        return False, "quiz.questions is empty"
    if not note_sections:
        return False, "notes.sections is empty"
    if not cheat_sections:
        return False, "cheatsheet.sections is empty"

    return True, None


def _bundle_repair_snapshot(bundle: dict) -> str:
    """Compact bundle snapshot sent back to AI for targeted corrections."""
    if not isinstance(bundle, dict):
        return "{}"

    def _trim_text(value: object, limit: int = 200) -> str:
        return str(value or "").strip()[:limit]

    quiz = bundle.get("quiz") if isinstance(bundle.get("quiz"), dict) else {}
    notes = bundle.get("notes") if isinstance(bundle.get("notes"), dict) else {}
    cheatsheet = bundle.get("cheatsheet") if isinstance(bundle.get("cheatsheet"), dict) else {}

    snapshot = {
        "metadata": bundle.get("metadata", {}),
        "quiz": {
            "question_count": len(quiz.get("questions") or []) if isinstance(quiz.get("questions"), list) else 0,
            "sample_questions": [
                _trim_text((q or {}).get("question"))
                for q in (quiz.get("questions") or [])[:3]
                if isinstance(q, dict)
            ],
        },
        "notes": {
            "section_count": len(notes.get("sections") or []) if isinstance(notes.get("sections"), list) else 0,
            "sample_sections": [
                _trim_text((s or {}).get("section_title"))
                for s in (notes.get("sections") or [])[:3]
                if isinstance(s, dict)
            ],
        },
        "cheatsheet": {
            "section_count": len(cheatsheet.get("sections") or []) if isinstance(cheatsheet.get("sections"), list) else 0,
            "sample_sections": [
                _trim_text((s or {}).get("section_title"))
                for s in (cheatsheet.get("sections") or [])[:3]
                if isinstance(s, dict)
            ],
        },
    }
    return json.dumps(snapshot, ensure_ascii=True)


def _merge_repaired_bundle(original: dict, repaired: dict) -> dict:
    """Preserve valid existing sections and only overlay repaired fields."""
    if not isinstance(original, dict):
        return repaired if isinstance(repaired, dict) else {}
    if not isinstance(repaired, dict):
        return original

    merged = copy.deepcopy(original)

    repaired_meta = repaired.get("metadata") if isinstance(repaired.get("metadata"), dict) else {}
    original_meta = merged.get("metadata") if isinstance(merged.get("metadata"), dict) else {}
    merged["metadata"] = {**original_meta, **repaired_meta}

    for key in ("quiz", "notes", "cheatsheet"):
        candidate = repaired.get(key)
        if isinstance(candidate, dict) and candidate:
            merged[key] = candidate

    if isinstance(repaired.get("is_academic"), bool):
        merged["is_academic"] = repaired.get("is_academic")

    return merged


def _request_targeted_bundle_repair(
    text: str,
    taxonomy_context: dict,
    current_bundle: dict,
    issues: list[str],
) -> dict:
    issue_lines = "\n".join(f"- {item}" for item in issues if item)
    repair_guidance = (
        "You already generated a mostly usable academic bundle. "
        "Do NOT regenerate from scratch. Preserve all valid parts and fix only the listed issues.\n"
        f"Issues to fix:\n{issue_lines}\n\n"
        "Current bundle snapshot (for patching context):\n"
        f"{_bundle_repair_snapshot(current_bundle)}\n\n"
        "Return a complete corrected bundle JSON with metadata, quiz, notes, and cheatsheet."
    )
    return generate_academic_bundle(
        text,
        taxonomy_context=taxonomy_context,
        extra_guidance=repair_guidance,
    )


def _sanitize_quiz(quiz: object) -> dict:
    """Ensure quiz has valid structure with fallback defaults."""
    if not isinstance(quiz, dict):
        quiz = {}
    
    questions = quiz.get("questions") if isinstance(quiz.get("questions"), list) else []
    
    sanitized_questions = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        safe_q = {
            "question": str(q.get("question") or "Question").strip()[:300] or "Question",
            "options": [],
            "answer": "A",
            "explanation": str(q.get("explanation") or "").strip()[:500]
        }
        
        raw_opts = q.get("options") or q.get("choices") or []
        if isinstance(raw_opts, list):
            for opt in raw_opts[:4]:
                opt_text = str(opt.get("text") if isinstance(opt, dict) else opt or "").strip()[:200]
                if opt_text:
                    safe_q["options"].append({"text": opt_text})
        
        while len(safe_q["options"]) < 4:
            safe_q["options"].append({"text": f"Option {len(safe_q['options']) + 1}"})
        
        safe_q["options"] = safe_q["options"][:4]
        
        sanitized_questions.append(safe_q)
    
    if not sanitized_questions:
        sanitized_questions = [
            {
                "question": "What is the key concept?",
                "options": [
                    {"text": "Primary concept"},
                    {"text": "Alternative viewpoint"},
                    {"text": "Related concept"},
                    {"text": "Contrasting idea"}
                ],
                "answer": "A",
                "explanation": "Review the source material for this answer."
            }
        ]
    
    return {"questions": sanitized_questions[:30]}


def _sanitize_notes(notes: object) -> dict:
    """Ensure notes have valid structure with fallback defaults."""
    if not isinstance(notes, dict):
        notes = {}
    
    sections = notes.get("sections") if isinstance(notes.get("sections"), list) else []
    
    sanitized_sections = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        
        safe_section = {
            "section_title": str(section.get("section_title") or "Section").strip()[:200] or "Section",
            "section_type": "concepts",
            "content": []
        }
        
        raw_content = section.get("content") or section.get("blocks") or []
        if isinstance(raw_content, list):
            for block in raw_content[:6]:
                norm_block = _normalize_note_block(block)
                if norm_block:
                    safe_section["content"].append(norm_block)
        
        if not safe_section["content"]:
            safe_section["content"] = [
                {"block_type": "paragraph", "text": "Key concepts and definitions for this section."}
            ]
        
        sanitized_sections.append(safe_section)
    
    if not sanitized_sections:
        sanitized_sections = [
            {
                "section_title": "Key Concepts",
                "section_type": "concepts",
                "content": [
                    {"block_type": "paragraph", "text": "Core ideas and principles covered in the source material."}
                ]
            }
        ]
    
    return {"sections": sanitized_sections[:10]}


def _sanitize_cheatsheet(cheatsheet: object) -> dict:
    """Ensure cheatsheet has valid structure with fallback defaults."""
    if not isinstance(cheatsheet, dict):
        cheatsheet = {}
    
    sections = cheatsheet.get("sections") if isinstance(cheatsheet.get("sections"), list) else []
    
    sanitized_sections = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        
        safe_section = {
            "section_title": str(section.get("section_title") or "Reference").strip()[:200] or "Reference",
            "section_type": "formulas",
            "entries": []
        }
        
        raw_entries = section.get("entries") or section.get("content") or []
        if isinstance(raw_entries, list):
            for entry in raw_entries[:8]:
                norm_entry = _normalize_cheatsheet_entry(entry)
                if norm_entry:
                    safe_section["entries"].append(norm_entry)
        
        if not safe_section["entries"]:
            safe_section["entries"] = [
                {"label": "Key Fact", "content": "Important information from the section"}
            ]
        
        sanitized_sections.append(safe_section)
    
    if not sanitized_sections:
        sanitized_sections = [
            {
                "section_title": "Quick Reference",
                "section_type": "formulas",
                "entries": [
                    {"label": "Definition", "content": "Key concept summary"}
                ]
            }
        ]
    
    return {"sections": sanitized_sections[:8]}


def build_validated_bundle_from_text(
    text: str,
    *,
    taxonomy_context: dict | None = None,
) -> dict:
    """
    Generate an academic bundle and run the full validation/repair/sanitization
    pipeline used by upload analysis.
    """
    safe_text = (text or "").strip()
    if len(safe_text) < 10:
        return {
            "ok": False,
            "error": "Could not extract enough text from document.",
            "bundle": None,
        }

    context = taxonomy_context or _taxonomy_context_for_ai()
    concept_guidance = _build_concept_extraction_guidance(safe_text)
    bundle = generate_academic_bundle(
        safe_text,
        taxonomy_context=context,
        extra_guidance=concept_guidance,
    )
    if isinstance(bundle, dict) and bundle.get("error"):
        return {
            "ok": False,
            "error": bundle["error"],
            "bundle": None,
        }

    repair_applied = False
    repair_reasons: list[str] = []

    if isinstance(bundle, dict) and bundle.get("is_academic") is True:
        _apply_concept_topic_metadata(bundle, safe_text)
        quality_ok, quality_error = _validate_bundle_content_quality(bundle)
        if not quality_ok:
            logger.warning("AI bundle quality invalid on first pass: %s", quality_error)
            repair_applied = True
            repair_reasons.append(f"content_quality: {quality_error}")
            bundle_retry = _request_targeted_bundle_repair(
                text=safe_text,
                taxonomy_context=context,
                current_bundle=bundle,
                issues=[
                    f"Bundle quality check failed: {quality_error}",
                    "Ensure metadata has title, description, and subject_hint.",
                    "Ensure quiz.questions, notes.sections, and cheatsheet.sections are non-empty arrays.",
                ],
            )
            if isinstance(bundle_retry, dict) and bundle_retry.get("error"):
                return {
                    "ok": False,
                    "error": bundle_retry["error"],
                    "bundle": None,
                }
            bundle = _merge_repaired_bundle(bundle, bundle_retry)

        is_valid, normalized_meta, validation_error = _validate_taxonomy_selection(
            bundle.get("metadata", {}),
            context,
        )
        if not is_valid:
            logger.warning("AI taxonomy selection invalid on first pass: %s", validation_error)
            repair_applied = True
            repair_reasons.append(f"taxonomy: {validation_error}")
            bundle_retry = _request_targeted_bundle_repair(
                text=safe_text,
                taxonomy_context=context,
                current_bundle=bundle,
                issues=[
                    f"Taxonomy validation failed: {validation_error}",
                    "If *_match_basis is 'existing', matched_*_name must be an exact DB name from the provided lists.",
                    "If no exact DB name exists, set *_match_basis to 'new' and provide a specific *_hint.",
                ],
            )
            if isinstance(bundle_retry, dict) and bundle_retry.get("error"):
                return {
                    "ok": False,
                    "error": bundle_retry["error"],
                    "bundle": None,
                }

            bundle_retry = _merge_repaired_bundle(bundle, bundle_retry)

            if isinstance(bundle_retry, dict) and bundle_retry.get("is_academic") is True:
                retry_valid, retry_normalized_meta, retry_error = _validate_taxonomy_selection(
                    bundle_retry.get("metadata", {}),
                    context,
                )
                if not retry_valid:
                    return {
                        "ok": False,
                        "error": "AI taxonomy matching failed validation twice. Please try again.",
                        "reason": retry_error,
                        "bundle": None,
                    }
                bundle_retry["metadata"] = retry_normalized_meta
            bundle = bundle_retry
        else:
            bundle["metadata"] = normalized_meta

        bundle["quiz"] = _sanitize_quiz(bundle.get("quiz"))
        bundle["notes"] = _sanitize_notes(bundle.get("notes"))
        bundle["cheatsheet"] = _sanitize_cheatsheet(bundle.get("cheatsheet"))
        bundle["repair_applied"] = repair_applied
        bundle["repair_reasons"] = repair_reasons

    return {
        "ok": True,
        "bundle": bundle,
        "error": None,
    }


def analyze_uploaded_resource(file_path: str) -> dict:
    """
    Extract text from an uploaded file and ask the AI layer for a structured
    academic bundle.
    """
    text = extract_text_from_file(file_path)
    if not text or len(text.strip()) < 10:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            error_message = (
                "Could not extract readable text from this PDF. "
                "It may be scanned/image-only; try an OCR-enabled PDF or a text-based export."
            )
        else:
            error_message = "Could not extract enough text from document."

        return {
            "ok": False,
            "error": error_message,
            "text": text or "",
        }

    taxonomy_context = _taxonomy_context_for_ai()
    generation_result = build_validated_bundle_from_text(text, taxonomy_context=taxonomy_context)
    if not generation_result.get("ok"):
        response = {
            "ok": False,
            "error": generation_result.get("error") or "AI generation failed.",
            "text": text,
        }
        if generation_result.get("reason"):
            response["reason"] = generation_result["reason"]
        return response

    bundle = generation_result.get("bundle")

    return {
        "ok": True,
        "text": text,
        "bundle": bundle,
    }

def _find_existing_resource(
    subject_id: int | None,
    content_type: str,
    ai_title: str,
    description: str,
) -> Post | None:
    """
    Search for an existing post with the same subject, content_type, and similar title/description.
    Uses semantic similarity (via SequenceMatcher) to detect duplicates.
    Returns the existing Post if found (high confidence match), None otherwise.
    """
    if not subject_id or not ai_title or content_type not in {"quiz", "notes", "cheatsheet"}:
        return None

    try:
        existing_posts = Post.query.filter_by(
            subject_id=subject_id,
            content_type=content_type,
            status="approved"
        ).order_by(Post.created_at.desc()).all()

        if not existing_posts:
            return None

        ai_title_lower = ai_title.lower().strip()
        description_lower = (description or "").lower().strip()

        for post in existing_posts:
            post_title_lower = (post.title or "").lower().strip()
            post_desc_lower = (post.description or "").lower().strip()

            title_similarity = SequenceMatcher(None, ai_title_lower, post_title_lower).ratio()
            description_similarity = SequenceMatcher(None, description_lower, post_desc_lower).ratio() if description_lower and post_desc_lower else 0.0

            combined_similarity = (title_similarity * 0.7) + (description_similarity * 0.3)

            if combined_similarity >= 0.78:
                logger.info(
                    "Found existing %s for subject_id=%s (similarity=%.2f, existing_post_id=%d)",
                    content_type, subject_id, combined_similarity, post.id
                )
                return post

        return None
    except Exception as exc:
        logger.warning("Error searching for existing resource: %s", exc)
        return None


def save_generated_selection(
    selection_type: str,
    content: dict,
    metadata: dict,
    user,
    subject_id: int | None = None,
    bundle: dict | None = None,
    content_difficulty: str | None = None,
) -> tuple[Post | None, str | None]:
    """
    Persist a generated selection as a post and quiz payload.
    Returns (post, error_message).
    """
    if selection_type not in {"quiz", "notes", "cheatsheet"}:
        return None, "Unsupported selection type."

    try:
        metadata_copy = dict(metadata or {})
        bundle_copy = copy.deepcopy(bundle) if isinstance(bundle, dict) else None
        primary_payload = copy.deepcopy(content)

        ai_title = (metadata_copy.get("title") or "").strip()
        if not ai_title:
            ai_title = (metadata_copy.get("subject_hint") or "Untitled Study Material").strip()

        metadata_copy["topic_label"] = _derive_topic_label(metadata_copy, ai_title)
        metadata_copy["topic_key"] = _topic_key_from_label(metadata_copy["topic_label"])

        subject = None
        if subject_id:
            try:
                subject = db.session.get(Subject, int(subject_id))
            except (TypeError, ValueError):
                subject = None

        persisted_posts: dict[str, Post] = {}
        if not subject:
            with db.session.no_autoflush:
                subject = _resolve_or_create_subject(metadata_copy, primary_payload)

        existing = _find_existing_resource(
            subject_id=subject.id if subject else None,
            content_type=selection_type,
            ai_title=ai_title,
            description=metadata_copy.get("description", "")
        )
        if existing:
            logger.info("Reusing existing %s (id=%d) instead of regenerating", selection_type, existing.id)
            user_bookmark = Bookmark.query.filter_by(
                user_id=user.id,
                post_id=existing.id
            ).first()
            if not user_bookmark:
                db.session.add(Bookmark(user_id=user.id, post_id=existing.id))
                db.session.commit()
            return existing, None

        persisted_posts: dict[str, Post] = {}

        def _persist_one(content_type: str, payload: dict, is_primary: bool = False) -> Post:
            payload_copy = copy.deepcopy(payload)
            payload_copy["document_type"] = content_type

            post = Post(
                title=ai_title or "Untitled Study Material",
                description=metadata_copy.get("description", ""),
                author=user,
                status="approved",
                content_type=content_type,
                flair=_normalize_post_flair(metadata_copy.get("flair", "academic")),
                content_difficulty=content_difficulty or None,
            )
            db.session.add(post)

            nonlocal subject
            if subject is None:
                with db.session.no_autoflush:
                    subject = _resolve_or_create_subject(metadata_copy, payload_copy)

            if subject is not None:
                    # Removed duplicate subject resolution
                    post.subject_id = subject.id

            db.session.flush()

            sidecar_doc = _build_sidecar_document(content_type, payload_copy, metadata_copy)
            validated_sidecar = _build_and_validate_sidecar_with_retry(
                content_type=content_type,
                payload=payload_copy,
                metadata=metadata_copy,
                max_attempts=2,
            )

            _save_sidecar_and_attach_document(post, content_type, validated_sidecar)

            quiz_data = _quizdata_from_validated_document(
                validated_doc=validated_sidecar,
                metadata=metadata_copy,
                content_type=content_type,
                selection_type=selection_type,
                subject_id=subject.id if subject is not None else None,
            )
            quiz_data.post_id = post.id
            db.session.add(quiz_data)

            if is_primary:
                db.session.add(Bookmark(user_id=user.id, post_id=post.id))

            persisted_posts[content_type] = post
            return post

        if bundle_copy and any(isinstance(bundle_copy.get(ct), dict) for ct in ("quiz", "notes", "cheatsheet")):
            for content_type in ("quiz", "notes", "cheatsheet"):
                payload = bundle_copy.get(content_type)
                if isinstance(payload, dict):
                    _persist_one(content_type, payload, is_primary=(content_type == selection_type))
        else:
            _persist_one(selection_type, primary_payload, is_primary=True)

        if subject is not None:
            subject.post_count = subject.posts.count()

        db.session.commit()
        return persisted_posts.get(selection_type), None
    except Exception as exc:
        db.session.rollback()
        logger.exception("Failed to save generated selection")
        return None, str(exc)