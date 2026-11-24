#!/usr/bin/env python3
"""Exercise the solve wait/collect/finalize contract with a mocked CLI, never Slurm."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
PAYLOAD = PACKAGE / "tests/evidence/historical-3968344-fixture/submission"

MOCK = r'''#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path
args=sys.argv[1:]
events=Path(os.environ["CASE08_FIXTURE_EVENTS"])
rows=json.loads(events.read_text()) if events.exists() else []
cmd=args.pop(0)
rows.append({"command":cmd,"args":args})
events.write_text(json.dumps(rows,indent=2))
if cmd == "probe":
 print(json.dumps({"snapshot_sha256":"fixture-probe-sha","state":"READY"}))
elif cmd == "submit":
 def val(flag): return args[args.index(flag)+1]
 assert args.count("--nodes") == 1 and val("--nodes") == "1"
 assert val("--ntasks") == "1" and val("--cpus") == "8"
 assert val("--mem") == "8G" and val("--time") == "00:30:00"
 src=Path(val("--src")); manifest=json.loads((src/"source-manifest.json").read_text())
 assert manifest["run_plan"]["labels"] == ["B-dt1fs","B-dt2fs","U-dt1fs","U-dt2fs"]
 assert manifest["run_plan"]["max_ps_each"] == 50 and manifest["run_plan"]["max_total_ps"] == 200
 assert manifest["allocation"] == {"host":"ikkem","partition":"cpu","nodes":1,"cpus":8,"memory_gib":8,"walltime":"00:30:00"}
 print(json.dumps({"job_id":"FIXTURE-3968344","plan_sha256":"fixture-plan-sha","snapshot_sha256":"fixture-probe-sha"}))
elif cmd == "wait":
 assert "--job" in args and "--timeout" in args and args[args.index("--timeout")+1] == "1860"
 print(json.dumps({"state":"COMPLETED","exit_code":0,"receipt":{"JobIDRaw":"FIXTURE-3968344","State":"COMPLETED","ExitCode":"0:0","Partition":"cpu"}}))
elif cmd == "collect":
 dest=Path(args[args.index("--dest")+1]); dest.mkdir(parents=True,exist_ok=True)
 shutil.copytree(Path(os.environ["CASE08_FIXTURE_PAYLOAD"]),dest/"submission")
else:
 raise SystemExit("unexpected CLI command: "+cmd)
'''


class SolveCollectContractTests(unittest.TestCase):
    def test_single_bounded_submit_wait_collect_and_finalize(self):
        if not PAYLOAD.is_dir():
            self.skipTest("completed Oracle payload is not available in this checkout")
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); app=root/"app"; solution=root/"solution"; bin_dir=root/"bin"
            assets=app/"environment/assets"; assets.mkdir(parents=True)
            shutil.copytree(PACKAGE/"environment/assets",assets,dirs_exist_ok=True)
            solution.mkdir(); shutil.copy2(PACKAGE/"solution/case08_remote.sh",solution)
            shutil.copy2(PACKAGE/"solution/case08_tools.py",solution)
            bin_dir.mkdir(); cli=bin_dir/"hpc"; cli.write_text(MOCK); cli.chmod(0o755)
            events=root/"events.json"
            env=os.environ.copy(); env.update({
                "APP":str(app),"SOLUTION":str(solution),"PATH":str(bin_dir)+os.pathsep+env["PATH"],
                "CASE08_FIXTURE_EVENTS":str(events),"CASE08_FIXTURE_PAYLOAD":str(PAYLOAD),
            })
            result=subprocess.run(["bash",str(PACKAGE/"solution/solve.sh")],env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            calls=json.loads(events.read_text())
            self.assertEqual(["probe","submit","wait","collect"],[x["command"] for x in calls])
            self.assertEqual(1,sum(x["command"]=="submit" for x in calls))
            submission=app/"submission"
            for name in ("diagnostics.csv","numerical-comparison.json","continuation-decision.json","scientific-rationale.md","cli-submission.json","cli-scheduler.json","cli-probe-snapshot.json"):
                self.assertTrue((submission/name).is_file(),name)
            final=json.loads((submission/"remote-provenance.json").read_text())
            self.assertEqual("FIXTURE-3968344",final["job_id"])
            work=next(app.glob(".case08-work-*"))
            manifest=json.loads((work/"source-manifest.json").read_text())
            self.assertEqual(200,manifest["run_plan"]["max_total_ps"])
            self.assertEqual("00:30:00",manifest["allocation"]["walltime"])


if __name__ == "__main__":
    unittest.main()
