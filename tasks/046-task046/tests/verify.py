#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including plan.json, run-ledger.json, topology.json).
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Investigate conductivity estimates with consistent temperature, units, and sampling evidence.
"""Static task diagnostics and root-owned runner with independent review gate."""
from __future__ import annotations

# The terminal adapter is installed only in the separate CompChemBench verifier image.
if __name__ == "__main__" and __import__("sys").argv[1:] == ["--terminal"]:
    import runpy as _runpy
    from pathlib import Path as _Path
    import sys as _sys
    _entry = _Path(__file__).resolve().parent / "harbor_runtime" / "entry.py"
    if not _entry.is_file():
        raise SystemExit("The pinned CompChemBench verifier image is required for terminal grading.")
    _sys.argv = [str(_entry)]
    _runpy.run_path(str(_entry), run_name="__main__")
    raise SystemExit(0)


"""Partial portable scorer: deterministic diagnostics; final scientific review is mandatory.

This entry point never returns an overall PASS or reward. Native execution and
free scientific conclusions are adjudicated with the complete private protocol.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
try:
    import numpy as np

except ImportError:
    np = None


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def diagnostics(package,submission,test_root):
    protocol=json.loads((test_root/'assessment-protocol.json').read_text())
    checks=[]
    def check(k,value,detail=''):
        checks.append({'check':k,'passed':bool(value),'detail':detail})
    for name in protocol['expected_outputs']:
        p=submission/name
        good=any(x.is_file() and x.stat().st_size>0 for x in p.rglob('*')) if name.endswith('/') and p.is_dir() else p.is_file() and p.stat().st_size>0
        check('L1.'+name,good)
    if not all(c['passed'] for c in checks):return checks
    if protocol.get('construct')=='budgeted-md-decision/v1':
        checks += _budget_diagnose(submission, protocol)
        checks += _native_estimator_diagnose(submission, protocol)
        if protocol.get('runtime_bound'):
            checks += _remote_diagnose(submission, answer_mode=os.environ.get('CCB_ANSWER_MODE'))
        return checks
    if protocol['case_id']=='reline-01-train':
        pred=np.load(submission/'predictions.npz',allow_pickle=False)
        energy=np.load(package/'inputs/data/valid/set.000/energy.npy',allow_pickle=False)
        force=np.load(package/'inputs/data/valid/set.000/force.npy',allow_pickle=False).reshape(-1,304,3)
        e,f=pred['energy'],pred['force']
        good=e.shape==(1000,) and f.shape==(1000,304,3) and np.isfinite(e).all() and np.isfinite(f).all()
        check('L1.prediction_schema',good)
        if good:
            delta=(e-energy)/304
            metrics={'raw_energy_rmse_eV_atom':float(np.sqrt(np.mean(delta**2))),
                     'centered_energy_rmse_eV_atom':float(np.sqrt(np.mean((delta-delta.mean())**2))),
                     'force_component_rmse_eV_A':float(np.sqrt(np.mean((f-force)**2)))}
            reported=json.loads((submission/'metrics.json').read_text())
            check('L3.label_metrics',all(k in reported and np.isclose(reported[k],v,rtol=1e-6,atol=1e-12) for k,v in metrics.items()),json.dumps(metrics))
            threshold=protocol['numeric_policy']['training']
            check('L3.energy_magnitude',metrics['centered_energy_rmse_eV_atom']<=threshold['centered_energy_max_eV_atom'])
            check('L3.force_magnitude',metrics['force_component_rmse_eV_A']<=threshold['force_max_eV_A'])
            baseline=threshold['baseline']
            check('L3.improves_no_learning_baseline',metrics['centered_energy_rmse_eV_atom']<baseline['centered_energy_rmse_eV_atom'] and metrics['force_component_rmse_eV_A']<baseline['force_component_rmse_eV_A'])
        protected=set(protocol['author_model_sha256'])
        model_files=[p for p in (submission/'model').rglob('*') if p.is_file()]
        check('L2.not_byte_identical_author_model',not any(file_hash(p) in protected for p in model_files),'Only byte identity is checked; genuine training and equivalent model replay still need scientific review.')
    elif protocol['case_id']=='reline-02-density':
        with (submission/'density.csv').open(newline='') as f: rows=list(csv.DictReader(f))
        try:
            ts=[float(r['T_K']) for r in rows]
            check('L1.temperature_rows',ts==[323,333,343,353,363,373])
            ref=protocol['numeric_policy']['density']
            means=np.array([float(r['mean_g_cm3']) for r in rows]);sems=np.array([float(r['sem_g_cm3']) for r in rows]);blocks=np.array([int(r['n_blocks']) for r in rows])
            good=len(rows)==6 and np.isfinite(means).all() and np.isfinite(sems).all() and (sems>=0).all() and (blocks>=8).all()
            check('L3.precision_and_block_count',good and (sems<=ref['sem_max_g_cm3']).all(),'Block independence still requires native-series review.')
            if good:
                check('L3.published_density_means',(np.abs(means-np.array(ref['reference']))<=ref['equivalence_margin_g_cm3']+ref['reference_rounding_g_cm3']).all())
                check('L3.negative_mean_thermal_slope',np.polyfit(ts,means,1)[0]<0,'Confidence interval, precision margin and valid NPT execution remain in the manual protocol.')
        except (KeyError,ValueError,TypeError) as exc:check('L1.density_schema',False,str(exc))
    else:
        # The frozen diffusion/collective/HG contracts allow scientific equivalent
        # serialization choices. Do not invent an output schema or give PASS based
        # on arbitrary boolean declarations to make these cases scoreable.
        for path in submission.glob('*.npz'):
            try:
                with np.load(path,allow_pickle=False) as a:
                    good=bool(a.files) and all(v.size>0 and (not np.issubdtype(v.dtype,np.number) or np.isfinite(v).all()) for v in [a[k] for k in a.files])
                check('L1.npz_finite.'+path.name,good)
            except (ValueError,OSError) as exc:check('L1.npz_parse.'+path.name,False,str(exc))
        for path in submission.glob('*.json'):
            try:
                obj=json.loads(path.read_text());check('L1.json_parse.'+path.name,isinstance(obj,(dict,list)) and bool(obj))
            except (ValueError,OSError) as exc:check('L1.json_parse.'+path.name,False,str(exc))
    return checks

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--submission',type=Path,required=True);args=ap.parse_args()
    package=Path(__file__).resolve().parents[1]
    try:
        if np is None:
            raise ImportError('NumPy is required by the partial diagnostic checker')
        default_package=Path(__file__).resolve().parents[1]
        package=Path(os.environ.get('APP',str(default_package))).resolve()
        test_root=Path(os.environ.get('TESTS',str(package/'tests'))).resolve()
        refs=json.loads((test_root/'reference-hashes.json').read_text())
        bad=[]
        for p,h in refs.items():
            path=(test_root/p[len('tests/'):] if p.startswith('tests/') else package/p)
            if path.is_symlink() or not path.is_file() or file_hash(path)!=h:bad.append(p)
        if bad:
            print(json.dumps({'status':'PREFLIGHT_ERROR','agent_graded':False,'bad_inputs_or_references':bad,'reward':None}));return 2
        try:
            checks=diagnostics(package,args.submission,test_root)
        except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc:
            checks=[{'check':'L1.submission_parse','passed':False,'detail':str(exc)}]
        failed=[c for c in checks if not c['passed']]
        result={'status':'FAIL' if failed else 'SCIENTIFIC_REVIEW_REQUIRED','checks':checks,
                'implementation':'partial','overall_scientific_pass':False,'reward':0 if failed else None,
                'manual_protocol':'tests/review-rubric.md','qualification_granted':False}
        print(json.dumps(result,indent=2,ensure_ascii=False));return 1 if failed else 0
    except (ImportError,OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        print(json.dumps({'status':'INFRASTRUCTURE_ERROR','agent_graded':False,'reward':None,'error':str(exc)}));return 2

# ---- Task 46 budget and native execution diagnostics ----
"""Deterministic budget/trace checks. Native execution and scientific judgement remain manual."""
import hashlib
import json
import math
import numpy as np
from pathlib import Path

_COLLECTIVE_ACTUAL_TEMPERATURES_K=(363.0,363.15)

def _collective_temperature_from_plan(plan, policy):
    """Read the one frozen actual T from the existing protocol.ensemble field."""
    nominal=[float(t) for t in policy.get('temperatures_K',[])]
    if set(nominal)!=set(_COLLECTIVE_ACTUAL_TEMPERATURES_K):
        raise ValueError('public collective temperature choices must be nominal 363 K and supplied-input 363.15 K')
    ensemble=plan.get('protocol',{}).get('ensemble','')
    values=re.findall(r'\b([0-9]+(?:\.[0-9]+)?)\s*K\b',str(ensemble),flags=re.I)
    if len(values)!=1:
        raise ValueError('protocol.ensemble must freeze exactly one actual temperature, 363.0 or 363.15 K')
    temperature=float(values[0])
    if temperature not in _COLLECTIVE_ACTUAL_TEMPERATURES_K:
        raise ValueError('actual collective temperature is outside the nominal-363-K input choices')
    return temperature

def _safe_submission_file(submission, reference):
    if not isinstance(reference,dict): return None
    rel=PurePosixPath(str(reference.get('path','')))
    if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0]!='execution': return None
    path=submission.joinpath(*rel.parts)
    if not path.is_file() or path.is_symlink(): return None
    try:
        if _sha(path)!=reference.get('sha256'): return None
    except OSError:
        return None
    return path

def _input_seed_sources(text):
    """Extract literal/variable-resolved seeds from common LAMMPS RNG commands."""
    lines=[line.split('#',1)[0].strip() for line in text.splitlines()]
    variables={}
    for line in lines:
        words=line.split()
        if len(words)>=4 and words[0].lower()=='variable' and words[2].lower()=='equal':
            variables[words[1]]=words[3]
    def integer(token):
        token=token.strip().strip('"\'')
        match=re.fullmatch(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?',token)
        if match: token=variables.get(match.group(1),'')
        try:
            value=float(token)
            return int(value) if math.isfinite(value) and value>0 and value.is_integer() else None
        except (TypeError,ValueError,OverflowError):
            return None
    seeds=[]; has_random=False; unresolved=False
    random_fix_styles={'langevin','temp/csvr','dpd','dpd/tstat'}
    for line in lines:
        words=line.split()
        if not words: continue
        command=words[0].lower()
        seed_index=None
        if command=='velocity' and len(words)>2 and words[2].lower()=='create':
            has_random=True; seed_index=4
        elif command=='fix' and len(words)>3 and words[3].lower() in random_fix_styles:
            has_random=True; seed_index=7
        if seed_index is not None:
            value=integer(words[seed_index]) if len(words)>seed_index else None
            if value is None: unresolved=True
            else: seeds.append(value)
    return seeds,has_random,unresolved,lines

def _deterministic_pilot_restart_branch(submission, row, plan, complete_runs, input_path, input_text):
    if row.get('stage')!='intervention': return False,'null seed is allowed only for a completed intervention branch'
    checkpoint=row.get('parent_checkpoint_sha256')
    if not isinstance(checkpoint,str) or not re.fullmatch(r'[0-9a-f]{64}',checkpoint):
        return False,'parent checkpoint digest is missing or malformed'
    parents=[]
    for parent in complete_runs:
        restart=parent.get('native_artifacts',{}).get('restart',{})
        if parent.get('stage')=='pilot' and restart.get('sha256')==checkpoint:
            path=_safe_submission_file(submission,restart)
            if path is not None and file_hash(path)==checkpoint:
                parents.append((parent,restart))
    if len(parents)!=1: return False,'checkpoint digest must identify exactly one hashed completed-pilot restart'
    parent,restart=parents[0]
    remote_root=plan.get('inputs',{}).get('remote_root')
    try:
        root=PurePosixPath(str(remote_root))
        rel=PurePosixPath(str(restart.get('path','')))
        if not root.is_absolute() or '..' in root.parts or rel.is_absolute() or '..' in rel.parts:
            return False,'frozen remote root or parent restart path is unsafe'
        expected=str(root.joinpath(*rel.parts))
    except (TypeError,ValueError):
        return False,'frozen parent restart path cannot be resolved'
    commands=[line for line in _input_seed_sources(input_text)[3] if line]
    read_restart=[line.split() for line in commands if line.split()[0].lower()=='read_restart']
    if len(read_restart)!=1 or len(read_restart[0])!=2 or read_restart[0][1]!=expected:
        return False,'native input does not read the hashed pilot restart named by parent_checkpoint_sha256'
    if any(line.split()[0].lower()=='include' for line in commands):
        return False,'included input prevents proving deterministic restart continuation'
    if any(line.split()[0].lower()=='velocity' for line in commands):
        return False,'velocity command prevents deterministic-seed waiver'
    if not any(line.split()[0].lower()=='fix' and len(line.split())>3 and line.split()[3].lower()=='nvt' for line in commands):
        return False,'native continuation does not declare deterministic NVT integration'
    _,has_random,unresolved,_=_input_seed_sources(input_text)
    if has_random or unresolved:
        return False,'native continuation contains an unresolved/random thermostat source'
    return True,f'deterministic NVT continuation from hashed pilot restart {parent.get("run_id")}'

def _run_seed_is_bound(submission, row, plan, complete_runs):
    seed=row.get('seed')
    input_path=_safe_submission_file(submission,row.get('native_artifacts',{}).get('input'))
    if input_path is None: return False,'hashed native input is unavailable'
    try: text=input_path.read_text(encoding='utf-8',errors='strict')
    except (OSError,UnicodeError): return False,'native input cannot be decoded as text'
    seeds,has_random,unresolved,_=_input_seed_sources(text)
    if seed is None:
        return _deterministic_pilot_restart_branch(submission,row,plan,complete_runs,input_path,text)
    if isinstance(seed,bool) or not isinstance(seed,int) or seed<=0:
        return False,'seed must be a positive integer unless a deterministic restart waiver is proven'
    if row.get('stage') in ('pilot','confirmation') or has_random:
        if unresolved or seed not in seeds:
            return False,f'ledger seed {seed} does not match a resolved seed in the hashed native input'
    return True,f'ledger seed {seed} is bound to native input' if has_random else f'positive seed {seed} recorded for deterministic run'

def _positive_run_seed_key(row):
    seed=row.get('seed')
    return (float(row['T_K']),seed) if isinstance(seed,int) and not isinstance(seed,bool) and seed>0 else None

def _budget_diagnose(submission, protocol):
    numeric_refs=json.loads((Path(__file__).resolve().parent/'refs.json').read_text(encoding='utf-8'))['budget_ledger']
    checks=[]
    def check(name, ok, detail=''):
        checks.append({'check':name,'passed':bool(ok),'detail':detail})
    for name in ['plan.json','topology.json','results.json']:
        obj=json.loads((submission/name).read_text())
        check('L1.parse.'+name,isinstance(obj,dict) and bool(obj))
    series='msd-vacf.npz' if protocol['case_id']=='reline-04-diffusion' else 'correlations.npz'
    with np.load(submission/series,allow_pickle=False) as data:
        check('L1.finite_series',bool(data.files) and all(data[k].size>0 and (not np.issubdtype(data[k].dtype,np.number) or np.isfinite(data[k]).all()) for k in data.files))
    policy=protocol['budget_policy']
    plan=json.loads((submission/'plan.json').read_text(encoding='utf-8'))
    collective=protocol.get('case_id')=='reline-05-collective'
    study_temperature=None
    if collective:
        try: study_temperature=_collective_temperature_from_plan(plan,policy)
        except (KeyError,TypeError,ValueError,OverflowError) as exc:
            check('L3.frozen_temperature_consistency',False,str(exc))
    ledger=json.loads((submission/'run-ledger.json').read_text())
    runs=ledger['runs']
    if not isinstance(runs,list) or not runs:raise ValueError('nonempty runs required')
    ids=[r['run_id'] for r in runs]
    check('L1.unique_run_ids',len(ids)==len(set(ids)))
    charged_steps=0;charged_ps=0;complete=[]
    for r in runs:
        requested=r['requested_steps'];executed=r.get('executed_steps');dt=r['dt_fs']
        if isinstance(requested,bool) or not isinstance(requested,int) or requested<=0:raise ValueError('requested_steps must be positive integer')
        if not isinstance(dt,(int,float)) or isinstance(dt,bool) or not math.isfinite(dt) or not 0<dt<=.5:raise ValueError('finite 0<dt_fs<=0.5 required')
        if r['status'] not in ['complete','failed','unknown']:raise ValueError('invalid attempt status')
        if executed is not None and (isinstance(executed,bool) or not isinstance(executed,int) or not 0<=executed<=requested):raise ValueError('invalid executed_steps')
        # Unknown or failed attempts consume their entire declared reservation;
        # this deliberately prevents releasing quota on an unauditable attempt.
        charged=requested if r['status']!='complete' else executed
        if charged is None:raise ValueError('complete runs require executed_steps')
        charged_steps+=charged;charged_ps+=charged*dt/1000
        if r['status']=='complete':
            complete.append(r)
            paths=r['native_artifacts']
            required=['input','log','trajectory','restart']
            check('L2.native_manifest.'+r['run_id'],all(k in paths for k in required))
            for kind in required:
                if kind not in paths:continue
                refs=_native_artifact_file_refs(kind,paths[kind])
                good=bool(refs)
                for label,item in refs:
                    if not isinstance(item,dict):
                        good=False;continue
                    p=Path(item.get('path',''));target=submission/p
                    safe=not p.is_absolute() and '..' not in p.parts and p.parts and p.parts[0]=='execution'
                    item_good=safe and target.is_file() and not target.is_symlink() and target.stat().st_size>0
                    if item_good:item_good=hashlib.sha256(target.read_bytes()).hexdigest()==item.get('sha256')
                    good &= item_good
                check('L2.native_hash.'+r['run_id']+'.'+kind,good)
    check('L3.total_step_budget',charged_steps<=policy['max_md_steps'],str(charged_steps))
    check('L3.total_time_budget',charged_ps<=policy['max_aggregate_ps']+1e-9,str(charged_ps))
    check('L3.single_gpu_per_run',all(isinstance(r.get('gpu_count'),int) and not isinstance(r['gpu_count'],bool) and 0<=r['gpu_count']<=1 for r in runs))
    check('L3.reported_budget',math.isclose(float(ledger['charged_ps']),charged_ps,rel_tol=numeric_refs['reported_time_rtol'],abs_tol=numeric_refs['reported_time_atol_ps']) and ledger['charged_steps']==charged_steps)
    if collective:
        results=json.loads((submission/'results.json').read_text())
        temperature_matches=False
        if study_temperature is not None:
            try:
                temperature_matches=(math.isclose(float(results.get('T_K',float('nan'))),study_temperature,rel_tol=0,abs_tol=1e-6)
                    and all(math.isclose(float(r.get('T_K',float('nan'))),study_temperature,rel_tol=0,abs_tol=1e-6) for r in runs))
            except (TypeError,ValueError,OverflowError): pass
        check('L3.frozen_temperature_consistency',temperature_matches,
              f"frozen actual temperature={study_temperature}; plan.protocol.ensemble, results T_K, and every ledger T_K must match")
        seed_details=[]
        for row in complete:
            ok,detail=_run_seed_is_bound(submission,row,plan,complete)
            if not ok: seed_details.append(f"{row.get('run_id')}: {detail}")
        check('L3.seed_binding',not seed_details,'; '.join(seed_details))
    duration=lambda r:r['executed_steps']*r['dt_fs']/1000
    pilot=[r for r in complete if r['stage']=='pilot']
    confirm=[r for r in complete if r['stage']=='confirmation']
    adaptive=[r for r in complete if r['stage']=='adaptive']
    confirm_keys=[_positive_run_seed_key(r) for r in confirm]
    confirm_keys=[k for k in confirm_keys if k is not None]
    check('L3.confirmation_unique_seed',len(confirm_keys)==len(confirm) and len(set(confirm_keys))==len(confirm))
    check('L3.actual_adaptive_tranche',bool(adaptive) and sum(map(duration,adaptive))>=policy['minimum_adaptive_ps'])
    check('L3.actual_confirmation',len(confirm)>=policy['minimum_confirmation_runs'] and all(duration(r)>=policy['minimum_confirmation_run_ps'] for r in confirm))
    keys=lambda rs:{k for k in (_positive_run_seed_key(r) for r in rs) if k is not None}
    check('L3.confirmation_fresh_seed',not (keys(confirm)&keys([r for r in complete if r['stage']!='confirmation'])))
    check('L3.pilot_distinct_seed',len(keys(pilot))==len(pilot))
    if protocol['case_id']=='reline-04-diffusion':
        check('L3.pilot_coverage',all(sum(float(r['T_K'])==t and duration(r)>=policy['pilot_run_ps'] for r in pilot)>=policy['pilot_min_runs_per_temperature'] for t in policy['pilot_temperatures_K']))
    else:
        check('L3.pilot_coverage',study_temperature is not None and len(pilot)>=policy['pilot_min_runs_per_temperature'] and all(math.isclose(float(r['T_K']),study_temperature,rel_tol=0,abs_tol=1e-6) and duration(r)>=policy['pilot_run_ps'] for r in pilot))
        pairs=[r for r in complete if r['stage']=='intervention']
        check('L3.controlled_intervention',len(pairs)>=2 and all(duration(r)>=policy['minimum_control_run_ps'] for r in pairs) and len({r['control_setting'] for r in pairs})>=2 and len({r['parent_checkpoint_sha256'] for r in pairs})==1 and all(len(r['parent_checkpoint_sha256'])==64 for r in pairs))
        check('L3.fixed_temperature',study_temperature is not None and all(math.isclose(float(r['T_K']),study_temperature,rel_tol=0,abs_tol=1e-6) for r in complete))
    if collective:
        check('L3.allowed_temperature',study_temperature in _COLLECTIVE_ACTUAL_TEMPERATURES_K and all(math.isclose(float(r['T_K']),study_temperature,rel_tol=0,abs_tol=1e-6) for r in complete) if study_temperature is not None else False)
    else:
        check('L3.allowed_temperature',all(float(r['T_K']) in policy['temperatures_K'] for r in complete))
    probes=ledger.get('author_probe_frame_ids',[])
    check('L3.ensemble_probe_budget',isinstance(probes,list) and len(probes)<=policy['max_author_ensemble_probe_frames'])
    decision=json.loads((submission/'decision.json').read_text())
    claims=decision['claims']
    check('L1.core_claims',set(policy['required_claim_ids']).issubset(claims))
    for cid in policy['required_claim_ids']:
        row=claims.get(cid,{})
        check('L3.reasoned_claim.'+cid,row.get('status') in ['supported','contradicted','inconclusive'] and bool(row.get('scope')) and bool(row.get('evidence')) and bool(row.get('reason')))
    trace=json.loads((submission/'decision-trace.json').read_text())['decisions']
    check('L3.explicit_tradeoff',bool(trace) and all(len(x.get('alternatives',[]))>=2 and x.get('chosen') and x.get('pilot_evidence') and x.get('prediction') and x.get('followup_run_ids') and set(x['followup_run_ids']).issubset(set(ids)) for x in trace))
    check('L3.next_action',bool(decision.get('next_action')) and bool(decision.get('expected_information_gain')))
    return checks


def _native_artifact_file_refs(kind, item):
    if kind=="trajectory" and isinstance(item,dict) and "path" not in item:
        positions=item.get("positions");velocities=item.get("velocities")
        if isinstance(positions,dict) and isinstance(velocities,dict):
            return [("positions",positions),("velocities",velocities)]
        return []
    return [(kind,item)] if isinstance(item,dict) else []


# Independent native estimator replay.  This code intentionally consumes only
# the public atom structure, submitted topology/results/arrays, and hashed native
# trajectory bytes; it never imports the submitted solve.sh implementation.
_NATIVE_SPECIES = ("choline", "chloride", "urea")
_NATIVE_MASSES = {1: 1.0, 2: 16.0, 3: 14.0, 4: 12.0, 5: 35.45}
_NATIVE_FORMULAS = {
    "choline": {"C": 5, "H": 14, "N": 1, "O": 1},
    "chloride": {"Cl": 1}, "urea": {"C": 1, "H": 4, "N": 2, "O": 1}}
_NATIVE_ELEMENTS = {1:"H",2:"O",3:"N",4:"C",5:"Cl"}
_NATIVE_CHARGES = {"choline": 1.0, "chloride": -1.0, "urea": 0.0}
_NATIVE_E_CHARGE = 1.602176634e-19
_NATIVE_KB = 1.380649e-23
_NATIVE_RTOL, _NATIVE_ATOL = 1e-6, 1e-12


def _native_min_image(delta, box):
    return delta - box * np.rint(delta / box)


def _native_read_structure(path):
    atom_types, xyz, bounds = {}, {}, {}
    in_atoms = False
    for line in path.read_text(encoding="utf-8").splitlines():
        words = line.split()
        if not words:
            continue
        if len(words) >= 4 and words[-2:] in (["xlo", "xhi"], ["ylo", "yhi"], ["zlo", "zhi"]):
            bounds[words[-2][0]] = (float(words[0]), float(words[1]))
        if words[0] == "Atoms":
            in_atoms = True
            continue
        if not in_atoms or words[0].startswith("#"):
            continue
        try:
            atom_id, atom_type = int(words[0]), int(words[1])
            position = np.asarray([float(x) for x in words[2:5]], dtype=float)
        except (ValueError, IndexError):
            if words[0][0].isalpha():
                in_atoms = False
            continue
        if atom_id in atom_types:
            raise ValueError("duplicate atom ID in trusted public structure")
        atom_types[atom_id], xyz[atom_id] = atom_type, position
    if sorted(atom_types) != list(range(1, 2433)) or set(bounds) != set("xyz"):
        raise ValueError("public structure atom inventory/orthogonal box is invalid")
    types = np.asarray([atom_types[i] for i in range(1, 2433)], dtype=np.int64)
    positions = np.asarray([xyz[i] for i in range(1, 2433)], dtype=float)
    box = np.asarray([bounds[a][1] - bounds[a][0] for a in "xyz"], dtype=float)
    if not np.isfinite(positions).all() or not np.isfinite(box).all() or np.any(box <= 0):
        raise ValueError("public structure contains invalid coordinates or box")

    radii = {1:.31,2:.66,3:.71,4:.76,5:0.0}
    allowed_bonds = {(1,2),(1,3),(1,4),(2,3),(2,4),(3,4),(4,4)}
    adjacency = [set() for _ in types]
    for i in range(len(types)):
        for j in range(i+1,len(types)):
            pair=tuple(sorted((int(types[i]),int(types[j]))))
            if pair not in allowed_bonds:
                continue
            delta=_native_min_image(positions[j]-positions[i],box)
            cutoff=1.25*(radii[pair[0]]+radii[pair[1]])
            if float(np.dot(delta,delta)) <= cutoff*cutoff:
                adjacency[i].add(j); adjacency[j].add(i)
    seen, molecules = set(), []
    for start in range(len(types)):
        if start in seen:
            continue
        stack, component = [start], []
        seen.add(start)
        while stack:
            i = stack.pop(); component.append(i)
            for j in adjacency[i]:
                if j not in seen:
                    seen.add(j); stack.append(j)
        from collections import Counter
        formula = Counter(_NATIVE_ELEMENTS[int(types[i])] for i in component)
        matched = [s for s, expected in _NATIVE_FORMULAS.items() if dict(formula) == expected]
        if len(matched) != 1:
            raise ValueError(f"public structure has unclassified molecular component {dict(formula)}")
        ids = np.asarray(sorted(component), dtype=np.int64)
        species = matched[0]
        molecules.append({"species": species, "ids": ids,
                          "mass": np.asarray([_NATIVE_MASSES[int(types[i])] for i in ids])})
    molecules.sort(key=lambda m: (_NATIVE_SPECIES.index(m["species"]), int(m["ids"][0])))
    counts = {s: sum(m["species"] == s for m in molecules) for s in _NATIVE_SPECIES}
    if counts != {"choline":64,"chloride":64,"urea":128}:
        raise ValueError(f"periodic graph species counts mismatch: {counts}")
    return types, box, molecules


def _native_topology_agrees(topology, molecules):
    expected = sorted((m["species"], [int(i)+1 for i in m["ids"]]) for m in molecules)
    claimed=[]
    for molecule in topology.get("molecules", []):
        species=molecule.get('species',molecule.get('type'))
        if 'species' in molecule and 'type' in molecule and molecule['species']!=molecule['type']:
            raise ValueError('submitted topology has conflicting species/type labels')
        claimed.append((species,molecule.get('atom_ids_1based')))
    claimed.sort()
    if expected != claimed:
        raise ValueError("submitted topology atom partition differs from independent public-structure graph")

def _native_topology_alias_selftest(molecules):
    rows=[{'type':m['species'],'atom_ids_1based':[int(i)+1 for i in m['ids']]} for m in molecules]
    _native_topology_agrees({'molecules':rows},molecules)
    bad=[dict(row,atom_ids_1based=list(row['atom_ids_1based'])) for row in rows]
    bad[0]['atom_ids_1based'][0]=-1
    try: _native_topology_agrees({'molecules':bad},molecules)
    except ValueError: pass
    else: raise AssertionError('topology type alias weakened atom-partition checking')
    conflict=[dict(row,atom_ids_1based=list(row['atom_ids_1based'])) for row in rows]
    conflict[0]['species']='chloride'
    try: _native_topology_agrees({'molecules':conflict},molecules)
    except ValueError: pass
    else: raise AssertionError('conflicting topology species/type labels were accepted')


def _native_frame_com(rows, types, molecules, box):
    xyz = rows[:, 2:5]
    vel = rows[:, 5:8]
    com = np.empty((len(molecules), 3), dtype=float)
    vcom = np.empty_like(com)
    for index, mol in enumerate(molecules):
        ids, weights = mol["ids"], mol["mass"]
        anchor = xyz[int(ids[0])]
        relative = _native_min_image(xyz[ids] - anchor, box)
        com[index] = anchor + np.average(relative, axis=0, weights=weights)
        vcom[index] = np.average(vel[ids], axis=0, weights=weights)
    return com, vcom


def _native_read_split_velocity_frame(stream, expected_types, expected_box, expected_step, sort_id_verified):
    marker=stream.readline()
    if not marker:
        raise ValueError("paired velocity dump ended before position dump")
    if marker.strip()!="ITEM: TIMESTEP" or int(stream.readline())!=expected_step:
        raise ValueError("paired velocity frame timestep differs from positions")
    if stream.readline().strip()!="ITEM: NUMBER OF ATOMS":
        raise ValueError("paired velocity atom-count marker is missing")
    n=int(stream.readline())
    if n!=len(expected_types):
        raise ValueError("paired velocity atom count differs from public structure")
    bh=stream.readline().split()
    if bh[:3]!=["ITEM:","BOX","BOUNDS"]:
        raise ValueError("paired velocity box header is invalid")
    triclinic=bh[3:6]==["xy","xz","yz"]
    flags=bh[6:] if triclinic else bh[3:]
    if flags!=["pp","pp","pp"]:
        raise ValueError("paired velocity dump must use fully periodic boundaries")
    bounds=np.asarray([[float(x) for x in stream.readline().split()] for _ in range(3)])
    if bounds.shape!=(3,3 if triclinic else 2) or not np.isfinite(bounds).all():
        raise ValueError("paired velocity bounds are invalid")
    if triclinic and np.any(np.abs(bounds[:,2])>1e-12):
        raise ValueError("paired velocity dump has unsupported nonzero tilt")
    box=bounds[:,1]-bounds[:,0]
    if not np.allclose(box,expected_box,rtol=0,atol=1e-8):
        raise ValueError("paired position/velocity boxes differ")
    ah=stream.readline().split()
    if ah[:2]!=["ITEM:","ATOMS"]:
        raise ValueError("paired velocity atom columns are missing")
    cols=ah[2:]
    if not all(k in cols for k in ("vx","vy","vz")):
        raise ValueError("paired velocity dump lacks vx/vy/vz")
    id_idx=cols.index("id") if "id" in cols else None
    type_idx=cols.index("type") if "type" in cols else None
    elem_idx=cols.index("element") if "element" in cols else None
    if id_idx is None and not sort_id_verified:
        raise ValueError("paired velocity dump without IDs requires native dump_modify sort id")
    elem_map={"H":1,"O":2,"N":3,"C":4,"Cl":5}
    parsed=[]
    for order in range(n):
        fields=stream.readline().split()
        if len(fields)!=len(cols):
            raise ValueError("paired velocity dump row is malformed")
        atom_id=int(fields[id_idx]) if id_idx is not None else order+1
        if atom_id<1 or atom_id>n:
            raise ValueError("paired velocity atom ID is outside public inventory")
        atom_type=(int(fields[type_idx]) if type_idx is not None else
                   elem_map.get(fields[elem_idx]) if elem_idx is not None else None)
        if atom_type is not None and atom_type!=int(expected_types[atom_id-1]):
            raise ValueError("paired velocity atom type/element differs from positions mapping")
        velocity=[float(fields[cols.index(k)]) for k in ("vx","vy","vz")]
        parsed.append((atom_id,velocity))
    parsed.sort(key=lambda row:row[0])
    if [row[0] for row in parsed]!=list(range(1,n+1)):
        raise ValueError("paired velocity atom IDs are missing, repeated, or noncontiguous")
    return np.asarray([row[1] for row in parsed],dtype=float)


def _native_frames(path, expected_types, molecules, velocity_path=None, sort_id_verified=False):
    steps, boxes, coms, velocities = [], [], [], []
    fixed_box = None
    from contextlib import ExitStack
    with ExitStack() as stack:
        stream=stack.enter_context(path.open(encoding="utf-8"))
        velocity_stream=stack.enter_context(velocity_path.open(encoding="utf-8")) if velocity_path else None
        while True:
            marker = stream.readline()
            if not marker:
                break
            if marker.strip() != "ITEM: TIMESTEP":
                raise ValueError(f"invalid native dump frame marker in {path}")
            step_line = stream.readline().strip()
            if not re.fullmatch(r"[+-]?\d+", step_line):
                raise ValueError("native dump timestep is not an integer")
            step = int(step_line)
            if stream.readline().strip() != "ITEM: NUMBER OF ATOMS":
                raise ValueError("native dump atom count marker is missing")
            n = int(stream.readline())
            if n != len(expected_types):
                raise ValueError("native dump atom count differs from public structure")
            box_header = stream.readline().split()
            if box_header[:3] != ["ITEM:", "BOX", "BOUNDS"]:
                raise ValueError("native dump box header is invalid")
            triclinic = box_header[3:6] == ["xy", "xz", "yz"]
            flags = box_header[6:] if triclinic else box_header[3:]
            if flags != ["pp", "pp", "pp"]:
                raise ValueError("native dump must use fully periodic boundaries")
            bounds = np.asarray([[float(x) for x in stream.readline().split()] for _ in range(3)])
            if bounds.shape != (3, 3 if triclinic else 2) or not np.isfinite(bounds).all():
                raise ValueError("native dump bounds are invalid")
            if triclinic and np.any(np.abs(bounds[:, 2]) > 1e-12):
                raise ValueError("native dump has unsupported nonzero tilt")
            box = bounds[:, 1] - bounds[:, 0]
            if fixed_box is not None and not np.allclose(box, fixed_box, rtol=0, atol=1e-8):
                raise ValueError("native NVT box changes between frames")
            fixed_box = box.copy()
            header = stream.readline().split()
            if header[:2] != ["ITEM:", "ATOMS"]:
                raise ValueError("native dump atom columns are missing")
            cols = header[2:]
            if not ("type" in cols or "element" in cols):
                raise ValueError("native dump needs atom type or element columns")
            id_idx=cols.index("id") if "id" in cols else None
            if id_idx is None and not sort_id_verified:
                raise ValueError("native dump without atom IDs requires native dump_modify sort id")
            pos_keys = ("xu", "yu", "zu") if all(k in cols for k in ("xu","yu","zu")) else ("x","y","z")
            vel_keys = ("vx","vy","vz")
            if not all(k in cols for k in pos_keys):
                raise ValueError("native dump lacks a complete position vector")
            has_velocity=all(k in cols for k in vel_keys)
            if any(k in cols for k in vel_keys) and not has_velocity:
                raise ValueError("native dump has an incomplete velocity vector")
            if not has_velocity and velocity_stream is None:
                raise ValueError("native positions dump has no paired velocity dump")
            idx = {k: cols.index(k) for k in pos_keys}
            type_idx = cols.index("type") if "type" in cols else None
            elem_idx = cols.index("element") if "element" in cols else None
            image_idx = [cols.index(k) for k in ("ix","iy","iz")] if all(k in cols for k in ("ix","iy","iz")) else None
            atom_rows = []
            for _ in range(n):
                fields = stream.readline().split()
                if len(fields) != len(cols):
                    raise ValueError("truncated or malformed native atom row")
                atom_rows.append(fields)
            atom_rows=[(int(row[id_idx]) if id_idx is not None else order+1,row) for order,row in enumerate(atom_rows)]
            atom_rows.sort(key=lambda item:item[0])
            if [atom_id for atom_id,_ in atom_rows] != list(range(1,n+1)):
                raise ValueError("native atom IDs are not unique contiguous 1-based IDs")
            rows = np.empty((n, 8), dtype=float)
            for atom_index, (atom_id,row) in enumerate(atom_rows):
                if type_idx is not None:
                    atom_type = int(row[type_idx])
                else:
                    elem_map = {"H":1,"O":2,"N":3,"C":4,"Cl":5}
                    atom_type = elem_map.get(row[elem_idx])
                    if atom_type is None:
                        raise ValueError("unknown native element column value")
                if atom_type != int(expected_types[atom_index]):
                    raise ValueError("native atom type/element mapping differs from public structure")
                pos = np.asarray([float(row[idx[k]]) for k in pos_keys])
                if pos_keys == ("x","y","z"):
                    if image_idx:
                        pos += np.asarray([int(row[k]) for k in image_idx]) * box
                    else:
                        pos = np.mod(pos, box)
                rows[atom_index, :2] = (atom_id, atom_type)
                rows[atom_index, 2:5] = pos
                if has_velocity:
                    rows[atom_index, 5:8] = [float(row[cols.index(k)]) for k in vel_keys]
            if not has_velocity:
                rows[:,5:8]=_native_read_split_velocity_frame(velocity_stream,expected_types,box,step,sort_id_verified)
            if not np.isfinite(rows).all():
                raise ValueError("native trajectory contains nonfinite state values")
            com, vcom = _native_frame_com(rows, expected_types, molecules, box)
            steps.append(step); boxes.append(box.copy()); coms.append(com); velocities.append(vcom)
        if velocity_stream is not None and velocity_stream.readline():
            raise ValueError("paired velocity dump contains unmatched extra frames")
    if len(steps) < 2:
        raise ValueError("native trajectory needs at least two frames")
    diff = np.diff(steps)
    if np.any(diff <= 0) or len(set(diff.tolist())) != 1:
        raise ValueError("native trajectory timestep cadence is irregular")
    return np.asarray(steps), np.asarray(boxes), np.asarray(coms), np.asarray(velocities)


def _native_first_frame_end(path):
    """Return byte offset after the first complete standard LAMMPS dump frame."""
    with path.open("rb") as stream:
        if stream.readline().strip()!=b"ITEM: TIMESTEP":
            raise ValueError("native dump has no first frame")
        if not stream.readline(): raise ValueError("truncated first timestep")
        if stream.readline().strip()!=b"ITEM: NUMBER OF ATOMS": raise ValueError("invalid first atom-count marker")
        count_line=stream.readline()
        if not count_line: raise ValueError("truncated first atom count")
        count=int(count_line)
        header=stream.readline().split()
        if header[:3] != [b"ITEM:",b"BOX",b"BOUNDS"]: raise ValueError("invalid first box header")
        for _ in range(3):
            if not stream.readline(): raise ValueError("truncated first box bounds")
        atom_header=stream.readline().split()
        if atom_header[:2] != [b"ITEM:",b"ATOMS"]: raise ValueError("invalid first atom header")
        for _ in range(count):
            if not stream.readline(): raise ValueError("truncated first atom frame")
        return stream.tell()


def _native_concatenated_dump_hash(parent_path, extension_path, skip_extension_first):
    digest=hashlib.sha256()
    for path in (parent_path, extension_path):
        offset=_native_first_frame_end(path) if path==extension_path and skip_extension_first else 0
        with path.open("rb") as stream:
            if offset: stream.seek(offset)
            for block in iter(lambda:stream.read(1<<20),b""):
                digest.update(block)
    return digest.hexdigest()


def _native_positive_run_no_integrator_warnings(log_text):
    """Return NoFix warnings bound to positive-step LAMMPS run blocks.

    A zero-step run is allowed for setup/probes.  LAMMPS emits NoFix before its
    Verlet setup line, so only an echoed new `run N` command clears old pending
    state; the setup banner is deliberately not a reset boundary.
    """
    warning=re.compile(r"No fixes with time integration, atoms won.t move",re.I)
    command=re.compile(r"^\s*run\s+([0-9]+)(?:\s|$)",re.I)
    loop=re.compile(r"Loop time of\s+[0-9.eE+-]+.*?for\s+(\d+)\s+steps",re.I)
    pending=0;block=0;failures=[]
    for line_no,line in enumerate(log_text.splitlines(),1):
        if command.search(line):
            pending=0;block+=1
        if warning.search(line):
            pending+=1
        match=loop.search(line)
        if match:
            count=int(match.group(1))
            if pending and count>0:
                failures.append({"run_block":block,"loop_steps":count,"line":line_no})
            pending=0
    return failures


def _native_input_thermostat_temperatures(input_text):
    variables={}
    for line in input_text.splitlines():
        line=line.split("#",1)[0]
        m=re.match(r"\s*variable\s+(\S+)\s+equal\s+([+-]?[0-9.eE]+)\s*$",line,re.I)
        if m:
            variables[m.group(1)]=m.group(2)
    targets=[]
    number=r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    patterns=(
        re.compile(r"\bfix\s+\S+\s+\S+\s+(?:nvt|npt)\b.*?\btemp\s+"+number+r"\s+"+number,re.I),
        re.compile(r"\bfix\s+\S+\s+\S+\s+langevin\s+"+number+r"\s+"+number,re.I),
        re.compile(r"\bfix\s+\S+\s+\S+\s+temp/rescale\s+\d+\s+"+number+r"\s+"+number,re.I))
    for raw in input_text.splitlines():
        line=raw.split("#",1)[0]
        line=re.sub(r"\$\{([^}]+)\}",lambda m:variables.get(m.group(1),m.group(0)),line)
        for pattern in patterns:
            match=pattern.search(line)
            if match:
                targets.extend((float(match.group(1)),float(match.group(2))))
                break
    return targets


def _native_input_sorted_dump_paths(input_text):
    dump_ids={};sorted_ids=set()
    for raw in input_text.splitlines():
        line=raw.split("#",1)[0].strip()
        if not line:
            continue
        words=line.split()
        if words[0].lower()=="dump" and len(words)>=6:
            dump_ids[words[1]]=Path(words[5]).name
        elif words[0].lower()=="dump_modify" and len(words)>=4 and words[2].lower()=="sort" and words[3].lower()=="id":
            sorted_ids.add(words[1])
    return {filename:(dump_id in sorted_ids) for dump_id,filename in dump_ids.items()}


def _native_dump_has_ids(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.startswith("ITEM: ATOMS"):
                return "id" in line.split()[2:]
    raise ValueError(f"native dump has no atom column header: {path}")

def _frozen_plan_replay_parameters(plan):
    """Resolve only lossless aliases already frozen in the candidate plan."""
    errors=[]; sources={}
    shell=plan.get('shell_observable',{})
    cutoff=plan.get('shell_cutoff_A',shell.get('neighbor_cutoff_Angstrom'))
    if 'shell_cutoff_A' in plan and 'neighbor_cutoff_Angstrom' in shell:
        try:
            if not math.isclose(float(plan['shell_cutoff_A']),float(shell['neighbor_cutoff_Angstrom']),rel_tol=0,abs_tol=1e-12):
                errors.append('flat and nested shell cutoffs conflict')
        except (TypeError,ValueError,OverflowError): errors.append('flat and nested shell cutoffs are not numeric')
    if cutoff is None: errors.append('frozen shell cutoff is missing')
    else: sources['shell_cutoff_A']='shell_cutoff_A' if 'shell_cutoff_A' in plan else 'shell_observable.neighbor_cutoff_Angstrom'

    exclusions={}
    frozen=plan.get('excluded_time',{})
    stage_names={'pilot':'pilot','intervention':'control','adaptive':'adaptive','confirmation':'confirmation'}
    nested_exclusions={}
    for stage,source_stage in stage_names.items():
        item=frozen.get(source_stage,{})
        if isinstance(item,dict) and item.get('exclude_first_ps') is not None:
            nested_exclusions[stage]=item['exclude_first_ps']
    if 'excluded_initial_time_ps' in plan:
        exclusions={stage:plan['excluded_initial_time_ps'] for stage in ('pilot','intervention','adaptive','confirmation')}
        sources['excluded_initial_time_ps']='excluded_initial_time_ps'
        if nested_exclusions:
            try:
                flat=float(plan['excluded_initial_time_ps'])
                if any(not math.isclose(flat,float(v),rel_tol=0,abs_tol=1e-12) for v in nested_exclusions.values()):
                    errors.append('flat and nested exclusion times conflict')
            except (TypeError,ValueError,OverflowError):
                errors.append('flat and nested exclusion times are not numeric')
    else:
        for stage in stage_names:
            if stage not in nested_exclusions:
                errors.append(f'frozen exclusion time missing for {stage}')
            else: exclusions[stage]=nested_exclusions[stage]
        sources['excluded_initial_time_ps']='excluded_time.<stage>.exclude_first_ps'
    try:
        if any(not math.isfinite(float(v)) or float(v)<0 for v in exclusions.values()):
            errors.append('frozen exclusion times must be finite and nonnegative')
        if len({float(v) for v in exclusions.values()})>1:
            errors.append('stage-specific exclusion times cannot be collapsed to one replay definition')
    except (TypeError,ValueError,OverflowError): errors.append('frozen exclusion time is not numeric')

    windows=plan.get('integration_windows_ps')
    wp=plan.get('windows',{})
    nested_windows=None
    try: nested_windows=[wp['short']['upper_ps'],wp['long']['upper_ps']]
    except (KeyError,TypeError): pass
    if windows is None:
        windows=nested_windows
        if windows is not None: sources['integration_windows_ps']='windows.short/long.upper_ps'
    else:
        sources['integration_windows_ps']='integration_windows_ps'
        if nested_windows is not None:
            try:
                if len(windows)!=len(nested_windows) or any(not math.isclose(float(a),float(b),rel_tol=0,abs_tol=1e-12) for a,b in zip(windows,nested_windows)):
                    errors.append('flat and nested integration windows conflict')
            except (TypeError,ValueError,OverflowError):
                errors.append('flat and nested integration windows are not numeric')
    if not isinstance(windows,list) or len(windows)<2:
        errors.append('frozen integration windows are missing'); windows=[]
    try:
        windows=[float(v) for v in windows]
        if any(not math.isfinite(v) or v<=0 for v in windows) or len(set(windows))<2:
            errors.append('frozen integration windows must contain at least two distinct positive values')
    except (TypeError,ValueError,OverflowError):
        errors.append('frozen integration windows are not numeric'); windows=[]
    max_lag=plan.get('max_lag_ps')
    if max_lag is None and windows:
        max_lag=max(windows); sources['max_lag_ps']='maximum frozen integration window'
    elif max_lag is not None: sources['max_lag_ps']='max_lag_ps'
    try:
        max_lag=float(max_lag)
        if not math.isfinite(max_lag) or max_lag<=0 or (windows and max_lag+1e-12<max(windows)):
            errors.append('frozen max lag must cover every integration window')
    except (TypeError,ValueError,OverflowError):
        errors.append('frozen maximum lag is missing or not numeric'); max_lag=None

    origin_indices=plan.get('origin_frame_indices')
    origin_stride=plan.get('origin_stride_frames')
    origin_phase=plan.get('origin_phase_frames',0)
    origin_error=''
    if origin_indices is not None:
        if origin_stride is not None: origin_error='frozen plan declares both origin indices and origin stride'
        elif (not isinstance(origin_indices,list) or not origin_indices
              or any(isinstance(x,bool) or not isinstance(x,int) for x in origin_indices)
              or origin_indices!=sorted(set(origin_indices))):
            origin_error='frozen origin_frame_indices must be a nonempty strictly increasing integer list'
    elif isinstance(origin_stride,bool) or not isinstance(origin_stride,int) or origin_stride<1:
        origin_error='frozen plan does not declare an origin stride or origin_frame_indices'
    elif isinstance(origin_phase,bool) or not isinstance(origin_phase,int) or not 0<=origin_phase<origin_stride:
        origin_error='frozen origin phase must be an integer in [0, stride)'
    else: sources['time_origins']='origin_stride_frames/origin_phase_frames'
    if origin_indices is not None and not origin_error: sources['time_origins']='origin_frame_indices'
    return {'shell_cutoff_A':cutoff,'excluded_by_stage':exclusions,'integration_windows_ps':windows,
            'max_lag_ps':max_lag,'origin_frame_indices':origin_indices,
            'origin_stride_frames':origin_stride,'origin_phase_frames':origin_phase,
            'origin_error':origin_error,'errors':errors,'sources':sources}


def _native_replay_run(run_id, result, series, ledger_run, trajectory, types, molecules, plan,
                       series_index=0, series_run_count=1, frame_data=None,
                       temperature_K=363.0, frozen_parameters=None):
    frozen_parameters=frozen_parameters or _frozen_plan_replay_parameters(plan)
    if frozen_parameters['errors']:
        raise ValueError('; '.join(frozen_parameters['errors']))
    if frozen_parameters['origin_error']:
        raise ValueError(frozen_parameters['origin_error'])
    cutoff=float(frozen_parameters['shell_cutoff_A'])
    stage=ledger_run.get('stage')
    excluded=float(frozen_parameters['excluded_by_stage'].get(stage,frozen_parameters['excluded_by_stage'].get('intervention')))
    max_lag_ps=float(frozen_parameters['max_lag_ps'])
    origin_indices=frozen_parameters['origin_frame_indices']
    origin_stride=frozen_parameters['origin_stride_frames']
    origin_phase=frozen_parameters['origin_phase_frames']
    integration_windows=list(frozen_parameters['integration_windows_ps'])
    if (not math.isfinite(cutoff) or cutoff<=0 or not math.isfinite(excluded) or excluded<0
            or not math.isfinite(max_lag_ps) or max_lag_ps<=0
            or (origin_indices is None and (origin_stride<1 or origin_phase<0 or origin_phase>=origin_stride))
            or len(set(integration_windows))<2
            or any(not math.isfinite(x) or x<=0 for x in integration_windows)):
        raise ValueError(f"{run_id}: plan contains invalid fixed-shell or integration parameters")
    steps, boxes, com, vel = frame_data if frame_data is not None else _native_frames(trajectory, types, molecules)
    dt_ps = float(ledger_run["dt_fs"]) * float(np.median(np.diff(steps))) / 1000.0
    keep = (steps - steps[0]) * float(ledger_run["dt_fs"]) / 1000.0 >= excluded - 1e-12
    steps, boxes, com, vel = steps[keep], boxes[keep], com[keep], vel[keep]
    if len(steps) < 2:
        raise ValueError(f"{run_id}: no post-exclusion trajectory frames")
    if result.get("trajectory_steps") != steps.tolist():
        raise ValueError(f"{run_id}: results.json trajectory_steps differ from post-exclusion native frames")
    if int(result.get("n_frames",-1)) != len(steps):
        raise ValueError(f"{run_id}: results.json n_frames differs from native frames")
    observed_counts={s:sum(m["species"]==s for m in molecules) for s in _NATIVE_SPECIES}
    if result.get("species_counts") != observed_counts:
        raise ValueError(f"{run_id}: results.json species_counts differ from independent topology")
    native_volume=float(np.mean(np.prod(boxes,axis=1)))
    if not math.isclose(float(result.get("volume_mean_A3",float("nan"))),native_volume,rel_tol=_NATIVE_RTOL,abs_tol=_NATIVE_ATOL):
        raise ValueError(f"{run_id}: results.json mean volume differs from native boxes")
    frame_dt = float(np.median(np.diff(steps))) * float(ledger_run["dt_fs"]) / 1000.0
    if not math.isfinite(frame_dt) or frame_dt<=0:
        raise ValueError(f"{run_id}: invalid native frame time spacing")
    declared_lag_frames=int(round(max_lag_ps/frame_dt))
    if declared_lag_frames>len(steps)-1:
        raise ValueError(f"{run_id}: native trajectory does not cover the declared maximum lag")
    max_lag=declared_lag_frames
    origin_limit=len(steps)-max_lag
    if origin_indices is None:
        origins=np.arange(origin_phase,origin_limit,origin_stride,dtype=int)
    else:
        if any(index<0 or index>=origin_limit for index in origin_indices):
            raise ValueError(f"{run_id}: plan origin_frame_indices exceed the native usable lag range")
        origins=np.asarray(origin_indices,dtype=int)
    if "n_time_origins" in result and int(result["n_time_origins"]) != len(origins):
        raise ValueError(f"{run_id}: results.json n_time_origins differs from declared sampling")
    if len(origins) < 2:
        raise ValueError(f"{run_id}: fewer than two fixed-rule origins")
    lag = np.arange(max_lag + 1, dtype=float) * frame_dt
    species_ids = {s: np.asarray([i for i,m in enumerate(molecules) if m["species"] == s],dtype=int) for s in _NATIVE_SPECIES}
    n = len(origins); shape = (3,3,max_lag+1)
    nc0 = np.zeros((3,3)); nc_fixed = np.zeros(shape); nc_refresh = np.zeros(shape)
    nc_retention = np.zeros(shape); shell_vfixed = np.zeros(shape); shell_vrefresh = np.zeros(shape)
    c_total = np.zeros(max_lag+1); c_self = np.zeros(max_lag+1)
    charges = np.asarray([_NATIVE_CHARGES[m["species"]] for m in molecules])
    ionic = np.flatnonzero(charges != 0)
    current = vel * charges[None,:,None]
    for o in origins:
        for ai, sa in enumerate(_NATIVE_SPECIES):
            ia = species_ids[sa]
            for bi, sb in enumerate(_NATIVE_SPECIES):
                ib = species_ids[sb]
                d0 = _native_min_image(com[o][ia][:,None,:] - com[o][ib][None,:,:], boxes[o])
                origin_shell = np.einsum("ijk,ijk->ij",d0,d0) <= cutoff*cutoff
                if sa == sb:
                    origin_shell[np.arange(len(ia)),np.arange(len(ib))] = False
                nc0[ai,bi] += origin_shell.sum()/len(ia)
                origin_count = int(origin_shell.sum())
                # Chunk lag vectorization bounds temporary memory while avoiding
                # a Python loop over every lag and every molecular pair.
                for begin in range(0,max_lag+1,16):
                    end=min(max_lag+1,begin+16)
                    frames=com[o+begin:o+end]
                    dlag=_native_min_image(frames[:,ia][:,:,None,:]-frames[:,ib][:,None,:,:],boxes[o+begin:o+end,None,None,:])
                    now=np.einsum("kijc,kijc->kij",dlag,dlag)<=cutoff*cutoff
                    if sa==sb:
                        now[:,np.arange(len(ia)),np.arange(len(ib))]=False
                    overlap=now & origin_shell[None,:,:]
                    nc_fixed[ai,bi,begin:end]+=np.count_nonzero(overlap,axis=(1,2))/len(ia)
                    nc_refresh[ai,bi,begin:end]+=np.count_nonzero(now,axis=(1,2))/len(ia)
                    nc_retention[ai,bi,begin:end]+=np.count_nonzero(overlap,axis=(1,2))/max(1,origin_count)
                    pair_v=np.einsum("ic,kjc->kij",vel[o,ia],vel[o+begin:o+end,ib])
                    shell_vfixed[ai,bi,begin:end]+=np.where(origin_shell[None,:,:],pair_v,0).sum(axis=(1,2))/len(ia)
                    shell_vrefresh[ai,bi,begin:end]+=np.where(now,pair_v,0).sum(axis=(1,2))/len(ia)
        j0=current[o,ionic].sum(axis=0)
        jt=current[o:o+max_lag+1,ionic].sum(axis=1)
        c_total += np.einsum("c,kc->k",j0,jt)
        c_self += np.einsum("ic,kic->k",current[o,ionic],current[o:o+max_lag+1,ionic])
    nc0 /= n; nc_fixed /= n; nc_refresh /= n; nc_retention /= n
    shell_vfixed /= n; shell_vrefresh /= n; c_total /= n; c_self /= n
    v2 = np.asarray([np.mean(np.sum(vel[:,species_ids[s],:]**2,axis=-1)) for s in _NATIVE_SPECIES])
    norm = np.sqrt(v2[:,None]*v2[None,:])[:,:,None]
    norm_fixed = shell_vfixed / np.maximum(norm,1e-30)
    norm_refresh = shell_vrefresh / np.maximum(norm,1e-30)
    c_distinct = c_total - c_self
    def integ(y):
        out=np.zeros_like(y,dtype=float)
        out[...,1:]=np.cumsum((y[...,1:]+y[...,:-1])*np.diff(lag)/2,axis=-1)
        return out
    gkt, gks, gkd = integ(c_total), integ(c_self), integ(c_distinct)
    candidates = {
        "lag_ps": lag, "NC0_ordered_pairs": nc0,
        "NC_fixed_origin_ordered_pairs": nc_fixed, "NC_refreshed_ordered_pairs": nc_refresh,
        "NC_fixed_origin_velocity_correlation_normalized": norm_fixed,
        "NC_refreshed_velocity_correlation_normalized": norm_refresh,
        "C_current_total_e2_A2_ps-2": c_total,
        "C_current_self_e2_A2_ps-2": c_self,
        "C_current_distinct_e2_A2_ps-2": c_distinct,
        "GK_total_e2_A2_ps-1": gkt, "GK_self_e2_A2_ps-1": gks,
        "GK_distinct_e2_A2_ps-1": gkd,
        "ordered_species": np.asarray(_NATIVE_SPECIES)}
    optional={"NC_integral_fixed_origin_ps":integ(norm_fixed),
              "NC_integral_refreshed_ps":integ(norm_refresh),
              "n_origins":np.asarray([n])}
    for name,expected in optional.items():
        if f"{run_id}__{name}" in series or name in series:
            candidates[name]=expected

    def stored_array(name, expected):
        key=f"{run_id}__{name}"
        if key in series:
            actual=np.asarray(series[key])
        elif name in series:
            stored=np.asarray(series[name])
            if stored.shape==np.asarray(expected).shape and (series_run_count==1 or name in {"lag_ps","ordered_species"}):
                actual=stored
            elif stored.ndim==np.asarray(expected).ndim+1 and stored.shape[0]==series_run_count and stored.shape[1:]==np.asarray(expected).shape:
                actual=stored[series_index]
            else:
                raise ValueError(f"correlations.npz array {name} does not identify sampling for {run_id}; got shape {stored.shape}, expected {np.asarray(expected).shape} or a run-leading axis")
        else:
            raise ValueError(f"correlations.npz lacks required independent-replay array {key} (or shared {name})")
        return actual

    actual_species=np.asarray(stored_array("ordered_species",np.asarray(_NATIVE_SPECIES))).astype(str).tolist()
    if len(actual_species)!=3 or set(actual_species)!=set(_NATIVE_SPECIES):
        raise ValueError(f"{run_id}: ordered_species must uniquely label the three public species")
    axis_order=[actual_species.index(s) for s in _NATIVE_SPECIES]
    errors = {}
    for name, expected in candidates.items():
        key = f"{run_id}__{name}"
        actual=np.asarray(stored_array(name,expected))
        if name in {"NC0_ordered_pairs","NC_fixed_origin_ordered_pairs","NC_refreshed_ordered_pairs",
                    "NC_fixed_origin_velocity_correlation_normalized","NC_refreshed_velocity_correlation_normalized",
                    "NC_integral_fixed_origin_ps","NC_integral_refreshed_ps"}:
            actual=np.take(np.take(actual,axis_order,axis=0),axis_order,axis=1)
        elif name == "ordered_species":
            actual=np.take(actual,axis_order,axis=0)
        if actual.shape != np.asarray(expected).shape:
            raise ValueError(f"{key} shape differs from native replay: {actual.shape} vs {np.asarray(expected).shape}")
        if np.issubdtype(np.asarray(expected).dtype,np.number):
            delta=np.abs(actual.astype(float)-np.asarray(expected,dtype=float))
            scale=np.maximum(np.abs(np.asarray(expected,dtype=float)),1e-30)
            max_abs=float(np.max(delta)) if delta.size else 0.0
            max_rel=float(np.max(delta/scale)) if delta.size else 0.0
            if not np.allclose(actual,expected,rtol=_NATIVE_RTOL,atol=_NATIVE_ATOL,equal_nan=False):
                raise ValueError(f"{key} differs from independent native replay (max_abs={max_abs:g}, max_rel={max_rel:g})")
            errors[name]={"max_abs":max_abs,"max_rel":max_rel}
        elif not np.array_equal(actual,np.asarray(expected)):
            raise ValueError(f"{key} differs from independent native replay")
        else:
            errors[name]={"max_abs":0.0,"max_rel":0.0}

    # Public ordered-pair reciprocity: N_i <N_ij> = N_j <N_ji>.
    populations=np.asarray([len(species_ids[s]) for s in _NATIVE_SPECIES],dtype=float)
    reciprocity=np.zeros((3,3))
    for ai in range(3):
        for bi in range(3):
            reciprocity[ai,bi]=populations[ai]*nc0[ai,bi]-populations[bi]*nc0[bi,ai]
    if not np.allclose(reciprocity,0,rtol=0,atol=1e-8):
        raise ValueError(f"independent ordered-pair reciprocity failed: {reciprocity.tolist()}")
    pair_results=result.get("pair_results",{})
    for ai,sa in enumerate(_NATIVE_SPECIES):
        for bi,sb in enumerate(_NATIVE_SPECIES):
            key=f"{sa}__{sb}"; pair=pair_results.get(key)
            if not isinstance(pair,dict):
                raise ValueError(f"results.json lacks ordered pair {run_id}/{key}")
            scalar=(float(pair["NC0_mean_neighbors_per_center"]),float(nc0[ai,bi]))
            if not math.isclose(scalar[0],scalar[1],rel_tol=_NATIVE_RTOL,abs_tol=_NATIVE_ATOL):
                raise ValueError(f"results.json NC0 mismatch for {run_id}/{key}")
            residual=float(pair["reciprocity_residual_pair_counts"])
            if not math.isclose(residual,float(reciprocity[ai,bi]),rel_tol=0,abs_tol=1e-8):
                raise ValueError(f"results.json reciprocity residual mismatch for {run_id}/{key}")
            for field, expected in (
                ("fixed_origin_neighbor_count_per_center",nc_fixed[ai,bi]),
                ("refreshed_shell_neighbors_per_center",nc_refresh[ai,bi]),
                ("fixed_origin_cohort_retention_fraction",nc_retention[ai,bi]),
                ("NC_fixed_origin_normalized_velocity_correlation",norm_fixed[ai,bi]),
                ("NC_refreshed_normalized_velocity_correlation",norm_refresh[ai,bi])):
                actual=np.asarray(pair.get(field),dtype=float)
                if actual.shape != expected.shape or not np.allclose(actual,expected,rtol=_NATIVE_RTOL,atol=_NATIVE_ATOL):
                    raise ValueError(f"results.json {run_id}/{key}/{field} differs from native replay")
    windows=result.get("windows",{})
    if not math.isclose(float(result.get("shell_cutoff_A",float("nan"))),cutoff,rel_tol=0,abs_tol=_NATIVE_ATOL):
        raise ValueError(f"{run_id}: result shell cutoff differs from frozen plan")
    if not math.isclose(float(result.get("excluded_initial_time_ps",float("nan"))),excluded,rel_tol=0,abs_tol=_NATIVE_ATOL):
        raise ValueError(f"{run_id}: result initial exclusion differs from frozen plan")
    for window in integration_windows:
        row=windows.get(f"{window:g}_ps")
        if not isinstance(row,dict):
            raise ValueError(f"results.json lacks {window:g}-ps Green-Kubo window for {run_id}")
        used_lag=float(row.get("lag_ps",float("nan")))
        if (not math.isfinite(used_lag) or used_lag<0 or used_lag>float(lag[-1])+1e-12
                or abs(used_lag-window)>frame_dt*(0.5+1e-12)):
            raise ValueError(f"{run_id}: reported {window:g}-ps GK cutoff does not match the frozen window on the native lag grid")
        hi=int(np.searchsorted(lag,used_lag,side="left"))
        if hi<len(lag) and math.isclose(float(lag[hi]),used_lag,rel_tol=0,abs_tol=1e-12):
            expected_gk=(gkt[hi],gks[hi],gkd[hi])
        else:
            lo=hi-1
            fraction=(used_lag-float(lag[lo]))/float(lag[hi]-lag[lo])
            def at_cutoff(correlation,integral):
                c_end=float(correlation[lo]+fraction*(correlation[hi]-correlation[lo]))
                return float(integral[lo]+(used_lag-float(lag[lo]))*(correlation[lo]+c_end)/2)
            expected_gk=(at_cutoff(c_total,gkt),at_cutoff(c_self,gks),at_cutoff(c_distinct,gkd))
        for field, expected in zip(("integral_current_total_e2_A2_ps-1",
                                    "integral_current_self_e2_A2_ps-1",
                                    "integral_current_distinct_e2_A2_ps-1"),expected_gk):
            if not math.isclose(float(row[field]),float(expected),rel_tol=_NATIVE_RTOL,abs_tol=_NATIVE_ATOL):
                raise ValueError(f"results.json {run_id}/{window:g}ps/{field} differs from native replay")
        sigma_factor=(_NATIVE_E_CHARGE**2*1e22 /
                      (3.0*native_volume*_NATIVE_KB*float(temperature_K)))
        for field,expected in (("finite_window_conductivity_S_m",expected_gk[0]*sigma_factor),
                               ("self_nernst_einstein_proxy_S_m",expected_gk[1]*sigma_factor)):
            if not math.isclose(float(row[field]),float(expected),rel_tol=_NATIVE_RTOL,abs_tol=_NATIVE_ATOL):
                raise ValueError(f"results.json {run_id}/{window:g}ps/{field} differs from native replay")
        gamma=float(expected_gk[0]/expected_gk[1]) if abs(expected_gk[1])>1e-30 else None
        got=row.get("gamma_window_total_over_self")
        if gamma is None:
            if got is not None:
                raise ValueError(f"results.json {run_id}/{window:g}ps gamma should be null")
        elif not math.isclose(float(got),gamma,rel_tol=_NATIVE_RTOL,abs_tol=_NATIVE_ATOL):
            raise ValueError(f"results.json {run_id}/{window:g}ps gamma differs from native replay")
    return {"run_id":run_id,"trajectory_path":str(trajectory),"trajectory_sha256":_sha(trajectory),
            "trajectory_bytes":trajectory.stat().st_size,"frames":int(len(steps)),
            "post_exclusion_frames":int(len(com)),"origin_count":int(n),
            "lags":int(max_lag+1),"reciprocity_max_abs":float(np.max(np.abs(reciprocity))),
            "parameters":{"shell_cutoff_A":cutoff,"excluded_initial_time_ps":excluded,
                "max_lag_ps":max_lag_ps,"origin_stride_frames":origin_stride,
                "origin_frame_indices_count":None if origin_indices is None else len(origin_indices),
                "origin_frame_indices_first_last":None if origin_indices is None or not origin_indices else [origin_indices[0],origin_indices[-1]],
                "origin_phase_frames":origin_phase,
                "integration_windows_ps":integration_windows,"dt_frame_ps":frame_dt,
                "frozen_parameter_sources":frozen_parameters['sources']},
            "replay_work":{"origins":int(n),"lags":int(max_lag+1),"molecules":int(len(molecules)),
                "ordered_species_pair_origins_lags":int(9*n*(max_lag+1)),
                "temporary_pair_scratch_upper_bound_bytes":int(16*128*128*3*8)},
            "comparison_rtol":_NATIVE_RTOL,"comparison_atol":_NATIVE_ATOL,
            "array_error_summary":errors}


def _native_estimator_diagnose(submission, protocol):
    if protocol.get("case_id") != "reline-05-collective":
        return []
    checks=[]
    def add(name, ok, detail): checks.append({"check":name,"passed":bool(ok),"detail":detail})
    plan=json.loads((submission/"plan.json").read_text(encoding="utf-8"))
    ledger=json.loads((submission/"run-ledger.json").read_text(encoding="utf-8"))
    results=json.loads((submission/"results.json").read_text(encoding="utf-8"))
    topo=json.loads((submission/"topology.json").read_text(encoding="utf-8"))
    structure=submission/"inputs"/"inputs"/"strc.lmp"
    if not structure.is_file():
        structure=submission/"inputs"/"strc.lmp"
    refs=json.loads((Path(__file__).resolve().parent/"refs.json").read_text(encoding="utf-8"))
    replay_policy=refs["scientific_values"]["native_estimator_replay"]
    global _NATIVE_RTOL, _NATIVE_ATOL, _NATIVE_E_CHARGE, _NATIVE_KB
    _NATIVE_RTOL=float(replay_policy["comparison_rtol"])
    _NATIVE_ATOL=float(replay_policy["comparison_atol"])
    _NATIVE_E_CHARGE=float(replay_policy["conductivity_conversion"]["constant_e_C"])
    _NATIVE_KB=float(replay_policy["conductivity_conversion"]["constant_kB_J_K"])
    if _sha(structure)!=replay_policy["public_structure_sha256"]:
        raise _VerifierIntegrityError("native estimator replay public structure hash mismatch")
    public_contract=_trusted_public_output_contract()
    if _sha(public_contract)!=replay_policy.get("public_output_contract_sha256"):
        raise _VerifierIntegrityError("native estimator replay public output-contract pin mismatch")
    try:
        _trusted_output_contract_selftest()
        _native_replay_selftest(replay_policy.get("self_pin",{}))
        _provenance_format_selftest()
        types,_,molecules=_native_read_structure(structure)
        _native_topology_alias_selftest(molecules)
    except _VerifierIntegrityError:
        raise
    except Exception as exc:
        raise _VerifierIntegrityError(f"native verifier internal self-test failed: {exc}") from exc
    try:
        trusted_temperature=_collective_temperature_from_plan(plan,protocol["budget_policy"])
        add('L3.frozen_temperature_source',True,
            f"actual T={trusted_temperature:g} K read from plan.protocol.ensemble; nominal grid is 363 K")
    except (KeyError,TypeError,ValueError,OverflowError) as exc:
        add('L3.frozen_temperature_source',False,str(exc))
        add('L2.native_estimator_replay',False,'not run because the frozen actual temperature is unresolved')
        return checks
    native_temperature_rows=[]
    native_temperature_ok=True
    for row in ledger.get('runs',[]):
        if row.get('status')!='complete': continue
        input_path=_safe_submission_file(submission,row.get('native_artifacts',{}).get('input'))
        if input_path is None:
            native_temperature_ok=False
            native_temperature_rows.append({'run_id':row.get('run_id'),'error':'hashed native input is unavailable'})
            continue
        try:
            targets=_native_input_thermostat_temperatures(input_path.read_text(encoding='utf-8'))
            matched=bool(targets) and all(math.isclose(t,trusted_temperature,rel_tol=0,abs_tol=1e-8) for t in targets)
        except (OSError,UnicodeError,ValueError) as exc:
            targets=[];matched=False;error=str(exc)
        else: error=''
        native_temperature_ok &= matched
        native_temperature_rows.append({'run_id':row.get('run_id'),'targets_K':targets,'matched_frozen_actual_T':matched,'error':error})
    add('L2.native_temperature_binding',native_temperature_ok and bool(native_temperature_rows),
        json.dumps({'frozen_actual_temperature_K':trusted_temperature,'runs':native_temperature_rows},separators=(',',':')))
    frozen_parameters=_frozen_plan_replay_parameters(plan)
    add('L3.frozen_estimator_parameters',not frozen_parameters['errors'],
        json.dumps({'errors':frozen_parameters['errors'],'resolved_sources':frozen_parameters['sources']},separators=(',',':')))
    add('L3.frozen_time_origins',not bool(frozen_parameters['origin_error']),
        frozen_parameters['origin_error'] or json.dumps({'source':frozen_parameters['sources'].get('time_origins')},separators=(',',':')))
    topology_error=''
    try: _native_topology_agrees(topo,molecules)
    except (ValueError,KeyError,TypeError) as exc: topology_error=str(exc)
    add('L2.native_topology_agreement',not bool(topology_error),topology_error or 'submitted atom/molecule partition agrees with independent public-structure graph')
    if frozen_parameters['errors'] or frozen_parameters['origin_error'] or topology_error:
        add('L2.native_estimator_replay',False,
            'independent replay not attempted: a required frozen plan parameter is missing/invalid or topology does not agree; candidate arrays/results were not used to reconstruct analysis choices')
        return checks
    series_path=submission/"correlations.npz"
    reports=[]
    replay_failed=False
    complete=[row for row in ledger["runs"] if row.get("status")=="complete"]
    series_run_count=len(complete)
    with np.load(series_path,allow_pickle=False) as arrays:
        series={key:arrays[key] for key in arrays.files}
        for series_index,row in enumerate(complete):
            rid=row["run_id"]
            result=results.get("runs",{}).get(rid)
            if not isinstance(result,dict):
                raise ValueError(f"results.json lacks complete native run {rid}")
            rel=PurePosixPath(result.get("trajectory_path",""))
            if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0]!="execution":
                raise ValueError(f"{rid}: unsafe trajectory_path in results.json")
            trajectory=submission.joinpath(*rel.parts)
            if not trajectory.is_file() or trajectory.is_symlink():
                raise ValueError(f"{rid}: trajectory_path does not name a regular native dump")
            artifact=row.get("native_artifacts",{}).get("trajectory",{})
            artifact_refs=_native_artifact_file_refs("trajectory",artifact)
            if not artifact_refs:
                raise ValueError(f"{rid}: trajectory artifact has an unsupported encoding")
            native_files={}
            for label,item in artifact_refs:
                artifact_path=PurePosixPath(str(item.get("path","")))
                if artifact_path.is_absolute() or ".." in artifact_path.parts or not artifact_path.parts or artifact_path.parts[0]!="execution":
                    raise ValueError(f"{rid}: unsafe native {label} trajectory artifact path")
                native_file=submission.joinpath(*artifact_path.parts)
                if not native_file.is_file() or native_file.is_symlink() or _sha(native_file)!=item.get("sha256"):
                    raise ValueError(f"{rid}: native {label} trajectory artifact hash mismatch")
                native_files[label]=native_file
            native_trajectory=native_files.get("trajectory",native_files.get("positions"))
            velocity_trajectory=native_files.get("velocities")
            if trajectory != native_trajectory:
                if velocity_trajectory is not None:
                    raise ValueError(f"{rid}: paired-dump analysis path must identify its native positions dump")
                manifest_path=trajectory.parent/"trajectory-analysis-manifest.json"
                if not manifest_path.is_file() or manifest_path.is_symlink():
                    raise ValueError(f"{rid}: merged analysis trajectory manifest is missing")
                manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
                parent_id=manifest.get("parent_run_id")
                parent=next((x for x in ledger["runs"] if x.get("run_id")==parent_id and x.get("status")=="complete"),None)
                if (trajectory.name!="trajectory-analysis.dump" or not parent
                        or manifest.get("analysis_dump_sha256")!=_sha(trajectory)
                        or manifest.get("extension_dump_sha256")!=artifact.get("sha256")):
                    raise ValueError(f"{rid}: merged analysis trajectory is not bound to native parent/extension dumps")
                parent_ref=parent.get("native_artifacts",{}).get("trajectory",{})
                parent_path=submission.joinpath(*PurePosixPath(parent_ref["path"]).parts)
                if (not parent_path.is_file() or _sha(parent_path)!=manifest.get("parent_dump_sha256")
                        or manifest.get("duplicate_boundary_frame_removed") not in (True,False)
                        or manifest.get("analysis_dump_sha256")!=_native_concatenated_dump_hash(
                            parent_path,native_trajectory,manifest.get("duplicate_boundary_frame_removed"))):
                    raise ValueError(f"{rid}: merged analysis trajectory parent hash mismatch")
            if result.get("trajectory_sha256")!=_sha(trajectory):
                raise ValueError(f"{rid}: results.json trajectory hash does not bind replayed dump")
            log_path=None; input_path=None; positive=[]; warning_failures=[]; thermostat_targets=[]
            steps=boxes=com=vel=None
            report_base={"run_id":rid,"trajectory_path":str(trajectory),"trajectory_sha256":_sha(trajectory),
                "trajectory_bytes":trajectory.stat().st_size,
                "native_trajectory_artifacts":[{"role":label,"path":str(path),"sha256":_sha(path),"bytes":path.stat().st_size} for label,path in native_files.items()],
                "ledger_executed_steps":int(row["executed_steps"]),"status":"PASS"}
            try:
                if not math.isclose(float(row.get("T_K",float("nan"))),trusted_temperature,rel_tol=0,abs_tol=1e-9):
                    raise ValueError(f"{rid}: ledger temperature differs from public task temperature")
                input_ref=row.get("native_artifacts",{}).get("input",{})
                input_rel=PurePosixPath(str(input_ref.get("path","")))
                if input_rel.is_absolute() or ".." in input_rel.parts or not input_rel.parts or input_rel.parts[0]!="execution":
                    raise ValueError(f"{rid}: unsafe native input artifact path")
                input_path=submission.joinpath(*input_rel.parts)
                if not input_path.is_file() or input_path.is_symlink() or _sha(input_path)!=input_ref.get("sha256"):
                    raise ValueError(f"{rid}: native input artifact hash mismatch")
                input_text=input_path.read_text(encoding="utf-8",errors="replace")
                sorted_dumps=_native_input_sorted_dump_paths(input_text)
                thermostat_targets=_native_input_thermostat_temperatures(input_text)
                if not thermostat_targets or any(not math.isclose(t,trusted_temperature,rel_tol=0,abs_tol=1e-8) for t in thermostat_targets):
                    raise ValueError(f"{rid}: native thermostat temperature does not match the public task temperature")
                log_ref=row.get("native_artifacts",{}).get("log",{})
                log_rel=PurePosixPath(str(log_ref.get("path","")))
                if log_rel.is_absolute() or ".." in log_rel.parts or not log_rel.parts or log_rel.parts[0]!="execution":
                    raise ValueError(f"{rid}: unsafe native log artifact path")
                log_path=submission.joinpath(*log_rel.parts)
                if not log_path.is_file() or log_path.is_symlink() or _sha(log_path)!=log_ref.get("sha256"):
                    raise ValueError(f"{rid}: native log artifact hash mismatch")
                log_text=log_path.read_text(encoding="utf-8",errors="replace")
                warning_failures=_native_positive_run_no_integrator_warnings(log_text)
                if warning_failures:
                    raise ValueError(f"{rid}: NoFix warning belongs to positive-step LAMMPS run: {warning_failures}")
                loops=[(float(sec),int(count)) for sec,count in re.findall(
                    r"Loop time of\s+([0-9.eE+-]+).*?for\s+(\d+)\s+steps",log_text)]
                positive=[(sec,count) for sec,count in loops if count>0]
                if not positive or sum(count for _,count in positive)!=int(row["executed_steps"]):
                    raise ValueError(f"{rid}: positive native LAMMPS loop accounting differs from run-ledger")
                if velocity_trajectory is not None:
                    pos_name=PurePosixPath(str(artifact["positions"]["path"])).name
                    vel_name=PurePosixPath(str(artifact["velocities"]["path"])).name
                    no_ids=not _native_dump_has_ids(native_trajectory) or not _native_dump_has_ids(velocity_trajectory)
                    sort_id_verified=bool(sorted_dumps.get(pos_name)) and bool(sorted_dumps.get(vel_name)) if no_ids else False
                else:
                    no_ids=not _native_dump_has_ids(native_trajectory)
                    sort_id_verified=bool(sorted_dumps.get(native_trajectory.name)) if no_ids else False
                frame_data=_native_frames(native_trajectory,types,molecules,velocity_path=velocity_trajectory,
                                          sort_id_verified=sort_id_verified)
                steps,boxes,com,vel=frame_data
                report_base.update({"native_frame_count":int(len(steps)),"first_step":int(steps[0]),"last_step":int(steps[-1]),
                    "post_exclusion_frame_count":int(np.count_nonzero((steps-steps[0])*float(row["dt_fs"])/1000.0>=float(plan["excluded_initial_time_ps"])-1e-12))})
                report=_native_replay_run(rid,result,series,row,trajectory,types,molecules,plan,
                    series_index=series_index,series_run_count=series_run_count,frame_data=frame_data,
                    temperature_K=trusted_temperature,frozen_parameters=frozen_parameters)
                report["native_input"]={"path":str(input_path),"sha256":_sha(input_path),
                    "bytes":input_path.stat().st_size,"thermostat_temperature_targets_K":thermostat_targets,
                    "sorted_dump_id_flags":sorted_dumps}
                report["native_log"]={"path":str(log_path),"sha256":_sha(log_path),
                    "bytes":log_path.stat().st_size,"positive_loop_steps":[count for _,count in positive],
                    "positive_loop_seconds":[sec for sec,_ in positive]}
                report["status"]="PASS"
                reports.append(report)
            except (OSError,ValueError,KeyError,TypeError,OverflowError) as exc:
                report_base["status"]="FAIL";report_base["error"]=str(exc)
                if log_path is not None and log_path.is_file() and not log_path.is_symlink():
                    report_base["native_log"]={"path":str(log_path),"sha256":_sha(log_path),"bytes":log_path.stat().st_size,
                        "positive_loop_steps":[count for _,count in positive],"NoFix_positive_run_matches":warning_failures}
                if input_path is not None and input_path.is_file() and not input_path.is_symlink():
                    report_base["native_input"]={"path":str(input_path),"sha256":_sha(input_path),
                        "bytes":input_path.stat().st_size,"thermostat_temperature_targets_K":thermostat_targets}
                reports.append(report_base);replay_failed=True
    add("L2.native_estimator_replay",bool(reports) and not replay_failed,
        json.dumps({"public_structure_sha256":_sha(structure),"replayed_complete_run_count":len(reports),
            "failed_count":sum(x.get("status")!="PASS" for x in reports),
            "candidate_correlations_npz":{"path":str(series_path),"sha256":_sha(series_path),"bytes":series_path.stat().st_size},
            "runs":reports},separators=(",",":")))
    return checks


def _native_replay_selftest(policy):
    """Tiny physical counterexamples pin the estimator's easy-to-miss rules."""
    required_policy={"NC0_ordered_pairs","NC_fixed_origin_ordered_pairs",
        "NC_refreshed_ordered_pairs","C_current_total_e2_A2_ps-2",
        "C_current_self_e2_A2_ps-2","C_current_distinct_e2_A2_ps-2",
        "GK_total_e2_A2_ps-1","GK_self_e2_A2_ps-1","GK_distinct_e2_A2_ps-1"}
    if not required_policy.issubset(set(policy.get("required_arrays",[]))):
        raise AssertionError("refs self-pin does not enumerate the core replay arrays")
    temperature_policy={'temperatures_K':[363.0,363.15]}
    for temperature in (363.0,363.15):
        if _collective_temperature_from_plan({'protocol':{'ensemble':f'NVT at {temperature:g} K'}},temperature_policy)!=temperature:
            raise AssertionError('nominal-363 actual-temperature resolution failed')
    try:
        _collective_temperature_from_plan({'protocol':{'ensemble':'NVT at 364 K'}},temperature_policy)
    except ValueError:
        pass
    else: raise AssertionError('off-grid temperature unexpectedly accepted')
    nested_plan={'shell_observable':{'neighbor_cutoff_Angstrom':6.0},
        'excluded_time':{s:{'exclude_first_ps':0.5} for s in ('pilot','control','adaptive','confirmation')},
        'windows':{'short':{'upper_ps':0.5},'long':{'upper_ps':2.0}}}
    resolved=_frozen_plan_replay_parameters(nested_plan)
    if (resolved['errors'] or resolved['shell_cutoff_A']!=6.0
            or resolved['excluded_by_stage']['intervention']!=0.5
            or resolved['integration_windows_ps']!=[0.5,2.0] or resolved['max_lag_ps']!=2.0
            or not resolved['origin_error']):
        raise AssertionError('nested frozen parameter aliases or missing-origin diagnostic failed')
    nested_plan['origin_stride_frames']=2
    if _frozen_plan_replay_parameters(nested_plan)['origin_error']:
        raise AssertionError('explicit frozen origin stride was not accepted')
    conflicting=dict(nested_plan,shell_cutoff_A=5.0)
    if not _frozen_plan_replay_parameters(conflicting)['errors']:
        raise AssertionError('conflicting frozen shell-cutoff aliases were accepted')
    duplicate_repr=dict(nested_plan,excluded_initial_time_ps=0.5,integration_windows_ps=[0.5,2.0])
    if _frozen_plan_replay_parameters(duplicate_repr)['errors']:
        raise AssertionError('equivalent flat and nested exclusion/window representations were rejected')
    duplicate_repr['excluded_initial_time_ps']=0.25
    if not any('exclusion times conflict' in e for e in _frozen_plan_replay_parameters(duplicate_repr)['errors']):
        raise AssertionError('conflicting flat and nested exclusion representations were accepted')
    duplicate_repr['excluded_initial_time_ps']=0.5
    duplicate_repr['integration_windows_ps']=[0.5,1.5]
    if not any('integration windows conflict' in e for e in _frozen_plan_replay_parameters(duplicate_repr)['errors']):
        raise AssertionError('conflicting flat and nested window representations were accepted')
    zero_run=("run 0\nWARNING: No fixes with time integration, atoms won't move\n"
              "Setting up Verlet run ...\nLoop time of 0.01 on 1 procs for 0 steps\n"
              "run 10\nSetting up Verlet run ...\nLoop time of 0.02 on 1 procs for 10 steps\n")
    positive_run=("run 10\nWARNING: No fixes with time integration, atoms won't move\n"
                  "Setting up Verlet run ...\nLoop time of 0.02 on 1 procs for 10 steps\n")
    unrelated_warning="WARNING: Neighbor list info is not current\nLoop time of 0.02 on 1 procs for 10 steps\n"
    if (_native_positive_run_no_integrator_warnings(zero_run)
            or len(_native_positive_run_no_integrator_warnings(positive_run))!=1
            or _native_positive_run_no_integrator_warnings(unrelated_warning)):
        raise AssertionError("run-scoped NoFix warning positive/negative fixtures failed")
    targets=_native_input_thermostat_temperatures("variable TEMP equal 363.0\nfix t all nvt temp ${TEMP} ${TEMP} 0.1\n")
    wrong_targets=_native_input_thermostat_temperatures("fix t all nvt temp 364 364 0.1\n")
    if targets!=[363.0,363.0] or not wrong_targets or all(t==363.0 for t in wrong_targets):
        raise AssertionError("native thermostat temperature binding fixtures failed")
    # Unequal populations make ordered-pair normalization visibly directional.
    species={"choline":np.asarray([0,1]),"chloride":np.asarray([2]),"urea":np.asarray([3,4])}
    xyz=np.asarray([[0.,0,0],[1.,0,0],[1.5,0,0],[4.,0,0],[7.,0,0]])
    box=np.asarray([10.,10.,10.]); counts=np.zeros((3,3)); fixed=np.zeros((3,3)); refreshed=np.zeros((3,3))
    names=_NATIVE_SPECIES
    lag_xyz=xyz.copy(); lag_xyz[2]=[6.,0,0]; lag_xyz[3]=[1.4,0,0]
    for ai,a in enumerate(names):
        for bi,b in enumerate(names):
            ia,ib=species[a],species[b]
            d0=_native_min_image(xyz[ia][:,None,:]-xyz[ib][None,:,:],box)
            d1=_native_min_image(lag_xyz[ia][:,None,:]-lag_xyz[ib][None,:,:],box)
            shell0=np.einsum("ijk,ijk->ij",d0,d0)<=4.0
            shell1=np.einsum("ijk,ijk->ij",d1,d1)<=4.0
            if ai==bi:
                np.fill_diagonal(shell0,False); np.fill_diagonal(shell1,False)
            counts[ai,bi]=shell0.sum()/len(ia)
            fixed[ai,bi]=(shell0&shell1).sum()/len(ia)
            refreshed[ai,bi]=shell1.sum()/len(ia)
    pop=np.asarray([len(species[s]) for s in names],dtype=float)
    if np.max(np.abs(pop[:,None]*counts-pop[None,:]*counts.T))>1e-12:
        raise AssertionError("small ordered-pair reciprocity positive case failed")
    if not math.isclose(float(counts[0,0]),1.0,rel_tol=0,abs_tol=1e-12):
        raise AssertionError("same-species origin self-pairs were not excluded")
    if np.array_equal(fixed,refreshed):
        raise AssertionError("small fixed-vs-refreshed-shell counterexample is ineffective")
    if np.allclose(counts,counts.T):
        raise AssertionError("small ordered-pair transpose counterexample is ineffective")
    velocity=np.asarray([[1.,0,0],[2.,0,0],[-1.,0,0],[3.,0,0],[4.,0,0]])
    q=np.asarray([1.,1.,-1.,0.,0.])
    current=velocity*q[:,None]
    total=float(np.dot(current.sum(axis=0),current.sum(axis=0)))
    self_term=float(np.einsum("ic,ic->",current,current))
    distinct=total-self_term
    if not math.isclose(total,self_term+distinct,rel_tol=0,abs_tol=1e-12):
        raise AssertionError("small CJJ self/distinct positive case failed")
    if math.isclose(total,self_term,rel_tol=0,abs_tol=1e-12):
        raise AssertionError("small omitted-distinct counterexample is ineffective")
    # Verify the production lag-chunk broadcasting against a scalar reference.
    tiny_pos=np.stack((xyz,lag_xyz,xyz,lag_xyz))
    tiny_vel=np.stack((velocity,velocity*0.5,velocity*1.5,velocity*0.25))
    for ai,a in enumerate(names):
        for bi,b in enumerate(names):
            ia,ib=species[a],species[b]
            origin=_native_min_image(tiny_pos[0][ia][:,None,:]-tiny_pos[0][ib][None,:,:],box)
            shell0=np.einsum("ijk,ijk->ij",origin,origin)<=4.0
            if ai==bi: np.fill_diagonal(shell0,False)
            direct_counts=[]; direct_vel=[]
            for k in range(4):
                delta=_native_min_image(tiny_pos[k][ia][:,None,:]-tiny_pos[k][ib][None,:,:],box)
                now=np.einsum("ijk,ijk->ij",delta,delta)<=4.0
                if ai==bi: np.fill_diagonal(now,False)
                direct_counts.append(int(np.count_nonzero(shell0 & now)))
                pair_v=np.einsum("ic,jc->ij",tiny_vel[0,ia],tiny_vel[k,ib])
                direct_vel.append(float(pair_v[shell0].sum()))
            delta=_native_min_image(tiny_pos[:4][:,ia][:,:,None,:]-tiny_pos[:4][:,ib][:,None,:,:],box)
            now=np.einsum("kijc,kijc->kij",delta,delta)<=4.0
            if ai==bi: now[:,np.arange(len(ia)),np.arange(len(ib))]=False
            chunk_counts=np.count_nonzero(now & shell0[None,:,:],axis=(1,2))
            chunk_vel=np.einsum("ic,kjc->kij",tiny_vel[0,ia],tiny_vel[:4,ib])
            chunk_vel=np.where(shell0[None,:,:],chunk_vel,0).sum(axis=(1,2))
            if (not np.array_equal(chunk_counts,np.asarray(direct_counts))
                    or not np.allclose(chunk_vel,direct_vel,rtol=0,atol=1e-12)):
                raise AssertionError("chunked native shell/correlation replay differs from scalar reference")

# ---- Task 46 candidate-submitted provenance checks ----
"""Cross-check candidate-submitted execution provenance; it is not host attestation."""

import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath

SCHEMA = "case05-candidate-execution-provenance/v2"
MAX_ALLOCATIONS = 18
MAX_CONCURRENT_JOBS = 1
FILE_KINDS = ("batch", "stdout", "stderr", "scheduler_record")


def _normalize_scheduler_state(value):
    return {"completed":"complete", "complete":"complete",
            "failed":"failed", "unknown":"unknown"}.get(value.lower(), value) if isinstance(value,str) else value


def _provenance_format_selftest():
    if (_normalize_scheduler_state("COMPLETED")!="complete"
            or _normalize_scheduler_state("FAILED")!="failed"
            or _normalize_scheduler_state("UNKNOWN")!="unknown"
            or _normalize_scheduler_state("CANCELLED")!="CANCELLED"):
        raise AssertionError("scheduler state normalization accepted an unsupported state")
    with tempfile.TemporaryDirectory(prefix="task46-provenance-files-") as temp:
        root=Path(temp); run=root/"execution"/"run1"; run.mkdir(parents=True)
        files={}
        for kind in FILE_KINDS:
            path=run/f"{kind}.dat"; path.write_text(kind)
            files[kind]={"path":path.relative_to(root).as_posix(),"sha256":_sha(path)}
        extra=run/"trajectory.dump"; extra.write_text("trajectory bytes")
        files["trajectory"]={"path":extra.relative_to(root).as_posix(),"sha256":_sha(extra)}
        actual,ok=_validate_provenance_file_refs(root,"run1",files)
        if not ok or "trajectory" not in actual:
            raise AssertionError("additional hash-bound execution reference was rejected")
        files["trajectory"]["sha256"]="0"*64
        if _validate_provenance_file_refs(root,"run1",files)[1]:
            raise AssertionError("additional execution reference with wrong hash was accepted")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class _VerifierIntegrityError(RuntimeError):
    """A trusted verifier asset or its internal self-test is unavailable/invalid."""


def _trusted_public_output_contract(local_path=None, harbor_path=None):
    """Resolve source-tree or immutable Harbor assets, never APP/env copies."""
    local_path=Path(local_path) if local_path is not None else Path(__file__).resolve().parents[1]/"environment"/"assets"/"output-contract.json"
    harbor_path=Path(harbor_path) if harbor_path is not None else Path("/opt/bench07-task/environment/assets/output-contract.json")
    present=[]
    for path in (local_path,harbor_path):
        if path.is_symlink():
            raise _VerifierIntegrityError("trusted public output-contract path is a symlink")
        if path.is_file(): present.append(path)
    if not present:
        raise _VerifierIntegrityError("trusted public output-contract is unavailable")
    if len({_sha(path) for path in present})!=1:
        raise _VerifierIntegrityError("trusted public output-contract copies conflict")
    return present[0]


def _trusted_output_contract_selftest():
    with tempfile.TemporaryDirectory(prefix="task46-contract-pin-") as temp:
        root=Path(temp); local=root/"local"; harbor=root/"harbor"
        local.write_bytes(b"contract")
        harbor.write_bytes(b"contract")
        if _trusted_public_output_contract(local,harbor)!=local:
            raise AssertionError("matching trusted contract copies were not resolved")
        harbor.write_bytes(b"different")
        try:
            _trusted_public_output_contract(local,harbor)
        except _VerifierIntegrityError:
            pass
        else:
            raise AssertionError("conflicting trusted contract copies were accepted")


def _file(root: Path, raw: object) -> Path | None:
    if not isinstance(raw, str):
        return None
    rel = PurePosixPath(raw)
    if (rel.is_absolute() or rel.as_posix() != raw or not rel.parts
            or any(part in {"", ".", ".."} for part in rel.parts)
            or rel.parts[0] != "execution"):
        return None
    path = root.joinpath(*rel.parts)
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    return path if path.is_file() else None


def _validate_provenance_file_refs(submission: Path, run_id, files):
    """Validate required and additional declared execution-file references alike."""
    if not isinstance(files,dict) or not set(FILE_KINDS).issubset(files):
        return {},False
    actual={}; good=True; prefix=("execution",str(run_id))
    for kind,ref in files.items():
        if not isinstance(kind,str) or not kind or not isinstance(ref,dict):
            good=False
            continue
        path=_file(submission,ref.get("path"))
        digest=ref.get("sha256")
        raw_path=ref.get("path")
        valid=(path is not None and isinstance(digest,str) and _sha(path)==digest
               and isinstance(raw_path,str) and PurePosixPath(raw_path).parts[:2]==prefix)
        good &= valid
        if path is not None: actual[kind]=path
    return actual,good


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None


def _candidate_diagnose_provenance(submission: Path, *, answer_mode='agent') -> list[dict]:
    """Return ordinary candidate checks for the self-contained Agent lane.

    The candidate's receipt, scheduler records, scripts, and logs are mutually
    cross-checked against its run ledger. They remain candidate-submitted claims;
    no field is relabeled as a runner/host observation.
    """
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str = ""):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})

    ledger_path = submission / "run-ledger.json"
    if ledger_path.is_symlink() or not ledger_path.is_file():
        check("L2.candidate_provenance.ledger", False, "Candidate run ledger must be a regular file.")
        return checks
    ledger = _load(ledger_path)
    if not isinstance(ledger, dict) or ledger.get("schema") != "case05-author-cumulative-run-ledger/v1":
        check("L2.candidate_provenance.ledger", False, "Candidate run ledger is missing or malformed.")
        return checks
    runs = ledger.get("runs")
    if not isinstance(runs, list) or not runs or any(not isinstance(row, dict) for row in runs):
        check("L2.candidate_provenance.ledger_runs", False, "Ledger must contain a nonempty array of run records.")
        return checks
    safe_attempt_path = _file(submission, "execution/execution-receipt.json")
    safe_order_path = _file(submission, "execution/execution-order.json")
    receipt = _load(safe_attempt_path) if safe_attempt_path is not None else None
    order = _load(safe_order_path) if safe_order_path is not None else None
    if not isinstance(receipt, dict) or receipt.get("schema") != SCHEMA:
        check("L2.candidate_provenance.receipt", False, "Candidate execution receipt is missing or malformed.")
        return checks
    attempt_id = receipt.get("attempt_id")
    check("L2.candidate_provenance.attempt_id", isinstance(attempt_id, str) and bool(attempt_id.strip()))
    check("L2.candidate_provenance.origin", receipt.get("origin") == "candidate-submitted-crosschecked",
          "Candidate artifacts are cross-checked, not host-attested.")
    check("L2.candidate_provenance.historical_mode_not_selectable",
          answer_mode in {"agent", "oracle"} and receipt.get("evidence_mode") == answer_mode,
          "Execution evidence must match the trusted runner mode; no historical lane is selectable.")
    check("L2.candidate_provenance.ledger_hash",
          isinstance(receipt.get("ledger_sha256"), str) and _sha(ledger_path) == receipt.get("ledger_sha256"))

    ids = [row.get("run_id") for row in runs]
    check("L2.candidate_provenance.unique_run_ids",
          all(isinstance(rid, str) and rid not in {"", ".", ".."}
              and re.fullmatch(r"[A-Za-z0-9_.-]+", rid) for rid in ids)
          and len(set(ids)) == len(ids),
          "Run IDs must be unique, nonempty path-safe identifiers.")
    expected_order = {"schema": "case05-candidate-execution-order/v1",
                      "attempt_id": attempt_id, "run_ids": ids}
    check("L2.candidate_provenance.run_order",
          isinstance(order, dict) and order == expected_order
          and isinstance(receipt.get("order_sha256"), str)
          and safe_order_path is not None and _sha(safe_order_path) == receipt.get("order_sha256"),
          "Declared run order must equal the ordered run ledger for this attempt.")
    records = receipt.get("jobs")
    check("L2.candidate_provenance.job_inventory",
          isinstance(records, list) and len(records) == len(runs),
          "One candidate provenance record is required for every ledger attempt.")
    if not isinstance(records, list) or len(records) != len(runs):
        return checks

    record_ids = [r.get("run_id") if isinstance(r, dict) else None for r in records]
    check("L2.candidate_provenance.job_order", record_ids == ids,
          "Receipt jobs must match ledger run order exactly.")
    check("L2.candidate_provenance.unique_job_ids",
          all(isinstance(r, dict) and isinstance(r.get("job_id"), str) and r.get("job_id") for r in records)
          and len({r.get("job_id") for r in records if isinstance(r, dict)}) == len(records),
          "Every attempt needs a unique nonempty candidate job identifier.")

    all_files_ok = True
    scheduler_ok = True
    binding_ok = True
    allocation_ids: list[str] = []
    allocated_intervals: list[tuple[dt.datetime, dt.datetime]] = []
    array_ok = True
    nodes_ok = True
    times_ok = True
    for run, record in zip(runs, records):
        if not isinstance(record, dict):
            all_files_ok = scheduler_ok = binding_ok = False
            continue
        rid = run.get("run_id")
        label = str(rid)
        resources = record.get("resources")
        allocation_id = record.get("allocation_id")
        elapsed_seconds = record.get("elapsed_seconds")
        start_time, end_time = record.get("start_time"), record.get("end_time")
        try:
            start = dt.datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            end = dt.datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            timezone_aware = start.utcoffset() is not None and end.utcoffset() is not None
            elapsed_finite = (type(elapsed_seconds) is int
                              or type(elapsed_seconds) is float and math.isfinite(elapsed_seconds))
            elapsed_in_range = elapsed_finite and 0 <= elapsed_seconds <= 3600
            elapsed_matches = (timezone_aware and end >= start and elapsed_in_range
                               and abs((end - start).total_seconds() - float(elapsed_seconds)) <= 2.0)
        except (AttributeError, OverflowError, TypeError, ValueError):
            start = end = None
            timezone_aware = elapsed_finite = False
            elapsed_matches = False
        resource_ok = (isinstance(resources, dict)
                       and type(resources.get("cpus")) is int and 1 <= resources["cpus"] <= 4
                       and type(resources.get("memory_mb")) is int and 1 <= resources["memory_mb"] <= 8192
                       and type(resources.get("gpus")) is int and resources["gpus"] == run.get("gpu_count") and 0 <= resources["gpus"] <= 1
                       and type(run.get("gpu_count")) is int
                       and type(resources.get("nodes")) is int and resources["nodes"] == 1
                       and type(resources.get("walltime_minutes")) is int
                       and 1 <= resources["walltime_minutes"] <= 60
                       and elapsed_finite
                       and 0 <= elapsed_seconds <= resources["walltime_minutes"] * 60
                       and elapsed_matches
                       and (allocation_id is None or isinstance(allocation_id, str) and bool(allocation_id.strip()))
                       and (run.get("status") != "complete" or isinstance(allocation_id, str)))
        nodes_ok &= (isinstance(resources, dict) and type(resources.get("nodes")) is int
                     and resources.get("nodes") == 1)
        times_ok &= timezone_aware and elapsed_finite and elapsed_matches
        if allocation_id is not None:
            if isinstance(allocation_id, str) and allocation_id.strip():
                allocation_ids.append(allocation_id)
                if start is not None and end is not None and timezone_aware and end >= start:
                    allocated_intervals.append((start, end))
            else:
                binding_ok = False
        same_fields = (record.get("attempt_id") == attempt_id
                       and record.get("run_id") == rid
                       and record.get("job_id") == str(run.get("job_id", ""))
                       and record.get("stage") == run.get("stage")
                       and record.get("status") == run.get("status")
                       and record.get("plan_sha256") == run.get("plan_sha256")
                       and record.get("requested_steps") == run.get("requested_steps")
                       and record.get("executed_steps") == run.get("executed_steps")
                       and record.get("dt_fs") == run.get("dt_fs")
                       and record.get("gpu_count") == run.get("gpu_count")
                       and (type(record.get("exit_code")) is int or record.get("exit_code") is None))
        same_fields = same_fields and ((run.get("status") == "complete" and record.get("exit_code") == 0)
                                       or (run.get("status") != "complete" and
                                           (record.get("exit_code") is None and allocation_id is None
                                            or type(record.get("exit_code")) is int and record.get("exit_code") != 0)))
        same_fields = same_fields and resource_ok
        binding_ok &= same_fields
        files = record.get("files")
        actual_paths,file_refs_ok=_validate_provenance_file_refs(submission,rid,files)
        all_files_ok &= file_refs_ok
        if not isinstance(files,dict) or not set(FILE_KINDS).issubset(files):
            scheduler_ok = False
            continue
        batch_path = actual_paths.get("batch")
        batch_text = batch_path.read_text(encoding="utf-8", errors="replace") if batch_path else ""
        declared_array = record.get("array_job")
        array_directive = any(re.match(r"^\s*#SBATCH\s+(?:--array(?:=|\s)|-a(?:\s|=))", line)
                              for line in batch_text.splitlines())
        array_ok &= (declared_array is False
                     and not array_directive
                     and not (isinstance(record.get("job_id"), str)
                              and (any(ch in record["job_id"] for ch in "[]%")
                                   or re.fullmatch(r"\d+_\d+", record["job_id"]) is not None)))
        scheduler = _load(actual_paths["scheduler_record"]) if "scheduler_record" in actual_paths else None
        if not isinstance(scheduler, dict):
            scheduler_ok = False
            continue
        scheduler_ok &= (scheduler.get("schema") == "case05-candidate-scheduler-record/v2"
                         and scheduler.get("origin") == "candidate-submitted"
                         and scheduler.get("attempt_id") == attempt_id
                         and scheduler.get("run_id") == rid
                         and scheduler.get("job_id") == record.get("job_id")
                         and _normalize_scheduler_state(scheduler.get("state")) == record.get("status")
                         and scheduler.get("requested_steps") == run.get("requested_steps")
                         and scheduler.get("executed_steps") == run.get("executed_steps")
                         and scheduler.get("dt_fs") == run.get("dt_fs")
                         and scheduler.get("gpu_count") == run.get("gpu_count")
                         and scheduler.get("exit_code") == record.get("exit_code")
                         and scheduler.get("resources") == resources
                         and scheduler.get("array_job") is False
                         and scheduler.get("allocation_id") == allocation_id
                         and scheduler.get("elapsed_seconds") == elapsed_seconds
                         and scheduler.get("start_time") == start_time
                         and scheduler.get("end_time") == end_time)
        for kind in ("batch", "stdout", "stderr"):
            item = scheduler.get(kind)
            declared = files.get(kind)
            if not isinstance(item, dict) or not isinstance(declared, dict) or item != declared:
                scheduler_ok = False
        check("L2.candidate_provenance.record." + label, same_fields,
              "Job identity, run order, plan, status, resource and attempt fields must match the ledger.")

    check("L2.candidate_provenance.files", all_files_ok,
          "Batch, stdout, stderr and scheduler-record bytes must match their declared hashes.")
    check("L2.candidate_provenance.scheduler_crosscheck", scheduler_ok,
          "Scheduler records must bind the same attempt/job/resources and file hashes.")
    check("L2.candidate_provenance.ledger_crosscheck", binding_ok,
          "Receipt job rows must agree with the run ledger.")
    check("L3.candidate_provenance.max_allocations",
          len(allocation_ids) <= MAX_ALLOCATIONS and len(allocation_ids) == len(set(allocation_ids)),
          "At most 18 scheduler allocations may be declared; an allocation ID cannot be reassigned.")
    active_ends: list[dt.datetime] = []
    overlapping = False
    for start, end in sorted(allocated_intervals):
        active_ends = [active_end for active_end in active_ends if active_end > start]
        if len(active_ends) >= MAX_CONCURRENT_JOBS:
            overlapping = True
        active_ends.append(end)
    check("L3.candidate_provenance.max_concurrent_jobs", not overlapping,
          "Allocated job intervals must not overlap; the budget permits one concurrent job.")
    check("L3.candidate_provenance.single_node", nodes_ok,
          "Every allocated attempt must request exactly one node.")
    check("L3.candidate_provenance.non_array", array_ok,
          "Array jobs are outside the declared scheduler contract.")
    check("L3.candidate_provenance.time_intervals", times_ok,
          "Timestamps must be finite, timezone-aware, ordered, and consistent with elapsed time.")
    return checks

# ---- Task 46 remote/native diagnostics adapter ----
"""Validate new reference and Agent executions through the same native evidence contract."""


def _remote_diagnose(submission, trusted=None, answer_mode=None):
    if trusted is not None or answer_mode not in {'agent', 'oracle'}:
        raise RuntimeError('Unsupported trusted context or runner answer mode')
    return _candidate_diagnose_provenance(submission, answer_mode=answer_mode)

# ---- Root-owned private isolation preflight ----
"""Fail-closed check for the runner's root-owned private verifier mount."""

import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


CORE_NAMES = {
    "read:assessment-protocol.json",
    "read:reference-hashes.json",
    "read:refs.json",
    "read:verify.py",
    "import:verify.py",
    "read:root-sentinel",
    "overwrite:root-sentinel",
    "create:second-sentinel",
    "create:private-tests",
    "overwrite:reference-hashes.json",
}


def _isolation_preflight(tests: Path, logs: Path, answer_mode=None) -> dict:
    protocol = json.loads((tests / "assessment-protocol.json").read_text(encoding="utf-8"))
    if protocol.get("runtime_bound") and answer_mode not in {"agent", "oracle"}:
        raise RuntimeError("runner answer mode is missing or unsupported")
    protected = [tests / name for name in (
        "assessment-protocol.json", "reference-hashes.json", "refs.json", "verify.py",
    )]
    review = tests / "scientific-review.json"
    record = {"schema": "reline05-private-tests-preflight/v2", "status": "INFRA",
              "uid": os.getuid(), "euid": os.geteuid(), "answer_mode": answer_mode, "checks": []}
    sentinel = logs / ("isolation-root-" + uuid.uuid4().hex)
    second = logs / ("isolation-replay-" + uuid.uuid4().hex)
    probe = tests / (".isolation-write-" + uuid.uuid4().hex)
    probe_created = False
    try:
        if os.geteuid() != 0 or tests.is_symlink() or not tests.is_dir():
            raise RuntimeError("private tests must be a mounted root-owned directory")
        root_info = tests.stat()
        if (root_info.st_uid, root_info.st_gid, root_info.st_mode & 0o777) != (0, 0, 0o700):
            raise RuntimeError("private tests root ownership or mode mismatch")
        actual_protected = protected + ([review] if review.exists() else [])
        for path in actual_protected:
            info = path.lstat()
            if path.is_symlink() or not path.is_file() or (info.st_uid, info.st_gid, info.st_mode & 0o777) != (0, 0, 0o600):
                raise RuntimeError(f"unsafe private verifier file: {path.name}")
            path.read_bytes()

        try:
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            if exc.errno not in (errno.EROFS, errno.EACCES, errno.EPERM):
                raise RuntimeError(f"unexpected /tests write-probe error: {exc}") from exc
        else:
            probe_created = True
            os.close(fd)
            raise RuntimeError("private tests mount is writable")

        fd = os.open(sentinel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(b"case07-root-only")
        child = r"""import errno,importlib.util,json,os,sys
protected=sys.argv[1:5]; sentinel,second,create,review=sys.argv[5:9]; checks=[]
def attempt(name,fn):
 try: fn()
 except OSError as exc: return {"name":name,"result":"DENIED" if exc.errno in (errno.EACCES,errno.EPERM) else "UNEXPECTED","errno":exc.errno}
 return {"name":name,"result":"ALLOWED"}
for path in protected: checks.append(attempt("read:"+os.path.basename(path),lambda p=path:open(p,"rb").read(1)))
def import_verify():
 spec=importlib.util.spec_from_file_location("case07_private_verify",protected[-1]); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
checks.append(attempt("import:verify.py",import_verify))
checks.append(attempt("read:root-sentinel",lambda:open(sentinel,"rb").read(1)))
checks.append(attempt("overwrite:root-sentinel",lambda:open(sentinel,"wb").write(b"X")))
checks.append(attempt("create:second-sentinel",lambda:os.open(second,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)))
checks.append(attempt("create:private-tests",lambda:os.open(create,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)))
checks.append(attempt("overwrite:reference-hashes.json",lambda:open(protected[1],"wb").write(b"X")))
optional_review={"status":"ABSENT"} if review=="-" else attempt("read:scientific-review.json",lambda:open(review,"rb").read(1))
print(json.dumps({"uid":os.getuid(),"gid":os.getgid(),"capeff":open("/proc/self/status").read().split("CapEff:")[1].splitlines()[0].strip(),"checks":checks,"optional_review":optional_review},sort_keys=True))
"""
        setpriv = shutil.which("setpriv")
        if not setpriv:
            raise RuntimeError("setpriv is unavailable for private-tests isolation check")
        proc = subprocess.run(
            [setpriv, "--reuid=65534", "--regid=65534", "--clear-groups", "--no-new-privs",
             "--bounding-set=-all", "--", sys.executable, "-I", "-c", child,
             *map(str, protected), str(sentinel), str(second), str(probe), str(review if review.exists() else "-")],
            capture_output=True, text=True, timeout=20,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        record["child_stdout"] = proc.stdout
        record["child_stderr"] = proc.stderr
        if proc.returncode != 0:
            raise RuntimeError(f"UID65534 isolation probe failed: {proc.stderr[-1000:]}")
        result = json.loads(proc.stdout)
        checks = result.get("checks", [])
        names = {item.get("name") for item in checks if isinstance(item, dict)}
        if (result.get("uid") != 65534 or result.get("gid") != 65534
                or result.get("capeff") != "0000000000000000"
                or not isinstance(checks, list) or len(checks) != 10 or names != CORE_NAMES
                or any(not isinstance(item, dict) or item.get("result") != "DENIED"
                       or type(item.get("errno")) is not int
                       or item["errno"] not in (errno.EACCES, errno.EPERM) for item in checks)):
            raise RuntimeError("UID65534 isolation checks did not meet the exact denial contract")
        optional = result.get("optional_review")
        expected_optional = "DENIED" if review.exists() else "ABSENT"
        if (not isinstance(optional, dict) or optional.get("status", optional.get("result")) != expected_optional
                or (review.exists() and (type(optional.get("errno")) is not int
                                         or optional["errno"] not in (errno.EACCES, errno.EPERM)))):
            raise RuntimeError("optional historical review isolation check failed")
        record.update({"status": "PASS", "child_result": result,
                       "protected_files": [path.name for path in actual_protected],
                       "runner_tests_mount_read_only": True})
        return record
    except Exception as exc:
        record["error"] = repr(exc)
        raise
    finally:
        cleanup_errors = []
        for path in (sentinel, second):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append({"path": str(path), "error": repr(exc)})
        if probe_created:
            try:
                probe.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append({"path": str(probe), "error": repr(exc)})
        if cleanup_errors:
            record["cleanup_errors"] = cleanup_errors
            record["status"] = "INFRA"
        (logs / "private-isolation.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        if cleanup_errors:
            raise RuntimeError("private-isolation probe cleanup failed")

# ---- Runner adapter and independent scientific review gate ----
"""Runner adapter: deterministic diagnostics plus a trusted, submission-bound review."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys



APP = Path(os.environ.get("APP", "/app")).resolve()
TESTS = Path(os.environ.get("TESTS", "/tests")).resolve()
LOGS = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
REPORT = LOGS / "verification.json"
REVIEW = TESTS / "scientific-review.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_hash(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def outputs_manifest(expected: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in expected:
        directory = raw.endswith("/")
        rel = raw[:-1] if directory else raw
        if not rel or PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
            raise ValueError(f"invalid expected output path: {raw!r}")
        path = APP / rel
        current = APP
        for part in PurePosixPath(rel).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"expected output path contains a symlink: {raw}")
        if directory:
            if not path.is_dir():
                raise ValueError(f"required output directory missing: {raw}")
            for item in sorted(path.rglob("*")):
                if item.is_symlink():
                    raise ValueError(f"expected output contains a symlink: {item.relative_to(APP)}")
                if item.is_dir():
                    continue
                if not item.is_file():
                    raise ValueError(f"expected output contains a non-regular file: {item.relative_to(APP)}")
                item_rel = item.relative_to(APP).as_posix()
                if item_rel in seen:
                    raise ValueError(f"duplicate output manifest path: {item_rel}")
                seen.add(item_rel)
                rows.append({"path": item_rel, "sha256": sha256(item)})
            if not any(row["path"].startswith(rel + "/") for row in rows):
                raise ValueError(f"required output directory is empty: {raw}")
        else:
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"required output file missing or not regular: {raw}")
            if rel in seen:
                raise ValueError(f"duplicate output manifest path: {rel}")
            seen.add(rel)
            rows.append({"path": rel, "sha256": sha256(path)})
    return sorted(rows, key=lambda row: row["path"])


def protocol_data() -> dict:
    protocol_path = TESTS / "assessment-protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if not isinstance(protocol, dict) or not isinstance(protocol.get("case_id"), str):
        raise ValueError("assessment protocol must identify its case")
    outputs = protocol.get("expected_outputs")
    criteria = protocol.get("criteria")
    if not isinstance(outputs, list) or not outputs or not all(isinstance(x, str) and x for x in outputs):
        raise ValueError("assessment protocol has no valid expected_outputs")
    if len(set(outputs)) != len(outputs):
        raise ValueError("assessment protocol contains duplicate expected_outputs")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("assessment protocol has no criteria")
    required = [c.get("criterion") for c in criteria if isinstance(c, dict) and c.get("necessary") is True]
    if not required or any(not isinstance(x, str) or not x for x in required) or len(set(required)) != len(required):
        raise ValueError("assessment protocol has empty, missing, or duplicate necessary criteria")
    return protocol


def validate_review(protocol: dict, manifest: list[dict[str, str]]) -> tuple[str, dict]:
    if not isinstance(protocol, dict) or not isinstance(protocol.get("expected_outputs"), list) or not protocol["expected_outputs"]:
        raise ValueError("trusted protocol has no expected outputs")
    protocol_criteria = protocol.get("criteria")
    if not isinstance(protocol_criteria, list) or not protocol_criteria:
        raise ValueError("trusted protocol has no criteria")
    required_list = [item.get("criterion") for item in protocol_criteria
                     if isinstance(item, dict) and item.get("necessary") is True]
    if (not required_list or any(not isinstance(name, str) or not name for name in required_list)
            or len(set(required_list)) != len(required_list)):
        raise ValueError("trusted protocol has empty or duplicate necessary criteria")
    if REVIEW.is_symlink():
        raise ValueError("trusted scientific review is a symlink")
    if not REVIEW.exists():
        return "REVIEW_REQUIRED", {"reason": "No trusted submission-specific scientific review is recorded."}
    if not REVIEW.is_file():
        raise ValueError("trusted scientific review is not a regular file")
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    if not isinstance(review, dict) or review.get("schema") != "scientific-review/v1":
        raise ValueError("trusted scientific review schema mismatch")
    if review.get("case_id") != protocol.get("case_id"):
        raise ValueError("trusted scientific review case_id mismatch")
    if review.get("protocol_sha256") != sha256(TESTS / "assessment-protocol.json"):
        raise ValueError("trusted scientific review protocol hash mismatch")
    if review.get("submission_manifest_sha256") != json_hash(manifest):
        raise ValueError("trusted scientific review submission manifest mismatch")

    required = set(required_list)
    decisions = review.get("criteria")
    if not isinstance(decisions, list):
        raise ValueError("trusted scientific review criteria must be an array")
    seen: set[str] = set()
    for item in decisions:
        if not isinstance(item, dict):
            raise ValueError("trusted scientific review criterion must be an object")
        name = item.get("criterion")
        if not isinstance(name, str) or name not in required or name in seen:
            raise ValueError(f"unknown or repeated review criterion: {name!r}")
        seen.add(name)
        if item.get("verdict") not in {"PASS", "FAIL", "INFRA"}:
            raise ValueError(f"invalid review verdict for {name}")
        if not isinstance(item.get("reviewer"), str) or not item["reviewer"].strip():
            raise ValueError(f"missing reviewer identity for {name}")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError(f"review reason missing for {name}")
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"missing evidence references for {name}")
        for record in evidence:
            if not isinstance(record, dict):
                raise ValueError(f"malformed evidence reference for {name}")
            rel = record.get("path")
            if not isinstance(rel, str) or PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
                raise ValueError(f"evidence path escapes APP for {name}")
            path = APP / rel
            current = APP
            for part in PurePosixPath(rel).parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError(f"evidence path contains a symlink: {rel}")
            if not path.is_file() or path.is_symlink() or sha256(path) != record.get("sha256"):
                raise ValueError(f"evidence hash mismatch: {rel}")
    if seen != required:
        raise ValueError(f"trusted review has missing criteria: {sorted(required - seen)}")
    verdicts = {item["verdict"] for item in decisions}
    if "INFRA" in verdicts:
        raise ValueError("review records infrastructure failure; it cannot issue a scientific score")
    return ("FAIL" if "FAIL" in verdicts else "PASS"), {
        "reviewer": review.get("reviewer", "criterion-level reviewers"),
        "protocol_sha256": review["protocol_sha256"],
        "submission_manifest_sha256": review["submission_manifest_sha256"],
        "criteria": decisions,
    }


def _runner_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verifier", default=str(TESTS / "verify.py"))
    args = parser.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    info = LOGS.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError("private verifier logs must be a root-owned mode-0700 directory")
    for old in (LOGS / "reward.txt", REPORT, LOGS / "verdict.json"):
        if old.is_symlink():
            raise ValueError(f"unsafe verifier output path: {old.name}")
        old.unlink(missing_ok=True)
    _isolation_preflight(TESTS, LOGS, os.environ.get("CCB_ANSWER_MODE"))
    protocol = protocol_data()

    # Check all evaluator assets against the frozen private reference list. Public
    # input bytes are checked by the case verifier against the mounted APP tree.
    ref_file = TESTS / "reference-hashes.json"
    refs = json.loads(ref_file.read_text(encoding="utf-8"))
    if not isinstance(refs, dict) or refs.get("tests/assessment-protocol.json") != sha256(TESTS / "assessment-protocol.json"):
        raise ValueError("assessment protocol is not pinned by reference-hashes.json")
    bad = []
    for declared, expected_hash in refs.items():
        if declared.startswith("tests/"):
            path = TESTS / declared[len("tests/"):]
            if path == ref_file:
                continue
        elif declared.startswith("inputs/"):
            path = APP / declared
        else:
            raise ValueError(f"unsupported trusted reference path: {declared}")
        if path.is_symlink() or not path.is_file() or sha256(path) != expected_hash:
            bad.append(declared)
    if bad:
        raise RuntimeError(f"trusted scoring assets are invalid: {bad}")

    proc = subprocess.run(
        [sys.executable, args.verifier, "--submission", str(APP)],
        cwd=APP, capture_output=True, text=True, timeout=300,
        env={"PATH": os.environ.get("PATH", "/opt/deepmd/bin:/usr/bin:/bin"),
             "HOME": "/tmp", "APP": str(APP), "TESTS": str(TESTS), "LOGS": str(LOGS),
             "CCB_ANSWER_MODE": os.environ.get("CCB_ANSWER_MODE", ""),
             "TF_CPP_MIN_LOG_LEVEL": "2", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"},
    )
    try:
        diagnostic = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError(f"diagnostic verifier returned no structured JSON (rc={proc.returncode}): {proc.stdout[-1000:]} {proc.stderr[-1000:]}") from exc
    if not isinstance(diagnostic, dict):
        raise RuntimeError("diagnostic verifier response must be an object")
    status = str(diagnostic.get("status", "")).upper()
    checks = diagnostic.get("checks")
    if (not isinstance(checks, list) or not checks
            or any(not isinstance(c, dict) or type(c.get("passed")) is not bool for c in checks)):
        if status not in {"PREFLIGHT_ERROR", "INFRASTRUCTURE_ERROR", "ENV_INVALID", "ERROR"}:
            raise RuntimeError("diagnostic verifier returned missing or malformed checks")
    if proc.returncode == 2 or status in {"PREFLIGHT_ERROR", "INFRASTRUCTURE_ERROR", "ENV_INVALID", "ERROR"}:
        result = {"status": "INFRA_ERROR", "agent_graded": False, "reward": None,
                  "diagnostics": diagnostic}
        REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print("INFRA_ERROR: scoring preflight or verifier failed", file=sys.stderr)
        return 2
    if proc.returncode != 0 and not (proc.returncode == 1 and status == "FAIL"):
        raise RuntimeError(f"diagnostic verifier returned unexpected exit/status: rc={proc.returncode} status={status!r}")
    if status not in {"FAIL", "SCIENTIFIC_REVIEW_REQUIRED", "REVIEW_REQUIRED", "DIAGNOSTIC_ONLY"}:
        raise RuntimeError(f"diagnostic verifier returned unsupported status {status!r}")
    if status == "FAIL" or any(not c.get("passed", False) for c in checks):
        if status != "FAIL":
            raise RuntimeError("failed diagnostic checks were not reported as FAIL")
        result = {"status": "FAIL", "reward": 0, "diagnostics": diagnostic}
        REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print("FAIL: deterministic diagnostic criterion failed", file=sys.stderr)
        (LOGS / "reward.txt").write_text("0\n", encoding="utf-8")
        return 1

    try:
        manifest = outputs_manifest(protocol["expected_outputs"])
    except ValueError as exc:
        result = {"status": "FAIL", "reward": 0, "diagnostics": diagnostic,
                  "delivery_failure": str(exc)}
        REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        (LOGS / "reward.txt").write_text("0\n", encoding="utf-8")
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    decision, review_details = validate_review(protocol, manifest)
    if decision == "REVIEW_REQUIRED":
        result = {"status": "REVIEW_REQUIRED", "implementation": "partial",
                  "diagnostics": diagnostic, "review": review_details,
                  "submission_manifest": manifest, "submission_manifest_sha256": json_hash(manifest)}
        REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print("REVIEW_REQUIRED: manual scientific adjudication is pending")
        return 0
    result = {"status": decision, "reward": 1 if decision == "PASS" else 0,
              "diagnostics": diagnostic, "review": review_details,
              "submission_manifest": manifest, "submission_manifest_sha256": json_hash(manifest)}
    REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    (LOGS / "reward.txt").write_text(f"{result['reward']}\n", encoding="utf-8")
    print(f"{decision}: trusted scientific review applied")
    return 0 if decision == "PASS" else 1

if __name__ == "__main__":
    if sys.argv[1:] == ["--runner"]:
        sys.argv = [sys.argv[0]]
        try:
            raise SystemExit(_runner_main())
        except Exception as exc:
            LOGS.mkdir(parents=True, exist_ok=True)
            if REPORT.exists():
                REPORT.unlink()
            (LOGS / "reward.txt").unlink(missing_ok=True)
            REPORT.write_text(json.dumps({"status": "INFRA_ERROR", "reward": None,
                                          "agent_graded": False, "error": str(exc)},
                                         indent=2, ensure_ascii=False) + "\n")
            print(f"INFRA_ERROR: {exc}", file=sys.stderr)
            raise SystemExit(2)
    else:
        raise SystemExit(main())
