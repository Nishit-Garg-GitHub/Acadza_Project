import json
import tempfile
import unittest
from pathlib import Path

from tools.evaluate_groq import evaluate


class EvaluationReport(unittest.TestCase):
    def test_missing_groq_output_is_not_run_and_metrics_are_explicitly_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "results.json"
            baseline.write_text(json.dumps([{"reportId": "R1", "verdict": "defect"}]), encoding="utf-8")
            report = evaluate(
                groq_results=root / "results_groq.json",
                baseline_results=baseline,
                groq_log=root / "run_log_groq.json",
                baseline_log=root / "run_log.json",
                ground_truth=root / "ground_truth.json",
            )
        self.assertEqual(report["status"], "not_run")
        self.assertEqual(report["model_agreement"]["shared_reports"], 0)
        self.assertIsNone(report["quality_metrics"]["classification_accuracy"]["value"])
        self.assertEqual(report["ground_truth"]["verified_labels"], 0)

    def test_agreement_is_separate_from_ground_truth_accuracy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "results.json"
            groq = root / "results_groq.json"
            baseline.write_text(json.dumps([{
                "reportId": "R1", "verdict": "defect", "repair": "answer_key", "route": "auto_apply",
                "edit": {"field": "answer", "replace": "B"},
            }]), encoding="utf-8")
            groq.write_text(baseline.read_text(encoding="utf-8"), encoding="utf-8")
            labels_path = root / "ground_truth.json"
            labels_path.write_text(json.dumps({"results": [{
                "reportId": "R1", "verdict": "defect", "repair": "answer_key",
                "answer": "B", "auto_apply_correct": True,
            }]}), encoding="utf-8")
            report = evaluate(
                groq_results=groq,
                baseline_results=baseline,
                groq_log=root / "run_log_groq.json",
                baseline_log=root / "run_log.json",
                ground_truth=labels_path,
            )
        self.assertEqual(report["model_agreement"]["verdict"]["agreement"], 1)
        self.assertEqual(report["quality_metrics"]["classification_accuracy"]["value"], 1)
        self.assertEqual(report["quality_metrics"]["auto_apply_precision"]["value"], 1)
        self.assertEqual(report["ground_truth"]["verified_labels"], 1)


if __name__ == "__main__":
    unittest.main()
