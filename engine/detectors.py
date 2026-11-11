"""Deterministic record checks. Cheap, explainable, run on every question (reported or not).

They do three jobs:
 1. hand the LLM judge hard facts instead of hoping it notices ("option D not present"),
 2. power the unreported-defect sweep at zero token cost,
 3. give the guards something to cross-check LLM edits against.
"""
import math
import re

from .linearize import plain

NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


SCRIPT = re.compile(r"[\^_]\s*(\([^()]*\)|-?\w+)")


def _nums(s):
    """numbers a reader would call 'values' - exponents and subscripts (m^2, ε_0) are dropped"""
    out = []
    s = SCRIPT.sub(" ", s.replace(",", ""))
    for m in NUM.finditer(s):
        try:
            out.append(float(m.group()))
        except ValueError:
            pass
    return out


def _close(a, b, tol=0.02):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def answer_problems(rec):
    a, t = rec.answer, rec.qtype
    if t == "scq":
        if not (isinstance(a, str) and re.fullmatch(r"[A-D]", a)):
            return f"scq answer must be one letter A-D, found {a!r}"
        if rec.options and a not in rec.options:
            return f"key {a} is not one of the options present ({''.join(rec.options)})"
    elif t == "mcq":
        if not isinstance(a, list) or not all(isinstance(x, str) and re.fullmatch(r"[A-D]", x) for x in a):
            return f"mcq answer must be a list of single letters, found {a!r}"
    elif t == "integerQuestion":
        if not (isinstance(a, str) and re.fullmatch(r"-?\d+(\.\d+)?", a.strip())):
            return f"integer answer must be numeric, found {a!r}"
    return None


def solution_vs_key(rec):
    """Does the last number the stored solution arrives at match the key? (scq: which option holds it)"""
    sol = rec.solution_text
    if not sol:
        return None
    nums = _nums(sol)
    if not nums:
        return None
    final = nums[-1]
    if rec.qtype == "integerQuestion":
        try:
            key = float(str(rec.answer).strip())
        except ValueError:
            return None
        tail = nums[-3:]
        if any(_close(n, key) for n in tail):
            return {"solution_final": final, "key": key, "match": True}
        scaled = bool(final and key) and abs(round(math.log10(abs(key / final)))) >= 1 and _close(
            key / final, 10 ** round(math.log10(abs(key / final))))
        return {"solution_final": final, "key": key, "match": False, "power_of_ten": scaled}
    if rec.qtype == "scq" and rec.options:
        holders = [k for k, v in rec.options.items() if v and any(_close(final, n, 0.005) for n in _nums(v))]
        if len(holders) == 1:
            return {"solution_final": final, "option_with_value": holders[0], "key": rec.answer,
                    "match": holders[0] == rec.answer}
    return None


FIG_RE = re.compile(r"\b(shown in (the )?(fig|figure|diagram)|given (fig|figure|diagram)|as shown|in the figure|refer(ring)? to (the )?(fig|figure))", re.I)
EXAM_RE = re.compile(r"\(\s*(NEET|JEE|AIIMS|AIPMT|BITSAT|CBSE|KCET|MHT[- ]?CET|WBJEE)[^)]{0,30}\d{4}\s*\)", re.I)
LATEX_RE = re.compile(r"\\(frac|sqrt|AA|times|alpha|beta|theta|lambda|mu|pi|left|right|text|mathrm|circ|degree|cdot)\b")
AMP_IN_MATH = re.compile(r"<mi>\s*&(amp;)?\s*</mi>")
NOISE_RE = re.compile(r"space for rough work|^\s*Q\.?\s*\d+[.)]", re.I | re.M)
UNIT_HINT = re.compile(r"\(\s*in [^)]+\)|\bin (cm|m|mm|kg|g|s|sec|seconds|N|J|eV|V|volt|W|A|K|%|dioptres?|m/s|rad)\b|_{2,}\s*\S", re.I)


def run(rec):
    f = []

    def add(code, field, detail, repair=None, severity="info"):
        f.append({"code": code, "field": field, "detail": detail, "suggests": repair, "severity": severity})

    # options
    if rec.qtype in ("scq", "mcq"):
        present = [k for k in "ABCD" if k in rec.options]
        missing = [k for k in "ABCD" if k not in rec.options]
        if missing:
            add("OPTION_MISSING", "question", f"option(s) {','.join(missing)} not present in record", "option_repair", "high")
        blanks = [k for k in present if not rec.options[k].strip()]
        if blanks:
            add("OPTION_BLANK", "question", f"option(s) {','.join(blanks)} present but empty", "option_repair", "high")
        seen = {}
        for k in present:
            v = re.sub(r"\s+", " ", rec.options[k]).strip().lower()
            if v and v in seen:
                add("OPTION_DUPLICATE", "question", f"options {seen[v]} and {k} are identical: {rec.options[k]!r}", "identical_options", "high")
            seen.setdefault(v, k)
    # answer format / type
    p = answer_problems(rec)
    if p:
        add("ANSWER_MALFORMED", "answer", p, "answer_key", "high")
    if rec.qtype == "mcq" and isinstance(rec.answer, list):
        letters = [x for x in rec.answer if isinstance(x, str) and re.fullmatch(r"[A-D]", x.strip())]
        if len(letters) == 1:
            add("MCQ_SINGLE_KEY", "questionType", f"stored as mcq but only one correct letter ({letters[0]})", "type_mismatch", "high")
    # solution vs key
    sk = solution_vs_key(rec)
    if sk and not sk["match"]:
        add("SOLUTION_KEY_MISMATCH", "answer", f"stored solution ends at {sk['solution_final']:g}; key is {rec.answer!r}"
            + (f"; that value is option {sk['option_with_value']}" if "option_with_value" in sk else "")
            + ("; differs by a power of ten (check units asked)" if sk.get("power_of_ten") else ""),
            None, "medium" if sk.get("power_of_ten") else "high")
    # figures
    for fld, html in (("question", rec.question_html), ("solution", rec.solution_html)):
        txt = plain(html)
        if FIG_RE.search(txt) and not rec.images and "<img" not in html:
            add("FIGURE_MISSING", fld, "text refers to a figure but no image is attached", "diagram", "high")
        m = EXAM_RE.search(txt)
        if m:
            add("EXAM_TAG", fld, f"exam tag in text: {m.group()!r}", "exam_reference")
        m = LATEX_RE.search(txt)
        if m:
            add("MARKUP_LEAK", fld, f"raw LaTeX visible: {m.group()!r}", "markup_leak", "medium")
        if AMP_IN_MATH.search(html):
            add("MARKUP_LEAK", fld, "LaTeX alignment '&' rendered as a visible character inside MathML", "markup_leak")
        if re.search(r"&lt;/?[a-z]+", html):
            add("MARKUP_LEAK", fld, "escaped HTML tag visible as text", "markup_leak")
        if NOISE_RE.search(txt):
            add("NOISE", fld, "stray question number / rough-work text", "noise")
    # integer questions with no unit / answer form
    if rec.qtype == "integerQuestion" and not UNIT_HINT.search(rec.stem):
        add("ANSWER_FORM_UNSTATED", "question", "integer question does not state the unit/form of the answer", "answer_form")
    if not rec.solution_text.strip():
        add("SOLUTION_EMPTY", "solution", "no solution stored", "solution_missing", "medium")
    return f


def history_after(rec, iso_ts):
    """errorHistory entries made after a report was filed -> candidate already_fixed."""
    return [h for h in (rec.raw.get("errorHistory") or []) if (h.get("at") or "") > iso_ts]
