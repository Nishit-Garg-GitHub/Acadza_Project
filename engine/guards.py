"""Deterministic guards between the LLM's proposal and the database.

The LLM proposes; code disposes. An edit is auto-applied only if EVERY check passes.
Any failure downgrades the case to faculty_review (never silently drops it), and the failed
check is shown to faculty in the console.
"""
import difflib
import json
import re
from collections import Counter

from . import detectors
from .linearize import linearize, plain
from .records import split_options

AUTO_MIN_CONF = 0.85
HIGH_STAKES = {"answer_key", "type_mismatch"}
HIGH_STAKES_MIN_CONF = 0.90


def _digits(s):
    return Counter(re.findall(r"\d", s or ""))


def _nums(s):
    return Counter(f"{float(x):g}" for x in re.findall(r"\d+(?:\.\d+)?", (s or "").replace(",", "")))


def norm_answer(a):
    """'A,B,D' / ["A","B","D"] / 'B' / '50' -> canonical comparable form"""
    if a is None:
        return None
    if isinstance(a, list):
        letters = []
        for x in a:
            letters += re.findall(r"[A-D]", str(x).upper())
        return ",".join(sorted(set(letters)))
    s = str(a).strip()
    if re.fullmatch(r"\s*\[.*\]\s*", s):
        try:
            return norm_answer(json.loads(s))
        except ValueError:
            pass
    if re.fullmatch(r"[A-Da-d](\s*[, ]\s*[A-Da-d])*", s):
        return ",".join(sorted(set(re.findall(r"[A-D]", s.upper()))))
    try:
        return f"{float(s):g}"
    except ValueError:
        return s


def parse_answer_value(s):
    s = s.strip()
    if s.startswith("["):
        return json.loads(s)
    return s


def valid_answer_for(qtype, value, options):
    if qtype == "scq":
        return isinstance(value, str) and re.fullmatch(r"[A-D]", value) and (not options or value in options)
    if qtype == "mcq":
        return isinstance(value, list) and len(value) >= 1 and all(isinstance(x, str) and re.fullmatch(r"[A-D]", x) for x in value)
    if qtype == "integerQuestion":
        return isinstance(value, str) and re.fullmatch(r"-?\d+(\.\d+)?", value)
    return False


def apply_edit(current, edit):
    if edit["field"] in ("question", "solution"):
        return current.replace(edit["find"], edit["replace"], 1)
    return edit["replace"]


class Check:
    def __init__(self):
        self.items = []

    def __call__(self, name, ok, detail=""):
        self.items.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    @property
    def passed(self):
        return all(i["ok"] for i in self.items)


def evaluate(rec, d, solve, det, screen, taxonomy):
    """d = judge decision for one report. Returns (route, checks, cleaned_edits)."""
    ck = Check()
    verdict, repair, edits = d["verdict"], d.get("repair"), list(d.get("edits") or [])

    ck("closed_list", verdict in taxonomy["verdicts"] and (repair is None or repair in taxonomy["repairs"]),
       f"verdict={verdict} repair={repair}")
    if verdict != "defect":
        if repair is not None or edits:
            ck("no_edit_without_defect", True, "dropped repair/edits attached to a non-defect verdict")
        if verdict == "already_fixed":
            ck("already_fixed_has_history", bool(rec.raw.get("errorHistory")), "errorHistory shows a later faculty fix"
               if rec.raw.get("errorHistory") else "no errorHistory entry - cannot be already_fixed")
        ck("confident_dismissal", d.get("confidence", 0) >= 0.6,
           f"{d.get('confidence', 0):.2f} - closing a report without a fix needs confidence >= 0.6")
        return ("no_change" if ck.passed else "faculty_review"), ck.items, []

    if not ck("repair_present", repair in taxonomy["repairs"], "defect needs a repair key"):
        return "faculty_review", ck.items, []
    spec = taxonomy["repairs"][repair]
    auto = spec["auto"]
    ck("repair_auto_allowed", auto, "taxonomy: auto=true" if auto else "taxonomy: auto=false, human must approve")

    # injection: never auto-apply on a report that tried to instruct the system
    if screen.get("injection"):
        ck("no_injection", False, "comment contains instructions to the system; human must look")

    clean = []
    for e in edits:
        f = e["field"]
        cur = rec.field_value(f) if f in ("question", "solution", "answer", "questionType", "chapter", "subject") else None
        in_scope = f in spec["fields"]
        if auto:
            ck(f"scope:{f}", in_scope, f"{repair} may touch {spec['fields'] or 'nothing'}")
        if f in ("question", "solution"):
            n = cur.count(e["find"]) if e["find"] else 0
            if not ck(f"anchor:{f}", n == 1, f"find string occurs {n}x in stored {f}" if n != 1 else "find string occurs exactly once"):
                continue
        else:
            same = norm_answer(cur) == norm_answer(e["find"]) if f == "answer" else (cur == e["find"])
            if not ck(f"anchor:{f}", same, f"stored {f} is {cur!r}, edit expects {e['find']!r}"):
                continue
        clean.append(e)

    if not auto:
        return "faculty_review", ck.items, clean
    if not clean:
        ck("has_edit", False, "auto repair proposed with no applicable edit")
        return "faculty_review", ck.items, clean

    # --- repair-specific invariants --------------------------------------
    after = {"question": rec.question_html, "solution": rec.solution_html, "answer": rec.field_value("answer"),
             "questionType": rec.qtype}
    for e in clean:
        after[e["field"]] = apply_edit(after.get(e["field"], ""), e)
    q_before, q_after = rec.question_text, linearize(after["question"])
    s_after = linearize(after["solution"])

    if repair == "spelling":
        for e in clean:
            ck("letters_only", re.sub(r"[A-Za-z\s’'-]", "", plain(e["find"])) == re.sub(r"[A-Za-z\s’'-]", "", plain(e["replace"])),
               "only letters/spaces change; no value, symbol or tag moves")
    elif repair in ("noise", "exam_reference"):
        for e in clean:
            ck("deletion_only", e["replace"].strip() == "" or e["replace"] in e["find"], "edit only removes text")
            if repair == "exam_reference":
                ck("removes_exam_tag", bool(detectors.EXAM_RE.search(plain(e["find"]))), "removed span is an exam tag")
    elif repair in ("markup_leak", "notation"):
        before_txt = rec.question_text + rec.solution_text
        after_txt = q_after + s_after
        ck("values_unchanged", _digits(before_txt) == _digits(after_txt), "same digits before and after (render-only change)")
    elif repair == "answer_form":
        for e in clean:
            ops = difflib.SequenceMatcher(None, e["find"], e["replace"], autojunk=False).get_opcodes()
            ck("additive", all(op in ("equal", "insert") for op, *_ in ops), "existing text kept; only inserts the unit/form")
    elif repair == "stem_data":
        for e in clean:
            added = e["replace"].replace(e["find"], "") if e["find"] in e["replace"] else e["replace"]
            missing = [n for n in _nums(plain(added)) if n not in _nums(rec.solution_text)]
            ck("value_from_solution", not missing, "every inserted value appears in the stored solution"
               if not missing else f"inserted value(s) {missing} not in stored solution")
    elif repair == "option_repair":
        st_b, op_b = split_options(q_before)
        st_a, op_a = split_options(q_after)
        ck("stem_unchanged", re.sub(r"\s+", "", st_b) == re.sub(r"\s+", "", st_a), "stem text identical")
        changed = [k for k in op_a if op_b.get(k, None) != op_a[k]]
        ck("options_complete", all(op_a.get(k, "").strip() for k in "ABCD"), f"after edit options={list(op_a)}")
        for k in changed:
            if k == rec.answer:
                sv = _nums((solve or {}).get("final_value", ""))
                ck(f"option_{k}_derivable", sv and sv == _nums(op_a[k]),
                   f"restored keyed option '{op_a[k]}' matches blind solve '{(solve or {}).get('final_value')}'")
            else:
                ck(f"option_{k}_derivable", False,
                   f"option {k} is a distractor; its original text cannot be recovered from the record - new content needs a human")
    elif repair in ("solution_fix", "solution_missing"):
        key = rec.answer
        target = rec.options.get(key, "") if rec.qtype == "scq" else str(key)
        tn = _nums(target)
        tail = list(_nums(" ".join(re.findall(r"\d+(?:\.\d+)?", s_after)[-4:])).keys())
        ck("solution_reaches_key", bool(tn) and any(n in tail for n in tn),
           f"new solution ends at the keyed answer ({target.strip()})")
    elif repair == "answer_key":
        e = next((x for x in clean if x["field"] == "answer"), None)
        if ck("edits_answer", e is not None, "answer_key must change the answer field"):
            new = parse_answer_value(e["replace"])
            ck("valid_for_type", valid_answer_for(rec.qtype, new, rec.options), f"{new!r} valid for {rec.qtype}")
            sa = norm_answer((solve or {}).get("answer"))
            ck("blind_solve_agrees", sa is not None and sa == norm_answer(new),
               f"blind solve={sa} proposed={norm_answer(new)}")
            sk = detectors.solution_vs_key(rec)
            sol_supports = bool(sk) and (sk.get("option_with_value") == new or
                                         (rec.qtype == "integerQuestion" and norm_answer(sk.get("solution_final")) == norm_answer(new)))
            format_only = norm_answer(new) == norm_answer(rec.answer)
            strong_solve = (solve or {}).get("confidence", 0) >= 0.85
            ck("second_signal", sol_supports or format_only or strong_solve,
               "stored solution's own result supports new key" if sol_supports else
               "format-only fix (same letters)" if format_only else
               "blind solve confidence >= 0.85" if strong_solve else "no second independent signal")
            if screen.get("claimed_option") and norm_answer(new) in [norm_answer(x) for x in screen["claimed_option"]] and screen.get("injection"):
                ck("not_comment_demand", False, "new key equals what an injected comment demanded")
    elif repair == "type_mismatch":
        newtype = after.get("questionType")
        ck("valid_type", newtype in ("scq", "mcq", "integerQuestion"), newtype)
        ans = next((x for x in clean if x["field"] == "answer"), None)
        if ck("answer_converted", ans is not None, "type change must re-encode the answer"):
            nv = parse_answer_value(ans["replace"])
            ck("answer_valid_for_new_type", valid_answer_for(newtype, nv, rec.options), f"{nv!r} for {newtype}")
            ck("blind_solve_agrees", norm_answer((solve or {}).get("answer")) == norm_answer(nv),
               f"blind solve={(solve or {}).get('answer')}")

    thr = HIGH_STAKES_MIN_CONF if repair in HIGH_STAKES else AUTO_MIN_CONF
    ck("confidence", d.get("confidence", 0) >= thr, f"{d.get('confidence', 0):.2f} vs threshold {thr}")
    return ("auto_apply" if ck.passed else "faculty_review"), ck.items, clean


PROMISE_RE = re.compile(r"\b(fixed|corrected|updated the|have changed|we changed|fix kar (diya|di)|theek kar (diya|di)|sahi kar (diya|di)|is live)\b", re.I)


def reply_consistent(reply, route):
    if not reply or len(reply) > 600:
        return False
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", reply.strip()) if s]
    if len(sentences) > 3:
        return False
    if route != "auto_apply" and PROMISE_RE.search(reply):
        return False
    return True
