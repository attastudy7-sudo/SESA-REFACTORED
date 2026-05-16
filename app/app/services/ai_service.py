"""
ai_service.py
=============
Gemini wrapper for generating post metadata and an academic content bundle
(quiz, notes, cheatsheet) from uploaded source material.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from urllib import error as urlerror
from urllib import request as urlrequest

logger = logging.getLogger(__name__)

# ─── Free OpenRouter fallback models (auto-retry chain) ───────────────────────
_FREE_OPENROUTER_MODELS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
]

# Subset used for heavy structured calls (quiz, notes, cheatsheet) — excludes the wildcard
_FREE_OPENROUTER_MODELS_STRUCTURED = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
]

_OPENROUTER_MISSING_MODELS: set[str] = set()
_OPENROUTER_FREE_BLOCKED_UNTIL = 0.0

# Per-key throttle: tracks last call time per API key so multiple users
# can generate simultaneously as long as they use different keys.
# Falls back to a shared lock only when a single key is in use.
_AI_MIN_CALL_INTERVAL_SECONDS = float(os.environ.get("AI_MIN_CALL_INTERVAL_SECONDS", "2.0"))
_AI_KEY_LAST_CALL: dict[str, float] = {}
_AI_KEY_LOCKS: dict[str, threading.Lock] = {}
_AI_KEY_REGISTRY_LOCK = threading.Lock()

_invalid_gemini_keys: set[str] = set()
_invalid_gemini_lock = logging.Lock() if hasattr(logging, "Lock") else None

try:
    import google.generativeai as genai
    from google.generativeai import types
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None  # type: ignore
    types = None  # type: ignore
    _GENAI_AVAILABLE = False
    logger.warning("google-generativeai not installed. Run: pip install google-generativeai")


def _load_keys() -> list[str]:
    keys: list[str] = []
    single = os.environ.get("GEMINI_API_KEY")
    if single:
        keys.append(single)
    for index in range(1, 20):
        key = os.environ.get(f"GEMINI_API_KEY_{index}")
        if key:
            keys.append(key)
    random.shuffle(keys)
    if _invalid_gemini_keys:
        keys = [key for key in keys if key not in _invalid_gemini_keys]
    return keys


def _normalize_flair(value: object) -> str:
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


def _key_label(api_key: str) -> str:
    if not api_key:
        return "<empty>"
    return f"...{api_key[-4:]}"


def _openrouter_models_are_free(model_candidates: list[str]) -> bool:
    return bool(model_candidates) and all(model.endswith(":free") for model in model_candidates)


def _openrouter_rate_limit_message(body: str, exc: Exception | None = None) -> tuple[str, float | None]:
    reset_at = None
    message = body.strip() if body else ""

    if exc is not None:
        headers = getattr(exc, "headers", None)
        if headers is not None:
            reset_value = headers.get("X-RateLimit-Reset")
            try:
                if reset_value:
                    reset_at = float(reset_value) / 1000.0
            except (TypeError, ValueError):
                reset_at = None

    if not message:
        message = "OpenRouter rate limit exceeded."
    if "free-models-per-day" in message:
        message += " Free OpenRouter models are exhausted for today."

    return message, reset_at


def _skip_blocked_openrouter_models(model_candidates: list[str]) -> list[str]:
    return [model for model in model_candidates if model not in _OPENROUTER_MISSING_MODELS]


def _get_key_lock(key: str) -> threading.Lock:
    """Get or create a per-key lock."""
    with _AI_KEY_REGISTRY_LOCK:
        if key not in _AI_KEY_LOCKS:
            _AI_KEY_LOCKS[key] = threading.Lock()
        return _AI_KEY_LOCKS[key]


def _throttle_before_ai_call(key: str = "shared") -> None:
    """Throttle calls per API key, not globally."""
    if _AI_MIN_CALL_INTERVAL_SECONDS <= 0:
        return
    now = time.time()
    last = _AI_KEY_LAST_CALL.get(key, 0.0)
    wait_seconds = (last + _AI_MIN_CALL_INTERVAL_SECONDS) - now
    if wait_seconds > 0:
        time.sleep(wait_seconds)
    _AI_KEY_LAST_CALL[key] = time.time()


def _build_openrouter_candidates(default_candidates: list[str] | None) -> list[str]:
    candidates = list(default_candidates or [])
    preferred = (os.environ.get("OPENROUTER_MODEL") or "").strip()
    if preferred:
        candidates = [model for model in candidates if model != preferred]
        candidates.insert(0, preferred)
    return candidates


def _mark_invalid_gemini_key(api_key: str) -> None:
    _invalid_gemini_keys.add(api_key)


def _is_invalid_gemini_key(api_key: str) -> bool:
    return api_key in _invalid_gemini_keys


def _is_gemini_auth_error(error_text: str) -> bool:
    text = (error_text or "").lower()
    # Restrict to explicit provider auth/key signals. Avoid generic "invalid"
    # because application-level errors can include that word.
    auth_markers = (
        "api_key_invalid",
        "api key not valid",
        "invalid api key",
        "api key invalid",
        "expired api key",
        "api key expired",
        "invalidargument: api key",
        "permission_denied",
    )
    return any(marker in text for marker in auth_markers)


def warn_if_gemini_keys_invalid() -> bool:
    """Probe configured Gemini keys once at startup and log a clear warning if all fail."""
    # Skip probe in development to avoid burning free tier quota on every restart
    if os.environ.get("FLASK_ENV") == "development" or os.environ.get("SKIP_GEMINI_PROBE"):
        logger.info("Gemini startup probe skipped.")
        return True

    if not _GENAI_AVAILABLE:
        logger.warning("Gemini startup check skipped: google-generativeai is not installed.")
        return False

    keys = _load_keys()
    if not keys:
        logger.warning("Gemini startup check: no Gemini API keys are configured.")
        return False

    model_name = os.environ.get("GEMINI_MODEL_PREFERENCES", "gemini-2.0-flash-lite").split(",")[0].strip() or "gemini-2.0-flash-lite"
    probe_prompt = "Return a single JSON object: {\"ok\": true}."

    saw_auth_error = False
    last_error = ""
    for index, api_key in enumerate(keys, start=1):
        key_label = _key_label(api_key)
        logger.info("Gemini startup check: trying key %d/%d (%s) with model %s.", index, len(keys), key_label, model_name)
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction="Return only valid JSON.",
            )
            model.generate_content(
                probe_prompt,
                generation_config=types.GenerationConfig(
                    temperature=0,
                    max_output_tokens=16,
                    response_mime_type="application/json",
                ),
                request_options={"timeout": 10},
            )
            logger.info("Gemini startup check passed with model %s.", model_name)
            return True
        except Exception as exc:
            error_text = str(exc).lower()
            last_error = str(exc)
            if _is_gemini_auth_error(error_text):
                saw_auth_error = True
                _mark_invalid_gemini_key(api_key)
                logger.warning("Gemini startup check: key %s rejected by provider (%s).", key_label, exc)
                continue
            logger.warning("Gemini startup check failed for key %s and model %s: %s", key_label, model_name, exc)

    if saw_auth_error:
        logger.warning("All configured Gemini API keys appear invalid or unauthorized. Replace keys before using Gemini.")
    else:
        logger.warning(
            "Gemini startup check failed for all keys, but not due to explicit key auth errors. Last error: %s",
            last_error or "unknown",
        )
    return False


_METADATA_PROMPT = """You are an academic content metadata assistant for Knowly.
Given content, generate metadata. Respond ONLY with valid JSON containing ALL of these exact keys:

{
  "title": "Clear title (max 100 chars, no codes)",
  "description": "2-3 sentence summary",
  "subject_hint": "Academic subject name",
  "programme_hint": "Best-fit programme name (e.g., BSc Computer Science)",
  "faculty_hint": "Best-fit faculty category (e.g., Computing & Technology)",
  "subject_match_basis": "new",
  "programme_match_basis": "new",
  "matched_subject_name": "",
  "matched_programme_name": "",
  "flair": "academic"
}

Rules:
- Every key above is required. Do not omit any.
- flair must be one of: academic, casual, visual, interactive.
- subject_match_basis and programme_match_basis must be "existing" or "new"."""

_MATH_FORMAT_RULES = """Math formatting rules:
- Write mathematical expressions in LaTeX.
- Use inline delimiters: $...$ for short expressions.
- Use display delimiters: $$...$$ for standalone equations.
- Do not output plain-text formulas like x^2 + y^2 = z^2 without LaTeX delimiters.
- Keep delimiters balanced and valid.
"""

_QUIZ_SYSTEM_PROMPT = """You are KnowlyGen, a high-stakes exam predictor for university students.
Generate a comprehensive, structured quiz based EXCLUSIVELY on the provided material.
Respond ONLY with valid JSON.

KnowlyGen quiz calibration:
- Always generate exactly 30 total questions.
- All 30 questions must be multiple-choice questions only.
- Each question must have exactly 4 options labeled A, B, C, and D.
- Use a standard exam-style spread of difficulty across the 30 MCQs rather than mixing question formats.

{math_rules}
"""

_NOTES_SYSTEM_PROMPT = """You are KnowlyGen, a concise study tutor.
Generate structured study notes from the provided material.
Respond ONLY with valid JSON.

KnowlyGen notes calibration:
- Scale depth to the source length and topic complexity so the notes feel complete, not skeletal.
- Short material should still produce 3-4 sections; medium material should expand to 4-5 sections; long material should expand to 5-7 sections; very long material should expand to 6-10 sections.
- Every mathematical section should include formulas and at least one worked example when relevant.
- Summary must contain at least 5 complete-sentence revision points.
- Worked examples must include at least 3 steps.

KnowlyGen notes schema:
- Top-level keys: schema_version, document_type, generated_at, title, course, level, metadata, sections, summary.
- Each section must have section_number, section_title, section_type, and content.
- Each content item must be one of: paragraph, definition, theorem, proof, note, formula, example, worked_example, list, table, diagram_placeholder.
- Formula blocks must include label and text.
- Worked examples must include text and a steps array.
- Tables must use headers and rows, never plain text.
- Summary must be a list of at least 5 full-sentence revision points.

{math_rules}
"""

_CHEATSHEET_SYSTEM_PROMPT = """You are KnowlyGen.
Generate a high-density cheatsheet/summary focused on formulas, definitions, and recall entries.
Respond ONLY with valid JSON.

KnowlyGen cheatsheet calibration:
- Prioritise density: the document should read like a fast exam-day reference, not a narrative summary.
- Each section should usually contain 4-10 entries, with at least one formulas section.
- Use compact formulas, key definitions, and short application notes; avoid filler prose.
- Cover all standard formulas for the topic at the requested level.

KnowlyGen cheatsheet schema:
- Top-level keys: schema_version, document_type, generated_at, title, course, level, metadata, sections.
- Metadata must include purpose and may include exam_context and topics.
- Each section must have section_title, section_type, and entries.
- Each entry must have label and content, with optional notes and example.
- Content must be the formula string or compact symbolic statement, never a list.

{math_rules}
"""

_ACADEMIC_BUNDLE_PROMPT = f"""You are KnowlyGen, an academic strategist.
Decide if content is educational.

If NOT educational, return exactly:
{{"is_academic": false, "reason": "Brief explanation why"}}

If educational, return exactly this shape:
{{
  "is_academic": true,
  "metadata": {{
    "title": "...",
    "description": "...",
    "subject_hint": "...",
    "programme_hint": "...",
    "faculty_hint": "...",
    "flair": "..."
  }},
  "quiz": {{ ... }},
  "notes": {{ ... }},
  "cheatsheet": {{ ... }}
}}

Constraints:
{_QUIZ_SYSTEM_PROMPT.format(math_rules=_MATH_FORMAT_RULES)}
{_NOTES_SYSTEM_PROMPT.format(math_rules=_MATH_FORMAT_RULES)}
{_CHEATSHEET_SYSTEM_PROMPT.format(math_rules=_MATH_FORMAT_RULES)}
"""


def _bundle_output_guidance(source_text: str) -> str:
    """Return KnowlyGen-style output sizing guidance based on source length."""
    word_count = max(1, len(source_text.split()))

    if word_count < 800:
        notes_sections = "3-4"
        notes_blocks = "3-4"
        cheat_sections = "3-4"
        cheat_entries = "4-6"
    elif word_count < 2000:
        notes_sections = "4-5"
        notes_blocks = "4-5"
        cheat_sections = "4-5"
        cheat_entries = "5-7"
    elif word_count < 5000:
        notes_sections = "5-7"
        notes_blocks = "5-6"
        cheat_sections = "5-6"
        cheat_entries = "6-8"
    else:
        notes_sections = "6-10"
        notes_blocks = "6+"
        cheat_sections = "6-8"
        cheat_entries = "8-10"

    return f"""KnowlyGen output calibration:
- Quiz: always exactly 30 total questions, all of them multiple-choice questions with 4 options each.
- Notes: target {notes_sections} sections, with at least {notes_blocks} meaningful content blocks per section when the topic warrants it.
- Cheatsheet: target {cheat_sections} sections and {cheat_entries} entries per section; keep it formula-first, dense, and exam-ready.
- The output should feel proportionate to the source material: short sources stay compact, longer sources become more expansive and detailed.
"""


def generate_metadata(content: str, mode: str = "file") -> dict:
    return _generate_structured(content, "metadata", mode=mode)


# ── Per-component doc_type system prompts ─────────────────────────────────────
_COMPONENT_SYSTEM_PROMPTS = {
    "quiz": _QUIZ_SYSTEM_PROMPT.format(math_rules=_MATH_FORMAT_RULES),
    "notes": _NOTES_SYSTEM_PROMPT.format(math_rules=_MATH_FORMAT_RULES),
    "cheatsheet": _CHEATSHEET_SYSTEM_PROMPT.format(math_rules=_MATH_FORMAT_RULES),
}

# Register per-component prompts so _generate_structured can resolve them
_SYSTEM_PROMPTS_EXTRA = {
    "quiz": _COMPONENT_SYSTEM_PROMPTS["quiz"],
    "notes": _COMPONENT_SYSTEM_PROMPTS["notes"],
    "cheatsheet": _COMPONENT_SYSTEM_PROMPTS["cheatsheet"],
}

_ACADEMIC_CHECK_PROMPT = """You are KnowlyGen, an academic strategist.
Decide if the content is educational.

If NOT educational, return exactly:
{"is_academic": false, "reason": "Brief explanation why"}

If educational, return exactly:
{"is_academic": true}

Respond ONLY with valid JSON."""


def _check_is_academic(content: str) -> dict:
    """Quick single call to decide if content is educational before committing to full generation."""
    return _generate_structured(content[:3000], "academic_check")


def generate_academic_bundle(
    content: str,
    taxonomy_context: dict | None = None,
    extra_guidance: str | None = None,
) -> dict:
    """
    Generate a full academic bundle (metadata + quiz + notes + cheatsheet) via
    sequential per-component calls instead of one monolithic prompt.  This keeps
    each call within token limits and makes partial failures recoverable.
    """
    # 1. Academic gate-check (cheap, fast)
    gate = _generate_structured(content[:3000], "academic_check")
    if isinstance(gate, dict) and gate.get("is_academic") is False:
        return gate  # propagate non-academic signal to caller unchanged

    # 2. Metadata
    metadata_result = _generate_structured(
        content,
        "metadata",
        taxonomy_context=taxonomy_context,
        extra_guidance=extra_guidance,
    )
    if isinstance(metadata_result, dict) and metadata_result.get("error"):
        return {"error": f"metadata generation failed: {metadata_result['error']}"}

    # 3. Quiz, notes, cheatsheet — robust, never fail for quiz
    components: dict = {}
    errors: dict = {}

    # Circuit breaker state
    if not hasattr(generate_academic_bundle, "_ai_failure_count"):
        generate_academic_bundle._ai_failure_count = 0
        generate_academic_bundle._ai_failure_ts = 0

    for component in ("quiz", "notes", "cheatsheet"):
        max_attempts = 3 if component == "quiz" else 2
        result = None
        for attempt in range(1, max_attempts + 1):
            try:
                result = _generate_structured(
                    content,
                    component,
                    extra_guidance=extra_guidance,
                    model_candidates_override=_FREE_OPENROUTER_MODELS_STRUCTURED,
                )
                # Validate output structure
                if component == "quiz":
                    if not (isinstance(result, dict) and "questions" in result and isinstance(result["questions"], list) and len(result["questions"]) > 0):
                        raise ValueError("Quiz output invalid or empty")
                elif component == "notes":
                    if not (isinstance(result, dict) and "sections" in result and isinstance(result["sections"], list) and len(result["sections"]) > 0):
                        raise ValueError("Notes output invalid or empty")
                elif component == "cheatsheet":
                    if not (isinstance(result, dict) and "sections" in result and isinstance(result["sections"], list) and len(result["sections"]) > 0):
                        raise ValueError("Cheatsheet output invalid or empty")
                # Success, reset failure count
                generate_academic_bundle._ai_failure_count = 0
                break
            except Exception as exc:
                logger.warning(f"{component} generation attempt {attempt} failed: {exc}\nInput: {content[:500]}")
                result = None
                generate_academic_bundle._ai_failure_count += 1
                generate_academic_bundle._ai_failure_ts = time.time()
        # Circuit breaker: if too many failures in a short window, skip further AI attempts
        if generate_academic_bundle._ai_failure_count >= 6 and (time.time() - generate_academic_bundle._ai_failure_ts) < 300:
            logger.error(f"AI circuit breaker triggered after {generate_academic_bundle._ai_failure_count} failures in 5 minutes. Using local fallback for {component}. Input: {content[:500]}")
            result = _local_quiz_from_content(content) if component == "quiz" else (
                _local_notes_from_content(content) if component == "notes" else _local_cheatsheet_from_content(content)
            )
            # Do not reset failure count here
        # Fallbacks if still invalid
        elif component == "quiz" and (not isinstance(result, dict) or "questions" not in result or not isinstance(result["questions"], list) or len(result["questions"]) == 0):
            logger.error(f"All AI quiz generation attempts failed, using local fallback quiz. Input: {content[:500]}")
            try:
                result = _local_quiz_from_content(content)
            except Exception as exc:
                logger.critical(f"Local quiz fallback failed: {exc}\nInput: {content[:500]}")
                result = {"_generation_failed": True, "questions": [], "metadata": {"total_questions": 0}}

        elif component == "notes" and (not isinstance(result, dict) or "sections" not in result or not isinstance(result["sections"], list) or len(result["sections"]) == 0):
            logger.error(f"All AI notes generation attempts failed, using local fallback notes. Input: {content[:500]}")
            try:
                result = _local_notes_from_content(content)
            except Exception as exc:
                logger.critical(f"Local notes fallback failed: {exc}\nInput: {content[:500]}")
                result = {"sections": [], "summary": [], "metadata": {}}
        elif component == "cheatsheet" and (not isinstance(result, dict) or "sections" not in result or not isinstance(result["sections"], list) or len(result["sections"]) == 0):
            logger.error(f"All AI cheatsheet generation attempts failed, using local fallback cheatsheet. Input: {content[:500]}")
            try:
                result = _local_cheatsheet_from_content(content)
            except Exception as exc:
                logger.critical(f"Local cheatsheet fallback failed: {exc}\nInput: {content[:500]}")
                result = {"sections": []}
        components[component] = result

    return {
        "is_academic": True,
        "metadata": metadata_result,
        "quiz": components["quiz"],
        "notes": components["notes"],
        "cheatsheet": components["cheatsheet"],
    }


def _extract_json_substring(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('```') and '```' in raw[3:]:
        raw = raw.split('```', 2)[1].strip()

    start = raw.find('{')
    end = raw.rfind('}')
    if start != -1 and end != -1 and end > start:
        candidate = raw[start:end + 1]
        stack = 0
        for idx, ch in enumerate(candidate):
            if ch == '{':
                stack += 1
            elif ch == '}':
                stack -= 1
            if stack == 0:
                return candidate[:idx + 1]
    return raw


def _fix_json_malformation(raw: str) -> str:
    import re

    raw = _extract_json_substring(raw).strip()
    raw = re.sub(r',\s*([\]}])', r'\1', raw)
    raw = re.sub(r',\s*,+', ',', raw)
    return raw


def _validate_bundle(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("is_academic") is not True:
        return False
    required = ["metadata", "quiz", "notes", "cheatsheet"]
    return all(key in data and isinstance(data[key], dict) for key in required)


def _validate_structured_output(doc_type: str, data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    if doc_type == "metadata":
        return all(k in data for k in ["title", "description", "subject_hint", "flair"])
    if doc_type == "bundle":
        return _validate_bundle(data)
    if doc_type == "academic_check":
        return "is_academic" in data
    if doc_type == "quiz":
        return "questions" in data and isinstance(data["questions"], list)
    if doc_type == "notes":
        return "sections" in data and isinstance(data["sections"], list)
    if doc_type == "cheatsheet":
        return "sections" in data and isinstance(data["sections"], list)
    return True


def _generate_via_openrouter(*, sys_prompt: str, user_prompt: str, doc_type: str, context: str, model_candidates: list[str] | None = None) -> dict | None:
    global _OPENROUTER_FREE_BLOCKED_UNTIL

    api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        return None

    model_candidates = _build_openrouter_candidates(model_candidates)
    if not model_candidates:
        return None

    model_candidates = _skip_blocked_openrouter_models(model_candidates)
    if not model_candidates:
        logger.warning("OpenRouter fallback models are unavailable for this process; using local fallback for %s.", doc_type)
        return _local_structured_fallback(doc_type, context)

    if _OPENROUTER_FREE_BLOCKED_UNTIL and time.time() < _OPENROUTER_FREE_BLOCKED_UNTIL and _openrouter_models_are_free(model_candidates):
        logger.warning("OpenRouter free-model path is temporarily blocked by quota window; using local fallback for %s.", doc_type)
        return _local_structured_fallback(doc_type, context)

    def _extract_openrouter_content(raw_response: object) -> str | None:
        if isinstance(raw_response, str):
            return raw_response
        if not isinstance(raw_response, dict):
            return None

        def _first_non_empty_text(value: object) -> str | None:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for key in ("text", "content", "output_text", "response", "arguments"):
                    nested = _first_non_empty_text(value.get(key))
                    if nested:
                        return nested
                return None
            if isinstance(value, list):
                parts: list[str] = []
                for item in value:
                    nested = _first_non_empty_text(item)
                    if nested:
                        parts.append(nested)
                joined = "\n".join(parts).strip()
                return joined or None
            return None

        choices = raw_response.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue

                for key in ("text", "content", "output_text", "response"):
                    text = _first_non_empty_text(choice.get(key))
                    if text:
                        return text

                message = choice.get("message")
                if isinstance(message, dict):
                    for key in ("content", "text", "output_text", "response", "reasoning"):
                        text = _first_non_empty_text(message.get(key))
                        if text:
                            return text

                    tool_calls = message.get("tool_calls")
                    if isinstance(tool_calls, list):
                        for call in tool_calls:
                            if not isinstance(call, dict):
                                continue
                            function = call.get("function")
                            if isinstance(function, dict):
                                text = _first_non_empty_text(function.get("arguments"))
                                if text:
                                    return text
                            text = _first_non_empty_text(call.get("arguments"))
                            if text:
                                return text
                else:
                    text = _first_non_empty_text(message)
                    if text:
                        return text

                delta = choice.get("delta")
                text = _first_non_empty_text(delta)
                if text:
                    return text

        for key in ("output_text", "response", "content", "text"):
            text = _first_non_empty_text(raw_response.get(key))
            if text:
                return text

        return None

    last_error = None
    for attempt_idx, model in enumerate(model_candidates):
        logger.info("OpenRouter attempt %d/%d: trying model %s", attempt_idx + 1, len(model_candidates), model)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.4 if doc_type != "metadata" else 0.7,
            "max_tokens": 8192 if doc_type == "quiz" else (4096 if doc_type in {"bundle", "notes", "cheatsheet"} else 1000),
            "response_format": {"type": "json_object"},
        }

        req = urlrequest.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://knowly.app",
                "X-Title": "knowly",
            },
            method="POST",
        )

        try:
            with _get_key_lock("openrouter"):
                _throttle_before_ai_call("openrouter")
                with urlrequest.urlopen(req, timeout=180) as response:
                    raw_response = json.loads(response.read().decode("utf-8"))
        except urlerror.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                body = ""

            if exc.code == 404:
                _OPENROUTER_MISSING_MODELS.add(model)
                if attempt_idx < len(model_candidates) - 1:
                    last_error = f"OpenRouter model {model} not found (404). Retrying next model..."
                    logger.warning(last_error)
                    continue

            if exc.code == 429:
                rate_message, reset_at = _openrouter_rate_limit_message(body, exc)
                last_error = f"OpenRouter model {model} rate-limited (429): {rate_message}"
                logger.warning(last_error)
                if _openrouter_models_are_free(model_candidates):
                    _OPENROUTER_FREE_BLOCKED_UNTIL = reset_at or (time.time() + 3600)
                    return _local_structured_fallback(doc_type, context)
                if attempt_idx < len(model_candidates) - 1:
                    continue
                return _local_structured_fallback(doc_type, context)

            if exc.code in (500, 502, 503, 504) and attempt_idx < len(model_candidates) - 1:
                last_error = f"OpenRouter model {model} transient HTTP {exc.code}. Retrying next model..."
                logger.warning(last_error)
                continue

            last_error = f"OpenRouter HTTP {exc.code}: {body[:260] or str(exc)}"
            return _local_structured_fallback(doc_type, context)
        except Exception as exc:
            last_error = f"OpenRouter request failed for model {model}: {exc}"
            logger.warning(last_error)
            if attempt_idx < len(model_candidates) - 1:
                continue
            return _local_structured_fallback(doc_type, context)

        if isinstance(raw_response, dict) and raw_response.get("error"):
            err = raw_response.get("error")
            if isinstance(err, dict):
                message = err.get("message") or err.get("code") or str(err)
            else:
                message = str(err)
            last_error = f"OpenRouter model {model} returned error payload: {message}"
            if attempt_idx < len(model_candidates) - 1:
                logger.warning(last_error)
                continue
            return {"error": last_error}

        content = _extract_openrouter_content(raw_response)

        if not isinstance(content, str) or not content.strip():
            last_error = f"OpenRouter model {model} returned unexpected response shape (missing content)."
            if attempt_idx < len(model_candidates) - 1:
                logger.warning(last_error)
                continue
            return _local_structured_fallback(doc_type, context)

        try:
            data = json.loads(_extract_json_substring(content))
        except Exception:
            try:
                data = json.loads(_fix_json_malformation(content))
            except Exception as exc:
                last_error = f"OpenRouter invalid JSON output: {exc}"
                if attempt_idx < len(model_candidates) - 1:
                    logger.warning("%s (model=%s). Retrying next model...", last_error, model)
                    continue
                return _local_structured_fallback(doc_type, context)

        if doc_type == "bundle" and data.get("is_academic") is False:
            logger.info("OpenRouter model %s succeeded (non-academic response)", model)
            return data
        if not _validate_structured_output(doc_type, data):
            if doc_type == "metadata":
                # Normalize can fill missing fields — don't hard-fail
                logger.warning("OpenRouter metadata missing some fields for model %s; normalizing.", model)
                return _normalize_metadata_fields(doc_type, data, context)
            return _local_structured_fallback(doc_type, context)
        if not data:
            return _local_structured_fallback(doc_type, context)

        logger.info("OpenRouter model %s succeeded", model)
        return _normalize_metadata_fields(doc_type, data, context)

    logger.warning("OpenRouter attempts exhausted for %s; using local fallback.", doc_type)
    return _local_structured_fallback(doc_type, context)


def _derive_fallback_title(content: str) -> str:
    if not content:
        return "Untitled Study Material"
    cleaned = " ".join(content.strip().split())
    if not cleaned:
        return "Untitled Study Material"
    # Remove common course code patterns (e.g., MATH101, CS 202, BIO-303)
    title = re.sub(r"\b([A-Z]{2,4}[- ]?\d{2,4}[A-Z]?)\b", "", cleaned)
    title = title.strip(" -:,.\n\t")
    title = title[:90]
    if len(cleaned) > 90:
        title += "..."
    return title or "Untitled Study Material"


def _split_source_sentences(content: str, limit: int = 4) -> list[str]:
    text = " ".join(str(content or "").split()).strip()
    if not text:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", text)
    cleaned = [sentence.strip() for sentence in sentences if sentence.strip()]
    if cleaned:
        return cleaned[:limit]
    return [text[:180]]


def _derive_subject_hint(content: str, title: str) -> str:
    candidate = str(title or "").strip() or str(content or "").strip()
    candidate = re.sub(
        r"\b(notes?|quiz(?:zes)?|cheat\s*sheet|cheatsheet|summary|guide|study\s+guide)\b",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s*[-:|]\s*$", "", candidate).strip()
    return candidate[:120] or "General Studies"


def _local_metadata_from_content(content: str) -> dict:
    title = _derive_fallback_title(content)
    sentences = _split_source_sentences(content, limit=2)
    description = " ".join(sentences).strip() or "Auto-generated summary based on the uploaded source material."
    if len(description) > 220:
        description = description[:217].rstrip() + "..."

    subject_hint = _derive_subject_hint(content, title)
    return {
        "title": title,
        "description": description,
        "subject_hint": subject_hint,
        "programme_hint": "General Studies",
        "faculty_hint": "General",
        "subject_match_basis": "new",
        "programme_match_basis": "new",
        "matched_subject_name": "",
        "matched_programme_name": "",
        "flair": "academic",
    }


def _local_quiz_from_content(content: str) -> dict:
    metadata = _local_metadata_from_content(content)
    sentences = _split_source_sentences(content, limit=5)
    quiz_questions: list[dict] = []

    for index, sentence in enumerate(sentences or [metadata["title"]], start=1):
        topic_phrase = sentence[:120].strip() or metadata["title"]
        quiz_questions.append(
            {
                "question": f"What is the main idea highlighted in part {index} of this material?",
                "options": [
                    {"letter": "A", "text": f"It focuses on {topic_phrase}."},
                    {"letter": "B", "text": "It is unrelated background information."},
                    {"letter": "C", "text": "It only lists random examples."},
                    {"letter": "D", "text": "It contradicts the source completely."},
                ],
                "answer": "A",
                "correct_answer": "A",
                "explanation": f"The source centers on: {topic_phrase}",
            }
        )

    while len(quiz_questions) < 3:
        quiz_questions.append(
            {
                "question": "What is the key concept in this material?",
                "options": [
                    {"letter": "A", "text": "The main concept from the uploaded source."},
                    {"letter": "B", "text": "A loosely related background detail."},
                    {"letter": "C", "text": "An unrelated example."},
                    {"letter": "D", "text": "A contradictory idea."},
                ],
                "answer": "A",
                "correct_answer": "A",
                "explanation": "This question reinforces the central idea from the uploaded source.",
            }
        )

    return {
        "questions": quiz_questions[:5],
        "metadata": {
            "time": "30 minutes",
            "total_marks": len(quiz_questions[:5]),
            "total_questions": len(quiz_questions[:5]),
        },
    }


def _local_notes_from_content(content: str) -> dict:
    metadata = _local_metadata_from_content(content)
    sentences = _split_source_sentences(content, limit=4)
    if not sentences:
        sentences = [f"Review the core ideas in {metadata['title']}." ]

    sections: list[dict] = []
    for index, sentence in enumerate(sentences[:3], start=1):
        sections.append(
            {
                "section_number": index,
                "section_title": f"Key Point {index}",
                "section_type": "concepts" if index == 1 else "revision",
                "content": [
                    {"block_type": "paragraph", "text": sentence[:240]},
                    {"block_type": "definition", "label": "Core Idea", "text": "This section captures the main concept from the uploaded material."},
                    {"block_type": "note", "text": "Revise this section and connect it to the rest of the material."},
                ],
            }
        )

    return {
        "sections": sections,
        "summary": [
            sentences[0] if sentences else "Review the uploaded material carefully.",
            f"Focus on the key ideas in {metadata['title']}.",
            "Revisit examples and definitions before attempting questions.",
            "Link each section back to the main topic to improve recall.",
            "Use the material as a revision anchor and practise active recall.",
        ][:5],
        "metadata": {
            "estimated_read_time": "30 mins",
            "focus_areas": "Core concepts from the uploaded source",
            "prerequisites": "General study skills",
        },
    }


def _local_cheatsheet_from_content(content: str) -> dict:
    metadata = _local_metadata_from_content(content)
    sentences = _split_source_sentences(content, limit=3)
    first_line = sentences[0] if sentences else f"Review the main ideas in {metadata['title']}."

    return {
        "sections": [
            {
                "section_title": "Quick Reference",
                "section_type": "formulas",
                "entries": [
                    {"label": "Core Idea", "content": first_line[:220] or "Key concept summary"},
                    {"label": "Revision Cue", "content": "Focus on the main terms, steps, and examples from the source."},
                ],
            }
        ],
        "metadata": {
            "purpose": "Quick reference for exams and revision",
            "exam_context": "",
            "topics": [metadata["subject_hint"]],
        },
    }


def _local_structured_fallback(doc_type: str, content: str) -> dict:
    if doc_type == "academic_check":
        return {"is_academic": True}
    if doc_type == "metadata":
        return _local_metadata_from_content(content)
    if doc_type == "quiz":
        return _local_quiz_from_content(content)
    if doc_type == "notes":
        return _local_notes_from_content(content)
    if doc_type == "cheatsheet":
        return _local_cheatsheet_from_content(content)
    if doc_type == "bundle":
        metadata = _local_metadata_from_content(content)
        return {
            "is_academic": True,
            "metadata": metadata,
            "quiz": _local_quiz_from_content(content),
            "notes": _local_notes_from_content(content),
            "cheatsheet": _local_cheatsheet_from_content(content),
        }
    return {"error": f"Unsupported local fallback doc_type={doc_type}"}


def _normalize_metadata_fields(doc_type: str, data: dict, source_content: str) -> dict:
    if doc_type == "metadata":
        data.setdefault("title", _derive_fallback_title(source_content))
        data.setdefault("description", "")
        data.setdefault("subject_hint", "General Studies")
        data.setdefault("programme_hint", "General Studies")
        data.setdefault("faculty_hint", "General")
        data.setdefault("subject_match_basis", "new")
        data.setdefault("programme_match_basis", "new")
        data.setdefault("matched_subject_name", "")
        data.setdefault("matched_programme_name", "")
        data["flair"] = _normalize_flair(data.get("flair", "academic"))
        return data

    if doc_type == "bundle" and isinstance(data.get("metadata"), dict):
        metadata = data["metadata"]
        metadata.setdefault("title", _derive_fallback_title(source_content))
        metadata.setdefault("description", "")
        metadata.setdefault("subject_hint", "General Studies")
        metadata.setdefault("programme_hint", "General Studies")
        metadata.setdefault("faculty_hint", "General")
        metadata.setdefault("subject_match_basis", "new")
        metadata.setdefault("programme_match_basis", "new")
        metadata.setdefault("matched_subject_name", "")
        metadata.setdefault("matched_programme_name", "")
        metadata["flair"] = _normalize_flair(metadata.get("flair", "academic"))
    return data


def _generate_structured(
    content: str,
    doc_type: str,
    mode: str = "file",
    taxonomy_context: dict | None = None,
    extra_guidance: str | None = None,
    model_candidates_override: list[str] | None = None,
) -> dict:
    openrouter_available = bool((os.environ.get("OPENROUTER_API_KEY") or "").strip())
    openrouter_models = _build_openrouter_candidates(model_candidates_override or _FREE_OPENROUTER_MODELS)

    if not _GENAI_AVAILABLE and not openrouter_available:
        return _local_structured_fallback(doc_type, content)

    keys = _load_keys()
    if not keys and not openrouter_available:
        return _local_structured_fallback(doc_type, content)

    system_prompts = {
        "metadata": _METADATA_PROMPT,
        "bundle": _ACADEMIC_BUNDLE_PROMPT,
        "academic_check": _ACADEMIC_CHECK_PROMPT,
        "quiz": _COMPONENT_SYSTEM_PROMPTS["quiz"],
        "notes": _COMPONENT_SYSTEM_PROMPTS["notes"],
        "cheatsheet": _COMPONENT_SYSTEM_PROMPTS["cheatsheet"],
    }
    sys_prompt = system_prompts.get(doc_type, _METADATA_PROMPT)

    max_ctx = 20000 if doc_type in {"bundle", "quiz", "notes", "cheatsheet"} else 3000
    context = content[:max_ctx]
    user_prompt = f"Target Document Type: {doc_type}\n\nSource Material:\n{context}"
    if taxonomy_context and doc_type in {"metadata", "bundle"}:
        taxonomy_payload = json.dumps(
            {
                "subjects": taxonomy_context.get("subjects", [])[:350],
                "programmes": taxonomy_context.get("programmes", [])[:160],
                "faculties": taxonomy_context.get("faculties", [])[:80],
            },
            ensure_ascii=True,
        )
        user_prompt += (
            "\n\nKnown taxonomy names (existing in database):\n"
            f"{taxonomy_payload}\n\n"
            "Selection rule:\n"
            "- Pick existing names when they are a good semantic fit.\n"
            "- When no existing name is a good fit, propose a new specific name and set *_match_basis to 'new'.\n"
            "- If you pick existing, matched_*_name must be an exact name from the list."
        )
    if doc_type == "bundle":
        user_prompt += (
            "\n\n" + _bundle_output_guidance(context) +
            "\nBundle quality rules:\n"
            "- The quiz should be exactly 30 multiple-choice questions with 4 options each and feel like a real exam set, not a tiny quizlet.\n"
            "- The notes should mirror KnowlyGen depth: enough sections, worked examples, and formulas to support real revision.\n"
            "- The cheatsheet should be compact but rich, with dense formula coverage and minimal filler.\n"
        )
    if extra_guidance:
        user_prompt += f"\n\nCorrection instruction:\n{extra_guidance.strip()}"
    if doc_type == "metadata" and mode == "topic":
        user_prompt = f"Generate metadata for the topic: {content}"

    if not keys and openrouter_available:
        return _generate_via_openrouter(
            sys_prompt=sys_prompt,
            user_prompt=user_prompt,
            doc_type=doc_type,
            context=context,
            model_candidates=openrouter_models,
        )

    candidate_models = os.environ.get(
        "GEMINI_MODEL_PREFERENCES",
        "gemini-2.0-flash-lite,gemini-flash-latest,gemini-2.0-flash"
    ).split(",")
    candidate_models = [model.strip() for model in candidate_models if model.strip()]

    last_error = None
    saw_auth_error = False
    for api_index, api_key in enumerate(keys, start=1):
        if _is_invalid_gemini_key(api_key):
            logger.info("Skipping known invalid Gemini key %d/%d (%s).", api_index, len(keys), _key_label(api_key))
            continue

        key_label = _key_label(api_key)
        logger.info("Gemini rotation: using key %d/%d (%s).", api_index, len(keys), key_label)

        for model_name in candidate_models:
            logger.info("Gemini rotation: key %s -> model %s.", key_label, model_name)
            for attempt in range(2):
                try:
                    if attempt > 0:
                        time.sleep((attempt ** 2) + random.random())

                    genai.configure(api_key=api_key)
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        system_instruction=sys_prompt,
                    )

                    with _get_key_lock(api_key):
                        _throttle_before_ai_call(api_key)
                        response = model.generate_content(
                            user_prompt,
                            generation_config=types.GenerationConfig(
                                temperature=0.4 if doc_type != "metadata" else 0.7,
                                max_output_tokens=8192 if doc_type in {"bundle", "quiz", "notes", "cheatsheet"} else 1000,
                                response_mime_type="application/json",
                            ),
                            request_options={"timeout": 90},
                        )

                    raw = _extract_json_substring((response.text or "").strip())
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        data = json.loads(_fix_json_malformation(raw))

                    if doc_type == "bundle" and data.get("is_academic") is False:
                        return data

                    if not _validate_structured_output(doc_type, data):
                        raise ValueError(f"Invalid output format for doc_type={doc_type}")
                    if not data:
                        raise ValueError("Parsed AI content is empty.")

                    logger.info("Gemini rotation: success with key %s and model %s.", key_label, model_name)
                    return _normalize_metadata_fields(doc_type, data, context)

                except Exception as exc:
                    last_error = str(exc)
                    error_text = last_error.lower()
                    if _is_gemini_auth_error(error_text):
                        saw_auth_error = True
                        _mark_invalid_gemini_key(api_key)
                        logger.warning("Gemini key %s rejected by provider on model %s: %s", key_label, model_name, exc)
                        break
                    if "404" in last_error:
                        logger.warning("Gemini model %s unavailable for key %s: %s", model_name, key_label, exc)
                        break
                    if "503" in last_error or "429" in last_error:
                        if attempt < 1:
                            wait_seconds = (2 ** (attempt + 1)) + random.uniform(0, 1)
                            logger.warning("Gemini throttled for key %s/model %s; retrying in %.1fs.", key_label, model_name, wait_seconds)
                            time.sleep(wait_seconds)
                            continue
                    logger.warning("Gemini call failed for key %s/model %s/attempt %d: %s", key_label, model_name, attempt + 1, exc)
                    break

    if saw_auth_error and last_error:
        if openrouter_available:
            fallback = _generate_via_openrouter(
                sys_prompt=sys_prompt,
                user_prompt=user_prompt,
                doc_type=doc_type,
                context=context,
                model_candidates=openrouter_models,
            )
            if fallback and not fallback.get("error"):
                logger.info("OpenRouter fallback succeeded after Gemini auth errors.")
                return fallback
        return _local_structured_fallback(doc_type, content)

    if openrouter_available:
        fallback = _generate_via_openrouter(
            sys_prompt=sys_prompt,
            user_prompt=user_prompt,
            doc_type=doc_type,
            context=context,
            model_candidates=openrouter_models,
        )
        if fallback and not fallback.get("error"):
            logger.info("OpenRouter fallback succeeded after Gemini exhaustion.")
            return fallback

    return _local_structured_fallback(doc_type, content)


def analyze_image_for_search(image_data: bytes, mime_type: str) -> dict:
    """
    Analyze an academic-related image and return 2-5 keywords.
    Uses Gemini Vision capabilities.
    """
    keys = _load_keys()
    if not keys:
        return {"error": "No Gemini API keys configured."}

    # Use a fast, vision-capable model
    model_name = "gemini-2.0-flash-lite"
    prompt = "What academic topic or subject does this image relate to? Return 2-5 search keywords only (e.g., 'Organic Chemistry, Molecular Structure')."

    for api_key in keys:
        if _is_invalid_gemini_key(api_key):
            continue
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name=model_name)

            # Construct the vision part
            image_part = {"mime_type": mime_type, "data": image_data}

            with _get_key_lock(api_key):
                _throttle_before_ai_call(api_key)
                response = model.generate_content([prompt, image_part])

            keywords = (response.text or "").strip()
            # Basic cleanup in case Gemini adds extra prose
            if ":" in keywords:
                keywords = keywords.split(":", 1)[-1].strip()
            
            return {"keywords": keywords}
        except Exception as exc:
            logger.warning(f"Image analysis failed with Gemini key {api_key[-4:]}: {exc}")
            continue

    return {"error": "All AI attempts failed to analyze the image."}
