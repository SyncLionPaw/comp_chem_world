#!/usr/bin/env python3
"""Offline regression checks for Task 77's scientific verifier."""
import copy
import csv
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
TASK = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location("task77_verifier", TASK / "tests/verify.py")
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)
REFS = json.loads((TASK / "tests/refs.json").read_text(encoding="utf-8"))


def valid_app(root, molecule_transform=None, source_transform=None):
    final = root / "final"
    final.mkdir(parents=True)
    samples = copy.deepcopy(REFS["per_item"])
    for group in samples.values():
        for item in group:
            if molecule_transform:
                item["mol"] = molecule_transform(item["mol"])
    (final / "provenance.json").write_text(
        json.dumps({"samples": samples}), encoding="utf-8")

    with (final / "statistics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=verifier.COLUMNS)
        writer.writeheader()
        for method in verifier.GEOMETRY:
            kernel, basis = method.split("|")
            for quantity in verifier.QUANTITIES:
                group = f"{method}|{quantity}"
                values = verifier.moments([item["err"] for item in samples[group]])
                source = "SI Table 14" if method.startswith("sTDA") else "SI Table 3"
                if source_transform:
                    source = source_transform(source, method, quantity)
                writer.writerow(dict(row_type="recomputed-from-raw", kernel=kernel,
                    basis=basis, quantity=quantity, **dict(zip(verifier.STATS, values)),
                    source_table=source))
        for method in verifier.ENERGY:
            kernel, basis = method.split("|")
            for quantity, table in verifier.ENERGY_SOURCES.items():
                values = REFS["kernel_energy_verify_only"][quantity]["values"][method]
                source = f"SI Table {table}"
                if source_transform:
                    source = source_transform(source, method, quantity)
                writer.writerow(dict(row_type="verified-against-SI", kernel=kernel,
                    basis=basis, quantity=quantity, me=values[0], mae=values[1],
                    max="", std=values[2], source_table=source))

    means = [verifier.moments([item["err"] for item in samples[f"{k}|dihedral"]])[0]
             for k in verifier.GEOMETRY]
    report = "M14 default aEX=0.2 and remedy aEX=0.25. Dihedral ME: " + "; ".join(
        f"{method}: {mean:.8f}" for method, mean in zip(verifier.GEOMETRY, means))
    (final / "report.md").write_text(report, encoding="utf-8")
    return root


class VerifierRegression(unittest.TestCase):
    def test_molecule_integer_spellings(self):
        for value in (1, 1.0, "1", "M1", "M01", "01"):
            with self.subTest(value=value):
                self.assertEqual(verifier.molecule_id(value), 1)
        for value in (True, 0, "M0", 1.5, "1.0", float("inf")):
            with self.subTest(value=value), self.assertRaises(verifier.CandidateError):
                verifier.molecule_id(value)

    def test_source_identifier_spellings_and_incidental_number(self):
        for source in ("3", "3.", "S3", "S3.", "SI3", "SI Table 3", "SI Table 3.",
                       "Table 3", "Table 3.", "T 3", "表3", "Tables 3 and 14",
                       "Tables3and14", "3/S3"):
            with self.subTest(source=source):
                self.assertTrue(verifier.source_matches(source, 3))
        for source in ("3 molecules", "3.5", "Table 3.5", "S3.5", "Table 30",
                       "Table " + "9" * 5000):
            with self.subTest(source=source):
                self.assertFalse(verifier.source_matches(source, 3))

    def test_equivalent_numeric_ids_and_source_spellings_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            app = valid_app(Path(temp), molecule_transform=float,
                source_transform=lambda original, method, quantity: (
                    "3/S3." if re.search(r"\d+", original).group() == "3"
                    else "SI" + re.search(r"\d+", original).group() + "."))
            self.assertEqual(verifier.evaluate(app, TASK / "tests")["status"], "PASS")

    def test_extreme_finite_candidate_values_are_fail_not_env_invalid(self):
        with tempfile.TemporaryDirectory() as temp:
            app = valid_app(Path(temp))
            path = app / "final/provenance.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            first_group = next(iter(data["samples"].values()))
            for item in first_group:
                item["err"] = 1e308
            path.write_text(json.dumps(data), encoding="utf-8")
            result = verifier.evaluate(app, TASK / "tests")
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("molecular errors differ" in issue for issue in result["problems"]))

    def test_oversized_molecule_id_is_candidate_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            app = valid_app(root / "app")
            path = app / "final/provenance.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["samples"][next(iter(data["samples"]))][0]["mol"] = "9" * 5000
            path.write_text(json.dumps(data), encoding="utf-8")
            logs = root / "logs"
            env = os.environ.copy()
            env.update(APP=str(app), TESTS=str(TASK / "tests"), LOGS=str(logs),
                       PYTHON=sys.executable)
            result = subprocess.run(["bash", str(TASK / "tests/test.sh")], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            report = json.loads((logs / "verification.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual((logs / "reward.txt").read_text(encoding="utf-8").strip(), "0")


if __name__ == "__main__":
    unittest.main()
