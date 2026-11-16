"""Unpaid engineering probe, deliberately incomplete scientific submission."""
import base64, json
from pathlib import Path
from harbor.agents.nop import NopAgent

REMOTE = r'''import collections,json,math,os,re,subprocess,sys,time
from pathlib import Path
root,prefix,account,partition,encoded=sys.argv[1:]
p=Path(root)
assert re.fullmatch(r'[a-f0-9]{32}',p.name) and p.parent.name=='runs'
assert prefix=='ccb05-'+p.name[:12]+'-'
stage=p/'stages/prep';stage.mkdir(parents=True,exist_ok=False)
import base64
(stage/'dye.xyz').write_bytes(base64.b64decode(encoded))
probe="""import collections,json,math
from pathlib import Path
lines=Path('dye.xyz').read_text().splitlines();n=int(lines[0]);rows=[r.split() for r in lines[2:]]
assert n==72 and len(rows)==n
counts=collections.Counter(r[0] for r in rows)
assert counts=={'C':41,'H':29,'N':1,'O':1}
xyz=[[float(v) for v in r[1:4]] for r in rows]
assert all(math.isfinite(v) for r in xyz for v in r)
span=[max(r[i] for r in xyz)-min(r[i] for r in xyz) for i in range(3)]
assert all(x>0 for x in span)
Path('mvp-result.json').write_text(json.dumps({'atoms':n,'composition':dict(counts),'coordinate_span_angstrom':span,'scope':'input geometry read on compute node; no MD or QM'}))
"""
(stage/'probe.py').write_text(probe)
(stage/'mvp.sbatch').write_text('#!/bin/bash\nset -euo pipefail\npython3 probe.py\n')
args=['sbatch','--parsable','--account='+account,'--partition='+partition,'--job-name='+prefix+'prep','--chdir='+str(stage),'--cpus-per-task=1','--nodes=1','--ntasks=1','--mem=256M','--time=00:02:00','--output='+str(stage/'slurm-%j.out'),str(stage/'mvp.sbatch')]
jid=subprocess.check_output(args,text=True,timeout=30).strip().split(';')[0]
assert jid.isdigit()
end=time.monotonic()+300
while time.monotonic()<end:
 active=subprocess.check_output(['squeue','-h','-j',jid,'-o','%T'],text=True,timeout=20).strip()
 if not active:break
 time.sleep(5)
else: raise RuntimeError('MVP queue/run observation exceeded five minutes; infrastructure not qualified')
result=json.loads((stage/'mvp-result.json').read_text())
result.update(job_id=jid,remote_attempt_root=root,job_prefix=prefix)
print(json.dumps(result))
'''

class MvpAgent(NopAgent):
    @staticmethod
    def name(): return 'bench03-hpc-mvp'
    async def run(self,instruction,environment,context):
        import shlex
        # The candidate, not the trusted collector, reads the public structure.
        launcher = '''import base64,json,os,subprocess\nfrom pathlib import Path\nscript=base64.b64decode(%r)\nargs=[os.environ[k] for k in ['CCB_HPC_REMOTE_ATTEMPT_ROOT','CCB_HPC_JOB_NAME_PREFIX','CCB_HPC_ACCOUNT','CCB_HPC_PARTITION']]\nargs.append(base64.b64encode(Path('/app/assets/inputs/qm/dye_bare_cpcm_meoh.xyz').read_bytes()).decode())\ncmd=['ssh','ikkem',__import__('shlex').join(['python3','-',*args])]\np=subprocess.run(cmd,input=script,capture_output=True,timeout=340)\nif p.returncode:raise RuntimeError(p.stderr.decode()[-2000:])\nresult=json.loads(p.stdout)\nPath('/app/final/mvp.json').write_text(json.dumps(result,indent=2)+'\\n')\nprint(json.dumps(result))\n''' % base64.b64encode(REMOTE.encode()).decode()
        result=await environment.exec('python3 -c '+shlex.quote(launcher),timeout_sec=360)
        (self.logs_dir/'mvp-execution.json').write_text(json.dumps({'return_code':result.return_code,'stdout':result.stdout,'stderr':result.stderr},indent=2))
        if result.return_code:raise RuntimeError('HPC MVP failed; inspect engineering log')
