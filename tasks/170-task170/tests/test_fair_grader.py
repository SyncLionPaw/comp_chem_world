"""Bounded regression tests for case-04 public semantics and fair static grading.

These tests only execute the trusted reference writer and the verifier. They do
not execute any submitted make-lambda-input.py or run.sh; candidate helper
behavior is exercised separately inside the isolated grader container.
"""
from __future__ import annotations
import json
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

HERE=Path(__file__).resolve().parent
CASE=HERE.parent
VERIFY=HERE/"verify.py"
REFERENCE=CASE/"solution"/"solve.py"
ASSETS=CASE/"environment"

class FairGraderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=Path(tempfile.mkdtemp(prefix="case04-fair-grader-"))
        cls.base=cls.tmp/"reference-final"
        proc=subprocess.run([sys.executable,str(REFERENCE),str(cls.base)],capture_output=True,text=True,timeout=20)
        if proc.returncode: raise RuntimeError("trusted reference fixture generation failed")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp,ignore_errors=True)

    def clone(self,name):
        out=self.tmp/name
        shutil.copytree(self.base,out,dirs_exist_ok=True)
        return out

    def grade(self,final):
        env=os.environ.copy();env["APP"]=str(ASSETS)
        p=subprocess.run([sys.executable,str(VERIFY),str(final)],capture_output=True,text=True,env=env,timeout=20)
        self.assertIn(p.returncode,(0,1),p.stderr)
        return json.loads(p.stdout)

    def test_trusted_reference_chain_passes(self):
        result=self.grade(self.base)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))

    def test_synonymous_prefix_file_names_quotes_and_run_wrapper_pass(self):
        out=self.clone("aliases")
        for name in ("scf.in","coarse_scf.in","ph.in","q2r.in","matdyn.in"):
            p=out/name;text=p.read_text()
            text=text.replace("W2N3","alpha",)
            text=text.replace("'alpha'",'"alpha"')
            text=text.replace("'./tmp'",'"./run-area/"')
            text=text.replace("'alpha.dyn'",'"alpha.dyn"').replace("'alpha.fc'",'"alpha.fc"')
            text=text.replace("'alpha.dvscf'",'"alpha.dvscf"').replace("'alpha.phdos.dat'",'"alpha.phdos.dat"')
            p.write_text(text)
        p=out/"run.sh";text=p.read_text()
        text=text.replace("#!/usr/bin/env bash", "#!/usr/bin/env bash\nPW=${PW:-pw.x}\nPH=${PH:-ph.x}\nQ2R=${Q2R:-q2r.x}\nMATDYN=${MATDYN:-matdyn.x}\nLAMBDA=${LAMBDA:-lambda.x}\nPY=${PY:-python3}\nrun () { \"$@\" || exit 1; }")
        text=text.replace("pw.x < scf.in", "run \"$PW\" < scf.in")
        text=text.replace("pw.x < coarse_scf.in", "run $PW < coarse_scf.in")
        text=text.replace("ph.x < ph.in", "run $PH < ph.in")
        text=text.replace("q2r.x < q2r.in", "run $Q2R < q2r.in")
        text=text.replace("matdyn.x < matdyn.in", "run $MATDYN < matdyn.in")
        text=text.replace("lambda.x < lambda.in", "run $LAMBDA < lambda.in")
        text=text.replace("lambda.x < lambda-mu010.in", "run $LAMBDA < lambda-mu010.in")
        p.write_text(text)
        result=self.grade(out)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))

    def test_real_dataflow_mismatch_still_fails(self):
        out=self.clone("wrong-links")
        p=out/"q2r.in";p.write_text(p.read_text().replace("W2N3.dyn","wrong.dyn"))
        result=self.grade(out)
        self.assertEqual(result["overall"],"FAIL")
        failed={x["criterion"] for x in result["checks"] if not x["passed"]}
        self.assertIn("q2r_la2f",failed)

    def test_missing_interpolation_or_grid_still_fails(self):
        out=self.clone("missing-flag")
        p=out/"ph.in";p.write_text(p.read_text().replace("electron_phonon = 'interpolated',","electron_phonon = 'adiabatic',"))
        result=self.grade(out)
        self.assertEqual(result["overall"],"FAIL")
        failed={x["criterion"] for x in result["checks"] if not x["passed"]}
        self.assertIn("ph_interpolated",failed)

    def test_nonliteral_uncertainty_and_budget_language_pass(self):
        out=self.clone("uncertainty-language")
        p=out/"plan.json";plan=json.loads(p.read_text())
        plan["estimate_basis"]="预算按阶段估算；目前尚未进行基准测时。"
        plan["justifications"]={
            "dense_scf_k":"64 网格的收敛情况尚未验证，需与更密网格比较。",
            "coarse_scf_k":"粗 q 网格的误差方向和大小尚不清楚；需要做收敛比较。",
            "q":"插值不能恢复未采样 q 点的物理贡献，当前影响仍需验证。",
            "degauss":"尚未测量 0.005–0.02 Ry 范围内的展宽敏感性。",
        }
        p.write_text(json.dumps(plan,indent=2,ensure_ascii=False)+"\n")
        result=self.grade(out)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))

    def test_unsupported_directional_claim_remains_fail(self):
        out=self.clone("overclaim")
        p=out/"plan.json";plan=json.loads(p.read_text())
        plan["justifications"]["coarse_scf_k"]="The coarser mesh underestimates lambda; no convergence calculation was run."
        p.write_text(json.dumps(plan,indent=2)+"\n")
        result=self.grade(out)
        failed={x["criterion"] for x in result["checks"] if not x["passed"]}
        self.assertIn("grid_and_smearing_uncertainty_disclosed",failed)

    def test_unmeasured_cutoff_claim_remains_fail(self):
        out=self.clone("cutoff-overclaim")
        p=out/"plan.json";plan=json.loads(p.read_text())
        plan["justifications"]["degauss"]="The pseudopotential cutoff and smearing match the paper, so they are not additional error sources."
        p.write_text(json.dumps(plan,indent=2)+"\n")
        result=self.grade(out)
        failed={x["criterion"] for x in result["checks"] if not x["passed"]}
        self.assertIn("grid_and_smearing_uncertainty_disclosed",failed)

    def typed_uncertainty(self):
        return {
            "dense_k_status":"unknown","dense_k_note":"Dense mesh convergence remains unknown and was not measured.",
            "coarse_q_status":"unknown","coarse_q_note":"Coarse mesh convergence remains unknown and was not measured.",
            "interpolation_status":"unknown","interpolation_note":"Interpolation error remains unknown and was not measured.",
            "smearing_status":"unknown","smearing_note":"Smearing sensitivity remains unknown and was not measured.",
        }

    def test_typed_unknown_note_does_not_mask_same_note_overclaim(self):
        out=self.clone("typed-note-overclaim")
        p=out/"plan.json";plan=json.loads(p.read_text())
        plan["uncertainty"]=self.typed_uncertainty()
        plan["uncertainty"]["coarse_q_note"]="Convergence is unknown, but the coarse mesh definitely underestimates lambda."
        p.write_text(json.dumps(plan,indent=2)+"\n")
        result=self.grade(out)
        failed={x["criterion"] for x in result["checks"] if not x["passed"]}
        self.assertIn("grid_and_smearing_uncertainty_disclosed",failed)

    def test_typed_unknown_does_not_mask_legacy_overclaim(self):
        out=self.clone("typed-plus-legacy-overclaim")
        p=out/"plan.json";plan=json.loads(p.read_text())
        plan["uncertainty"]=self.typed_uncertainty()
        plan["justifications"]["coarse_scf_k"]="The coarse grid definitely underestimates lambda; convergence is unknown."
        p.write_text(json.dumps(plan,indent=2)+"\n")
        result=self.grade(out)
        failed={x["criterion"] for x in result["checks"] if not x["passed"]}
        self.assertIn("grid_and_smearing_uncertainty_disclosed",failed)

    def test_localized_negated_direction_claim_is_not_overclaim(self):
        out=self.clone("localized-negative-claim")
        p=out/"plan.json";plan=json.loads(p.read_text())
        plan["uncertainty"]=self.typed_uncertainty()
        plan["justifications"]["coarse_scf_k"]="It is not established that the coarse mesh underestimates lambda."
        p.write_text(json.dumps(plan,indent=2)+"\n")
        result=self.grade(out)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))

    def test_honest_typed_unknown_notes_pass(self):
        out=self.clone("typed-honest-unknown")
        p=out/"plan.json";plan=json.loads(p.read_text())
        plan["uncertainty"]=self.typed_uncertainty()
        p.write_text(json.dumps(plan,indent=2)+"\n")
        result=self.grade(out)
        self.assertEqual(result["overall"],"PASS",result.get("failed"))

    def test_candidate_helper_host_invoke_is_blocked_before_subprocess(self):
        replay_path=HERE/"helper_sandbox_replay.py"
        spec=importlib.util.spec_from_file_location("case04_helper_replay_for_guard_test",replay_path)
        replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
        with mock.patch.object(replay.subprocess,"run") as candidate_subprocess:
            with self.assertRaisesRegex(RuntimeError,"only inside the Linux grader container|container marker missing"):
                replay.invoke(Path("."),Path("."),Path("."))
            candidate_subprocess.assert_not_called()

    def test_budget_arithmetic_and_caps_remain_enforced(self):
        out=self.clone("bad-budget")
        p=out/"plan.json";plan=json.loads(p.read_text())
        plan["estimated_core_hours"]["total"]+=1
        p.write_text(json.dumps(plan,indent=2)+"\n")
        result=self.grade(out)
        failed={x["criterion"] for x in result["checks"] if not x["passed"]}
        self.assertIn("budget_sum_and_limits",failed)

    def test_public_plan_schema_is_inline_and_complete(self):
        instruction=(CASE/"instruction.md").read_text()
        headings=[line for line in instruction.splitlines() if line.startswith("## ")]
        self.assertEqual(headings,["## Background","## Task","## Requirements","## Files"])
        for token in (
            "`route`=`qe_native`", "`qe_target`=`QE 7.2`", "`execution_order`",
            "`structure`", "`cutoffs.ecutwfc_ry`", "`smearing`", "`grids`",
            "`estimated_core_hours`", "`estimate_basis`", "`justifications`",
            "`dense_scf_k`", "`coarse_scf_k`", "`q`", "`degauss`",
        ):
            self.assertIn(token,instruction)

if __name__=="__main__": unittest.main()
