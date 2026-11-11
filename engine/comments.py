"""Student comments are untrusted input. Screen them before any model sees them.

The comment is a *lead*: we extract what it claims (a value, an option letter, a category hint)
and flag attempts to instruct the system. The LLM judge receives the comment inside a data
fence together with these flags, and the guards refuse any edit that merely does what an
injected comment asked for.
"""
import re

INJECTION = [
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)",
    r"\byou are (now )?(the |an? )?(admin|system|developer|assistant|bot)\b",
    r"\b(system prompt|jailbreak|developer mode)\b",
    r"\bmark (this|the) (report|question) as\b",
    r"\b(change|set|update) the (answer|key)( key)? to\b",
    r"\bas an? (ai|llm|language model)\b",
    r"</?(system|assistant|user|instructions?)>",
]
HINGLISH = {"hai", "hona", "chahiye", "kyu", "kyun", "galat", "nahi", "aana", "aa", "raha", "kya", "karu", "toh",
            "me", "mein", "di", "ki", "hi", "sahi", "bhai", "yaar", "kuch", "aur", "pucha", "nhi"}
CATEGORY_HINTS = [
    ("display", r"\b(cut|cropped|not (loading|visible|showing properly)|forever to load|slow|loading|screen|font|overlap)\b"),
    ("app", r"\b(clicked|tapped|saved|submitted|selected) .* (but|and) .*(saved|recorded|showed|marked)\b|\bapp (crash|hang)|keyboard\b"),
    ("language", r"\b(hindi|marathi|tamil|telugu|bengali|gujarati|kannada|english) (me|mein|medium|version|language)\b|\bin hindi\b"),
    ("syllabus", r"\b(out of|outside|not in) (the )?syllabus\b|\bnot in (ncert|neet|jee)\b"),
    ("chapter", r"\b(wrong|incorrect) chapter\b|\bchapter is wrong\b|\bwhy is it in\b|\bfrom .* chapter\b"),
    ("figure", r"\b(figure|fig|diagram|image|graph) (not|missing|nahi)"),
    ("spelling", r"\bspell(ing)?\b|\btypo\b"),
    ("markup", r"\\[a-z]+|\bcode is showing\b|\bhtml\b|\blatex\b"),
    ("option", r"\boption [a-d] (is )?(missing|blank|empty)|\bonly \d options\b|\bblank\b|\bsame\b"),
    ("data", r"\b(not given|missing|nahi di|data missing|value hi nahi)\b"),
    ("answer", r"\b(answer|ans|key|correct answer)\b|\bshould be\b|\bhona chahiye\b|\baana chahiye\b|\bgot\b"),
    ("solution", r"\bsolution\b"),
    ("exam_tag", r"\b(neet|jee|aiims)\s*\d{4}\b"),
    ("unit", r"\bunit\b"),
]


def screen(comment: str) -> dict:
    c = (comment or "").strip()
    low = c.lower()
    inj = [p for p in INJECTION if re.search(p, low)]
    words = re.findall(r"[a-zA-Z]+", low)
    vowels = sum(ch in "aeiou" for ch in low)
    letters = sum(ch.isalpha() for ch in low)
    keyboard_mash = bool(re.fullmatch(r"[asdfghjklqwertyuiopzxcvbnm]{4,}", low)) and not any(
        w in low for w in ("wrong", "error", "answer", "option", "figure"))
    gibberish = (len(c) < 2) or (letters >= 4 and vowels / max(letters, 1) < 0.12) or (len(words) == 1 and keyboard_mash and low in ("asdf", "asdfgh", "qwerty", "asdfghjkl", "zxcv") )
    hinglish = sum(w in HINGLISH for w in words) >= 2
    hints = [name for name, pat in CATEGORY_HINTS if re.search(pat, low)]
    claimed_numbers = re.findall(r"(?<![a-z])-?\d+(?:\.\d+)?(?:\s*:\s*\d+)?", low)
    claimed_option = re.findall(r"\b(?:answer|ans|key|option|is|be|to)\s*\(?([a-d])\)?(?:\b|$)", low)
    return {
        "injection": bool(inj),
        "injection_patterns": inj,
        "gibberish": bool(gibberish),
        "vague": (not inj) and len(words) <= 2 and not claimed_numbers,
        "register": "hinglish" if hinglish else "english",
        "hints": hints,
        "claimed_numbers": claimed_numbers,
        "claimed_option": [x.upper() for x in claimed_option],
    }
