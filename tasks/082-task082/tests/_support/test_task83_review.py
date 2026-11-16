"""Review-binding regressions; synthetic findings are never science approval."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import task83_review as bridge


class ReviewBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / "app"
        self.final = self.app / "final"
        self.final.mkdir(parents=True)
        (self.final / "report.md").write_text("Synthetic protocol fixture, not scientific evidence.")
        (self.final / "provenance.json").write_text(json.dumps({"sources": ["Fixture only"], "science_pass": True}))
        self.grader = bridge.grader_module()
        self.tests = bridge.TASK / "tests"
        self.env = patch.dict(os.environ)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("TASK83_REVIEW_FILE", None)
        os.environ.pop("TASK83_REVIEW_SHA256", None)
        self.pending, _ = self.grader.evaluate(self.app, self.tests)
        rubric = json.loads((self.tests / "refs.json").read_text())
        self.review = {
            "schema": "bench12.task83.independent-open-review/v2",
            "task_id": self.grader.CASE_ID, "criteria_version": self.grader.VERSION,
            **{k: self.pending[k] for k in ("artifact_manifest_sha256", "rubric_sha256", "verifier_sha256")},
            "reviewer": "SYNTHETIC PROTOCOL FIXTURE, NOT SCIENCE APPROVAL",
            "status": "PASS",
            "criteria": {k: {"status": "PASS", "finding": "Fixture only", "evidence": ["report.md"]}
                         for k in rubric["criteria"]}}

    def evaluate_review(self):
        path = self.root / "review.json"
        path.write_text(json.dumps(self.review))
        os.environ.update(TASK83_REVIEW_FILE=str(path), TASK83_REVIEW_SHA256=hashlib.sha256(path.read_bytes()).hexdigest())
        return self.grader.evaluate(self.app, self.tests)

    def test_self_claim_remains_pending(self):
        self.assertEqual((self.pending["status"], self.pending["reward"], self.pending["science_validated"]),
                         ("REVIEW_REQUIRED", 0, False))

    def test_review_statuses(self):
        for status, criterion, reward in [("PASS", "PASS", 1), ("FAIL", "FAIL", 0),
                                          ("REVIEW_REQUIRED", "UNRESOLVED", 0)]:
            with self.subTest(status=status):
                self.review["status"] = status
                for finding in self.review["criteria"].values():
                    finding["status"] = criterion
                report, rc = self.evaluate_review()
                self.assertEqual((rc, report["status"], report["reward"]), (0, status, reward))

    def test_changed_research_cannot_reuse_review(self):
        (self.final / "report.md").write_text("Changed research record")
        report, rc = self.evaluate_review()
        self.assertEqual((rc, report["status"]), (2, "ENV_INVALID"))
        self.assertNotIn("reward", report)

    def test_missing_criterion_or_fake_evidence_cannot_pass(self):
        key = next(iter(self.review["criteria"]))
        self.review["criteria"][key]["evidence"] = ["nonexistent.out"]
        self.assertEqual(self.evaluate_review()[1], 2)
        del self.review["criteria"][key]
        self.assertEqual(self.evaluate_review()[1], 2)

    def test_operator_hash_and_symlink_gate(self):
        path = self.root / "review.json"
        path.write_text(json.dumps(self.review))
        with self.assertRaises(ValueError):
            bridge.approved_review(path, "0" * 64)
        alias = self.root / "alias.json"
        alias.symlink_to(path)
        with self.assertRaises(ValueError):
            bridge.approved_review(alias, hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
