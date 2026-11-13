"""Compare provider outputs without treating the Claude replay baseline as ground truth."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH = ROOT / "data" / "ground_truth.json"


def _read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _metric(value, count, reason=None):
    return {"value": value, "n": count, "reason": reason}


def _quality_metrics(groq, labels):
    by_id = {row["reportId"]: row for row in groq}
    pairs = [(by_id[row["reportId"]], row) for row in labels if row.get("reportId") in by_id]
    classification = [output["verdict"] == label["verdict"] for output, label in pairs if "verdict" in label]
    answer = [
        output.get("edit", {}).get("replace") == label["answer"]
        for output, label in pairs if label.get("answer") is not None
    ]
    repair = [
        output.get("repair") == label["repair"]
        for output, label in pairs if label.get("repair") is not None
    ]
    binary = [(output["verdict"] == "defect", label["verdict"] == "defect")
              for output, label in pairs if "verdict" in label]
    fp = sum(predicted and not actual for predicted, actual in binary)
    tn = sum(not predicted and not actual for predicted, actual in binary)
    fn = sum(not predicted and actual for predicted, actual in binary)
    tp = sum(predicted and actual for predicted, actual in binary)
    applied = [
        label["auto_apply_correct"] for output, label in pairs
        if output.get("route") == "auto_apply" and isinstance(label.get("auto_apply_correct"), bool)
    ]
    return {
        "classification_accuracy": _metric(sum(classification) / len(classification) if classification else None,
                                            len(classification), None if classification else "verified verdict labels unavailable"),
        "answer_key_accuracy": _metric(sum(answer) / len(answer) if answer else None,
                                       len(answer), None if answer else "verified answer labels unavailable"),
        "repair_correctness": _metric(sum(repair) / len(repair) if repair else None,
                                      len(repair), None if repair else "verified repair labels unavailable"),
        "false_positive_rate": _metric(fp / (fp + tn) if fp + tn else None, fp + tn,
                                       None if fp + tn else "verified non-defect labels unavailable"),
        "false_negative_rate": _metric(fn / (fn + tp) if fn + tp else None, fn + tp,
                                       None if fn + tp else "verified defect labels unavailable"),
        "auto_apply_precision": _metric(sum(applied) / len(applied) if applied else None, len(applied),
                                        None if applied else "verified auto-apply outcomes unavailable"),
    }


def evaluate(groq_results=None, baseline_results=None, groq_log=None, baseline_log=None, ground_truth=None):
    groq_results = Path(groq_results or ROOT / "results_groq.json")
    baseline_results = Path(baseline_results or ROOT / "results.json")
    groq_log = Path(groq_log or ROOT / "run_log_groq.json")
    baseline_log = Path(baseline_log or ROOT / "run_log.json")
    baseline = _read(baseline_results, [])
    groq = _read(groq_results, [])
    groq_run = _read(groq_log, {})
    baseline_run = _read(baseline_log, {})
    labels_path = Path(ground_truth) if ground_truth else GROUND_TRUTH
    labels_doc = _read(labels_path, {})
    labels = labels_doc.get("results", []) if isinstance(labels_doc, dict) else []
    baseline_by_id = {row["reportId"]: row for row in baseline}
    groq_by_id = {row["reportId"]: row for row in groq}
    shared = [(groq_by_id[key], baseline_by_id[key]) for key in groq_by_id.keys() & baseline_by_id.keys()]

    def agreement(field, normalize=lambda value: value):
        compared = [(normalize(left.get(field)), normalize(right.get(field))) for left, right in shared]
        count = sum(left == right for left, right in compared)
        return {"agreement": count / len(compared) if compared else None, "matches": count, "compared": len(compared)}

    def answer_edit(row):
        edit = row.get("edit") or {}
        return edit.get("replace") if edit.get("field") == "answer" else None

    route_counts = Counter(row.get("route") for row in groq)
    count = len(groq)
    calls = groq_run.get("calls", [])
    errors = groq_run.get("api_errors", [])
    failed_calls = sum(call.get("status") in ("error", "invalid_json") for call in calls)
    live_calls = [call for call in calls if call.get("mode") == "live"]
    token_data = groq_run.get("tokens", {})
    return {
        "schema_version": 1,
        "status": "complete" if groq_results.exists() else "not_run",
        "baseline": {
            "file": baseline_results.name,
            "model": baseline_run.get("model", "claude-opus-5-5"),
            "execution": baseline_run.get("mode", "replay"),
            "description": "Original Claude response recordings; not verified ground truth or live API output.",
        },
        "groq": {
            "file": groq_results.name,
            "present": groq_results.exists(),
            "provider": groq_run.get("provider", "groq"),
            "model": groq_run.get("model"),
            "execution": groq_run.get("mode"),
            "reports": count,
        },
        "ground_truth": {
            "file": labels_path.name if labels_path.exists() else None,
            "verified_labels": len(labels),
            "note": "Claude agreement is reported separately and is not scored as ground-truth correctness.",
        },
        "quality_metrics": _quality_metrics(groq, labels),
        "model_agreement": {
            "shared_reports": len(shared),
            "verdict": agreement("verdict"),
            "repair": agreement("repair"),
            "route": agreement("route"),
            "answer_edit": {
                "agreement": sum(answer_edit(left) == answer_edit(right) for left, right in shared) / len(shared)
                if shared else None,
                "matches": sum(answer_edit(left) == answer_edit(right) for left, right in shared),
                "compared": len(shared),
            },
        },
        "operational_metrics": {
            "reports_processed": count,
            "faculty_review_rate": route_counts["faculty_review"] / count if count else None,
            "no_change_rate": route_counts["no_change"] / count if count else None,
            "auto_apply_rate": route_counts["auto_apply"] / count if count else None,
            "api_failures": failed_calls + max(0, len(errors) - failed_calls),
            "input_tokens": token_data.get("input"),
            "output_tokens": token_data.get("output"),
            "estimated_cost_usd": groq_run.get("estimated_cost_usd"),
            "average_latency_ms": groq_run.get("average_latency_ms"),
            "live_api_responses": sum(call.get("status") == "response" for call in live_calls),
        },
        "limitations": [
            "Accuracy, false-positive/negative rates, repair correctness, and auto-apply precision require independently verified labels.",
            "The original replay outputs are a comparison baseline, not truth labels.",
            "Estimated cost remains null unless verified per-million-token prices are configured.",
        ],
    }


def main():
    report = evaluate()
    (ROOT / "evaluation_groq_vs_claude.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], "shared_reports": report["model_agreement"]["shared_reports"],
                      "ground_truth_labels": report["ground_truth"]["verified_labels"]}, indent=2))


if __name__ == "__main__":
    main()
