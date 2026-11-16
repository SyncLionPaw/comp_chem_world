#!/usr/bin/env python3
"""Regression checks for configured duration and native completion decisions."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("case08_tools", ROOT / "solution" / "case08_tools.py")
TOOLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOLS)


class ConfiguredDurationTests(unittest.TestCase):
    def check_completed(self, nsteps, dt, final_step):
        config = TOOLS.configured_run({"nsteps": str(nsteps), "dt": str(dt), "init-step": "0", "tinit": "0"})
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run / "md.log").write_text(
                f"           Step           Time\n            {final_step}        {final_step * dt:.5f}\nFinished mdrun\n"
            )
            result = TOOLS.native_completion(run, config)
        self.assertTrue(result["completed"])
        self.assertAlmostEqual(config["duration_ps"], nsteps * dt)

    def test_one_ps_11_energy_samples_can_complete(self):
        self.check_completed(1000, 0.001, 1000)

    def test_fifty_ps_configuration_completes(self):
        self.check_completed(50000, 0.001, 50000)

    def test_early_abort_stops(self):
        config = TOOLS.configured_run({"nsteps": "1000", "dt": "0.001"})
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run / "md.log").write_text("           Step           Time\n              400        0.40000\n")
            result = TOOLS.native_completion(run, config)
        self.assertFalse(result["completed"])

    def test_native_warning_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run / "md.log").write_text("LINCS WARNING at step 20\n")
            self.assertGreater(TOOLS.warning_count(run), 0)

    def test_task_budget_cap_remains_200_ps(self):
        task = (ROOT / "task.toml").read_text()
        self.assertIn("simulation_ps_max_total = 200", task)


if __name__ == "__main__":
    unittest.main()
