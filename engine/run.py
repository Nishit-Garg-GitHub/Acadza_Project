"""Report -> Fix pipeline.

    python -m engine.run                            # original Claude replay (no key, no spend)
    python -m engine.run --live                     # call the selected API provider
    python -m engine.run --live --record            # save provider recordings separately
    python -m engine.run --replay-set groq          # replay a Groq recording set

Stages per question (duplicate reports are grouped first, so N reports on one question cost one judge call):
  1 detectors (code)      2 screen comments (code)     3 blind solve (LLM)
  4 judge (LLM)           5 guards (code) -> route     6 reply check / rewrite (LLM only if a guard changed the route)
Outputs: results.json, findings_unreported.json, console/data.json, data/questions.patched.json, run_log.json
"""
import argparse
import copy
import json
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone

from . import comments, detectors, guards, prompts
from . import llm
from .llm import Unavailable
from .records import ROOT, load_all

TIER = {  # urgency weight: how much harm per hour the defect does, and to whom
    "answer_key": (100, "Grading is wrong: every attempt is mis-marked"),
    "type_mismatch": (95, "Grading is wrong: wrong marking scheme / negative marks"),
    "unsound": (90, "No correct option: every attempt is mis-marked"),
    "identical_options": (85, "Two options identical: correct students can be marked wrong"),
    "option_repair": (80, "Option missing/blank: question can't be answered fairly"),
    "stem_data": (75, "Data missing: question can't be solved as written"),
    "diagram": (75, "Figure missing: question can't be solved as written"),
    "wrong_question": (70, "Solution belongs to another question"),
    "solution_fix": (55, "Solution teaches a wrong step"),
    "solution_missing": (50, "No usable solution"),
    "answer_form": (45, "Unit not stated: correct students may type the wrong number"),
    "wrong_chapter": (30, "Mis-filed: shows up in the wrong practice sets"),
    "syllabus": (25, "Syllabus claim: needs faculty confirmation"),
    "notation": (20, "Notation glitch"),
    "markup_leak": (20, "Raw markup visible"),
    "spelling": (12, "Spelling"),
    "noise": (10, "Stray text"),
    "exam_reference": (10, "Exam tag in text"),
}
NON_DEFECT_WEIGHT = 5


def urgency(repair, verdict, n_reports, route):
    base, why = TIER.get(repair, (NON_DEFECT_WEIGHT, "No content defect")) if verdict == "defect" else (NON_DEFECT_WEIGHT, "No content defect")
    score = base + 6 * min(n_reports - 1, 4)  # more reporters ~ more students hitting it
    return score, why


# ---------------------------------------------------------------- fallbacks (LLM unavailable)
def fallback_judge(rec, det, reports, screens):
    """Rule-based triage used only if the judge call fails. Never auto-applies (confidence 0.4)."""
    codes = {f["code"]: f for f in det}
    out = []
    for r in reports:
        s = screens[r["reportId"]]
        v, rep = "no_error", None
        if s["gibberish"]:
            v = "not_actionable"
        elif "display" in s["hints"]:
            v = "display_issue"
        elif "app" in s["hints"]:
            v = "app_issue"
        elif "language" in s["hints"]:
            v = "language_mode"
        elif detectors.history_after(rec, r["reportedAt"]):
            v = "already_fixed"
        elif codes:
            top = next((f for f in det if f["severity"] == "high" and f["suggests"]), None)
            if top:
                v, rep = "defect", top["suggests"]
        out.append({"reportId": r["reportId"], "verdict": v, "repair": rep, "edits": [], "confidence": 0.4,
                    "evidence": "LLM judge unavailable; rule-based triage from detectors: "
                                + ("; ".join(f["detail"] for f in det) or "no detector findings"),
                    "student_reply": ""})
    return {"question_assessment": "Judge unavailable - rule-based fallback.", "reports": out, "other_findings": []}


def template_reply(verdict, route, register, evidence=""):
    hi = register == "hinglish"
    if route == "faculty_review" and verdict != "defect":
        return ("Thanks for reporting - ek faculty member is question ko check kar rahe hain." if hi
                else "Thanks for reporting this - a faculty member is checking the question now.")
    if verdict == "defect" and route == "auto_apply":
        return ("Aap sahi the - is question me galti thi aur ab theek ho gayi hai. Report karne ke liye thanks!" if hi
                else "You were right - this question had an error and it's now corrected. Thanks for reporting it.")
    if verdict == "defect":
        return ("Thanks! Aapne sahi jagah dhyan diya - ek faculty member ise abhi check kar rahe hain." if hi
                else "Thanks for flagging this - you spotted a real problem, and a faculty member is checking it now.")
    if verdict == "no_error":
        return ("Humne check kiya: question aur answer key dono sahi hain. Solution ek baar step-by-step dekh lo." if hi
                else "We checked this carefully and the question and answer key are correct. Have another look at the solution step by step.")
    if verdict == "display_issue":
        return "Thanks - the question content is fine, but we've passed the display problem to our app team."
    if verdict == "app_issue":
        return "Thanks - that sounds like an app problem rather than this question. We've passed it to the app team."
    if verdict == "language_mode":
        return ("Abhi yeh question sirf English me available hai. Hindi version ki request note kar li hai." if hi
                else "This question is only available in English right now; we've noted your language request.")
    if verdict == "already_fixed":
        return "Thanks - this was already corrected after you reported it. Please reload the question."
    return "Thanks for reporting. We couldn't find a problem with this question - if something still looks wrong, tell us what you saw."


# ---------------------------------------------------------------- pipeline
def run(mode="replay", record=False, only=None, output_suffix=None, replay_set="claude"):
    recs, reports, taxonomy = load_all()
    replay_dirs = {
        "claude": llm.REPLAY_DIR,
        "groq": llm.GROQ_REPLAY_DIR,
        "anthropic": llm.ANTHROPIC_REPLAY_DIR,
    }
    if replay_set not in replay_dirs:
        raise ValueError(f"unsupported replay set: {replay_set}")
    replay_dir = replay_dirs[replay_set]
    if mode == "live" and record:
        replay_dir = replay_dirs[llm.PROVIDER]
    client = llm.LLM(mode, record, replay_dir=replay_dir)
    suffix = output_suffix or (client.provider if mode == "live" else "replay")
    execution_provider = client.provider if mode == "live" else "replay"
    execution_model = client.model if mode == "live" else (
        "Claude Opus 5.5 (recorded)" if replay_set == "claude" else f"{replay_set} recordings"
    )

    def output_path(name):
        if not suffix:
            return ROOT / name
        if name == "data/questions.patched.json":
            return ROOT / "data" / f"questions.patched.{suffix}.json"
        if name == "console/data.json":
            return ROOT / "console" / f"data.{suffix}.json"
        stem, extension = name.rsplit(".", 1)
        return ROOT / f"{stem}_{suffix}.{extension}"

    screens = {r["reportId"]: comments.screen(r["comment"]) for r in reports}
    groups = OrderedDict()
    for r in sorted(reports, key=lambda r: r["reportedAt"]):
        groups.setdefault(r["questionId"], []).append(r)
    qids = list(groups) + [q for q in recs if q not in groups]  # reported first, then sweep
    if only:
        qids = [q for q in qids if q in only]

    jsys = prompts.judge_system(taxonomy)
    jschema = prompts.judge_schema(taxonomy)
    results, cases, sweep, notes = {}, [], [], []
    patched = {qid: copy.deepcopy(r.raw) for qid, r in recs.items()}

    for qid in qids:
        rec, reps = recs[qid], groups.get(qid, [])
        det = detectors.run(rec)
        # 3. blind solve
        try:
            solve = client.json("solver", qid, prompts.SOLVER_SYSTEM, prompts.solver_user(rec), prompts.SOLVER_SCHEMA, effort="high")
        except Unavailable as e:
            solve, _ = None, notes.append(str(e))
        # 4. judge
        juser = prompts.judge_user(rec, det, solve, reps, screens)
        try:
            judge = client.json("judge", qid, jsys, juser, jschema, effort="high")
            judge_src = "llm"
        except Unavailable as e:
            notes.append(str(e))
            judge, judge_src = fallback_judge(rec, det, reps, screens), "fallback"
        by_id = {d["reportId"]: d for d in judge.get("reports", [])}

        case_reports = []
        for r in reps:
            d = by_id.get(r["reportId"]) or fallback_judge(rec, det, [r], screens)["reports"][0]
            if d["verdict"] != "defect":
                d = {**d, "repair": None, "edits": []}
            route, checks, edits = guards.evaluate(rec, d, solve, det, screens[r["reportId"]], taxonomy)
            reply, reply_src = d.get("student_reply", ""), "judge"
            if not guards.reply_consistent(reply, route):
                decision = {"verdict": d["verdict"], "repair": d.get("repair"), "route": route, "evidence": d["evidence"]}
                try:
                    reply = client.json("reply", r["reportId"], prompts.REPLY_SYSTEM,
                                     prompts.reply_user(r, decision, screens[r["reportId"]]["register"]),
                                     prompts.REPLY_SCHEMA, effort="low", max_tokens=2000)["student_reply"]
                    reply_src = "reply-llm"
                except Unavailable:
                    reply, reply_src = template_reply(d["verdict"], route, screens[r["reportId"]]["register"]), "template"
                if not guards.reply_consistent(reply, route):
                    reply, reply_src = template_reply(d["verdict"], route, screens[r["reportId"]]["register"]), "template"
            res = {
                "reportId": r["reportId"], "questionId": qid, "verdict": d["verdict"],
                "repair": d.get("repair") if d["verdict"] == "defect" else None,
                "edit": edits[0] if edits else None,
                "route": route, "confidence": round(float(d.get("confidence", 0)), 2),
                "evidence": d["evidence"], "student_reply": reply,
            }
            if len(edits) > 1:
                res["extra_edits"] = edits[1:]
            results[r["reportId"]] = res
            case_reports.append({"report": r, "screen": screens[r["reportId"]], "result": res,
                                 "checks": checks, "reply_source": reply_src})

        # apply auto edits once per question
        applied = []
        auto = [cr["result"] for cr in case_reports if cr["result"]["route"] == "auto_apply"]
        if auto:
            body = patched[qid][rec.qtype]
            seen = set()
            for res in auto:
                for e in [res["edit"]] + res.get("extra_edits", []):
                    key = json.dumps(e, sort_keys=True)
                    if key in seen:
                        continue
                    seen.add(key)
                    if e["field"] in ("question", "solution"):
                        body[e["field"]] = body[e["field"]].replace(e["find"], e["replace"], 1)
                    elif e["field"] == "answer":
                        body["answer"] = guards.parse_answer_value(e["replace"])
                    elif e["field"] == "questionType":
                        patched[qid][e["replace"]] = patched[qid].pop(rec.qtype)
                        patched[qid]["questionType"] = e["replace"]
                        body = patched[qid][e["replace"]]
                    else:
                        patched[qid][e["field"]] = e["replace"]
                    applied.append(e)
            patched[qid].setdefault("errorHistory", []).append({
                "type": "auto_fix", "actor": "triage-engine", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "note": ", ".join(sorted({res["repair"] for res in auto})) + " via " + ", ".join(res["reportId"] for res in auto)})

        # other findings (bonus: defects nobody reported)
        found = []
        for f in judge.get("other_findings", []):
            d = {"verdict": "defect", "repair": f["repair"], "edits": f["edits"], "confidence": f["confidence"], "evidence": f["evidence"]}
            route, checks, edits = guards.evaluate(rec, d, solve, det, {}, taxonomy)
            route = "faculty_review" if route == "auto_apply" else route  # unreported findings: propose, don't auto-apply
            found.append({"questionId": qid, "repair": f["repair"], "edits": edits, "confidence": f["confidence"],
                          "evidence": f["evidence"], "route": route, "checks": checks})
        sweep += found

        # case summary for the console
        if case_reports:
            lead = max(case_reports, key=lambda c: urgency(c["result"]["repair"], c["result"]["verdict"], 1, c["result"]["route"])[0])
            lr = lead["result"]
            score, why = urgency(lr["repair"], lr["verdict"], len(case_reports), lr["route"])
            lane = ("decide" if any(c["result"]["route"] == "faculty_review" for c in case_reports)
                    else "spotcheck" if any(c["result"]["route"] == "auto_apply" for c in case_reports)
                    else "sweep" if found else "replies")
            if found:  # an unreported finding can outrank the reported issue (e.g. a wrong solution behind a no_error report)
                fs, fwhy = max((TIER.get(f["repair"], (0, ""))[0] - 10, TIER.get(f["repair"], (0, ""))[1]) for f in found)
                if fs > score:
                    score, why = fs, fwhy + " (found by sweep)"
        else:
            top = max(found, key=lambda f: TIER.get(f["repair"], (0, ""))[0], default=None)
            if not top:
                continue
            score, why = TIER.get(top["repair"], (5, ""))
            score, lane = score - 10, "sweep"  # nobody reported it yet: below reported cases of the same tier
        cases.append({
            "questionId": qid, "lane": lane, "urgency": score, "urgencyReason": why,
            "firstReportedAt": reps[0]["reportedAt"] if reps else None,
            "assessment": judge.get("question_assessment", ""), "judgeSource": judge_src,
            "solve": solve, "detectors": det, "reports": case_reports, "findings": found, "applied": applied,
        })

    # ---------------------------------------------------------------- outputs
    ordered = [results[r["reportId"]] for r in reports if r["reportId"] in results]
    output_path("results.json").write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding="utf-8")
    output_path("findings_unreported.json").write_text(json.dumps(
        [f for f in sweep if not any(c["questionId"] == f["questionId"] and c["reports"] for c in cases)] +
        [f for f in sweep if any(c["questionId"] == f["questionId"] and c["reports"] for c in cases)],
        ensure_ascii=False, indent=1), encoding="utf-8")
    output_path("data/questions.patched.json").write_text(json.dumps(list(patched.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    lane_order = {"decide": 0, "spotcheck": 1, "sweep": 2, "replies": 3}
    cases.sort(key=lambda c: (lane_order[c["lane"]], -c["urgency"], c["firstReportedAt"] or "9"))
    console = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode, "provider": execution_provider,
        "model": execution_model,
        "execution": {
            "provider": execution_provider,
            "model": execution_model,
            "mode": mode,
            "status": ("failed" if not client.calls else "partial" if client.errors else "success")
            if mode == "live" else "replay",
            "last_successful_at": next((c["at"] for c in reversed(client.log) if c.get("status") == "response"), None)
            if mode == "live" and not client.errors else None,
            "api_errors": client.errors,
        },
        "promptVersions": [prompts.SOLVER_VERSION, prompts.JUDGE_VERSION, prompts.REPLY_VERSION],
        "taxonomy": taxonomy,
        "questions": {qid: {
            "id": qid, "subject": r.subject, "chapter": r.chapter, "type": r.qtype, "level": r.raw.get("level"),
            "stem": r.stem, "options": r.options,
            "question": r.question_html, "solution": r.solution_html, "answer": r.answer,
            "errorHistory": r.raw.get("errorHistory") or [], "updatedAt": r.raw.get("updatedAt")}
            for qid, r in recs.items()},
        "cases": cases,
    }
    output_path("console/data.json").write_text(json.dumps(console, ensure_ascii=False), encoding="utf-8")
    live_calls = [c for c in client.log if c.get("mode") == "live"]
    call_costs = [c.get("estimated_cost_usd") for c in live_calls]
    estimated_cost = sum(call_costs) if live_calls and all(cost is not None for cost in call_costs) else None
    log = {
        "mode": mode, "provider": execution_provider,
        "model": execution_model, "llm_calls_live": client.calls, "calls": client.log,
        "notes": notes, "api_errors": client.errors,
        "tokens": {
            "input": sum(c.get("input_tokens") or 0 for c in live_calls),
            "output": sum(c.get("output_tokens") or 0 for c in live_calls),
        },
        "average_latency_ms": round(sum(c.get("latency_ms", 0) for c in live_calls) / len(live_calls))
        if live_calls else None,
        "estimated_cost_usd": round(estimated_cost, 8) if estimated_cost is not None else None,
    }
    output_path("run_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")

    # summary
    from collections import Counter
    print(f"mode={mode} reports={len(ordered)} questions={len(qids)} cases={len(cases)} unreported_findings={len(sweep)}")
    print("routes  :", dict(Counter(r["route"] for r in ordered)))
    print("verdicts:", dict(Counter(r["verdict"] for r in ordered)))
    if notes:
        print(f"{len(notes)} stage(s) used safe fallback:", *notes[:8], sep="\n  ")
    return ordered


def smoke_test():
    """Make one real solver request and report the provider/model actually returned."""
    records, _, _ = load_all()
    qid, rec = next(iter(records.items()))
    client = llm.LLM("live")
    client.json("solver", qid, prompts.SOLVER_SYSTEM, prompts.solver_user(rec), prompts.SOLVER_SCHEMA,
                effort="high", max_tokens=4000)
    response = next((entry for entry in reversed(client.log) if entry.get("status") == "response"), None)
    if not response:
        raise RuntimeError("provider returned no successful response")
    print(json.dumps({
        "status": "success",
        "provider": response["provider"],
        "requested_model": client.model,
        "returned_model": response["model"],
        "input_tokens": response.get("input_tokens"),
        "output_tokens": response.get("output_tokens"),
        "latency_ms": response.get("latency_ms"),
    }, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--smoke-test", action="store_true", help="make one provider request without running evaluation")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--output-suffix", help="write outputs to suffixed files without replacing baseline data")
    ap.add_argument("--replay-set", choices=("claude", "groq", "anthropic"), default="claude")
    a = ap.parse_args(argv)
    if a.smoke_test:
        smoke_test()
        return
    run("live" if a.live else "replay", a.record, set(a.only) if a.only else None,
        a.output_suffix, a.replay_set)


if __name__ == "__main__":
    sys.exit(main())
