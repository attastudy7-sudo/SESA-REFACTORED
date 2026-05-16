import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

def categorize_video_title(video_title: str, allowed_subjects: list[str]) -> str | dict | None:
    """
    Uses Groq API (via standard library HTTP POST) to categorize a YouTube video title 
    into one of the allowed academic subjects.

    Args:
        video_title: The title of the YouTube video.
        allowed_subjects: A list of valid subject names.

    Returns:
        The matched subject dict or 'Uncategorized'.
    """
    import time
    import re
    
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY not found in environment.")
        return "Uncategorized"

    subjects_str = ", ".join(allowed_subjects)
    
    system_prompt = (
        "You are a strict academic categorization engine for the Knowly learning platform. "
        "Your task is to evaluate a YouTube video title and assign it to the most relevant academic subject "
        "from the provided list. "
        "\n\nRules:\n"
        "1. Return ONLY a JSON object with exactly three keys: 'subject', 'level', and 'sequence_score'.\n"
        f"2. Valid subjects are: {subjects_str}. You MUST use the exact name from this list. DO NOT append course codes or create your own variations.\n"
        "3. 'level' must be one of: 'Beginner', 'Intermediate', 'Advanced'.\n"
        "4. 'sequence_score' must be an integer from 0 to 100 representing its logical position in a curriculum "
        "(e.g., Intro is 5, Advanced concepts are 80+).\n"
        "5. If the title is clickbait or non-academic, return {'subject': 'Uncategorized', 'level': 'Beginner', 'sequence_score': 0}.\n"
        "6. Be precise and academic."
    )

    user_prompt = f"Categorize this title: '{video_title}'"

    try:
        max_retries = 3
        for attempt in range(max_retries):
            response = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"}
                },
                timeout=15
            )
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logger.warning(f"Groq API rate limited (429). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
            response.raise_for_status()
            break

        content = response.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        
        matched_subject = result.get("subject", "Uncategorized")
        level = result.get("level", "Beginner")
        sequence = result.get("sequence_score", 0)
        
        # Double check that the matched subject is in the allowed list
        if matched_subject != "Uncategorized" and matched_subject not in allowed_subjects:
            # 1. Clean up common AI hallucinations (like course codes "MA101 - ")
            cleaned_match = re.sub(r'^[A-Z]{1,4}\d{1,4}\s*[-:]\s*', '', matched_subject).strip()
            
            if cleaned_match in allowed_subjects:
                matched_subject = cleaned_match
                found = True
            else:
                # 2. Try a more aggressive fuzzy match
                found = False
                def normalize(s):
                    return re.sub(r'[^a-z0-9]', '', s.lower())

                norm_match = normalize(cleaned_match)
                for allowed in allowed_subjects:
                    norm_allowed = normalize(allowed)
                    if norm_allowed in norm_match or norm_match in norm_allowed:
                        logger.info(f"Fuzzy matched hallucinated subject '{matched_subject}' to '{allowed}'")
                        matched_subject = allowed
                        found = True
                        break
            
            if not found:
                logger.warning(f"Model returned subject '{matched_subject}' (cleaned: '{cleaned_match}') which is not in allowed list: {allowed_subjects}")
                matched_subject = "Uncategorized"
            
        return {
            "subject": matched_subject,
            "level": level,
            "sequence": sequence
        }


    except Exception as e:
        logger.error(f"Error during video categorization: {str(e)}")
        return "Uncategorized"
