#!/usr/bin/env python3
"""Parser fixtures only; archived trajectories are never current Oracle evidence."""
import importlib.util
import shutil
import csv
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("case08_verify", HERE / "verify.py")
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)
TOOL_SPEC = importlib.util.spec_from_file_location("case08_tools", HERE.parent / "solution/case08_tools.py")
TOOLS = importlib.util.module_from_spec(TOOL_SPEC)
TOOL_SPEC.loader.exec_module(TOOLS)
REVIEW_SPEC = importlib.util.spec_from_file_location("case08_review_status", HERE / "review_status.py")
REVIEW = importlib.util.module_from_spec(REVIEW_SPEC)
REVIEW_SPEC.loader.exec_module(REVIEW)


class EffectiveMdpFixtureTests(unittest.TestCase):
    def test_warning_counter_uses_events_not_lincs_parameter_names_or_nwall(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "md.log").write_text("lincs-warnangle = 30\n nwall = 2\n")
            (run / "mdrun.console.log").write_text("LINCS WARNING at step 42\n")
            self.assertEqual(1, VERIFY.log_warning_count(run))

    def test_archived_native_mdp_is_a_positive_parser_fixture_only(self):
        archived = HERE / "evidence/native-reference/results/case01/runs/B-dt1fs/mdout.mdp"
        values = VERIFY.mdp_values(archived)
        self.assertEqual([], VERIFY.effective_mdp_errors(values, 1))

    def test_excessive_steps_are_rejected(self):
        archived = HERE / "evidence/native-reference/results/case01/runs/B-dt1fs/mdout.mdp"
        values = VERIFY.mdp_values(archived)
        values["nsteps"] = "50001"
        self.assertIn("step count is non-positive or exceeds the 50 ps run cap", VERIFY.effective_mdp_errors(values, 1))

    def test_legal_seed_and_shorter_bounded_run_are_accepted(self):
        archived = HERE / "evidence/native-reference/results/case01/runs/B-dt1fs/mdout.mdp"
        values = VERIFY.mdp_values(archived)
        values["gen_seed"] = "987654321"
        values["nsteps"] = "10000"
        self.assertEqual([], VERIFY.effective_mdp_errors(values, 1))

    def test_changed_canonical_numeric_value_is_detectable(self):
        self.assertFalse(VERIFY.close_number(300.0 + 1.0, 300.0,
                                             VERIFY.DIAGNOSTIC_ABS_TOLERANCE["temperature_K"]))

    def test_alternate_analysis_is_reviewable_and_canonical_tampering_fails(self):
        oracle = (HERE / "evidence/historical-3968344-fixture/submission")
        for tamper in ("alternate", "numeric"):
            with self.subTest(tamper=tamper), tempfile.TemporaryDirectory() as tmp:
                app = Path(tmp) / "app"
                submission = app / "submission"
                submission.parent.mkdir(parents=True)
                shutil.copytree(oracle, submission)
                shutil.copytree(HERE.parent / "environment/assets", app / "environment/assets")
                if tamper == "alternate":
                    path = submission / "diagnostics.csv"
                    with path.open(newline="", encoding="utf-8") as handle:
                        reader = csv.DictReader(handle)
                        fieldnames, rows = reader.fieldnames, list(reader)
                    rows = list(reversed(rows[::2]))
                    with path.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(handle, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(rows)
                    comparison_path = submission / "numerical-comparison.json"
                    comparison = json.loads(comparison_path.read_text())
                    comparison["geometry_method"] = "equivalent coordination-number method using a declared solvent selection"
                    stats = comparison["statistics"]["by_run_and_timeblock"]
                    for windows in stats.values():
                        windows["common-window-0-10ps"] = windows.pop("full-0-50ps")
                        windows.pop("0-25ps", None)
                        windows.pop("25-50ps", None)
                    comparison_path.write_text(json.dumps(comparison))
                else:
                    path = submission / "diagnostics.csv"
                    with path.open(newline="", encoding="utf-8") as handle:
                        reader = csv.DictReader(handle)
                        fieldnames, rows = reader.fieldnames, list(reader)
                    rows[0]["temperature_K"] = str(float(rows[0]["temperature_K"]) + 1.0)
                    with path.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(handle, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(rows)
                result = VERIFY.check_candidate(app, HERE)
                if tamper == "alternate":
                    self.assertEqual("CHECKED", result["state"], result["failures"])
                    self.assertTrue(any("NOT_VERIFIED" in str(w) for w in result["warnings"]))
                else:
                    self.assertEqual("FAIL", result["state"])
                    self.assertTrue(any("temperature_K differs" in failure for failure in result["failures"]))

    def test_corrupt_trusted_execution_record_is_infra_error(self):
        oracle = (HERE / "evidence/historical-3968344-fixture/submission")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app, tests, logs = root / "app", root / "tests", root / "logs"
            (app / "submission").parent.mkdir(parents=True)
            shutil.copytree(oracle, app / "submission")
            shutil.copytree(HERE.parent / "environment/assets", app / "environment/assets")
            shutil.copytree(HERE, tests)
            trusted = tests / "evidence/verified-execution-3968344.json"
            trusted.write_text(trusted.read_text() + " ")
            code = REVIEW.run_case(app, tests, logs)
            report = json.loads((logs / "report.json").read_text())
            self.assertEqual(2, code)
            self.assertEqual("INFRA_ERROR", report["status"])

    def test_generated_index_has_every_mdp_referenced_group(self):
        gro = HERE.parent / "environment/assets/b.gro"
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.ndx"
            TOOLS.make_index(gro, index)
            self.assertEqual(VERIFY.expected_index_groups(gro), VERIFY.index_groups(index))

    def test_missing_non_water_group_is_rejected(self):
        gro = HERE.parent / "environment/assets/b.gro"
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.ndx"
            TOOLS.make_index(gro, index)
            text = index.read_text()
            index.write_text(text.replace("[ non-Water ]\n", "[ omitted ]\n"))
            groups = VERIFY.index_groups(index)
            self.assertIsNone(groups.get("non-Water"))

    def test_b_u_thermostat_groups_partition_all_atoms(self):
        assets = HERE.parent / "environment/assets"
        atom_counts = []
        for state in ("b", "u"):
            gro = assets / (state + ".gro")
            names = [line[5:10].strip() for line in gro.read_text().splitlines()[2:2 + int(gro.read_text().splitlines()[1])]]
            atom_counts.append(len(names))
            with tempfile.TemporaryDirectory() as tmp:
                index = Path(tmp) / "index.ndx"
                TOOLS.make_index(gro, index)
                groups = {name: set(members) for name, members in VERIFY.index_groups(index).items()}
            mdp = VERIFY.mdp_values(assets / "NVT-50ps-dt1fs.mdp")
            tc_groups = mdp["tc-grps"].split()
            for group in tc_groups + [mdp["imd-group"]]:
                self.assertIn(group, groups)
                self.assertTrue(groups[group])
            thermo = [groups[name] for name in tc_groups]
            for i, left in enumerate(thermo):
                for right in thermo[i + 1:]:
                    self.assertFalse(left & right)
            self.assertEqual(set(range(1, len(names) + 1)), set().union(*thermo))
        self.assertEqual(atom_counts[0], atom_counts[1])

    def test_archived_numeric_artifacts_exercise_independent_recomputation_only(self):
        archived = HERE / "evidence/native-reference/results/case01/analysis"
        with tempfile.TemporaryDirectory() as tmp:
            submission = Path(tmp)
            run = submission / "runs/B-dt1fs"
            run.mkdir(parents=True)
            shutil.copyfile(archived / "energy/B-dt1fs/energy.xvg", run / "energy.xvg")
            shutil.copyfile(archived / "water/B-dt1fs-wat20.gro", run / "sample-0001.gro")
            rows, summaries = VERIFY.recompute_diagnostics(submission)
        self.assertEqual(1, len(rows))
        self.assertEqual("runs/B-dt1fs/sample-0001.gro", rows[0]["source_frame"])
        self.assertTrue(250.0 < rows[0]["temperature_K"] < 350.0)
        self.assertGreater(rows[0]["water20_angle_mean_deg"], 80.0)
        self.assertGreater(summaries["B-dt1fs"]["full-0-50ps"]["Temperature"]["n"], 100)


if __name__ == "__main__":
    unittest.main()
