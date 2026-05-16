"""
app/services/quiz_service.py
============================
Quiz document validation, storage, and normalisation service.

This module is the SINGLE source of truth for:
  - Quiz JSON schema validation (embedded, no external files required)
  - Semantic validation (marks totals, numbering, option counts)
  - Flat-question normalisation (sections → grading-ready list)
  - Database write (QuizData)
  - quiz_from_sidecar helper (used during post approval)

Question type handling
----------------------
    multiple_choice  → 4 selectable options (A/B/C/D)

Quiz generation is intentionally MCQ-only in this app. Notes and cheatsheets
retain their structured validation and normalisation rules.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# EMBEDDED JSON SCHEMAS  (Draft 7)
# ═══════════════════════════════════════════════════════════════════════════════

_QUIZ_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["document_type", "title", "course", "level", "metadata", "sections"],
    "properties": {
        "document_type": {"type": "string", "enum": ["quiz"]},
        "title":         {"type": "string", "minLength": 1},
        "course":        {"type": "string"},
        "level":         {"type": "string"},
        "generated_at":  {"type": "string"},
        "document_hash": {"type": "string"},
        "schema_version":{"type": "string"},
        "type":          {"type": "string"},
        "instructions":  {
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}}
            ]
        },
        "metadata": {
            "type": "object",
            "required": ["total_questions", "total_marks"],
            "properties": {
                "total_questions":   {"type": "integer", "minimum": 1},
                "total_marks":       {"type": "integer", "minimum": 1},
                "time":              {"type": "string"},
                "time_allowed":      {"type": "string"},
            }
        },
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "section_letter", "section_title",
                    "question_type", "questions_count", "questions"
                ],
                "properties": {
                    "section_letter":      {"type": "string"},
                    "section_title":       {"type": "string"},
                    "question_type": {
                        "type": "string",
                        "enum": ["multiple_choice"]
                    },
                    "questions_count":     {"type": "integer", "minimum": 1},
                    "marks_per_question":  {"type": "number"},
                    "total_section_marks": {"type": "integer"},
                    "questions": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["question_number"],
                            "properties": {
                                "question_number": {"type": "integer"},
                                "question_text":   {"type": "string"},
                                "question":        {"type": "string"},
                                "marks":           {"type": ["integer", "number"]},
                                "correct_answer":  {},
                                "answer":          {},
                                "explanation":     {"type": "string"},
                                "options": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "letter": {"type": "string"},
                                            "text":   {"type": "string"},
                                        }
                                    }
                                },
                                "subparts": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "label":          {"type": "string"},
                                            "question_text":  {"type": "string"},
                                            "question":       {"type": "string"},
                                            "marks":          {"type": "integer"},
                                            "correct_answer": {},
                                            "answer":         {},
                                            "explanation":    {"type": "string"},
                                            "options": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "letter": {"type": "string"},
                                                        "text":   {"type": "string"},
                                                    }
                                                }
                                            },
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

_NOTES_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["document_type", "title", "course", "level", "metadata", "sections"],
    "properties": {
        "document_type": {"type": "string", "enum": ["notes"]},
        "title":         {"type": "string", "minLength": 1},
        "course":        {"type": "string"},
        "level":         {"type": "string"},
        "generated_at":  {"type": "string"},
        "document_hash": {"type": "string"},
        "summary": {
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}}
            ]
        },
        "metadata": {
            "type": "object",
            "properties": {
                "estimated_read_time": {"type": "string"},
            }
        },
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["section_number", "section_title", "content"],
                "properties": {
                    "section_number": {"type": "integer", "minimum": 1},
                    "section_title":  {"type": "string"},
                    "section_type":   {"type": "string"},
                    "content": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["block_type"],
                            "properties": {
                                "block_type": {
                                    "type": "string",
                                    "enum": [
                                        "paragraph", "definition", "theorem",
                                        "proof", "note", "formula", "example",
                                        "worked_example", "list", "table",
                                        "diagram_placeholder"
                                    ]
                                },
                                "label": {"type": "string"},
                                "text":  {"type": "string"},
                                "caption": {"type": "string"},
                                "items": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "steps": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "headers": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                },
                                "rows": {
                                    "type": "array",
                                    "items": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    }
                                },
                            }
                        }
                    }
                }
            }
        }
    }
}

_CHEATSHEET_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["document_type", "title", "course", "level", "sections"],
    "properties": {
        "document_type": {"type": "string", "enum": ["cheatsheet"]},
        "title":         {"type": "string", "minLength": 1},
        "course":        {"type": "string"},
        "level":         {"type": "string"},
        "generated_at":  {"type": "string"},
        "document_hash": {"type": "string"},
        "metadata":      {"type": "object"},
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["section_title", "entries"],
                "properties": {
                    "section_title": {"type": "string"},
                    "section_type":  {"type": "string"},
                    "entries": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["label", "content"],
                            "properties": {
                                "label":   {"type": "string"},
                                "content": {"type": "string"},
                                "notes":   {"type": "string"},
                                "example": {"type": "string"},
                            }
                        }
                    }
                }
            }
        }
    }
}

_SCHEMAS: dict[str, dict] = {
    "quiz":       _QUIZ_SCHEMA,
    "notes":      _NOTES_SCHEMA,
    "cheatsheet": _CHEATSHEET_SCHEMA,
}


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

class DocumentValidationError(Exception):
    """
    Raised when a document fails Phase 1 or Phase 2 validation.
    `errors` is a list of human-readable violation strings.
    """
    def __init__(self, errors: list[str]):
        self.errors = errors
        bullet_list = "\n".join(f"  • {e}" for e in errors)
        super().__init__(f"{len(errors)} validation error(s):\n{bullet_list}")


def validate_document(doc: dict) -> dict:
    """
    Validate and enrich a document dict.

    Runs schema validation, then type-specific semantic checks,
    then stamps generated_at and document_hash.

    Returns:
        The same dict with generated_at and document_hash populated.

    Raises:
        DocumentValidationError: Containing all violations found.
        ValueError: If document_type is missing or unrecognised.
    """
    doc_type = doc.get("document_type")
    if doc_type not in _SCHEMAS:
        raise ValueError(
            f"document_type '{doc_type}' is invalid or missing. "
            f"Must be one of: {list(_SCHEMAS)}"
        )

    errors: list[str] = []

    # Phase 1: JSON Schema
    errors.extend(_run_schema_validation(doc, doc_type))
    if errors:
        raise DocumentValidationError(errors)

    # Phase 2: Semantic validation
    semantic_fn = {
        "quiz":       _validate_quiz_semantics,
        "notes":      _validate_notes_semantics,
        "cheatsheet": _validate_cheatsheet_semantics,
    }[doc_type]

    errors.extend(semantic_fn(doc))
    if errors:
        raise DocumentValidationError(errors)

    # Phase 3: Enrich
    _enrich_document(doc)

    logger.info(
        "Document validated OK: type=%s title='%s' hash=%s",
        doc_type, doc.get("title", ""), doc.get("document_hash", "")[:12]
    )
    return doc


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — JSON SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

def _run_schema_validation(doc: dict, doc_type: str) -> list[str]:
    """Return list of schema violation strings (empty = pass)."""
    try:
        import jsonschema
        from jsonschema import Draft7Validator
    except ImportError:
        raise ImportError("jsonschema not installed. Run: pip install jsonschema")

    schema    = _SCHEMAS[doc_type]
    validator = Draft7Validator(schema)
    errors    = []

    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        path = " → ".join(str(p) for p in err.absolute_path) or "root"
        errors.append(f"[SCHEMA] {path}: {err.message}")

    return errors


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — SEMANTIC VALIDATORS
# ═══════════════════════════════════════════════════════════════════════════════

def _validate_quiz_semantics(doc: dict) -> list[str]:
    errors: list[str] = []

    sections = doc.get("sections", [])
    declared_total_q = doc["metadata"]["total_questions"]
    declared_total_m = doc["metadata"]["total_marks"]

    # Section letters must be sequential A → D
    actual_letters   = [s["section_letter"] for s in sections]
    expected_letters = [chr(65 + i) for i in range(len(sections))]
    if actual_letters != expected_letters:
        errors.append(
            f"[SEMANTIC] Section letters must be sequential A→D; "
            f"got {actual_letters}"
        )

    actual_total_q = 0
    actual_total_m = 0

    for section in sections:
        s_letter  = section["section_letter"]
        s_type    = section["question_type"]
        questions = section.get("questions", [])

        if s_type != "multiple_choice":
            errors.append(
                f"[SEMANTIC] Section {s_letter}: only multiple_choice sections are allowed, got '{s_type}'"
            )

        # Declared vs actual question count
        if len(questions) != section["questions_count"]:
            errors.append(
                f"[SEMANTIC] Section {s_letter}: header declares "
                f"{section['questions_count']} questions but "
                f"{len(questions)} are present"
            )

        # Question numbering (1-based, sequential within section)
        for i, q in enumerate(questions):
            expected_num = i + 1
            actual_num   = q.get("question_number")
            if actual_num != expected_num:
                errors.append(
                    f"[SEMANTIC] Section {s_letter} Q{i+1}: "
                    f"expected question_number={expected_num}, got {actual_num}"
                )

        # Type-specific checks
        if s_type == "multiple_choice":
            errors.extend(_check_mcq_section(s_letter, questions))
        elif s_type == "true_false":
            errors.extend(_check_tf_section(s_letter, questions))
        elif s_type == "short_answer":
            errors.extend(_check_sa_section(s_letter, questions))
        elif s_type == "problem_solving":
            errors.extend(_check_ps_section(s_letter, questions))

        # Explanation length (only for non-problem_solving; ps checks per subpart)
        if s_type != "problem_solving":
            for q in questions:
                _check_explanation_length(
                    q.get("explanation", ""),
                    f"Section {s_letter} Q{q.get('question_number', '?')}",
                    errors
                )

        # Marks accumulation — auto-correct section total
        section_marks = _compute_section_marks(s_type, questions)
        declared_section_marks = section.get("total_section_marks", section_marks)
        if section_marks != declared_section_marks:
            logger.warning(
                "Section %s: auto-correcting total_section_marks %s → %s",
                s_letter, declared_section_marks, section_marks,
            )
            section["total_section_marks"] = section_marks

        actual_total_m += section_marks
        actual_total_q += len(questions)

    # Auto-correct metadata totals
    if actual_total_q != declared_total_q:
        logger.warning(
            "Auto-correcting metadata.total_questions %s → %s",
            declared_total_q, actual_total_q,
        )
        doc["metadata"]["total_questions"] = actual_total_q

    if declared_total_q != 30:
        errors.append(
            f"[SEMANTIC] metadata.total_questions must be exactly 30, got {declared_total_q}"
        )

    if actual_total_q != 30:
        errors.append(
            f"[SEMANTIC] quiz must contain exactly 30 questions, found {actual_total_q}"
        )

    if actual_total_m != declared_total_m:
        logger.warning(
            "Auto-correcting metadata.total_marks %s → %s",
            declared_total_m, actual_total_m,
        )
        doc["metadata"]["total_marks"] = actual_total_m

    return errors


def _check_mcq_section(s_letter: str, questions: list[dict]) -> list[str]:
    errors = []
    valid_answers = {"A", "B", "C", "D"}
    for q in questions:
        q_id    = f"Section {s_letter} Q{q.get('question_number','?')}"
        options = q.get("options", [])

        if len(options) != 4:
            errors.append(
                f"[SEMANTIC] {q_id}: MCQ must have exactly 4 options, "
                f"found {len(options)}"
            )

        option_letters = [o.get("letter") for o in options]
        if option_letters != ["A", "B", "C", "D"]:
            errors.append(
                f"[SEMANTIC] {q_id}: MCQ option letters must be "
                f"['A','B','C','D'], got {option_letters}"
            )

        # Validate correct_answer for all MCQ questions
        ca = _get_correct_answer(q)
        if not ca or ca.upper() not in valid_answers:
            errors.append(
                f"[SEMANTIC] {q_id}: MCQ correct_answer '{ca}' must be "
                f"one of A/B/C/D"
            )
    return errors


def _check_tf_section(s_letter: str, questions: list[dict]) -> list[str]:
    errors = []
    for q in questions:
        q_id = f"Section {s_letter} Q{q.get('question_number','?')}"
        ca   = _get_correct_answer(q)
        if str(ca).strip().capitalize() not in ("True", "False"):
            errors.append(
                f"[SEMANTIC] {q_id}: true_false correct_answer must be "
                f"'True' or 'False', got '{ca}'"
            )
    return errors


def _check_sa_section(s_letter: str, questions: list[dict]) -> list[str]:
    """
    Short Answer can have any number of options (including 0).
    If no options are provided, True/False options will be added as fallback.
    """
    errors = []
    for q in questions:
        q_id    = f"Section {s_letter} Q{q.get('question_number','?')}"
        options = q.get("options", [])

        # Short answer questions can have any number of options (including 0)
        # No validation error for missing options
        option_letters = {o.get("letter", "") for o in options}
        ca = _get_correct_answer(q)
        if not ca:
            errors.append(
                f"[SEMANTIC] {q_id}: short_answer is missing correct_answer"
            )
        elif option_letters and ca not in option_letters:
            errors.append(
                f"[SEMANTIC] {q_id}: short_answer correct_answer '{ca}' must "
                f"match one of the option letters {sorted(option_letters)}"
            )
    return errors


def _check_ps_section(s_letter: str, questions: list[dict]) -> list[str]:
    """
    Problem Solving: each subpart must have EXACTLY 2 selectable options.
    correct_answer must match one of the two option letters.
    """
    errors = []
    for q in questions:
        q_id     = f"Section {s_letter} Q{q.get('question_number','?')}"
        subparts = q.get("subparts", [])

        if not subparts:
            errors.append(
                f"[SEMANTIC] {q_id}: problem_solving question must "
                f"have at least one subpart"
            )
            continue

        for j, sp in enumerate(subparts):
            expected_label = f"{chr(97 + j)})"
            actual_label   = sp.get("label", "")
            if actual_label != expected_label:
                errors.append(
                    f"[SEMANTIC] {q_id} subpart {j+1}: expected "
                    f"label '{expected_label}', got '{actual_label}'"
                )

            sp_id = f"{q_id} subpart '{actual_label}'"

            # Problem solving subparts can have any number of options (including 0)
            # If no options are provided, True/False options will be added as fallback
            sp_options = sp.get("options", [])
            sp_option_letters = {o.get("letter", "") for o in sp_options}
            sp_ca = _get_correct_answer(sp)
            if not sp_ca:
                errors.append(
                    f"[SEMANTIC] {sp_id}: missing correct_answer"
                )
            elif sp_ca not in sp_option_letters and sp_options:
                errors.append(
                    f"[SEMANTIC] {sp_id}: correct_answer '{sp_ca}' must "
                    f"match one of the option letters {sorted(sp_option_letters)}"
                )

            # Subpart explanation
            _check_explanation_length(
                sp.get("explanation", ""),
                sp_id,
                errors
            )

            # Subpart marks
            m = sp.get("marks", 0)
            if not isinstance(m, int) or m < 1:
                errors.append(
                    f"[SEMANTIC] {sp_id}: marks must be a positive integer, "
                    f"got {m!r}"
                )

        # Subpart marks must sum to question marks
        subpart_marks_sum = sum(
            sp.get("marks", 0) for sp in subparts
            if isinstance(sp.get("marks"), int)
        )
        q_marks = q.get("marks", 0)
        if isinstance(q_marks, (int, float)) and q_marks > 0:
            if int(q_marks) != subpart_marks_sum:
                errors.append(
                    f"[SEMANTIC] {q_id}: question marks={q_marks} ≠ "
                    f"sum of subpart marks={subpart_marks_sum}"
                )

    return errors


def _get_correct_answer(obj: dict) -> str:
    """Normalise correct_answer field — supports both 'correct_answer' and 'answer'."""
    ca = obj.get("correct_answer") or obj.get("answer", "")
    return str(ca).strip() if ca is not None else ""


def _compute_section_marks(s_type: str, questions: list[dict]) -> int:
    total = 0
    for q in questions:
        if s_type == "problem_solving":
            total += sum(
                sp.get("marks", 0) for sp in q.get("subparts", [])
                if isinstance(sp.get("marks"), (int, float))
            )
        else:
            m = q.get("marks", 0)
            total += m if isinstance(m, (int, float)) else 0
    return int(total)
# ── Notes ─────────────────────────────────────────────────────────────────────

def _validate_notes_semantics(doc: dict) -> list[str]:
    errors: list[str] = []
    sections = doc.get("sections", [])

    for i, section in enumerate(sections):
        expected_num = i + 1
        actual_num   = section.get("section_number")
        if actual_num != expected_num:
            errors.append(
                f"[SEMANTIC] Notes section {i+1}: expected "
                f"section_number={expected_num}, got {actual_num}"
            )

        content = section.get("content", [])
        if not content:
            errors.append(
                f"[SEMANTIC] Notes section {i+1} "
                f"('{section.get('section_title', '?')}'): "
                f"content array is empty"
            )

        for j, block in enumerate(content):
            if block.get("block_type") == "worked_example":
                steps = block.get("steps", [])
                if len(steps) < 3:
                    errors.append(
                        f"[SEMANTIC] Notes section {i+1} block {j+1}: "
                        f"worked_example must have at least 3 steps"
                    )

    summary = doc.get("summary", [])
    if len(summary) < 5:
        errors.append(
            f"[SEMANTIC] Notes summary must have at least 5 items, "
            f"found {len(summary)}"
        )

    return errors


# ── Cheatsheet ────────────────────────────────────────────────────────────────

def _validate_cheatsheet_semantics(doc: dict) -> list[str]:
    errors: list[str] = []
    sections = doc.get("sections", [])

    for i, section in enumerate(sections):
        entries = section.get("entries", [])
        if len(entries) < 4:
            errors.append(
                f"[SEMANTIC] Cheatsheet section {i+1} "
                f"('{section.get('section_title','?')}'): "
                f"must have at least 4 entries, found {len(entries)}"
            )

        for j, entry in enumerate(entries):
            if not entry.get("label", "").strip():
                errors.append(
                    f"[SEMANTIC] Cheatsheet section {i+1} entry {j+1}: "
                    f"label is empty"
                )
            if not entry.get("content", "").strip():
                errors.append(
                    f"[SEMANTIC] Cheatsheet section {i+1} entry {j+1}: "
                    f"content is empty"
                )

    if not any(section.get("section_type") == "formulas" for section in sections):
        errors.append("[SEMANTIC] Cheatsheet must include at least one formulas section")

    return errors


# ── Shared helpers ────────────────────────────────────────────────────────────

_MIN_EXPLANATION_WORDS = 10


def _check_explanation_length(
    text: str, context: str, errors: list[str]
) -> None:
    word_count = len(text.split())
    if word_count < _MIN_EXPLANATION_WORDS:
        errors.append(
            f"[SEMANTIC] {context}: explanation has {word_count} words "
            f"(minimum {_MIN_EXPLANATION_WORDS})"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — ENRICHMENT
# ═══════════════════════════════════════════════════════════════════════════════

def _enrich_document(doc: dict) -> None:
    """
    Stamp generated_at (if placeholder) and compute document_hash in-place.
    The hash is computed over all fields except document_hash itself.
    """
    gen_at = doc.get("generated_at", "")
    if not gen_at or "<" in gen_at or gen_at == "string":
        doc["generated_at"] = datetime.now(timezone.utc).isoformat()

    payload = {k: v for k, v in doc.items() if k != "document_hash"}
    doc["document_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


# ═══════════════════════════════════════════════════════════════════════════════
# FLAT QUESTION NORMALISATION
# ═══════════════════════════════════════════════════════════════════════════════

def _normalise_tf_answer(ca: str) -> str:
    """Normalise T/True/F/False → 'True' or 'False'."""
    ca = ca.strip().lower()
    if ca in ("true", "t"):
        return "True"
    if ca in ("false", "f"):
        return "False"
    return ca.capitalize()


def _build_tf_options() -> list[dict]:
    """Standard True/False option list."""
    return [
        {"letter": "True",  "text": "True"},
        {"letter": "False", "text": "False"},
    ]


def normalise_quiz_to_flat_questions(validated_doc: dict) -> list[dict]:
    """
    Convert a validated quiz document (sections structure) into a flat list
    of grading-ready question dicts.

        Each item in the returned list has:
            - type:          'mcq'
            - question:      HTML-safe question text (str)
            - answer:        correct_answer option letter
            - explanation:   explanation string
            - marks:         int
            - section:       section letter
            - section_title: section title
            - options:       list of {letter, text}
            - question_number: int (for reference)

        Quiz content is MCQ-only in this app.
    """
    flat: list[dict] = []

    for section in validated_doc.get("sections", []):
        s_letter = section.get("section_letter", "")
        s_title  = section.get("section_title", "")

        for q in section.get("questions", []):
            q_num  = q.get("question_number", 0)
            q_text = q.get("question_text") or q.get("question", "")
            ca = _get_correct_answer(q)

            flat.append({
                "type":           "mcq",
                "question":       q_text,
                "subpart_label":  None,
                "subpart_text":   None,
                "answer":         ca,
                "explanation":    q.get("explanation", ""),
                "marks":          q.get("marks", 0),
                "section":        s_letter,
                "section_title":  s_title,
                "question_number": q_num,
                "options":        q.get("options", []),
            })

    return flat


def _ensure_two_options(
    existing: list[dict], correct_answer: str
) -> list[dict]:
    """
    Guarantee exactly 2 options exist.
    If the AI provided fewer, inject a plausible second option.
    This is a safety fallback — validation should catch missing options before
    we reach this point.
    """
    if len(existing) >= 2:
        return existing[:2]

    # For questions with long text answers (like short answer or problem solving),
    # we need to provide simple True/False options as a fallback
    if len(existing) == 0:
        return [
            {"letter": "True", "text": "True"},
            {"letter": "False", "text": "False"}
        ]

    # If we have one option, add a contrasting one
    existing_letters = {o.get("letter", "") for o in existing}
    for candidate in ["True", "False", "A", "B"]:
        if candidate not in existing_letters:
            existing.append({"letter": candidate, "text": candidate})
            break

    return existing[:2]


# ═══════════════════════════════════════════════════════════════════════════════
# GRADING
# ═══════════════════════════════════════════════════════════════════════════════

def grade_quiz(flat_questions: list[dict], answers: dict[str, str]) -> tuple[float, int]:
    """
    Grade a flat question list against a user answers dict keyed by flat index.

    PS subparts are already exploded into individual flat entries by
    normalise_quiz_to_flat_questions — there is no nested subparts list here.
    Every entry regardless of type has its own answer, options, and marks.
    """
    total_marks  = sum(q.get("marks", 0) for q in flat_questions)
    earned_marks = 0.0

    for index, q in enumerate(flat_questions):
        correct_answer = str(q.get("answer") or "").strip()
        user_answer    = str(answers.get(str(index), "")).strip()

        has_options = bool(q.get("options"))
        is_auto     = has_options and bool(correct_answer)

        if is_auto and user_answer and correct_answer:
            if user_answer.upper() == correct_answer.upper():
                earned_marks += q.get("marks", 0)

    return earned_marks, int(total_marks)
    
# ═══════════════════════════════════════════════════════════════════════════════
# QUIZ ATTACHMENT HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def validate_and_attach_quiz(post, json_bytes: bytes):
    """
    Validate quiz JSON and attach it to a post.

    Stores a flat normalised question list (not raw sections) so that
    the grading endpoint can iterate directly without re-parsing section
    structure.

    Returns:
        Tuple of (QuizData, error_message).
        On success: (QuizData, None).
        On failure: (None, str).
    """
    from app import db
    from app.models import QuizData

    try:
        quiz_json     = json.loads(json_bytes.decode("utf-8"))
        validated_doc = validate_document(quiz_json)

        doc_type = validated_doc.get("document_type", "quiz")

        if doc_type == "notes":
            questions_to_store = [
                {
                    "section_number": s["section_number"],
                    "section_title":  s["section_title"],
                    "section_type":   s.get("section_type", ""),
                    "content":        s.get("content", []),
                }
                for s in validated_doc.get("sections", [])
            ]
            total_marks = 0
            xp_reward   = 10
        elif doc_type == "cheatsheet":
            questions_to_store = [
                {
                    "section_title": s["section_title"],
                    "section_type":  s.get("section_type", ""),
                    "entries":       s.get("entries", []),
                }
                for s in validated_doc.get("sections", [])
            ]
            total_marks = 0
            xp_reward   = 5
        else:
            questions_to_store = normalise_quiz_to_flat_questions(validated_doc)
            total_marks        = validated_doc["metadata"]["total_marks"]
            xp_reward          = max(5, total_marks // 10)

        quiz_data = QuizData.query.filter_by(post_id=post.id).first()
        if not quiz_data:
            quiz_data         = QuizData()
            quiz_data.post_id = post.id

        quiz_data.questions   = json.dumps(questions_to_store)
        quiz_data.total_marks = total_marks
        quiz_data.xp_reward   = xp_reward
        
        meta_dict = {
            "document_type":  doc_type,
            "title":          validated_doc.get("title", ""),
            "schema_version": validated_doc.get("schema_version", ""),
            "course":         validated_doc.get("course", ""),
            "level":          validated_doc.get("level", ""),
            "document_hash":  validated_doc.get("document_hash", ""),
            "generated_at":   validated_doc.get("generated_at", ""),
        }
        if doc_type == "quiz":
            meta_dict.update({
                "type":            validated_doc.get("type", ""),
                "instructions":    validated_doc.get("instructions", []),
                "total_questions": validated_doc["metadata"]["total_questions"],
                "total_marks":     validated_doc["metadata"]["total_marks"],
                "time":            validated_doc["metadata"].get("time", ""),
                "time_allowed":    validated_doc["metadata"].get("time_allowed", ""),
            })
        elif doc_type == "notes":
            notes_meta = validated_doc.get("metadata", {})
            meta_dict["estimated_read_time"] = notes_meta.get("estimated_read_time", "")
            meta_dict["focus_areas"]          = notes_meta.get("focus_areas", "")
            meta_dict["prerequisites"]        = notes_meta.get("prerequisites", "")
            # Top-level summary array
            meta_dict["summary"] = validated_doc.get("summary", [])
        elif doc_type == "cheatsheet":
            cs_meta = validated_doc.get("metadata", {})
            meta_dict["purpose"]       = cs_meta.get("purpose", "")
            meta_dict["exam_context"]  = cs_meta.get("exam_context", "")
            meta_dict["topics"]        = cs_meta.get("topics", [])
        quiz_data.meta = json.dumps(meta_dict)

        db.session.add(quiz_data)
        db.session.commit()

        logger.info(
            "Document attached to post %s: type=%s, %d sections/questions, %d total marks",
            post.id, doc_type, len(questions_to_store), total_marks
        )
        return quiz_data, None

    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    except DocumentValidationError as e:
        return None, f"Validation failed: {e}"
    except Exception:
        logger.exception("Error attaching quiz to post %s", post.id)
        return None, "Unexpected error — see server logs."

def quiz_from_sidecar(post):
    """
    Re-read the JSON sidecar attached to post.document, validate, and
    (re-)attach a QuizData record.

    Called from on_post_approved() in routes.py after post approval.

    Returns:
        QuizData on success, None on failure.
    """
    from app import db
    from app.models import QuizData

    if not post.document or not post.document.json_sidecar_path:
        logger.debug("Post %s has no json_sidecar_path; skipping.", post.id)
        return None

    sidecar_path = post.document.json_sidecar_path

    try:
        # ── Remote URL (Cloudinary or any https:// sidecar) ───────────────────
        if sidecar_path.startswith("http://") or sidecar_path.startswith("https://"):
            import requests as _req
            resp = _req.get(sidecar_path, timeout=15)
            resp.raise_for_status()
            json_bytes = resp.content

        # ── Local path ────────────────────────────────────────────────────────
        else:
            from flask import current_app
            # Resolve relative /static/... URLs to an absolute filesystem path
            if not os.path.isabs(sidecar_path):
                sidecar_path = os.path.join(
                    current_app.root_path,
                    "static", "uploads", "documents",
                    os.path.basename(sidecar_path),
                )
            if not os.path.exists(sidecar_path):
                logger.warning("Sidecar file not found at %s for post %s", sidecar_path, post.id)
                return None
            with open(sidecar_path, "rb") as f:
                json_bytes = f.read()

        quiz_data, error = validate_and_attach_quiz(post, json_bytes)
        if error:
            logger.warning("quiz_from_sidecar failed for post %s: %s", post.id, error)
            return None
        return quiz_data

    except Exception:
        logger.exception("quiz_from_sidecar error for post %s", post.id)
        return None