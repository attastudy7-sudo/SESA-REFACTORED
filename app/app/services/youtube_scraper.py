"""
YouTube video search using scraping (no API quota needed).
Uses HTML scraping to get video IDs, then oEmbed for metadata.
"""

import re
import time
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import current_app
import json

YOUTUBE_SEARCH_URL = "https://www.youtube.com/results"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def _is_whole_word_match(keyword, text):
    """Check if keyword exists in text as a whole word (case-insensitive)."""
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text, re.IGNORECASE))

def _norm_channel(name: str) -> str:
    """Normalize channel name for robust matching: lowercase, alphanumeric only."""
    return re.sub(r'[^a-z0-9]', '', name.lower())

# STEP 1 — Channel whitelist check (substring + normalized)
    channel_norm = _norm_channel(channel_lower)
    for key, (prog, subj) in TRUSTED_CHANNELS.items():
        if key in channel_lower or _norm_channel(key) == channel_norm:
            return {'category': prog, 'subject': subj}

TRUSTED_CHANNELS = {
    'khan academy': ('Science', 'Mathematics'),
    'crashcourse': ('Science', 'Arts'),
    'crash course': ('Science', 'Arts'),
    'mit opencourseware': ('Engineering', 'Science'),
    'ted-ed': ('Science', 'Arts'),
    'veritasium': ('Science', 'Physics'),
    'numberphile': ('Mathematics', 'Mathematics'),
    '3blue1brown': ('Mathematics', 'Mathematics'),
    'physics girl': ('Science', 'Physics'),
    'scishow': ('Science', 'Biology'),
    'asapscience': ('Science', 'Biology'),
    'socratica': ('Mathematics', 'Computer Science'),
    'programming with mosh': ('Computer Science', 'Programming'),
    'freecodecamp': ('Computer Science', 'Programming'),
    'free code camp': ('Computer Science', 'Programming'),
    'sentdex': ('Computer Science', 'Python'),
    'traversy media': ('Computer Science', 'Web Development'),
    'the organic chemistry tutor': ('Science', 'Chemistry'),
    'neso academy': ('Engineering', 'Electronics'),
    'gate smashers': ('Computer Science', 'CS Fundamentals'),
    'apna college': ('Computer Science', 'Programming'),
    'codesandnerd': ('Computer Science', 'Programming'),
    'jenny lectures': ('Computer Science', 'Data Structures'),
    'abdul bari': ('Computer Science', 'Algorithms'),
    'mit': ('Engineering', 'University'),
    'stanford': ('Science', 'University'),
    'harvard': ('Law', 'University'),
    'oxford university': ('Arts', 'University'),
    'nptel': ('Engineering', 'IIT'),
    'coursera': ('General', 'Education'),
    'edx': ('General', 'Education'),
    'udemy tutorial': ('Computer Science', 'Skills'),
    'byjus': ('Science', 'Education'),
    'professor leonard': ('Mathematics', 'Calculus'),
    'patrickjmt': ('Mathematics', 'Calculus'),
    'organic chemistry tutor': ('Science', 'Chemistry'),
    'dr trefor bazett': ('Mathematics', 'Mathematics'),
    'blackpenredpen': ('Mathematics', 'Mathematics'),
    'math with mr j': ('Mathematics', 'Mathematics'),
    'simple learning pro': ('Science', 'Science'),
    'anil kumar': ('Mathematics', 'Mathematics'),
    'kurzgesagt': ('Science', 'Knowledge'),
    'minutephysics': ('Science', 'Physics'),
    'minuteearth': ('Science', 'Earth Science'),
    'teded': ('Science', 'Arts'),
    'sciencechannel': ('Science', 'Science'),
    'national geographic': ('Science', 'Geography'),
    'pbs space time': ('Science', 'Physics'),
    'domain of science': ('Science', 'Science'),
    'tibees': ('Mathematics', 'Physics'),
    'zach star': ('Engineering', 'Engineering'),
    'welch labs': ('Mathematics', 'Science'),
    'engineeringmadesimple': ('Engineering', 'Engineering'),
    'engineer guy': ('Engineering', 'Engineering'),
    'practical engineering': ('Engineering', 'Engineering'),
    'real engineering': ('Engineering', 'Engineering'),
    'smartereveryday': ('Science', 'Science'),
    'smarter every day': ('Science', 'Science'),
    'codebasics': ('Computer Science', 'Data Science'),
    'sentdex': ('Computer Science', 'Python'),
    'tech with tim': ('Computer Science', 'Python'),
    'cs dojo': ('Computer Science', 'Programming'),
    'programming knowledge': ('Computer Science', 'Programming'),
    'derek banas': ('Computer Science', 'Programming'),
    'thenewboston': ('Computer Science', 'Programming'),
    'john fish': ('Computer Science', 'CS'),
    'mike and matty': ('Medicine', 'Study Skills'),
    'medcram': ('Medicine', 'Medicine'),
    'osmosis': ('Medicine', 'Medicine'),
    'armando hasudungan': ('Medicine', 'Biology'),
    'ninja nerd': ('Medicine', 'Medicine'),
    'lecturio': ('Medicine', 'Medicine'),
    'amboss': ('Medicine', 'Medicine'),
    'accountingcoach': ('Accounting', 'Accounting'),
    'asbill accounting': ('Accounting', 'Accounting'),
    'professor messer': ('Computer Science', 'CompTIA'),
    'comptia': ('Computer Science', 'CompTIA'),
    'crash course economics': ('Economics', 'Economics'),
    'econplusdal': ('Economics', 'Economics'),
    'jacob clifford': ('Economics', 'Economics'),
    'acdc econ': ('Economics', 'Economics'),
    'history with hilbert': ('History', 'History'),
    'tom richey': ('History', 'History'),
    'heimler history': ('History', 'History'),
    'simple history': ('History', 'History'),
    'geography now': ('Geography', 'Geography'),
    'professor dave explains': ('Science', 'Chemistry'),
    'tyler dewitt': ('Science', 'Chemistry'),
    'bozeman science': ('Science', 'Biology')
}

# Non-academic keywords to filter out (Hard Blacklist for Safety)
NON_ACADEMIC_KEYWORDS = {
    'gaming', 'playthrough', 'minecraft', 'fortnite', 'cod', 'call of duty',
    'roblox', 'among us', 'gta', 'grand theft auto', 'fifa', 'football game',
    'music video', 'song', 'album', 'rapper', 'hip hop', 'pop music',
    'movie', 'film', 'trailer', 'netflix', 'series', 'tv show', 'anime',
    'comedy', 'funny', 'vlog', 'prank', 'challenge', 'dance', 'tiktok',
    'beauty', 'makeup', 'fashion', 'clothing', 'shopping', 'haul',
    'recipe', 'cooking', 'food', 'restaurant', 'fast food',
    'car', 'vehicle', 'bike', 'motorcycle', 'truck',
    'sports', 'soccer', 'basketball', 'boxing', 'wrestling',
    'politics', 'news', 'election', 'political',
    'celebrity', 'star', 'fame', 'rumor', 'gossip',
    'horror', 'scary', 'prank video',
    'instagram', 'tiktok', 'social media', 'influencer',
    'reaction video', 'compilation', 'marathon', 'full movie',
    'meme', 'viral', 'trending', 'booty', 'sex scenes',
    'nsfw', 'porn', 'hentai', 'naked', 'nude', 'sexy', 'erotic', 'clubbing',
    'party', 'official music video', 'teaser', 'entertainment', 'gossip',
    'scandals', 'leak', 'dating', 'marriage', 'divorce', 'celebrity news',
    'gore', 'snuff', 'execution', 'murder', 'killing', 'decapitation', 
    'torture', 'amputation', 'corpse', 'dead body', 'autopsy', 'shooting', 
    'stabbing', 'violence', 'bloodbath', 'slaughter', 'massacre', 
    'xvideos', 'pornhub', 'xhamster', 'redtube', 'brazzers', 'bangbros', 
    'realitykings', 'ecchi', 'ahegao', 'bdsm', 'fetish', 'bondage', 
    'dominant', 'submissive', 'gangbang', 'orgy', 'squirt', 'facial', 
    'deepthroat', 'cream pie', 'blowjob', 'handjob', 'footjob', 'milf', 
    'gilf', 'dilf', 'loli', 'shota', 'incel', 'redpill', 'blackpill',
    'cum', 'semen', 'vagina', 'penis', 'clitoris', 'scrotum', 'testicles',
    'breasts', 'nipples', 'buttocks', 'rectum', 'anal', 'sodomy',
    'necrophilia', 'bestiality', 'pedophilia'
}

# Common academic keyword indicators
ACADEMIC_INDICATORS = {
    'tutorial', 'course', 'lecture', 'lesson', 'learn', 'class', 'education',
    'explained', 'introduction', 'basics', 'beginner', 'fundamental',
    'concept', 'theory', 'principle', 'formula', 'problem', 'solution',
    'exam', 'question', 'answer', 'test', 'quiz', 'practice',
    'chapter', 'module', 'unit', 'section', 'part', 'syllabus', 
    'curriculum', 'assignment', 'homework', 'revision', 'notes', 
    'textbook', 'worksheet', 'midterm', 'final', 'grade', 'mark', 
    'semester', 'term', 'degree', 'diploma', 'university', 'college', 
    'school', 'academic', 'physics', 'chemistry', 'biology', 'math', 
    'mathematics', 'engineering', 'computer science', 'programming', 
    'coding', 'medicine', 'nursing', 'health', 'anatomy', 'physiology', 
    'business', 'economics', 'accounting', 'finance', 'history', 
    'geography', 'psychology', 'philosophy', 'literature', 'language', 
    'grammar', 'writing', 'algebra', 'calculus', 'geometry', 'trigonometry', 
    'statistics', 'probability', 'linear algebra', 'differential equations', 
    'thermodynamics', 'electromagnetism', 'quantum', 'relativity', 'optics', 
    'mechanics', 'kinematics', 'genetics', 'evolution', 'ecology', 
    'microbiology', 'organic chemistry', 'inorganic chemistry', 
    'stoichiometry', 'titration', 'cell biology', 'algorithm', 
    'data structure', 'recursion', 'sorting', 'binary', 'array', 
    'linked list', 'stack', 'queue', 'graph', 'tree', 'dynamic programming', 
    'machine learning', 'neural network', 'database', 'sql', 'html', 'css', 
    'javascript', 'python', 'java', 'c++', 'react', 'api', 'backend', 
    'frontend', 'debugging', 'oop', 'object oriented', 'microeconomics', 
    'macroeconomics', 'supply demand', 'market', 'inflation', 'gdp', 
    'balance sheet', 'income statement', 'jurisprudence', 'tort', 
    'contract law', 'sociology', 'anthropology', 'political science', 
    'ethics', 'logic', 'rhetoric', 'linguistics', 'syntax', 'morphology',
    'world war', 'cold war', 'civil war', 'sexuality', 'gender studies',
    'classical music', 'music theory', 'drug policy', 'pharmacology',
    'social media studies', 'game theory', 'blood pressure', 'body systems', 'induction', 'proof', 'mathematical', 'theorem',
    'derivative', 'integral', 'matrix', 'vector', 'eigenvalue', 'limit', 'series', 'sequence', 'convergence',
    'hypothesis', 'conjecture', 'axiom', 'lemma', 'corollary',
    'polynomial', 'factorial', 'permutation', 'combination', 'modular',
    'cryptography', 'compiler', 'operating system', 'networking',
    'transistor', 'circuit', 'voltage', 'current', 'resistance', 'capacitor', 'inductor',
    'photosynthesis', 'mitosis', 'meiosis', 'osmosis', 'diffusion', 'biochemistry', 'genetics'
}

# Core academic concepts — broad fallback when DB keywords miss
CORE_CONCEPTS = {
    # Computer Science
    'data structures': 'Computer Science',
    'algorithms': 'Computer Science',
    'programming': 'Computer Science',
    'python': 'Computer Science',
    'java': 'Computer Science',
    'c++': 'Computer Science',
    'javascript': 'Computer Science',
    'web development': 'Computer Science',
    'machine learning': 'Computer Science',
    'artificial intelligence': 'Computer Science',
    'ai': 'Computer Science',
    'deep learning': 'Computer Science',
    'neural networks': 'Computer Science',
    'computer vision': 'Computer Science',
    'nlp': 'Computer Science',
    'natural language processing': 'Computer Science',
    'data science': 'Computer Science',
    'big data': 'Computer Science',
    'database': 'Computer Science',
    'sql': 'Computer Science',
    'software engineering': 'Computer Science',
    'computer architecture': 'Computer Science',
    'operating systems': 'Computer Science',
    'networks': 'Computer Science',
    'cybersecurity': 'Computer Science',
    'cryptography': 'Computer Science',
    'compiler': 'Computer Science',
    'compilers': 'Computer Science',
    'distributed systems': 'Computer Science',
    'cloud computing': 'Computer Science',
    'docker': 'Computer Science',
    'kubernetes': 'Computer Science',
    'devops': 'Computer Science',
    'git': 'Computer Science',
    'github': 'Computer Science',
    'dsa': 'Computer Science',
    'full stack': 'Computer Science',
    'frontend': 'Computer Science',
    'react': 'Computer Science',
    'angular': 'Computer Science',
    'vue': 'Computer Science',
    'node': 'Computer Science',
    'nodejs': 'Computer Science',
    'backend': 'Computer Science',
    'api': 'Computer Science',
    'rest': 'Computer Science',
    'graphql': 'Computer Science',
    'ci/cd': 'Computer Science',
    'aws': 'Computer Science',
    'azure': 'Computer Science',
    'gcp': 'Computer Science',
    'microservices': 'Computer Science',
    'serverless': 'Computer Science',
    'lambda': 'Computer Science',
    # Mathematics
    'calculus': 'Mathematics',
    'algebra': 'Mathematics',
    'geometry': 'Mathematics',
    'trigonometry': 'Mathematics',
    'statistics': 'Mathematics',
    'probability': 'Mathematics',
    'linear algebra': 'Mathematics',
    'differential equations': 'Mathematics',
    'discrete mathematics': 'Mathematics',
    'real analysis': 'Mathematics',
    'complex analysis': 'Mathematics',
    'numerical analysis': 'Mathematics',
    'numerical methods': 'Mathematics',
    'mathematical': 'Mathematics',
    'math': 'Mathematics',
    'maths': 'Mathematics',
    'number theory': 'Mathematics',
    'topology': 'Mathematics',
    'set theory': 'Mathematics',
    'logic': 'Mathematics',
    'proof': 'Mathematics',
    'theorem': 'Mathematics',
    'group theory': 'Mathematics',
    'ring theory': 'Mathematics',
    'field theory': 'Mathematics',
    'graph theory': 'Mathematics',
    'combinatorics': 'Mathematics',
    'optimization': 'Mathematics',
    'operations research': 'Mathematics',
    # Science
    'physics': 'Science',
    'chemistry': 'Science',
    'biology': 'Science',
    'genetics': 'Science',
    'ecology': 'Science',
    'microbiology': 'Science',
    'cell biology': 'Science',
    'organic chemistry': 'Science',
    'inorganic chemistry': 'Science',
    'physical chemistry': 'Science',
    'biochemistry': 'Science',
    'thermodynamics': 'Science',
    'electromagnetism': 'Science',
    'quantum': 'Science',
    'quantum mechanics': 'Science',
    'relativity': 'Science',
    'optics': 'Science',
    'mechanics': 'Science',
    'kinematics': 'Science',
    'electricity': 'Science',
    'magnetism': 'Science',
    'waves': 'Science',
    'sound': 'Science',
    'light': 'Science',
    'atomic': 'Science',
    'nuclear': 'Science',
    'particle': 'Science',
    'astronomy': 'Science',
    'earth science': 'Science',
    'geology': 'Science',
    'meteorology': 'Science',
    'oceanography': 'Science',
    # Engineering
    'electrical engineering': 'Engineering',
    'mechanical engineering': 'Engineering',
    'civil engineering': 'Engineering',
    'chemical engineering': 'Engineering',
    'computer engineering': 'Engineering',
    'biomedical engineering': 'Engineering',
    'biomedical': 'Engineering',
    'aerospace engineering': 'Engineering',
    'aerospace': 'Engineering',
    'materials engineering': 'Engineering',
    'materials science': 'Engineering',
    'nanotechnology': 'Engineering',
    'robotics': 'Engineering',
    'mechatronics': 'Engineering',
    'automation': 'Engineering',
    'control systems': 'Engineering',
    'signal processing': 'Engineering',
    'microprocessor': 'Engineering',
    'microprocessors': 'Engineering',
    'circuit': 'Engineering',
    'electronics': 'Engineering',
    'vlsi': 'Engineering',
    'power systems': 'Engineering',
    'motors': 'Engineering',
    'generators': 'Engineering',
    'transformers': 'Engineering',
    'engineering mechanics': 'Engineering',
    'material science': 'Engineering',
    'fluid mechanics': 'Engineering',
    'heat transfer': 'Engineering',
    'mass transfer': 'Engineering',
    'manufacturing': 'Engineering',
    'quality control': 'Engineering',
    'engineering design': 'Engineering',
    'cad': 'Engineering',
    'cam': 'Engineering',
    'cae': 'Engineering',
    'finite element': 'Engineering',
    'finite element analysis': 'Engineering',
    'fea': 'Engineering',
    'cfd': 'Engineering',
    'computational fluid dynamics': 'Engineering',
    'multibody dynamics': 'Engineering',
    # Economics
    'microeconomics': 'Economics',
    'macroeconomics': 'Economics',
    'international economics': 'Economics',
    'development economics': 'Economics',
    'behavioral economics': 'Economics',
    'econometrics': 'Economics',
    'public economics': 'Economics',
    'health economics': 'Economics',
    'environmental economics': 'Economics',
    'urban economics': 'Economics',
    'labor economics': 'Economics',
    'monetary economics': 'Economics',
    'financial economics': 'Economics',
    'industrial organization': 'Economics',
    'game theory': 'Economics',
    'decision theory': 'Economics',
    'utility theory': 'Economics',
    'welfare economics': 'Economics',
    'economic growth': 'Economics',
    'international trade': 'Economics',
    'supply chain': 'Business',
    'finance': 'Business',
    'accounting': 'Business',
    'taxation': 'Business',
    'budget': 'Business',
    'investment': 'Business',
    'stock market': 'Business',
    'marketing': 'Business',
    'human resources': 'Business',
    'hr': 'Business',
    'operations': 'Business',
    'logistics': 'Business',
    'entrepreneurship': 'Business',
    'business administration': 'Business',
    'mba': 'Business',
    'management': 'Business',
    'leadership': 'Business',
    'strategy': 'Business',
    'consulting': 'Business',
    'sales': 'Business',
    'negotiation': 'Business',
    # History
    'history': 'History',
    'ancient history': 'History',
    'medieval history': 'History',
    'renaissance': 'History',
    'early modern': 'History',
    'modern history': 'History',
    'world history': 'History',
    'military history': 'History',
    'political history': 'History',
    'social history': 'History',
    'history of science': 'History',
    'history of technology': 'History',
    # Philosophy
    'philosophy': 'Philosophy',
    'metaphysics': 'Philosophy',
    'epistemology': 'Philosophy',
    'ethics': 'Philosophy',
    'aesthetics': 'Philosophy',
    'political philosophy': 'Philosophy',
    'philosophy of mind': 'Philosophy',
    'philosophy of language': 'Philosophy',
    'philosophy of science': 'Philosophy',
    # Arts
    'literature': 'Arts',
    'poetry': 'Arts',
    'drama': 'Arts',
    'novel': 'Arts',
    'fiction': 'Arts',
    'shakespeare': 'Arts',
    'music': 'Arts',
    'music theory': 'Arts',
    'fine arts': 'Arts',
    'visual arts': 'Arts',
    'painting': 'Arts',
    'sculpture': 'Arts',
    'architecture': 'Arts',
    'design': 'Arts',
    'film': 'Arts',
    'theater': 'Arts',
    'dance': 'Arts',
    # Language
    'grammar': 'Language',
    'syntax': 'Language',
    'morphology': 'Language',
    'phonetics': 'Language',
    'phonology': 'Language',
    'semantics': 'Language',
    'pragmatics': 'Language',
    'linguistics': 'Language',
    'language teaching': 'Language',
    'esl': 'Language',
    'efl': 'Language',
    'toefl': 'Language',
    'ielts': 'Language',
    # Medicine
    'anatomy': 'Medicine',
    'physiology': 'Medicine',
    'pharmacology': 'Medicine',
    'immunology': 'Medicine',
    'pathology': 'Medicine',
    'surgery': 'Medicine',
    'clinical': 'Medicine',
    'medical': 'Medicine',
    'nursing': 'Medicine',
    'public health': 'Medicine',
    'epidemiology': 'Medicine',
    'biostatistics': 'Medicine',
    'genomics': 'Medicine',
    'proteomics': 'Medicine',
    'cardiology': 'Medicine',
    'oncology': 'Medicine',
    'pediatrics': 'Medicine',
    'gynecology': 'Medicine',
    'obstetrics': 'Medicine',
    'orthopedics': 'Medicine',
    'radiology': 'Medicine',
    'anesthesiology': 'Medicine',
    'emergency': 'Medicine',
    'primary care': 'Medicine',
    'neuroscience': 'Medicine',
    # Law
    'law': 'Law',
    'legal': 'Law',
    'contract law': 'Law',
    'tort law': 'Law',
    'constitutional law': 'Law',
    'criminal law': 'Law',
    'civil law': 'Law',
    'international law': 'Law',
    'jurisprudence': 'Law',
}

def is_academic_query(query: str, academic_keywords: set = None) -> bool:
    """
    Determine if a search query is academic/educational.
    
    Args:
        query: The search query
        academic_keywords: Optional set of keywords from database programmes/subjects
    
    Returns:
        True if query appears academic, False otherwise
    """
    query_lower = query.lower()
    query_words = set(query_lower.split())
    
    # Check if any non-academic keywords are present as whole words
    for keyword in NON_ACADEMIC_KEYWORDS:
        if _is_whole_word_match(keyword, query_lower):
            # If there's an academic indicator, might still be okay
            has_academic_indicator = any(_is_whole_word_match(indicator, query_lower) for indicator in ACADEMIC_INDICATORS)
            if not has_academic_indicator:
                return False
    
    # If academic keywords provided from database, check for matches
    if academic_keywords:
        # Check if query contains any academic keywords from database
        query_parts = query_lower.split()
        for part in query_parts:
            if part in academic_keywords:
                return True
        
        # Also check bigrams (two-word combinations)
        words = query_lower.split()
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            if bigram in academic_keywords:
                return True
        
        # Check if query contains any academic indicator words
        if any(indicator in query_lower for indicator in ACADEMIC_INDICATORS):
            return True
        
        # If no match but query is short (< 3 words), be slightly more permissive
        # than total rejection, but still cautious.
        if len(query_parts) < 2:
            return False
        
        return True
    
    # If no academic keywords provided, fall back to indicator check
    # Default to True — users on this platform are students searching academic topics
    indicator_match = any(indicator in query_lower for indicator in ACADEMIC_INDICATORS)
    if indicator_match:
        return True
    # Only block if clearly non-academic (already checked above via NON_ACADEMIC_KEYWORDS)
    return True


def categorize_video(title: str, channel: str, programme_keywords: dict, subject_keywords: dict) -> dict | None:
    """
    Categorize a video based on its title and channel against known programmes/subjects.
    Deterministic, rule-based approach.
    
    Args:
        title: Video title
        channel: YouTube channel name
        programme_keywords: Dict mapping keywords to programme names
        subject_keywords: Dict mapping keywords to (subject_name, programme_name) tuples
    
    Returns:
        Dict with 'category' (programme name) and optionally 'subject', or None if not academic
    """
    title_lower = title.lower()
    channel_lower = channel.lower()
    combined = f"{title_lower} {channel_lower}"

    # STEP 0 — Hard Rejection (Blacklist)
    for bad_word in NON_ACADEMIC_KEYWORDS:
        if _is_whole_word_match(bad_word, combined):
            return None

    # STEP 0.5 — Structural Music Video Check (Hard Rejection)
    music_patterns = [
        r'\b(official\s+)?(music\s+video|lyric\s+video|lyrics\s+video|audio\s+video)\b',
        r'\bft\.?\s+\w+.*official\b',
        r'\(official\s+(video|audio|mv|clip|visualizer)\)',
        r'\[official\s+(video|audio|mv|clip|visualizer)\]',
        r'\bvevo\b',
        r'\bworldstar\b',
        r'–\s*.+\s*(official|lyrics|audio|video|mv)$'
    ]
    for pattern in music_patterns:
        if re.search(pattern, title_lower, re.IGNORECASE):
            return None

    # STEP 1 — Channel whitelist check (substring + normalized)
    channel_norm = _norm_channel(channel_lower)
    for key, (prog, subj) in TRUSTED_CHANNELS.items():
        if key in channel_lower or _norm_channel(key) == channel_norm:
            return {'category': prog, 'subject': subj}

    # STEP 2 — Channel pattern check (requires title to also have an academic signal)
    channel_words = ['academy', 'university', 'college', 'institute', 'school', 'professor', 'tutor',
                     'lectures', 'learning', 'education', 'sciences', 'polytechnic', 'tutorials']
    if any(word in channel_lower for word in channel_words):
        # Don't accept on channel name alone — title must also carry an academic signal
        if any(_is_whole_word_match(ind, title_lower) for ind in ACADEMIC_INDICATORS):
            return {'category': 'General', 'subject': ''}
        # Otherwise fall through to stricter checks

    # STEP 3 — DB subject/programme keyword match (whole-word only to prevent false positives)
    # Guard: For broad single-word subjects, require at least one academic indicator in title.
    broad_subjects = {
        'mathematics', 'physics', 'chemistry', 'biology', 'economics',
        'history', 'philosophy', 'arts', 'language', 'medicine', 'law',
        'engineering', 'computer', 'science', 'general'
    }
    for keyword, value in subject_keywords.items():
        if len(keyword) >= 4 and _is_whole_word_match(keyword, combined):
            # If keyword is a broad single-word subject, skip unless title has an academic indicator
            if len(keyword.split()) == 1 and keyword.lower() in broad_subjects:
                if not any(_is_whole_word_match(ind, title_lower) for ind in ACADEMIC_INDICATORS):
                    continue
            if isinstance(value, tuple):
                return {'category': value[1], 'subject': value[0]}
            return {'category': value, 'subject': value}

    # STEP 3.5 — Core concepts fallback (catch common academic topics not in DB)
    for concept, subject in CORE_CONCEPTS.items():
        if _is_whole_word_match(concept, combined):
            return {'category': 'General', 'subject': subject}

    # STEP 4 — Taxonomy keyword scoring (adjusted for short queries)
    score = 0
    for indicator in ACADEMIC_INDICATORS:
        if _is_whole_word_match(indicator, combined):
            score += 1
    # Lower threshold for short queries (< 4 words) to be more permissive
    threshold = 2 if len(title_lower.split()) < 4 else 4
    if score >= threshold:
        return {'category': 'General', 'subject': ''}

        
    # STEP 5 — Structural pattern check
    patterns = [
        r'\bpart\s*\d+\b', r'\bchapter\s*\d+\b', r'\blecture\s*\d*\b',
        r'\bweek\s*\d+\b', r'\bunit\s*\d+\b', r'\bepisode\s*\d+\b',
        r'\bmod(ule)?\s*\d+\b', r'\bclass\s*\d+\b', r'\bsession\s*\d+\b',
        r'\bintroduction\s+to\b', r'\bbeginners?\s+guide\b', r'\bhow\s+to\b',
        r'\bexplained\b', r'\bfull\s+course\b', r'\bcomplete\s+course\b',
        r'\bcrash\s+course\b', r'\bstep\s+by\s+step\b', r'\bin\s+\d+\s+minutes?\b'
    ]
    for pattern in patterns:
        if re.search(pattern, title_lower):
            return {'category': 'General', 'subject': ''}

    # STEP 6 — Final rejection
    return None


def _get_redis():
    """Get Redis client if available."""
    return current_app.extensions.get('redis')


# Maximum unique IDs to extract from a single search-page scrape.
_SCRAPE_ID_CAP = 35
# Minimum pool size before a whitelist-biased second scrape is triggered.
_POOL_MIN = 18
# Channel suffixes appended to the query on the second, whitelist-biased scrape.
_WHITELIST_QUERY_SUFFIX = (
    " Khan Academy OR 3Blue1Brown OR Professor Leonard"
    " OR The Organic Chemistry Tutor OR CrashCourse"
)


def _scrape_unique_ids(html: str, cap: int, existing_seen: set | None = None) -> list[str]:
    """Extract up to *cap* unique non-Shorts video IDs from a YouTube results HTML page.

    Args:
        html: Raw HTML from the YouTube search results page.
        cap: Maximum number of IDs to return.
        existing_seen: Optional set of IDs already collected (for dedup across scrapes).

    Returns:
        Ordered list of unique, non-Shorts video IDs.
    """
    all_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)

    # Build the Shorts exclusion set from explicit Shorts context patterns.
    # Build the Shorts exclusion set from explicit Shorts context patterns.
    _shorts_pat = re.compile(
        r'"shortsLockupViewModel".*?"videoId":"([a-zA-Z0-9_-]{11})"'
    )
    shorts_ids: set[str] = set(_shorts_pat.findall(html))
    for match in re.finditer(r'"videoId":"([a-zA-Z0-9_-]{11})"', html):
        ctx_start = max(0, match.start() - 100)
        ctx_end = match.end() + 100
        context = html[ctx_start:ctx_end]
        if '/shorts/' in context or 'shorts' in context.lower():
            shorts_ids.add(match.group(1))

    seen: set[str] = set(existing_seen) if existing_seen else set()
    unique: list[str] = []
    for vid in all_ids:
        if vid not in seen and vid not in shorts_ids:
            seen.add(vid)
            unique.append(vid)
            if len(unique) >= cap:
                break
    return unique


def search_youtube_videos(query: str, max_results: int = 20, offset: int = 0) -> list[dict]:
    """
    Search YouTube videos using HTML scraping + oEmbed.
    No YouTube API quota needed.

    Args:
        query: Search term
        max_results: Maximum number of results (default 20)
        offset: Slice offset into the scraped ID pool

    Returns:
        List of video dicts with: video_id, title, thumbnail, channel, url
    """
    if not query or not query.strip():
        return []

    query = query.strip()
    redis_client = _get_redis()

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key = f"yt_search:{query.lower()}:{max_results}"
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    # Small jitter before the primary request to reduce detection risk.
    time.sleep(random.uniform(0.1, 0.3))

    try:
        # ── Part A: Primary scrape — extract up to _SCRAPE_ID_CAP IDs ─────────
        resp = requests.get(
            YOUTUBE_SEARCH_URL,
            params={"search_query": query},
            headers={"User-Agent": USER_AGENT},
            timeout=10
        )
        if resp.status_code != 200:
            return []

        unique_ids = _scrape_unique_ids(resp.text, cap=_SCRAPE_ID_CAP)

        # ── Part B: Whitelist-biased second scrape (sequential, no new tab) ───
        # Only triggered when the primary pool is thin (< _POOL_MIN IDs).
        if len(unique_ids) < _POOL_MIN:
            time.sleep(random.uniform(0.8, 1.8))  # polite delay before second request
            boosted_query = query + _WHITELIST_QUERY_SUFFIX
            try:
                resp2 = requests.get(
                    YOUTUBE_SEARCH_URL,
                    params={"search_query": boosted_query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=10
                )
                if resp2.status_code == 200:
                    # Merge, dedup preserving primary-scrape order; cap total at 25.
                    extra = _scrape_unique_ids(
                        resp2.text,
                        cap=_SCRAPE_ID_CAP - len(unique_ids),
                        existing_seen=set(unique_ids)
                    )
                    unique_ids.extend(extra)
            except Exception as e:
                current_app.logger.debug(f"Whitelist second-scrape failed (non-fatal): {e}")

        if not unique_ids:
            return []

        # ── Part C: Parallel oEmbed metadata fetch ────────────────────────────
        batch = unique_ids[offset:offset + max_results]
        results_by_index: dict[int, dict] = {}

        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_index = {
                executor.submit(_get_video_metadata, vid): i
                for i, vid in enumerate(batch)
            }
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    data = future.result()
                    if data:
                        results_by_index[idx] = data
                except Exception:
                    pass  # silently skip failed fetches

        # Reassemble in original batch order.
        videos = [
            results_by_index[i]
            for i in range(len(batch))
            if i in results_by_index
        ]

        # ── Part D: Float trusted-channel videos to the front ─────────────────
        trusted_keys = set(TRUSTED_CHANNELS.keys())

        def _is_trusted(video: dict) -> bool:
            ch = video.get("channel", "").lower()
            return any(key in ch for key in trusted_keys)

        trusted_videos = [v for v in videos if _is_trusted(v)]
        other_videos   = [v for v in videos if not _is_trusted(v)]
        videos = trusted_videos + other_videos

        # ── Cache results for 1 hour ──────────────────────────────────────────
        if videos and redis_client:
            try:
                redis_client.setex(cache_key, 3600, json.dumps(videos))
            except Exception:
                pass

        return videos

    except Exception as e:
        current_app.logger.warning(f"YouTube search failed: {e}")
        return []


def _get_video_metadata(video_id: str) -> dict | None:
    """Get video metadata via oEmbed endpoint (no API quota)."""
    redis_client = _get_redis()
    
    # Check cache
    cache_key = f"yt_video:{video_id}"
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass
    
    try:
        # Get title via oEmbed
        oembed_url = f"https://www.youtube.com/oembed?url=https://youtube.com/watch?v={video_id}&format=json"
        resp = requests.get(oembed_url, timeout=3)
        
        if resp.status_code != 200:
            return None
        
        data = resp.json()
        
        video_data = {
            "video_id": video_id,
            "title": data.get("title", "Untitled"),
            "thumbnail": f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
            "channel": data.get("author_name", "Unknown"),
            "url": f"https://www.youtube.com/watch?v={video_id}"
        }
        
        # Cache for 24 hours
        if redis_client:
            try:
                redis_client.setex(cache_key, 86400, json.dumps(video_data))
            except Exception:
                pass
        
        return video_data
        
    except Exception:
        return None


def search_videos_fallback(query: str, max_results: int = 10) -> list[dict]:
    """
    Fallback: Use YouTube Data API if scraping fails.
    """
    from app.services.youtube_video_fetcher import (
        fetch_and_store_videos_for_topic,
        TRUSTED_CHANNEL_IDS
    )
    import os
    
    api_key = current_app.config.get('YOUTUBE_API_KEY') or os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        return []
    
    videos = []
    for channel_id in TRUSTED_CHANNEL_IDS[:3]:
        params = {
            'part': 'snippet',
            'q': query,
            'type': 'video',
            'channelId': channel_id,
            'maxResults': max_results,
            'key': api_key,
        }
        
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params=params,
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get('items', []):
                if item['id']['kind'] == 'youtube#video':
                    title = item['snippet']['title'].lower()
                    if 'short' in title:
                        continue
                    videos.append({
                        'video_id': item['id']['videoId'],
                        'title': item['snippet']['title'],
                        'thumbnail': item['snippet']['thumbnails']['high']['url'],
                        'channel': item['snippet']['channelTitle'],
                        'url': f"https://www.youtube.com/watch?v={item['id']['videoId']}"
                    })
                    if len(videos) >= max_results:
                        break
        
        if len(videos) >= max_results:
            break
    
    return videos


def search_videos(query: str, max_results: int = 20, offset: int = 0) -> list[dict]:
    # Try scraping first (no quota)
    videos = search_youtube_videos(query, max_results, offset)
    if videos:
        return videos
    return search_videos_fallback(query, max_results)