"""Regression tests for candidate-addressed Case 08 science reviews."""
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).parent
SCIENCE = PACKAGE / "science"
FIXTURE = SCIENCE / "evidence/historical-3968344-fixture/submission"
SPEC = importlib.util.spec_from_file_location("review_status", SCIENCE / "review_status.py")
review_status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review_status)


class ReviewClosureTests(unittest.TestCase):
    def test_manifest_selects_only_its_candidate_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests = Path(tmp)
            candidate = {"submission/a": {"sha256": "a" * 64, "bytes": 1}}
            addressed_dir = tests / "author-reviews"
            addressed_dir.mkdir()
            addressed = addressed_dir / (review_status.canonical_sha(candidate) + ".json")
            addressed.write_text("{}", encoding="utf-8")
            (tests / "author-review.json").write_text("{}", encoding="utf-8")
            self.assertEqual(review_status.review_record_path(tests, candidate), addressed)
            changed = {"submission/a": {"sha256": "b" * 64, "bytes": 1}}
            self.assertEqual(review_status.review_record_path(tests, changed), tests / "author-review.json")

    def test_candidate_review_directory_cannot_be_a_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests = Path(tmp)
            target = tests / "target"
            target.mkdir()
            (tests / "author-reviews").symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "directory is a symlink"):
                review_status.review_record_path(tests, {})

    def test_fail_requires_a_failed_criterion(self):
        criteria = {name: {"status": "PASS", "evidence": "reviewed"}
                    for name in review_status.CRITERIA}
        with self.assertRaisesRegex(RuntimeError, "at least one failed criterion"):
            review_status.validate_criterion_statuses("FAIL", criteria)
        criteria[next(iter(criteria))]["status"] = "FAIL"
        review_status.validate_criterion_statuses("FAIL", criteria)

    def test_execution_binding_rejects_candidate_native_accounting_and_source_changes(self):
        candidate = {"submission/a": {"sha256": "a" * 64, "bytes": 1}}
        record = {"trusted_job_id": "4082781", "native_evidence_sha256": "b" * 64,
                  "accounting_evidence_sha256": "c" * 64}
        evidence = {
            "schema": "case08-verified-execution/v1", "job_id": "4082781",
            "review_status": "independently-reviewed",
            "candidate_manifest_sha256": review_status.canonical_sha(candidate),
            "source_manifest_sha256": "d" * 64,
            "native_evidence_sha256": record["native_evidence_sha256"],
            "accounting_evidence_sha256": record["accounting_evidence_sha256"],
            "execution_sources": {"runner.py": "e" * 64, "source-manifest.json": "d" * 64},
        }
        for changed in (
            {**evidence, "candidate_manifest_sha256": "f" * 64},
            {**evidence, "native_evidence_sha256": "f" * 64},
            {**evidence, "accounting_evidence_sha256": "f" * 64},
            {**evidence, "source_manifest_sha256": "f" * 64},
            {**evidence, "job_id": "4082782"},
        ):
            with self.assertRaises(RuntimeError):
                review_status.validate_execution_binding(changed, candidate, "d" * 64, record)

    def run_fixture(self, *, remove_reviews=False, tamper=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        app, tests = root / "app", root / "tests"
        shutil.copytree(FIXTURE, app / "submission")
        shutil.copytree(PACKAGE.parent / "environment/assets", app / "environment/assets")
        shutil.copytree(SCIENCE, tests)
        if remove_reviews:
            (tests / "author-review.json").unlink()
            shutil.rmtree(tests / "author-reviews", ignore_errors=True)
        if tamper == "candidate":
            (app / "submission/extra-review-output.txt").write_text("unreviewed", encoding="utf-8")
        elif tamper == "native":
            (app / "submission/runs/B-dt1fs/unreviewed-native.txt").write_text("unreviewed", encoding="utf-8")
        elif tamper == "source":
            path = tests / "review_status.py"
            path.write_text(path.read_text(encoding="utf-8") + "# changed scoring source\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code = review_status.run_case(app, tests, root / "logs")
        report = json.loads((root / "logs/report.json").read_text(encoding="utf-8"))
        return code, report

    def test_missing_review_is_pending_with_null_reward(self):
        code, report = self.run_fixture(remove_reviews=True)
        self.assertEqual(0, code)
        self.assertEqual("REVIEW_REQUIRED", report["status"])
        self.assertIsNone(report["reward"])

    def test_unreviewed_candidate_or_native_bytes_cannot_receive_reward(self):
        for tamper in ("candidate", "native"):
            with self.subTest(tamper=tamper):
                code, report = self.run_fixture(tamper=tamper)
                self.assertNotEqual("PASS", report["status"])
                self.assertNotEqual(1, report["reward"])
                if tamper == "candidate":
                    self.assertEqual(0, code)
                    self.assertEqual("REVIEW_REQUIRED", report["status"])
                    self.assertIsNone(report["reward"])

    def test_changed_scoring_source_cannot_use_review(self):
        code, report = self.run_fixture(tamper="source")
        self.assertEqual(2, code)
        self.assertEqual("INFRA_ERROR", report["status"])
        self.assertIsNone(report["reward"])

    def test_historical_3968344_review_rebinding_preserves_pass(self):
        code, report = self.run_fixture()
        self.assertEqual(0, code)
        self.assertEqual("PASS", report["status"])
        self.assertEqual(1, report["reward"])
        self.assertEqual("3968344", report["scientific_review"]["trusted_job_id"])


if __name__ == "__main__":
    unittest.main()
