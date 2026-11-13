import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from engine.records import load_all


class ReportApi(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = TestClient(create_app(Path(self.temp.name) / "test.sqlite3"))
        self.question_id = next(iter(load_all()[0]))

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def submit(self, comment):
        return self.client.post("/reports", json={
            "question_id": self.question_id, "comment": comment, "source": "test",
        })

    def test_health_and_report_input_validation(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertIn("provider", health.json())
        self.assertNotIn("api_key", json.dumps(health.json()).lower().replace("api_key_configured", ""))
        self.assertEqual(self.client.post("/reports", json={
            "question_id": "not-a-question", "comment": "Wrong answer",
        }).status_code, 422)
        self.assertEqual(self.client.post("/reports", json={
            "question_id": self.question_id, "comment": "  ",
        }).status_code, 422)

    def test_duplicate_reports_are_idempotent_and_listable(self):
        created = self.submit("The answer is wrong").json()
        duplicate = self.submit("  THE answer   is wrong  ").json()
        self.assertFalse(created["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(created["id"], duplicate["id"])
        self.assertEqual(len(self.client.get("/reports").json()), 1)
        self.assertEqual(self.client.get(f"/reports/{created['id']}").status_code, 200)

    def test_processing_and_faculty_actions_persist_without_publishing(self):
        report = self.submit("I think this question has a mistake").json()
        process = self.client.post(f"/reports/{report['id']}/process")
        self.assertEqual(process.status_code, 202)
        decision = self.client.get(f"/decisions/{report['id']}").json()
        self.assertIn(decision["status"], ("awaiting_review", "pending"))
        if decision["status"] == "pending":
            self.fail("background processing did not persist a decision")
        self.assertIn(decision["execution_mode"], ("replay", "live"))

        approved = self.client.post(
            f"/decisions/{decision['id']}/approve",
            json={"reviewer": "Faculty", "note": "Reviewed"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertFalse(approved.json()["published"])
        repeated = self.client.post(
            f"/decisions/{decision['id']}/approve",
            json={"reviewer": "Faculty"},
        )
        self.assertTrue(repeated.json()["duplicate"])
        self.assertEqual(self.client.post(
            f"/decisions/{decision['id']}/reject",
            json={"reviewer": "Faculty"},
        ).status_code, 409)
        audit = self.client.get("/audit").json()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["action"], "approve")
        self.assertEqual(self.client.post(f"/reports/{report['id']}/process").json()["duplicate"], True)

    def test_rejection_is_audited(self):
        report = self.submit("The option is blank").json()
        self.client.post(f"/reports/{report['id']}/process")
        decision = self.client.get(f"/decisions/{report['id']}").json()
        rejected = self.client.post(
            f"/decisions/{decision['id']}/reject",
            json={"reviewer": "Faculty", "note": "Not a defect"},
        )
        self.assertEqual(rejected.json()["status"], "rejected")
        self.assertEqual(self.client.get("/audit").json()[0]["action"], "reject")


if __name__ == "__main__":
    unittest.main()
