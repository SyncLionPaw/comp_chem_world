# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Reanalyse native outer-sphere energy-gap evidence and its statistical limitations.
from __future__ import annotations

"""Run the standalone Case 04 verifier and enforce the runner reward protocol."""
import json
import math
import os
import subprocess
import sys
import stat
import signal
from decimal import Decimal
from pathlib import Path

def _grade_entry() -> int:
    tests = Path(os.environ.get('TESTS', '/tests')).resolve()
    app = Path(os.environ.get('APP', '/app')).resolve()
    output_raw = Path(os.environ.get('CASE04_OUTPUT', app / 'final'))
    output = output_raw.absolute()
    logs = Path(os.environ.get('LOGS', '/logs/verifier')).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    reward_path = logs / 'reward.txt'
    report_path = logs / 'verification.json'
    try:
        secure_verifier_paths(tests,logs,app)
    except (EnvironmentFailure,OSError) as exc:
        reward_path.unlink(missing_ok=True)
        report={'status':'ENV_INVALID','error':str(exc)}
        try: report_path.write_text(json.dumps(report,ensure_ascii=False)+'\n')
        except OSError: pass
        print(json.dumps(report,ensure_ascii=False))
        return 2
    reward_path.unlink(missing_ok=True)
    report_path.unlink(missing_ok=True)

    def env_invalid(message: str, stdout: str='', stderr: str='') -> int:
        reward_path.unlink(missing_ok=True)
        report = {'status': 'ENV_INVALID', 'error': message}
        if stdout:
            (logs / 'verify.stdout.log').write_text(stdout)
        if stderr:
            (logs / 'verify.stderr.log').write_text(stderr)
        report_path.write_text(json.dumps(report, ensure_ascii=False) + '\n')
        print(json.dumps(report, ensure_ascii=False))
        return 2
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONNOUSERSITE': '1', 'APP': str(app), 'TESTS': str(tests), 'LOGS': str(logs)}
    try:
        proc = subprocess.run([sys.executable, str(tests / 'verify.py'), str(output)], cwd=str(app), capture_output=True, text=True, timeout=180, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return env_invalid(f'verifier could not complete: {type(exc).__name__}: {exc}')
    (logs / 'verify.stdout.log').write_text(proc.stdout)
    (logs / 'verify.stderr.log').write_text(proc.stderr)
    try:
        report = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        return env_invalid(f'invalid verifier JSON: {exc}', proc.stdout, proc.stderr)
    if not isinstance(report, dict):
        return env_invalid('verifier report must be a JSON object', proc.stdout, proc.stderr)
    status = report.get('status')
    overall = report.get('overall')
    if 'overall' in report and overall != status:
        return env_invalid('verifier overall status contradicts its status field', proc.stdout, proc.stderr)
    reward = report.get('reward')
    valid_reward = type(reward) in (int, float) and math.isfinite(reward)
    if status == 'PASS' and proc.returncode == 0 and valid_reward and (reward == 1):
        reward_path.write_text('1\n')
    elif status == 'FAIL' and proc.returncode == 1 and valid_reward and (reward == 0):
        reward_path.write_text('0\n')
    elif status in {'ENVIRONMENT_ERROR', 'ENV_INVALID'} and proc.returncode == 2 and ('reward' not in report):
        report['status'] = 'ENV_INVALID'
    else:
        return env_invalid('verifier status, reward, and exit code are inconsistent', proc.stdout, proc.stderr)
    report_path.write_text(json.dumps(report, ensure_ascii=False) + '\n')
    print(json.dumps(report, ensure_ascii=False))
    return proc.returncode
#!/usr/bin/env python3
"""Independent scorer for the approved Case 04 revision-3 budget contract.

Reference inputs are frozen under tests/refs.json. Scientific values are rebuilt
from the pinned revision-3 native records, the frozen task and sampling files,
and pinned public source assets. This program never imports GPAW or launches a
scientific calculation.
"""
import csv, hashlib, json, math, os, re, shutil, subprocess, sys, tempfile, stat
from pathlib import Path, PurePosixPath

class ScientificFailure(Exception): pass
class EnvironmentFailure(Exception): pass

def require(ok, msg):
    if not ok: raise ScientificFailure(msg)

def require_text(value, msg):
    require(isinstance(value, str) and bool(value.strip()), msg)

def _strict_json_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate JSON object key: '+key)
        result[key]=value
    return result

def readj(p):
    try: return json.loads(Path(p).read_text(encoding='utf-8'),object_pairs_hook=_strict_json_object)
    except Exception as e: raise ScientificFailure(f'cannot parse JSON {p}: {e}')

def digest(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def num(x): return type(x) in (int,float) and math.isfinite(x)
def near(a,b,tol=1e-8): return num(a) and num(b) and abs(a-b)<=tol

def run_candidate_analysis(script, cwd):
    if os.name!='posix' or os.geteuid()!=0:
        raise EnvironmentFailure('candidate replay isolation requires a root POSIX verifier container')
    nobody_uid=65534; nobody_gid=65534; workspace=Path(cwd).resolve()
    script_path=Path(script).resolve(); output_dir=script_path.parent; native_dir=output_dir/'native'
    for current,dirs,files in os.walk(workspace):
        here=Path(current)
        output_tree=(here==output_dir or output_dir in here.parents) and not (here==native_dir or native_dir in here.parents)
        try:
            if output_tree: os.chown(here,nobody_uid,nobody_gid); os.chmod(here,0o755)
            else: os.chown(here,0,0); os.chmod(here,0o555)
        except OSError as exc: raise EnvironmentFailure(f'cannot protect replay directory {here}: {exc}') from exc
        for name in files:
            path=here/name
            if output_tree and path!=script_path:
                continue
            try: os.chown(path,0,0); os.chmod(path,0o444)
            except OSError as exc: raise EnvironmentFailure(f'cannot protect replay input {path}: {exc}') from exc
    try:
        proc=subprocess.Popen([sys.executable,str(script)],cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'PYTHONNOUSERSITE':'1','HOME':'/tmp'},
            user=nobody_uid,group=nobody_gid,extra_groups=(),start_new_session=True)
        try:
            stdout,stderr=proc.communicate(timeout=60)
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass
        except subprocess.TimeoutExpired:
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            stdout,stderr=proc.communicate()
            raise subprocess.TimeoutExpired([sys.executable,str(script)],60,output=stdout,stderr=stderr)
        return subprocess.CompletedProcess([sys.executable,str(script)],proc.returncode,stdout,stderr)
    except subprocess.TimeoutExpired as exc:
        raise ScientificFailure('candidate analysis replay exceeded 60 seconds') from exc
    except OSError as exc:
        raise EnvironmentFailure(f'cannot start isolated candidate replay: {type(exc).__name__}: {exc}') from exc

def secure_verifier_paths(tests,logs,app):
    if os.name!='posix' or os.geteuid()!=0:
        raise EnvironmentFailure('private verifier evidence isolation requires a root POSIX verifier container')
    tests=Path(tests).resolve(); logs=Path(logs).resolve(); contract=Path(app).resolve()/'assets/output-contract.json'
    if tests.is_symlink() or not tests.is_dir() or logs.is_symlink() or not contract.is_file():
        raise EnvironmentFailure('trusted verifier paths are missing or redirected')
    try:
        for current,dirs,files in os.walk(tests,followlinks=False):
            here=Path(current)
            if here.is_symlink(): raise EnvironmentFailure('private tests tree contains a symlink')
            os.chown(here,0,0); os.chmod(here,0o700)
            for name in dirs+files:
                path=here/name
                if path.is_symlink(): raise EnvironmentFailure('private tests tree contains a symlink')
                os.chown(path,0,0); os.chmod(path,0o700 if path.is_dir() else 0o400)
        logs.mkdir(parents=True,exist_ok=True)
        for current,dirs,files in os.walk(logs,followlinks=False):
            here=Path(current); os.chown(here,0,0); os.chmod(here,0o700)
            for name in files:
                path=here/name
                if path.is_symlink(): raise EnvironmentFailure('verifier log tree contains a symlink')
                os.chown(path,0,0); os.chmod(path,0o600)
        os.chown(contract,0,0); os.chmod(contract,0o444)
    except OSError as exc:
        raise EnvironmentFailure(f'cannot isolate trusted verifier paths: {type(exc).__name__}: {exc}') from exc

def validate_sampling_design_structure(design, plan):
    expected_ensembles={e['ensemble'] for e in plan['ensembles']}
    require(isinstance(design,dict) and design.get('schema')=='case04-sampling-design-audit/v1'
            and isinstance(design.get('ensembles'),dict)
            and set(design['ensembles'])==expected_ensembles,
            'sampling-design-audit coverage/schema mismatch')
    for name in expected_ensembles:
        item=design['ensembles'][name]
        require(isinstance(item,dict) and isinstance(item.get('layers'),list)
                and isinstance(item.get('distinct_frame_pair_inclusion_probability_matrix'),list),
                'sampling-design ensemble entry has invalid types')
        require(all(isinstance(layer,dict) for layer in item['layers']),
                'sampling-design layer entry has invalid type')
        require(all(isinstance(row,list) and all(isinstance(cell,dict) for cell in row)
                    for row in item['distinct_frame_pair_inclusion_probability_matrix']),
                'sampling-design pair-probability matrix has invalid types')

def eqtree(a,b,tol=1e-8):
    if isinstance(b,dict): return isinstance(a,dict) and set(a)==set(b) and all(eqtree(a[k],b[k],tol) for k in b)
    if isinstance(b,list): return isinstance(a,list) and len(a)==len(b) and all(eqtree(x,y,tol) for x,y in zip(a,b))
    if isinstance(b,bool): return type(a) is bool and a is b
    if b is None or isinstance(b,str): return a==b
    if isinstance(b,(int,float)): return type(a) in (int,float) and not isinstance(a,bool) and math.isfinite(a) and abs(a-b)<=tol
    return a==b

def sha_checked(root, rel, expected):
    p=root/rel
    if not p.is_file(): raise EnvironmentFailure(f'missing frozen source input: {rel}')
    got=digest(p)
    if got!=expected: raise EnvironmentFailure(f'frozen source hash mismatch: {rel}')
    return got

def _safe_source(root, rel):
    relpath=PurePosixPath(rel)
    if relpath.is_absolute() or relpath.as_posix()!=rel or '..' in relpath.parts:
        raise EnvironmentFailure(f'unsafe trusted source path: {rel!r}')
    base=Path(root)
    p=base.joinpath(*relpath.parts)
    current=base
    for part in relpath.parts:
        current=current/part
        if current.is_symlink(): raise EnvironmentFailure(f'trusted source contains a symlink: {rel}')
    if not p.is_file(): raise EnvironmentFailure(f'missing trusted source: {rel}')
    return p

def materialize_sources(app_root, tests_root, refs, destination):
    """Reconstruct private JSON and hash-bound public native data in an isolated tree."""
    import tarfile
    archive_spec=refs.get('public_native_archive',{})
    archive=_safe_source(app_root,archive_spec.get('path',''))
    if digest(archive)!=archive_spec.get('sha256'):
        raise EnvironmentFailure('public native archive hash mismatch')
    native_bytes={}
    with tarfile.open(archive,'r:gz') as handle:
        for member in handle.getmembers():
            rel=PurePosixPath(member.name)
            if rel.is_absolute() or '..' in rel.parts or rel.parts[0]!='native' or member.issym() or member.islnk():
                raise EnvironmentFailure('unsafe public native archive member')
            if member.isdir(): continue
            if not member.isfile() or member.name in native_bytes:
                raise EnvironmentFailure('duplicate or unsupported native archive member')
            stream=handle.extractfile(member)
            if stream is None: raise EnvironmentFailure('unreadable native archive member')
            native_bytes[member.name]=stream.read()
    expected_members={v['path'] for v in refs.get('native_bindings',{}).values()}
    if set(native_bytes)!=expected_members:
        raise EnvironmentFailure('native archive member coverage mismatch')
    def bound_bytes(binding):
        if not isinstance(binding,dict) or set(binding)!={'root','path'}:
            raise EnvironmentFailure('invalid trusted source binding')
        if binding['root']=='app': return _safe_source(app_root,binding['path']).read_bytes()
        if binding['root']=='tests':
            value=refs.get('private_evidence_utf8',{}).get(binding['path'])
            if not isinstance(value,str): raise EnvironmentFailure('private JSON evidence is missing')
            return value.encode('utf-8')
        if binding['root']=='public-native': return native_bytes[binding['path']]
        raise EnvironmentFailure('unknown trusted source root')
    def materialize(logical,binding,expected):
        raw=bound_bytes(binding)
        if hashlib.sha256(raw).hexdigest()!=str(expected).removeprefix('sha256:'):
            raise EnvironmentFailure('frozen source hash mismatch: '+logical)
        target=_safe_source_parent(destination,logical)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
    for group,hashes in [('source_bindings','source_hashes'),('native_bindings','native_hashes')]:
        bindings=refs.get(group)
        if not isinstance(bindings,dict) or set(bindings)!=set(refs.get(hashes,{})):
            raise EnvironmentFailure('trusted source binding coverage mismatch')
        for logical,expected in refs[hashes].items(): materialize(logical,bindings[logical],expected)

def _safe_source_parent(root, rel):
    relpath=PurePosixPath(rel)
    if relpath.is_absolute() or relpath.as_posix()!=rel or '..' in relpath.parts:
        raise EnvironmentFailure(f'unsafe logical source path: {rel!r}')
    return Path(root).joinpath(*relpath.parts)

def load_sources(root, refs):
    for rel,h in refs['source_hashes'].items(): sha_checked(root,rel,h)
    tasks=readj(root/'runtimes/hpc/case04/review-v3/tasks.json')
    plan=readj(root/'runtimes/hpc/case04/review-v3/sampling_plan.json')
    require(len(tasks)==10 and len({t['index'] for t in tasks})==10,'frozen task table must contain ten unique tasks')
    require(plan.get('budget_revision')==3 and plan.get('submission_authorization',{}).get('budget_revision')==3,'wrong frozen sampling/authorization revision')
    trace=readj(root/'analysis/revision3/spin-audit/author-trajectory-spin-audit.json')['sampled_geometry_traceability']
    require(trace.get('unique_geometry_count')==8 and trace.get('all_match') is True and len(trace.get('records',[]))==8,'source trajectory-frame geometry audit is incomplete')
    task_by={t['geometry_id']:t for t in tasks if t['stage']=='production'}
    seen=set()
    for rec in trace['records']:
        t=task_by.get(rec.get('geometry_id')); c=rec.get('comparisons',{})
        require(t is not None and rec.get('ensemble')==t['ensemble'] and rec.get('trajectory_frame_zero_based')==t['frame_zero_based'],'trajectory audit source-frame mapping mismatch')
        require(rec.get('geometry_sha256')==t['geometry_sha256'] and rec.get('task_geometry')==t['geometry_path'],'trajectory audit geometry hash/path mismatch')
        require(c.get('numbers_exact') is True and c.get('pbc_exact') is True and c.get('all_match_at_1e-12') is True and num(c.get('positions_max_abs_diff_A')) and c['positions_max_abs_diff_A']<=1e-12 and num(c.get('cell_max_abs_diff_A')) and c['cell_max_abs_diff_A']<=1e-12 and num(c.get('masses_max_abs_diff_amu')) and c['masses_max_abs_diff_amu']<=1e-12,'trajectory-frame exact geometry comparison failed')
        seen.add(rec['geometry_id'])
    require(seen==set(task_by),'source trajectory audit does not cover all production geometries')
    return tasks,plan

def expected_manifest(root,tasks,plan,refs):
    files={}
    for rel in refs['native_hashes']:
        sha_checked(root,rel,refs['native_hashes'][rel]); files[rel]=refs['native_hashes'][rel]
    runtime={rel:refs['source_hashes'][rel] for rel in refs['source_hashes'] if rel.startswith('runtimes/hpc/case04/review-v3/')}
    assets={rel:refs['source_hashes'][rel] for rel in refs['source_hashes'] if ('10ps.traj' in rel or rel.endswith('/calc.py') or rel.endswith('computegaps.py') or rel.endswith('methods.json') or rel.endswith('OS_budget.json') or rel.endswith('energy-convention-audit.json'))}
    return {'schema':'case04-source-manifest/v1','case_id':'case-04-outer-sphere-budgeted','budget_revision':3,
      'source_identity':'frozen revision-3 tasks, sampling plan, geometry inputs, recovered native results/logs, and public source assets',
      'new_scientific_calculations':0,'runtime_inputs_sha256':runtime,'public_source_inputs_sha256':assets,
      'native_evidence_sha256':files,'native_attempt_records':20,'geometry_count':8,'paired_rows':10,
      'author_trajectory_frame_audit_sha256':refs['source_hashes']['analysis/revision3/spin-audit/author-trajectory-spin-audit.json'],
      'source_binding':'project-local pinned sources; portable only within this project evidence bundle'}

def audit_native(root,tasks,refs):
    nd=root/'analysis/revision3/native'
    ledger=[]
    try:
        ledger=[json.loads(x) for x in (nd/'attempts.jsonl').read_text().splitlines() if x.strip()]
    except Exception as e: raise ScientificFailure(f'native attempt ledger invalid: {e}')
    require(len(ledger)==20 and len({x.get('id') for x in ledger})==20,'revision-3 attempt ledger is incomplete or duplicated')
    lmap={x['id']:x for x in ledger}
    records={}; pairs=[]
    expected={(t['index'],s) for t in tasks for s in (0,-1)}
    for d in sorted(nd.glob('attempt-*')):
        if not d.is_dir(): continue
        try:
            r=readj(d/'result.json'); inp=readj(d/'input.json')
            gpaw=(d/'gpaw.txt').read_text(); cdft=(d/'cdft.txt').read_text(); ts=(d/'ts09.txt').read_text()
            geo=readj(d/'geometry.json')
        except Exception as e: raise ScientificFailure(f'{d.name}: missing/corrupt native evidence: {e}')
        idx,state=r.get('task_index'),r.get('state'); key=(idx,state)
        require(key in expected and key not in records,f'unexpected or duplicate task/state native record {key}')
        t=next(x for x in tasks if x['index']==idx)
        require(r.get('status')=='CONVERGED',f'{d.name}: result not converged')
        require(r.get('id')==d.name and inp.get('id')==d.name and d.name in lmap,f'{d.name}: attempt identity mismatch')
        logentry=lmap[d.name]
        require(logentry.get('task_index')==idx and logentry.get('state')==state and logentry.get('setting')==t['setting'],f'{d.name}: ledger mapping mismatch')
        require(r.get('geometry_id')==t['geometry_id'] and r.get('geometry_sha256')==t['geometry_sha256'] and inp.get('geometry_sha256')==t['geometry_sha256'] and digest(d/'geometry.json')==t['geometry_sha256'],f'{d.name}: geometry identity/hash mismatch')
        require(inp.get('task_index')==idx and inp.get('state')==state and inp.get('setting')==t['setting'] and inp.get('CO2_indices_zero_based')==t['CO2_indices_zero_based'],f'{d.name}: input/task identity mismatch')
        require(r.get('CO2_indices_zero_based')==t['CO2_indices_zero_based'] and r.get('total_cell_charge')==0 and inp.get('total_cell_charge')==0,f'{d.name}: CO2 atom map or total cell charge mismatch')
        require(geo.get('numbers') is not None and [geo['numbers'][i] for i in t['CO2_indices_zero_based']]==[6,8,8],f'{d.name}: mapped region is not C,O,O')
        target=0 if state==0 else -1
        require(r.get('target_local_charge')==target and inp.get('target_local_charge')==target,f'{d.name}: local charge target mismatch')
        require(bool(re.findall(r'Converged after (\d+) iterations\.',gpaw)),f'{d.name}: no converged GPAW SCF block')
        require('Optimization terminated successfully.' in cdft,f'{d.name}: cDFT optimizer did not terminate successfully')
        errs=re.findall(r'Errors? \[e\]:\s*([-+0-9.eE]+)',cdft)
        residual=r.get('residual_e'); tol=r.get('local_charge_tolerance_e')
        # Revision-3's runtime residual gate is 0.05 e for base and tight runs;
        # the tight run uses a smaller optimizer gtol, not a changed residual gate.
        expected_tol=0.05
        require(num(residual) and num(tol) and near(tol,expected_tol,1e-12) and near(inp.get('local_charge_tolerance_e'),expected_tol,1e-12) and abs(residual)<=tol,f'{d.name}: missing/nonfinite/out-of-tolerance charge residual')
        require(errs and abs(abs(float(errs[-1]))-abs(residual))<=5.1e-5,f'{d.name}: cDFT log residual does not match recorded residual')
        for field in ('E_DFT_without_constraint_potential_eV','TS09_correction_eV','E_PBE_TS09_eV','local_charge_e'):
            require(field in r and num(r[field]),f'{d.name}: missing/nonfinite {field}')
        require(abs(r['E_DFT_without_constraint_potential_eV']+r['TS09_correction_eV']-r['E_PBE_TS09_eV'])<1e-8,f'{d.name}: helper plus TS09 sum mismatch')
        tsval=re.search(r'vdW correction:\s*([-+0-9.eE]+)',ts)
        require(tsval and abs(float(tsval[1])-r['TS09_correction_eV'])<1e-8,f'{d.name}: TS09 log/result mismatch')
        moment_blocks=re.findall(r'Total magnetic moment: \(([^)]*)\)',gpaw)
        require(moment_blocks and all(num(float(x.strip())) for x in moment_blocks[-1].split(',')),f'{d.name}: final total moment missing/nonfinite')
        # Reconstruct the stored legacy helper from the final printed GPAW block (six-decimal precision).
        block=gpaw.rsplit('Energy contributions relative to reference atoms:',1)[-1]
        vals={}
        for label in ('Kinetic','Potential','XC','Local','Entropy (-ST)','SIC'):
            m=re.search(r'^'+re.escape(label)+r':\s*([+-]?[0-9]+\.[0-9]+)',block,re.M)
            require(m is not None,f'{d.name}: missing printed energy component {label}')
            vals[label]=float(m[1])
        require(abs(vals['SIC'])<1e-12,f'{d.name}: nonzero SIC has unverified energy convention')
        printed_helper=sum(vals[x] for x in ('Kinetic','Potential','XC','Local'))-vals['Entropy (-ST)']
        require(abs(r['E_DFT_without_constraint_potential_eV']-printed_helper)<1e-5,f'{d.name}: printed helper reconstruction mismatch')
        records[key]={'task':t,'result':r,'native_id':d.name,
                      'magnetization_components_mu_B':[float(x.strip()) for x in moment_blocks[-1].split(',')]}
    require(set(records)==expected,f'native state coverage mismatch: missing={sorted(expected-set(records))}')
    for t in tasks:
        n=records[(t['index'],0)]['result']; f=records[(t['index'],-1)]['result']
        gap=f['E_PBE_TS09_eV']-n['E_PBE_TS09_eV']
        pairs.append({'task':t,'neutral':n,'anion':f,'gap':gap})
    return records,pairs

def expected_rows(pairs):
    out=[]
    for p in pairs:
        t,n,a=p['task'],p['neutral'],p['anion']
        out.append({'system':t['system'],'ensemble':t['ensemble'],'frame':t['frame_zero_based'],'stage':t['stage'],'stratum':t['stratum'],'inclusion_probability':t['inclusion_probability'],'setting':t['setting'],
          'E_neutral_eV':n['E_PBE_TS09_eV'],'E_neutral_DFT_eV':n['E_DFT_without_constraint_potential_eV'],'E_neutral_TS09_eV':n['TS09_correction_eV'],
          'E_anion_eV':a['E_PBE_TS09_eV'],'E_anion_DFT_eV':a['E_DFT_without_constraint_potential_eV'],'E_anion_TS09_eV':a['TS09_correction_eV'],
          'gap_eV':p['gap'],'converged':True,'native_id':f"task-{t['index']:02d}/{n['id']}+{a['id']}",'geometry_id':t['geometry_id'],
          'neutral_local_charge_e':n['local_charge_e'],'anion_local_charge_e':a['local_charge_e'],'neutral_residual_e':n['residual_e'],'anion_residual_e':a['residual_e'],'source_quality':'recovered-native-result.json'})
    return out

def calc_stats(pairs,plan):
    result={}
    for ens in sorted({p['task']['ensemble'] for p in pairs if p['task']['stage']=='production'}):
        sample=[p for p in pairs if p['task']['ensemble']==ens and p['task']['stage']=='production']
        e=next(x for x in plan['ensembles'] if x['ensemble']==ens); N=e['target_population_size']
        require(len(sample)==2 and len({p['task']['stratum'] for p in sample})==2,f'{ens}: expected two distinct production strata')
        strata=plan['selected_strata'][ens]
        require(set(p['task']['stratum'] for p in sample)==set(strata),f'{ens}: selected strata mismatch')
        for p in sample:
            t=p['task']; pi=1/(2*t['stratum_size'])
            require(near(t['inclusion_probability'],pi,1e-15),f'{ens}: incorrect marginal inclusion probability')
        mean=sum(p['gap']/p['task']['inclusion_probability'] for p in sample)/N
        raw2=sum(p['gap']**2/p['task']['inclusion_probability'] for p in sample)/N
        descriptive=sum(p['gap'] for p in sample)/len(sample)
        empirical_var=sum((p['gap']-descriptive)**2 for p in sample)/len(sample)
        result[ens]={'target_population_size':N,'observed_base_gaps_eV':[p['gap'] for p in sample],
          'observed_strata':[p['task']['stratum'] for p in sample],
          'marginal_inclusion_probabilities':[p['task']['inclusion_probability'] for p in sample],
          'HT_mean_gap_eV':mean,'HT_raw_second_moment_eV2':raw2,
          'empirical_two_point_mean_eV':descriptive,'empirical_two_point_variance_ddof0_eV2':empirical_var,
          'variance_status':'One selected frame per stratum gives zero joint inclusion for distinct frames within that stratum; no model-free unbiased finite-population variance/design-variance estimator.'}
    return result

def _source_sensitivity(pairs):
    """Rebuild matched base/tight changes from native result records."""
    by_geometry={(p['task']['geometry_id'],p['task']['stage']):p for p in pairs}
    result={}
    for tight in (p for p in pairs if p['task']['stage']=='sensitivity'):
        t=tight['task']; base=by_geometry.get((t['geometry_id'],'production'))
        require(base is not None and t['geometry_id'] not in result,
                'sensitivity task has no unique matched production geometry')
        b0,b1=base['neutral'],base['anion']; a0,a1=tight['neutral'],tight['anion']
        result[t['geometry_id']]={
            'ensemble':t['ensemble'],'geometry_id':t['geometry_id'],
            'base_gap_eV':base['gap'],'tight_gap_eV':tight['gap'],
            'gap_change_eV':tight['gap']-base['gap'],
            'neutral_total_energy_change_eV':a0['E_PBE_TS09_eV']-b0['E_PBE_TS09_eV'],
            'anion_total_energy_change_eV':a1['E_PBE_TS09_eV']-b1['E_PBE_TS09_eV'],
            'neutral_DFT_change_eV':a0['E_DFT_without_constraint_potential_eV']-b0['E_DFT_without_constraint_potential_eV'],
            'neutral_TS09_change_eV':a0['TS09_correction_eV']-b0['TS09_correction_eV'],
            'anion_DFT_change_eV':a1['E_DFT_without_constraint_potential_eV']-b1['E_DFT_without_constraint_potential_eV'],
            'anion_TS09_change_eV':a1['TS09_correction_eV']-b1['TS09_correction_eV'],
            'neutral_local_charge_base_e':b0['local_charge_e'],
            'neutral_local_charge_tight_e':a0['local_charge_e'],
            'anion_local_charge_base_e':b1['local_charge_e'],
            'anion_local_charge_tight_e':a1['local_charge_e'],
            'energy_component_split':'Recovered result.json reports both DFT and TS09 terms; exact changes are reported above.'}
    return result

def _require_numeric_mapping(actual, expected, message):
    require(isinstance(actual,dict) and set(actual)==set(expected),message)
    for key,value in expected.items():
        require(near(actual.get(key),value,1e-8),message+f' ({key})')

def _check_ht_ensemble_tree(actual, expected, message):
    require(isinstance(actual,dict) and set(actual)==set(expected),message)
    for ens, expected_item in expected.items():
        item=actual[ens]
        require(isinstance(item,dict) and set(item)==set(expected_item),message+f' ({ens} fields)')
        require_text(item.get('variance_status'),message+f' ({ens} variance_status)')
        actual_values={key:value for key,value in item.items() if key!='variance_status'}
        expected_values={key:value for key,value in expected_item.items() if key!='variance_status'}
        require(eqtree(actual_values,expected_values,1e-8),message+f' ({ens} values)')

def _different_strata_probability_matches(value, expected, sizes):
    if num(value):
        return near(value,expected,1e-15)
    if not isinstance(value,str):
        return False
    text=value.strip()
    if text=='1/(6*N_h*N_k)':
        return True
    try:
        numeric=float(text)
    except ValueError:
        numeric=None
    if num(numeric) and near(numeric,expected,1e-15):
        return True
    match=re.fullmatch(
        r'1\s*/\s*\(\s*6\s*\*\s*(\d+)\s*\*\s*(\d+)\s*\)\s*=\s*'
        r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)', text)
    if not match:
        return False
    first,second=int(match.group(1)),int(match.group(2))
    try:
        stated=float(match.group(3))
    except ValueError:
        return False
    if not num(stated) or sorted((first,second))!=sorted(sizes):
        return False
    return near(1/(6*first*second),expected,1e-15) and near(stated,expected,1e-15)

def _check_probability_claims(actual, tasks, plan):
    expected_ensembles={e['ensemble'] for e in plan['ensembles']}
    require(isinstance(actual,dict) and set(actual)==expected_ensembles,
            'sampling-probability claim must cover exactly four plan ensembles')
    plan_by={e['ensemble']:e for e in plan['ensembles']}
    for ens in expected_ensembles:
        selected=[t for t in tasks if t['ensemble']==ens and t['stage']=='production']
        require(len(selected)==2 and len({t['stratum'] for t in selected})==2,
                f'{ens}: sampling-probability source tasks are incomplete')
        marginal={str(t['stratum']):1/(2*t['stratum_size']) for t in selected}
        item=actual[ens]
        require(isinstance(item,dict) and set(item)=={
            'marginal_pi_i_by_stratum','same_stratum_distinct_frame_pi_ij',
            'different_strata_pi_ij','target_population_size'},
            f'{ens}: sampling-probability claim fields mismatch')
        require(eqtree(item['marginal_pi_i_by_stratum'],marginal,1e-15),
                f'{ens}: sampling marginal inclusion probabilities mismatch')
        require(near(item['same_stratum_distinct_frame_pi_ij'],0.0,1e-15),
                f'{ens}: same-stratum joint inclusion probability must be zero')
        t0,t1=selected
        pi_ij=1/(6*t0['stratum_size']*t1['stratum_size'])
        different=item['different_strata_pi_ij']
        require(_different_strata_probability_matches(
            different,pi_ij,(t0['stratum_size'],t1['stratum_size'])),
                f'{ens}: different-strata joint inclusion probability mismatch')
        require(item['target_population_size']==plan_by[ens]['target_population_size'],
                f'{ens}: sampling target population size mismatch')

def _check_standard_claims(claim, diag_rows, audit, tasks, plan):
    conventions={
        'free_minus_external_gap_plus_state_specific_TS09_eV':('free_minus_external_plus_state_specific_TS09_HT','free_minus_external_gap_plus_state_specific_TS09_eV'),
        'extrapolated_minus_external_gap_plus_state_specific_TS09_eV':('extrapolated_minus_external_plus_state_specific_TS09_HT','extrapolated_minus_external_gap_plus_state_specific_TS09_eV')}
    require(isinstance(claim,dict) and claim.get('six_decimal_source_precision_eV')==1e-6,
            'standard-gap claims omit six-decimal printed-source precision')
    states={(r['task_index'],r['state']):r for r in audit['states']}
    row_by={r['task_index']:r for r in diag_rows}
    ensembles={e['ensemble'] for e in plan['ensembles']}
    for suffix,(claim_key,field) in conventions.items():
        section=claim.get(claim_key)
        require(isinstance(section,dict) and set(section)==ensembles,
                f'{suffix} must cover exactly all four production ensembles')
        for ens in ensembles:
            selected=[t for t in tasks if t['ensemble']==ens and t['stage']=='production']
            gaps=[]
            for t in selected:
                n=states[(t['index'],0)]; a=states[(t['index'],-1)]
                energy_key='printed_free_minus_external_eV' if suffix.startswith('free_') else 'printed_extrapolated_minus_external_eV'
                gap=(a[energy_key]+a['TS09_eV'])-(n[energy_key]+n['TS09_eV'])
                gaps.append(gap)
                require(near(row_by[t['index']].get(field),gap,1e-8),
                        f'{suffix}: diagnostic production gap differs from printed source reconstruction')
            n=next(e['target_population_size'] for e in plan['ensembles'] if e['ensemble']==ens)
            ht=sum(g/t['inclusion_probability'] for g,t in zip(gaps,selected))/n
            item=section[ens]
            require(isinstance(item,dict) and set(item)=={'HT_mean_eV','observed_gaps_eV'}
                    and near(item.get('HT_mean_eV'),ht,1e-8)
                    and eqtree(item.get('observed_gaps_eV'),gaps,1e-8),
                    f'{suffix}/{ens}: observed gaps or HT mean mismatch')

def _check_marcus_extensions(marcus, stats, pairs, root):
    methods=readj(root/'inputs/methods.json')
    require(near(marcus.get('temperature_K'),methods['OS']['temperature_K'],1e-12),
            'marcus.json temperature differs from pinned OS methods')
    neutral=stats['2K_neutral']['HT_mean_gap_eV']-stats['water_neutral']['HT_mean_gap_eV']
    anion=stats['2K_anion']['HT_mean_gap_eV']-stats['water_anion']['HT_mean_gap_eV']
    contrasts=marcus.get('between_system_point_contrasts')
    require(isinstance(contrasts,dict) and set(contrasts)=={
        'neutral_ensemble_2K_minus_water_eV','anion_ensemble_2K_minus_water_eV','warning'}
        and near(contrasts.get('neutral_ensemble_2K_minus_water_eV'),neutral,1e-8)
        and near(contrasts.get('anion_ensemble_2K_minus_water_eV'),anion,1e-8),
        'Marcus between-system point contrasts mismatch')
    sens=_source_sensitivity(pairs)
    got=marcus.get('setting_sensitivity')
    require(isinstance(got,list) and len(got)==len(sens)
            and {x.get('geometry_id') for x in got if isinstance(x,dict)}==set(sens),
            'Marcus setting-sensitivity geometry coverage mismatch')
    for item in got:
        expected=sens[item['geometry_id']]
        require(isinstance(item,dict) and set(item)==set(expected) and eqtree({k:v for k,v in item.items() if k!='energy_component_split'},{k:v for k,v in expected.items() if k!='energy_component_split'},1e-8),
                f"Marcus setting-sensitivity values mismatch for {item['geometry_id']}")
    flips=marcus.get('contrast_flip_thresholds')
    sensitivity_rows=list(sens.values())
    require(len(sensitivity_rows)==2,'expected two matched setting-sensitivity geometries')
    # The frozen task order defines the two geometry-specific shifts used by the stated scenario.
    sensitivity_tasks=[p for p in pairs if p['task']['stage']=='sensitivity']
    sensitivity_rows=[sens[p['task']['geometry_id']] for p in sensitivity_tasks]
    by_ensemble={p['task']['ensemble']:sens[p['task']['geometry_id']] for p in sensitivity_tasks}
    delta=by_ensemble['2K_anion']['gap_change_eV']-by_ensemble['water_anion']['gap_change_eV']
    # A bias can be reported as a magnitude or as the signed correction that
    # brings each contrast to zero; the public contract does not fix this convention.
    signed_biases=(isinstance(flips,dict)
        and near(flips.get('neutral_differential_contrast_bias_to_reverse_sign_eV'),-neutral,1e-8)
        and near(flips.get('anion_differential_contrast_bias_to_reverse_sign_eV'),-anion,1e-8)
        and isinstance(flips.get('warning'),str)
        and bool(re.fullmatch(r'proof:[A-Za-z0-9_.:-]+',flips['warning'])))
    numeric_flips={k:v for k,v in flips.items() if k!='warning'} if isinstance(flips,dict) else flips
    if signed_biases:
        numeric_flips=dict(numeric_flips)
        numeric_flips['neutral_differential_contrast_bias_to_reverse_sign_eV']=abs(neutral)
        numeric_flips['anion_differential_contrast_bias_to_reverse_sign_eV']=abs(anion)
    _require_numeric_mapping(numeric_flips,
        {'neutral_2K_minus_water_HT_point_contrast_eV':neutral,
         'neutral_differential_contrast_bias_to_reverse_sign_eV':abs(neutral),
         'neutral_equal_opposite_bias_per_system_to_reverse_sign_eV':abs(neutral)/2,
         'anion_2K_minus_water_HT_point_contrast_eV':anion,
         'anion_differential_contrast_bias_to_reverse_sign_eV':abs(anion),
         'anion_equal_opposite_bias_per_system_to_reverse_sign_eV':abs(anion)/2,
         'anion_setting_correction_if_two_single_geometry_shifts_were_generalizable_eV':delta,
         'anion_contrast_after_that_explicit_unverified_setting_scenario_eV':anion+delta},
        'Marcus contrast-flip thresholds mismatch')

def _candidate_output_inventory(root):
    root=Path(root)
    if root.is_symlink(): raise ScientificFailure('candidate output root cannot be a symlink')
    try: resolved_root=root.resolve(strict=True)
    except OSError as exc: raise ScientificFailure('candidate output root is missing or unreadable') from exc
    if not resolved_root.is_dir(): raise ScientificFailure('candidate output root is not a directory')
    inventory={}
    for path in resolved_root.rglob('*'):
        try: mode=path.lstat().st_mode
        except OSError as exc: raise ScientificFailure('candidate artifact is unreadable') from exc
        if stat.S_ISLNK(mode): raise ScientificFailure(f'candidate artifact contains a symlink: {path.relative_to(resolved_root)}')
        if stat.S_ISDIR(mode): continue
        if not stat.S_ISREG(mode): raise ScientificFailure(f'candidate artifact is not a regular file: {path.relative_to(resolved_root)}')
        try: path.resolve(strict=True).relative_to(resolved_root)
        except (OSError,ValueError) as exc: raise ScientificFailure('candidate artifact escapes its output root') from exc
        rel=path.relative_to(resolved_root).as_posix()
        posix=PurePosixPath(rel)
        if not rel or posix.is_absolute() or posix.as_posix()!=rel or '..' in posix.parts or '\\' in rel:
            raise ScientificFailure('candidate artifact has an unsafe or noncanonical relative path')
        inventory[rel]=digest(path)
    return inventory

def _proof_close(actual, expected, unit='eV'):
    if isinstance(expected,dict):
        return isinstance(actual,dict) and set(actual)==set(expected) and all(_proof_close(actual[k],v,unit) for k,v in expected.items())
    if isinstance(expected,list):
        return isinstance(actual,list) and len(actual)==len(expected) and all(_proof_close(a,b,unit) for a,b in zip(actual,expected))
    if isinstance(expected,bool): return type(actual) is bool and actual is expected
    if isinstance(expected,(int,float)):
        return num(actual) and abs(float(actual)-float(expected)) <= (1e-15 if unit=='probability' else 1e-8)
    return actual==expected

def _proof_rows_match(actual,expected,key_fields,unit='eV'):
    if not isinstance(actual,list) or len(actual)!=len(expected): return False
    def key(row): return tuple(row[k] for k in key_fields)
    try:
        aa=sorted(actual,key=key); ee=sorted(expected,key=key)
    except (KeyError,TypeError): return False
    return _proof_close(aa,ee,unit)

def _candidate_csv_rows(path,required_columns):
    path=Path(path)
    require(not path.is_symlink() and path.is_file() and path.stat().st_size>0,
            f'candidate CSV is missing, empty, or redirected: {path.name}')
    try:
        with path.open(newline='',encoding='utf-8') as handle:
            reader=csv.DictReader(handle); headers=reader.fieldnames; rows=list(reader)
    except (OSError,UnicodeError,csv.Error) as exc:
        raise ScientificFailure(f'candidate CSV cannot be parsed: {path.name}: {type(exc).__name__}: {exc}') from exc
    require(isinstance(headers,list) and len(headers)==len(set(headers)) and None not in headers
            and set(required_columns)<=set(headers),f'candidate CSV header mismatch: {path.name}')
    for index,row in enumerate(rows,1):
        require(None not in row and set(row)==set(headers) and all(isinstance(v,str) for v in row.values()),
                f'candidate CSV row shape mismatch: {path.name}:{index}')
        require(all(row.get(key) not in ('',None) for key in required_columns),
                f'candidate CSV row is missing a required value: {path.name}:{index}')
    return rows

def _candidate_float(value,context):
    try: result=float(value)
    except (TypeError,ValueError,OverflowError) as exc:
        raise ScientificFailure(f'candidate numeric field is malformed: {context}') from exc
    require(math.isfinite(result),f'candidate numeric field is nonfinite: {context}')
    return result

def _scope_set_matches(actual,values):
    if not isinstance(actual,str): return False
    tokens=actual.split(';')
    expected=set(values)
    return bool(expected) and all(tokens) and len(tokens)==len(set(tokens)) and set(tokens)==expected

def _validate_json_schema(value,schema,root_schema=None):
    root_schema=root_schema or schema
    if '$ref' in schema:
        node=root_schema
        for part in schema['$ref'].lstrip('#/').split('/'):
            node=node[part.replace('~1','/').replace('~0','~')]
        return _validate_json_schema(value,node,root_schema)
    if 'oneOf' in schema:
        matches=0
        for option in schema['oneOf']:
            try: _validate_json_schema(value,option,root_schema); matches+=1
            except ScientificFailure: pass
        require(matches==1,'schema oneOf validation failed')
        return
    if 'const' in schema: require(value==schema['const'],'schema const mismatch')
    if 'enum' in schema: require(value in schema['enum'],'schema enum mismatch')
    typ=schema.get('type')
    if typ=='object':
        require(isinstance(value,dict),'schema object type mismatch')
        require(set(schema.get('required',[]))<=set(value),'schema required property missing')
        props=schema.get('properties',{})
        if schema.get('additionalProperties') is False: require(set(value)<=set(props),'schema has unknown object key')
        for key,item in value.items():
            if key in props: _validate_json_schema(item,props[key],root_schema)
    elif typ=='array':
        require(isinstance(value,list),'schema array type mismatch')
        require(len(value)>=schema.get('minItems',0),'schema array shorter than minimum')
        if 'maxItems' in schema: require(len(value)<=schema['maxItems'],'schema array longer than maximum')
        for item in value: _validate_json_schema(item,schema.get('items',{}),root_schema)
    elif typ=='string':
        require(isinstance(value,str) and len(value)>=schema.get('minLength',0),'schema string type/length mismatch')
        if 'pattern' in schema: require(re.fullmatch(schema['pattern'],value) is not None,'schema string pattern mismatch')
    elif typ=='boolean': require(type(value) is bool,'schema boolean mismatch')
    elif typ=='integer': require(type(value) is int,'schema integer mismatch')
    elif typ=='number': require(num(value),'schema number is nonfinite or wrong type')
    elif typ=='null': require(value is None,'schema null type mismatch')

def _eval_proof_expr(expr, sources, quantities, assumptions, expected_unit=None, quantity_resolver=None):
    require(isinstance(expr,dict) and isinstance(expr.get('op'),str),'invalid proof expression')
    op=expr['op']
    if op=='source':
        require(set(expr)=={'op','id'} and expr['id'] in sources,'unknown proof source')
        result=sources[expr['id']]
    elif op=='literal':
        require(set(expr)=={'op','value','unit'} and num(expr['value']),'invalid expression literal')
        result=(Decimal(str(expr['value'])),expr['unit'],None,False)
    elif op=='quantity':
        require(set(expr)=={'op','id'},'invalid quantity reference')
        if quantity_resolver is not None: result=quantity_resolver(expr['id'])
        else:
            require(expr['id'] in quantities,'unknown quantity reference'); result=quantities[expr['id']]
    elif op=='assumption':
        require(set(expr)=={'op','id'} and expr['id'] in assumptions,'unknown assumption reference')
        item=assumptions[expr['id']]
        value=item.get('scalar')
        require(value is not None,'this assumption is not a scalar expression')
        result=(value,'eV',('assumption',expr['id']),True)
    elif op in ('neg','abs'):
        require(set(expr)=={'op','arg'},'invalid unary expression')
        v,u,s,c=_eval_proof_expr(expr['arg'],sources,quantities,assumptions,None,quantity_resolver)
        result=(-v if op=='neg' else abs(v),u,s,c)
    else:
        require(op in {'add','sub','mul','div','min','max','eq','lt','le','gt','ge'} and set(expr)=={'op','args'} and isinstance(expr['args'],list) and len(expr['args'])==2,'invalid binary expression')
        a=_eval_proof_expr(expr['args'][0],sources,quantities,assumptions,None,quantity_resolver); b=_eval_proof_expr(expr['args'][1],sources,quantities,assumptions,None,quantity_resolver)
        unit_dims={'dimensionless':{},'probability':{},'eV':{'energy':1},'eV^2':{'energy':2},
                   'frame':{'frame':1},'mu_B':{'moment':1},'e':{'charge':1}}
        require(a[1] in unit_dims and b[1] in unit_dims,'unsupported proof-expression unit')
        result_unit=None
        if op in {'mul','div'}:
            dims=dict(unit_dims[a[1]])
            for key,power in unit_dims[b[1]].items():
                dims[key]=dims.get(key,0)+(power if op=='mul' else -power)
                if dims[key]==0: del dims[key]
            units_by_dims={tuple(sorted(d.items())):u for u,d in unit_dims.items() if u!='probability'}
            result_unit=units_by_dims.get(tuple(sorted(dims.items())))
            if result_unit=='dimensionless' and op=='mul' and 'probability' in (a[1],b[1]): result_unit='probability'
            require(result_unit is not None,'proof expression produces an unsupported compound unit')
        else:
            require(a[1]==b[1],'proof expression unit mismatch')
        if a[2] is None: scope=b[2]
        elif b[2] is None: scope=a[2]
        elif a[2]==b[2]: scope=a[2]
        elif op in {'sub','add'} and a[2][0]==b[2][0] and a[2][0] in {'ensemble_ht','energy_convention'}:
            left_neg=expr['args'][0].get('op')=='neg'; right_neg=expr['args'][1].get('op')=='neg'
            def direct_term(node): return node.get('op') in {'source','quantity'}
            def simple_negated_term(node): return node.get('op')=='neg' and isinstance(node.get('arg'),dict) and direct_term(node['arg'])
            if a[2][0]=='energy_convention':
                a_prefix,a_ensemble=a[2][1].split('/',1); b_prefix,b_ensemble=b[2][1].split('/',1)
                require(a_prefix==b_prefix,'cross-ensemble convention contrasts must use the same energy convention')
            else: a_ensemble,b_ensemble=a[2][1],b[2][1]
            if op=='sub':
                require(direct_term(expr['args'][0]) and direct_term(expr['args'][1]),'cross-scope subtraction requires direct source/quantity terms')
                pair=(a_ensemble,b_ensemble)
            else:
                require((direct_term(expr['args'][0]) and simple_negated_term(expr['args'][1])) or
                        (simple_negated_term(expr['args'][0]) and direct_term(expr['args'][1])),
                        'cross-scope addition must be one direct term plus one explicitly negated direct term')
                pair=(b_ensemble,a_ensemble) if left_neg else (a_ensemble,b_ensemble)
            scope=('cross_ensemble_contrast',pair[0]+'-'+pair[1])
        else: raise ScientificFailure('proof expression combines incompatible scopes')
        conditional=a[3] or b[3]
        if op=='add': value,unit=a[0]+b[0],a[1]
        elif op=='sub': value,unit=a[0]-b[0],a[1]
        elif op=='mul':
            value=a[0]*b[0]; unit=result_unit
        elif op=='div':
            require(b[0]!=0,'division by zero in proof expression'); value=a[0]/b[0]; unit=result_unit
        elif op=='min': value,unit=min(a[0],b[0]),a[1]
        elif op=='max': value,unit=max(a[0],b[0]),a[1]
        elif op=='eq': value,unit=a[0]==b[0],'boolean'
        elif op=='lt': value,unit=a[0]<b[0],'boolean'
        elif op=='le': value,unit=a[0]<=b[0],'boolean'
        elif op=='gt': value,unit=a[0]>b[0],'boolean'
        else: value,unit=a[0]>=b[0],'boolean'
        result=(value,unit,scope,conditional)
    if expected_unit is not None: require(result[1]==expected_unit,'proof expression has wrong unit')
    return result

def _validate_scientific_argument(out,root,refs,tasks,plan,pairs,records,stats,diag_rows,energy_audit):
    """Evaluate v2.2 typed scientific claims against the independently rebuilt data."""
    contract_path=_safe_source(Path(os.environ.get('APP','/app')),'assets/output-contract.json')
    contract=readj(contract_path); pp=contract.get('scientific_proof_protocol',{})
    require(pp.get('schema')=='case04-scientific-proof-protocol/v2.2','unsupported proof protocol')
    data=readj(Path(out)/'scientific-claims.json')
    require(data.get('schema')=='case04-scientific-claims/v2.2','scientific-claims schema mismatch')
    _validate_json_schema(data,contract['artifact_schemas']['scientific-claims.json']['required_fields_and_types'])
    ens_names=sorted(stats); ensembles=set(ens_names); sources={}
    def source(key,value,unit,scope,id): sources[key]=(Decimal(str(value)),unit,(scope,id),False)
    for ens,s in stats.items():
        source('ht_gap/'+ens,s['HT_mean_gap_eV'],'eV','ensemble_ht',ens)
        e=next(e for e in plan['ensembles'] if e['ensemble']==ens); N=e['target_population_size']; q,rem=divmod(N,4)
        source('population_size/'+ens,N,'frame','finite_population',ens); source('observed_count/'+ens,2,'frame','ensemble_ht',ens)
        for h in range(4):
            nh=q+(h<rem); source(f'inclusion_pi/{ens}/{h}',1/(2*nh),'probability','ensemble_ht',ens)
            for j in range(4):
                nj=q+(j<rem); source(f'inclusion_pi_ij/{ens}/{h}/{j}',0 if h==j else 1/(6*nh*nj),'probability','ensemble_ht',ens)
    for p in pairs:
        t=p['task']; source(f"sample_gap/{t['index']}/{t['setting']}",p['gap'],'eV','geometry',t['geometry_id'])
    by_state={(x['task_index'],x['state']):x for x in energy_audit['states']}
    for conv in ('R3','free','extrapolated'):
        for ens in ens_names:
            terms=[]
            for pair in pairs:
                t=pair['task']
                if t['ensemble']!=ens or t['stage']!='production': continue
                if conv=='R3': gap=pair['gap']
                else:
                    f='printed_free_minus_external_eV' if conv=='free' else 'printed_extrapolated_minus_external_eV'
                    n=by_state[(t['index'],0)]; a=by_state[(t['index'],-1)]
                    gap=(a[f]+a['TS09_eV'])-(n[f]+n['TS09_eV'])
                terms.append(gap/t['inclusion_probability'])
            source(f'convention_ht/{conv}/{ens}',sum(terms)/next(e['target_population_size'] for e in plan['ensembles'] if e['ensemble']==ens),'eV','energy_convention',conv+'/'+ens)
    moment_catalog={}
    for rec in records.values():
        nid=rec['native_id']; r=rec['result']; gp=(Path(root)/'analysis/revision3/native'/nid/'gpaw.txt').read_text()
        moments=re.findall(r'Total magnetic moment: \(([^)]*)\)',gp)
        comps=[Decimal(x.strip()) for x in moments[-1].split(',')]
        moment_catalog[nid]=[float(x) for x in comps]
        for j,v in enumerate(comps): source(f'magnetization/{nid}/component_{j}',v,'mu_B','state_pair',nid)
        source(f'magnetization/{nid}/magnitude',sum(v*v for v in comps).sqrt(),'mu_B','state_pair',nid)
        source(f'local_charge/{nid}',rec['result']['local_charge_e'],'e','state_pair',nid)
        for j,v in enumerate(comps): source(f'magnetization/{nid}/component_{j}',v,'mu_B','state_pair',nid)
        source(f'magnetization/{nid}/magnitude',sum(v*v for v in comps).sqrt(),'mu_B','state_pair',nid)
        source(f'local_charge/{nid}',r['local_charge_e'],'e','state_pair',nid)
    raw_ass=data.get('assumptions'); require(isinstance(raw_ass,list),'assumptions must be an array')
    assumptions={}
    akeys={'unobserved_frame_value':{'ensemble','gap_eV'},'ensemble_gap_bias':{'ensemble','bias_eV'},'equilibrium_or_distribution':{'system','model'},'setting_transfer':{'source_geometry_ids','target_scope','bound_eV'},'state_assignment':{'state_record_ids','assignment'},'finite_population_bounds':{'ensemble','lower_gap_eV','upper_gap_eV'}}
    for a in raw_ass:
        require(isinstance(a,dict) and set(a)=={'id','kind','scope','parameters'} and a['id'] not in assumptions and a['kind'] in akeys,'invalid/duplicate assumption')
        require(set(a['parameters'])==akeys[a['kind']] and set(a['scope'])=={'kind','id'},'assumption shape mismatch')
        p=a['parameters']; scalar=None; extra={}
        if a['kind']=='unobserved_frame_value':
            require(p['ensemble'] in ensembles and a['scope']=={'kind':'finite_population','id':p['ensemble']},'unobserved-frame assumption scope mismatch')
            scalar=_eval_proof_expr(p['gap_eV'],sources,{},{} ,'eV')[0]
        elif a['kind']=='ensemble_gap_bias':
            require(p['ensemble'] in ensembles and a['scope']=={'kind':'energy_convention','id':p['ensemble']},'ensemble-bias assumption scope mismatch')
            scalar=_eval_proof_expr(p['bias_eV'],sources,{},{} ,'eV')[0]
        elif a['kind']=='equilibrium_or_distribution':
            require(a['scope']=={'kind':'finite_population','id':p['system']},'equilibrium/distribution assumption scope mismatch')
        elif a['kind']=='setting_transfer':
            require(a['scope']=={'kind':'geometry','id':p['target_scope']} and set(p['source_geometry_ids'])<=set(_source_sensitivity(pairs)),'setting-transfer assumption geometry/scope mismatch')
            scalar=_eval_proof_expr(p['bound_eV'],sources,{},{} ,'eV')[0]
        elif a['kind']=='state_assignment':
            known_ids={x['native_id'] for x in records.values()}; require(a['scope']['kind']=='state_pair' and set(p['state_record_ids'])<=known_ids,'state-assignment assumption has unknown native records')
        elif a['kind']=='finite_population_bounds':
            require(p['ensemble'] in ensembles and a['scope']=={'kind':'finite_population','id':p['ensemble']},'finite-population bounds scope mismatch')
            lo=_eval_proof_expr(p['lower_gap_eV'],sources,{},{} ,'eV')[0]; hi=_eval_proof_expr(p['upper_gap_eV'],sources,{},{} ,'eV')[0]
            require(lo<=hi and all(lo<=Decimal(str(v))<=hi for v in stats[p['ensemble']]['observed_base_gaps_eV']),'assumed bounds invalid/exclude observations'); extra={'lower':lo,'upper':hi}
        assumptions[a['id']]={'raw':a,'scalar':scalar,**extra}
    qraw=data.get('quantities'); require(isinstance(qraw,list) and qraw,'quantities required')
    qrecords={}
    for q in qraw:
        require(isinstance(q,dict) and set(q)=={'id','expression','unit','scope','value'} and q['id'] not in qrecords,'invalid/duplicate quantity')
        qrecords[q['id']]=q
    quantities={}; active=set()
    def qval(qid):
        require(qid in qrecords and qid not in active,'unknown/cyclic quantity reference')
        if qid in quantities:return quantities[qid]
        active.add(qid); q=qrecords[qid]
        z=_eval_proof_expr(q['expression'],sources,quantities,assumptions,q['unit'],qval)
        require(z[2] is not None and isinstance(z[2],tuple) and len(z[2])==2,
                'quantity expression must derive its scope from a source or scoped dependency')
        require(q['scope']=={'kind':z[2][0],'id':z[2][1]},'quantity scope mismatch')
        require(num(q['value']) and abs(float(z[0])-float(q['value']))<= (1e-15 if q['unit']=='probability' else 1e-8),'reported quantity differs from expression')
        active.remove(qid); quantities[qid]=z; return z
    for qid in qrecords:qval(qid)
    # Each proof has one exact, contract-defined input/report schema.
    proofs=data.get('proofs'); require(isinstance(proofs,list),'proofs must be an array')
    specs=pp.get('proof_kinds',{}); pmap={}
    for p in proofs:
        require(isinstance(p,dict) and set(p)=={'id','kind','inputs','reported'} and p['id'] not in pmap,'invalid/duplicate proof')
        require(p['kind'] in specs and set(p['inputs'])==set(specs[p['kind']]['inputs']) and set(p['reported'])==set(specs[p['kind']]['reported']),'proof schema mismatch')
        pmap[p['id']]=p
    results={}
    # Source audit and source-calculated witnesses.
    for pid,p in pmap.items():
        k,i,r=p['kind'],p['inputs'],p['reported']; results[pid]={}
        if k=='arithmetic':
            v=_eval_proof_expr(i['expression'],sources,quantities,assumptions)
            require(v[1]=='boolean' and type(r['result']) is bool and v[0] is True and r['result'] is True,'arithmetic assertion is not true')
        elif k=='source_audit':
            exp={'reported_ledger_records':len(records),'reported_unique_state_records':len(records),'reported_valid_pairs':len(pairs),'reported_base_geometries':8,'reported_tight_replays':2,'reported_source_hashes_verified':True,'reported_geometry_pairs_verified':True,'reported_state_charge_and_convergence_verified':True,'reported_energy_decomposition_verified':True}
            require(i['audit_scope']=='native_r3_source_reconstruction' and _proof_close(r,exp),'native source audit proof mismatch')
        elif k=='finite_population_completion':
            assign={x['ensemble']: _eval_proof_expr(x['value_expr'],sources,quantities,assumptions,'eV')[0] for x in i['assignments']}
            require(set(assign)==set(ens_names) and len(i['assignments'])==4,'completion must give one unobserved value per ensemble')
            rows=[]
            for ens in ens_names:
                obs=[Decimal(str(v)) for v in stats[ens]['observed_base_gaps_eV']]; N=stats[ens]['target_population_size']; vals=obs+[assign[ens]]*(N-len(obs)); mean=sum(vals)/N; var=sum((v-mean)**2 for v in vals)/N
                rows.append({'ensemble':ens,'computed_population_mean_eV':float(mean),'computed_population_variance_eV2':float(var)})
            require(_proof_rows_match(r['assignments'],rows,('ensemble',)),'completion moments incorrect'); results[pid]['rows']=rows
        elif k=='population_moment_nonidentifiability':
            comps=[pmap.get(x) for x in i['completion_proof_ids']]; require(len(comps)>=2 and all(x and x['kind']=='finite_population_completion' for x in comps) and set(i['ensembles'])==set(ens_names),'invalid moment completion refs/coverage')
            rows=[]
            for ens in ens_names:
                aa=next(x for x in comps[0]['reported']['assignments'] if x['ensemble']==ens); bb=next(x for x in comps[1]['reported']['assignments'] if x['ensemble']==ens)
                dm=bb['computed_population_mean_eV']-aa['computed_population_mean_eV']; dv=bb['computed_population_variance_eV2']-aa['computed_population_variance_eV2']; require(abs(dm)>1e-12 and abs(dv)>1e-12,'completions do not change both moments')
                rows.append({'ensemble':ens,'mean_diff_eV':dm,'variance_diff_eV2':dv})
            require(_proof_rows_match(r['reported_moment_changes'],rows,('ensemble',)),'moment nonidentifiability report mismatch')
        elif k=='ranking_nonidentifiability':
            require({(x['left_ensemble'],x['right_ensemble']) for x in i['contrast_pairs']}=={('2K_neutral','water_neutral'),('2K_anion','water_anion')},'population ranking proof must cover the neutral and anion K-minus-water targets')
            comps=[pmap.get(x) for x in i['completion_proof_ids']]; require(len(comps)>=2 and all(x and x['kind']=='finite_population_completion' for x in comps),'invalid ranking completion refs')
            rows=[]
            for c in i['contrast_pairs']:
                l,rr=c['left_ensemble'],c['right_ensemble']; dif=[]; ordering=[]
                for cp in comps:
                    dct={x['ensemble']:x['computed_population_mean_eV'] for x in cp['reported']['assignments']}; d=dct[l]-dct[rr]; dif.append(d); ordering.append('left_lower' if d<0 else 'right_lower' if d>0 else 'equal')
                require(len(set(ordering))>1 and 'equal' not in ordering,'completion does not reverse ranking')
                rows.append({'left_ensemble':l,'right_ensemble':rr,'left_minus_right_eV_by_completion':dif,'ordering_by_completion':ordering})
            require(_proof_rows_match(r['contrast_pairs'],rows,('left_ensemble','right_ensemble')),'ranking proof report mismatch')
        elif k=='design_variance_nonidentifiability':
            e=next(x for x in plan['ensembles'] if x['ensemble']==i['ensemble']); h=i['stratum']; q,rem=divmod(e['target_population_size'],4); Nh=q+(h<rem); require(type(h)is int and 0<=h<4 and Nh>1,'invalid design-variance stratum')
            exp={'target_population_size':e['target_population_size'],'stratum_size':Nh,'marginal_inclusion_probability':1/(2*Nh),'distinct_frame_joint_inclusion_probability':0.0}; require(_proof_close(r,exp,'probability'),'design variance proof mismatch')
        elif k=='source_convention_comparison':
            require(i['base_convention'] in ('R3','free','extrapolated') and i['alternative_convention'] in ('R3','free','extrapolated') and i['base_convention']!=i['alternative_convention'],'invalid source conventions')
            require({(x['left_ensemble'],x['right_ensemble']) for x in i['contrast_pairs']}=={('2K_neutral','water_neutral'),('2K_anion','water_anion')},'convention proof must compare the same neutral and anion water/K arms')
            rows=[]
            for c in i['contrast_pairs']:
                l,rr=c['left_ensemble'],c['right_ensemble']; bl=float(sources[f"convention_ht/{i['base_convention']}/{l}"][0]); br=float(sources[f"convention_ht/{i['base_convention']}/{rr}"][0]); al=float(sources[f"convention_ht/{i['alternative_convention']}/{l}"][0]); ar=float(sources[f"convention_ht/{i['alternative_convention']}/{rr}"][0]); ls=al-bl; rs=ar-br; bc=bl-br; ac=al-ar
                rows.append({'left_ensemble':l,'right_ensemble':rr,'base_left_HT_eV':bl,'base_right_HT_eV':br,'alternative_left_HT_eV':al,'alternative_right_HT_eV':ar,'left_shift_eV':ls,'right_shift_eV':rs,'base_contrast_eV':bc,'alternative_contrast_eV':ac,'differential_shift_eV':ls-rs,'flip':abs(bc)>1e-8 and abs(ac)>1e-8 and bc*ac<0})
            require(_proof_rows_match(r['contrast_pairs'],rows,('left_ensemble','right_ensemble')),'same-arm convention contrasts mismatch')
        elif k=='conditional_differential_bias':
            aids=i['assumption_ids']; require(len(aids)==2 and len(set(aids))==2 and all(x in assumptions and assumptions[x]['raw']['kind']=='ensemble_gap_bias' for x in aids),'bias proof requires exactly two distinct ensemble biases')
            rows=[]
            for c in i['contrast_pairs']:
                l,rr=c['left_ensemble'],c['right_ensemble']; bmap={assumptions[x]['raw']['parameters']['ensemble']:float(assumptions[x]['scalar']) for x in aids}; require(set(bmap)=={l,rr},'bias assumptions do not match arms'); src=float(sources['ht_gap/'+l][0]-sources['ht_gap/'+rr][0]); adj=src+bmap[l]-bmap[rr]
                rows.append({'left_ensemble':l,'right_ensemble':rr,'source_contrast_eV':src,'left_bias_eV':bmap[l],'right_bias_eV':bmap[rr],'adjusted_contrast_eV':adj,'flip':abs(src)>1e-8 and abs(adj)>1e-8 and src*adj<0})
            require(_proof_rows_match(r['contrast_pairs'],rows,('left_ensemble','right_ensemble')),'conditional bias proof arithmetic mismatch')
        elif k=='protocol_comparison':
            # The protocol catalog is derived from pinned source files below; unknown fields are not inferred from candidate prose.
            rows=_protocol_comparisons(Path(os.environ.get('APP','/app')),Path(root),refs,i['protocol_ids'],i['compared_fields'],records,tasks)
            require(_proof_rows_match(r['reported_comparisons'],rows,('field',)),'protocol comparison does not match source protocols')
            results[pid]['protocol_comparisons']=rows
        elif k in ('state_inference_limit','marcus_identifiability','setting_scope','ranking_under_bounds','design_information_gain','follow_up_relevance'):
            results[pid].update(_validate_remaining_proof(k,i,r,plan,pairs,records,stats,assumptions,sources,pp,Path(root)))
        else: raise EnvironmentFailure('trusted contract proof kind has no evaluator semantics: '+k)
    _check_claims_and_report(Path(out),data,pp,pmap,results,assumptions,stats,qrecords,plan,tasks,records,pairs)
    return {'proof_count':len(proofs),'claim_count':len(data['claims']),'finite_population_K_water_ranking':'not_established','marcus_parameters_and_barriers':'not_established'}

def _protocol_comparisons(app,root,refs,protocol_ids,fields,records,tasks):
    """Build normalized protocol facts from source AST and validated native inputs."""
    import ast
    app=Path(app); root=Path(root); cats={}
    def parse(path):
        return ast.parse(_safe_source(app,path).read_text(encoding='utf-8'))
    def calls(tree,name):
        return [n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id==name]
    def attr_calls(tree,attr):
        return [n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr==attr]
    def lit(node):
        if node is None: return None
        try: return ast.literal_eval(node)
        except Exception: return None
    def kw(node,key):
        if node is None:return None
        return lit(next((x.value for x in node.keywords if x.arg==key),None))
    def first(tree,name):
        xs=calls(tree,name); return xs[0] if xs else None
    def method(tree):
        g=first(tree,'GPAW'); xc=kw(g,'xc'); occ=kw(g,'occupations') or {}
        return {'calculator':'GPAW' if g else None,
                'xc':xc.get('name') if isinstance(xc,dict) else None,
                'mode':kw(g,'mode'),'basis':kw(g,'basis'),'grid_spacing_A':kw(g,'h')}
    def spin(tree,initial=None):
        g=first(tree,'GPAW'); occ=kw(g,'occupations') or {}
        return {'spinpol':kw(g,'spinpol'),'fixmagmom':occ.get('fixmagmom'),
                'anion_initial_moment_mu_B':initial}
    def cdft_facts(tree,local):
        c=first(tree,'CDFT')
        charges=kw(c,'charges'); regions=kw(c,'charge_regions')
        target=None
        if isinstance(charges,list) and len(charges)==1 and num(charges[0]): target=float(charges[0])
        region=sorted(regions[0]) if isinstance(regions,list) and len(regions)==1 and isinstance(regions[0],list) else None
        return target,region
    def final_binding(tree):
        bindings=attr_calls(tree,'set_calculator')
        if not bindings:return None
        arg=bindings[-1].args[0] if bindings[-1].args else None
        return arg.id if isinstance(arg,ast.Name) else None
    def energy_facts(tree, target):
        ts=bool(calls(tree,'vdWTkatchenko09prl'))
        binding=final_binding(tree)
        cdft=bool(calls(tree,'CDFT'))
        # R3 computes a separately reported TS09 correction after the cDFT result;
        # author MD scripts construct the wrapper but their final MD calculator is cDFT.
        code=' '.join(ast.unparse(n) for n in ast.walk(tree) if isinstance(n,(ast.Call,ast.Assign)))
        reported_ts09=('ts_correction' in code and 'E_PBE_TS09_eV' in code)
        return {'cdft_applied':bool(calls(tree,'CDFT')),
                'ts09_constructed':ts,
                'ts09_final_calculator_binding':bool(binding and 'cc' == binding),
                'ts09_in_reported_energy':reported_ts09}
    md={'water_neutral':'water_CO2/calc.py','water_anion':'water_CO2anion/calc.py',
        '2K_neutral':'2K_CO2/calc.py','2K_anion':'2K_CO2anion/calc.py'}
    for label,rel in md.items():
        tree=parse('assets/'+rel); target,region=cdft_facts(tree,True)
        g=first(tree,'GPAW'); occ=kw(g,'occupations') or {}; readcall=first(tree,'read')
        rcall=first(tree,'Langevin'); args=[]
        if rcall:
            for arg in rcall.args:
                args.append(lit(arg) if lit(arg) is not None else ast.unparse(arg))
        p='author_md/'+label
        cats[p]={'method':method(tree),'state':target,'spin':spin(tree),
          'energy':energy_facts(tree,target),
          'geometry':{'input_selector':ast.unparse(readcall.args[0]) if readcall and readcall.args else None,
                      'pbc':None,'vacuum_A':None},
          'sampling':{'langevin_arguments':args},'charge_region_index_set':region,
          'charge_region_mapped_elements':None,
          'raw_langevin_api_argument':args[-1] if args else None,'physical_friction_rate':None}
        # PBC and vacuum are literal source calls, normalized to the same keys for all MD sources.
        pbc=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='set_pbc']
        center=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='center']
        cats[p]['geometry']['pbc']=lit(pbc[0].args[0]) if pbc and pbc[0].args else None
        cats[p]['geometry']['vacuum_A']=next((kw(x,'vacuum') for x in center if kw(x,'vacuum') is not None),None)
    # The vertical script creates separate neutral and anion calculators. Its neutral path
    # has no CDFT target; only the anion path constructs and binds the CDFT calculator.
    vtree=parse('assets/computegaps.py'); vmethod=method(vtree); vspin=spin(vtree)
    vread=first(vtree,'read'); vregion=None; vtarget=None
    vc=first(vtree,'CDFT')
    if vc:
        charges=kw(vc,'charges'); regions=kw(vc,'charge_regions')
        vtarget=float(charges[0]) if isinstance(charges,list) and len(charges)==1 and num(charges[0]) else None
        vregion=sorted(regions[0]) if isinstance(regions,list) and len(regions)==1 and isinstance(regions[0],list) else None
    for state,target in (('neutral',None),('anion',vtarget)):
        is_anion=state=='anion'; p='author_vertical/'+state
        cats[p]={'method':vmethod,'state':target,'spin':vspin,
          'energy':{'cdft_applied':is_anion and vtarget is not None,'ts09_constructed':bool(calls(vtree,'vdWTkatchenko09prl')),
                    'ts09_final_calculator_binding':False,'ts09_in_reported_energy':False},
          'geometry':{'input_selector':ast.unparse(vread.args[0]) if vread and vread.args else None,'pbc':None,'vacuum_A':None},
          'sampling':{'kind':'vertical-single-point'},'charge_region_index_set':vregion if is_anion else None,
          'charge_region_mapped_elements':None,'raw_langevin_api_argument':None,'physical_friction_rate':None}
    # R3 protocol facts are taken from every source-audited native input in the named state/setting,
    # plus the archived run_pair implementation. Per-geometry maps preserve heterogeneous regions.
    for state,state_value in (('neutral',0),('anion',-1)):
      for setting in ('base','tight'):
        selected=[]
        for rec in records.values():
            t=rec['task']
            if t['setting']==setting and rec['result']['state']==state_value:
                folder=root/'analysis/revision3/native'/rec['native_id']
                inp=readj(folder/'input.json'); tree=ast.parse((folder/'run_pair.py').read_text(encoding='utf-8'))
                selected.append((t,inp,tree,folder))
        require(bool(selected),'protocol has no validated native inputs: '+state+'/'+setting)
        opts=[{k:v for k,v in x[1]['calculator_options'].items() if k!='txt'} for x in selected]
        firstopts=opts[0]
        for op in opts[1:]: require(op==firstopts,'native protocol options vary within declared state/setting')
        t0,inp0,tree0,folder0=selected[0]
        charge_regions={}; mapped={}; sampling={}
        for t,inp,tree,folder in selected:
            inds=sorted(inp['CO2_indices_zero_based']); charge_regions[t['geometry_id']]=inds
            geo=readj(folder/'geometry.json'); nums=geo['numbers']; mapped[t['geometry_id']]={'C':next(i for i in inds if nums[i]==6),'O':sorted(i for i in inds if nums[i]==8)}
            sampling[t['geometry_id']]={'stage':t['stage'],'frame_zero_based':t['frame_zero_based'],'stratum':t['stratum']}
        run_text=(folder0/'run_pair.py').read_text(encoding='utf-8')
        run_tree=tree0; has_init=bool(attr_calls(run_tree,'set_initial_magnetic_moments'))
        init_value=None
        for n in ast.walk(run_tree):
            if isinstance(n,ast.Assign) and isinstance(n.value,ast.Constant) and type(n.value.value) in (int,float):
                if any(isinstance(t,ast.Subscript) and isinstance(t.value,ast.Name) and t.value.id=='moments' for t in n.targets): init_value=float(n.value.value)
        xc=firstopts.get('xc') or {}; occ=firstopts.get('occupations') or {}
        p=f'revision3/{state}/{setting}'
        cats[p]={'method':{'calculator':'GPAW','xc':xc.get('name'),'mode':firstopts.get('mode'),'basis':firstopts.get('basis'),'grid_spacing_A':firstopts.get('h')},
          'state':float(inp0['target_local_charge']),'spin':{'spinpol':firstopts.get('spinpol'),'fixmagmom':occ.get('fixmagmom'),
             'anion_initial_moment_mu_B':init_value if state=='anion' and has_init else None},
          'energy':{'cdft_applied':bool(calls(run_tree,'CDFT')),
                    'ts09_constructed':True,'ts09_final_calculator_binding':False,'ts09_in_reported_energy':True},
          'geometry':{'input_selector':'task geometry JSON','pbc':None,'vacuum_A':None},
          'sampling':sampling,'charge_region_index_set':charge_regions,'charge_region_mapped_elements':mapped,
          'raw_langevin_api_argument':None,'physical_friction_rate':None}
    allowed={'method','state','spin','energy','geometry','sampling','raw_langevin_api_argument',
             'physical_friction_rate','charge_region_index_set','charge_region_mapped_elements'}
    require(len(set(protocol_ids))==len(protocol_ids),'duplicate protocol ID')
    rows=[]
    for field in fields:
        require(field in allowed,'unknown protocol field')
        values={p:cats[p].get(field) for p in protocol_ids if p in cats}
        require(len(values)==len(protocol_ids),'unknown protocol catalog ID')
        def has_unknown(value):
            if isinstance(value,dict): return any(has_unknown(x) for x in value.values())
            if isinstance(value,list): return any(has_unknown(x) for x in value)
            return value is None
        known=[]
        for value in values.values():
            if field in {'state','charge_region_index_set'}:
                known.append(value)  # null here is a source-known absence of a local constraint/region.
            elif not has_unknown(value):
                known.append(value)
        different=len(known)==len(values) and len({json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False) for v in known})>1
        rows.append({'field':field,'values_by_protocol':values,'different':different if len(known)==len(values) else False})
    return rows

def _validate_remaining_proof(kind,i,r,plan,pairs,records,stats,assumptions,sources,protocol,root):
    if kind=='state_inference_limit':
        require(i['target_predicate'] in {'spin_ground_state','radical_identity','global_minimum','unique_physical_energy'},'unknown state-inference target')
        ids=i['state_record_ids']; require(ids and all(any(x['native_id']==nid for x in records.values()) for nid in ids),'unknown native state record')
        rows=[]
        for nid in ids:
            rec=next(x for x in records.values() if x['native_id']==nid)
            rows.append({'state_record_id':nid,'magnetization_components_mu_B':rec['magnetization_components_mu_B'],'local_charge_e':rec['result']['local_charge_e']})
        require(r['inference_limit']=='does_not_establish' and _proof_rows_match(r['reported_observations'],rows,('state_record_id',)),'state observables or inference limit mismatch')
        return {'state_observations':rows}
    if kind=='marcus_identifiability':
        require(set(i['ensembles'])==set(stats),'Marcus identifiability must cover all ensembles')
        rows=[{'ensemble':e,'within_ensemble_variance_identified':False,'equilibrium_response_identified':False} for e in sorted(stats)]
        require(i['required_population_quantity'] in {'within_ensemble_variance','equilibrium_response','both'} and _proof_rows_match(r['reported_prerequisites'],rows,('ensemble',)),'Marcus prerequisites incorrectly asserted identified')
        return {'marcus_prerequisites':rows}
    if kind=='setting_scope':
        sens=_source_sensitivity(pairs); require(set(i['geometry_ids'])==set(sens),'setting proof geometry IDs mismatch')
        rows=[{'geometry_id':gid,'base_gap_eV':sens[gid]['base_gap_eV'],'tight_gap_eV':sens[gid]['tight_gap_eV'],'delta_eV':sens[gid]['gap_change_eV']} for gid in sorted(sens)]
        require(i['claim_scope'] in {'those_geometries','same_ensemble','all_ensembles'} and _proof_rows_match(r['reported_effects'],rows,('geometry_id',)),'setting comparison results mismatch')
        return {'setting_effects':rows}
    if kind=='ranking_under_bounds':
        allowed={('2K_neutral','water_neutral'),('2K_anion','water_anion')}
        pairs={(x['left_ensemble'],x['right_ensemble']) for x in i['contrast_pairs']}
        require(pairs and pairs<=allowed,'bounds proof must describe one or more declared K-minus-water contrasts')
        aids=i['assumption_ids']; amap={assumptions[x]['raw']['parameters']['ensemble']:assumptions[x] for x in aids if x in assumptions and assumptions[x]['raw']['kind']=='finite_population_bounds'}
        require(len(aids)==len(set(aids)) and set(amap)=={x for c in i['contrast_pairs'] for x in (c['left_ensemble'],c['right_ensemble'])},
                'bounds proof assumptions must cover exactly its contrast arms')
        rows=[]
        for c in i['contrast_pairs']:
            l,rr=c['left_ensemble'],c['right_ensemble']; require(l in amap and rr in amap,'bounds must cover both ranking arms')
            def interval(ens):
                obs=[Decimal(str(v)) for v in stats[ens]['observed_base_gaps_eV']]; N=Decimal(str(stats[ens]['target_population_size'])); n=Decimal(len(obs)); b=amap[ens]
                return [float((sum(obs)+(N-n)*b['lower'])/N),float((sum(obs)+(N-n)*b['upper'])/N)]
            li,ri=interval(l),interval(rr)
            order='left_greater' if li[0]>ri[1] else 'right_greater' if ri[0]>li[1] else 'overlap'
            rows.append({'left_ensemble':l,'right_ensemble':rr,'left_mean_interval_eV':li,'right_mean_interval_eV':ri,'ordering':order})
        require(_proof_rows_match(r['contrast_pairs'],rows,('left_ensemble','right_ensemble')) and all(x['ordering']!='overlap' for x in rows),'bounds do not establish the reported order')
        return {'bounded_rankings':rows}
    if kind=='design_information_gain':
        require(i['target_uncertainty']=='finite_population_sampling','unsupported information-gain target')
        source_ens={e['ensemble']:e for e in plan['ensembles']}; rows=[]; total=0
        require(len(i['strata'])==4 and {x['ensemble'] for x in i['strata']}==set(source_ens),'design must cover all four source ensembles')
        for choice in i['strata']:
            ens=choice['ensemble']; e=source_ens[ens]; N=e['target_population_size']; q,rem=divmod(N,4); sizes=[q+(h<rem) for h in range(4)]; H=4; k,m=choice['k'],choice['m']; require(type(k)is int and type(m)is int and 1<=k<=H and 1<=m<=min(sizes),'invalid k-of-H/m design')
            require(k>=2 and m>=2,'follow-up design does not create positive same- and cross-stratum pair information')
            reported=[x for x in r['strata'] if x['ensemble']==ens]
            require(len(reported)==H and {x['stratum'] for x in reported}==set(range(H)),'design information report must identify each source stratum exactly once')
            for h,Nh in enumerate(sizes):
                row=next(x for x in reported if x['stratum']==h); j=row['cross_stratum']
                require(type(j)is int and 0<=j<H and j!=h,'cross-stratum witness must name a distinct source stratum')
                same=(k/H)*m*(m-1)/(Nh*(Nh-1)) if Nh>1 else 0
                cross=(k*(k-1)/(H*(H-1)))*(m/Nh)*(m/sizes[j])
                rows.append({'ensemble':ens,'stratum':h,'cross_stratum':j,'H':H,'N_h':Nh,'k':k,'m':m,'marginal_pi_i':(k/H)*(m/Nh),'same_stratum_pi_ij':same,'cross_stratum_pi_ij':cross})
            total+=2*k*m
        reuse_list=i['reuse_source_task_ids']; require(len(reuse_list)==len(set(reuse_list)),'reuse list contains duplicate task IDs')
        all_tasks=readj(Path(root)/'runtimes/hpc/case04/review-v3/tasks.json'); source_by={t['index']:t for t in all_tasks}
        require(all(type(x)is int and x in source_by and source_by[x]['stage']=='production' for x in reuse_list),'reuse list must name distinct frozen production draws only')
        choices={x['ensemble']:x for x in i['strata']}; reuse_by={ens:[] for ens in choices}
        for idx in reuse_list: reuse_by[source_by[idx]['ensemble']].append(source_by[idx])
        plan_selected=plan['selected_strata']
        for ens, reused_tasks in reuse_by.items():
            choice=choices[ens]
            require(len({x['stratum'] for x in reused_tasks})==len(reused_tasks),'reused draws are not distinct design-frame contributions')
            if reused_tasks:
                require(choice['k']>=len(plan_selected[ens]) and choice['m']>=2,'nested continuation cannot retain the frozen draws and add second-order information')
                require(len(reused_tasks)==len(plan_selected[ens]) and {x['stratum'] for x in reused_tasks}==set(plan_selected[ens]),'reuse must retain exactly the frozen two-of-four selected strata and their base frames')
                pop=source_ens[ens]; N=pop['target_population_size']; lo,hi=pop['target_population']; q,rem=divmod(N,4); sizes=[q+(h<rem) for h in range(4)]
                for task in reused_tasks:
                    h=task['stratum']; first=lo+sum(sizes[:h]); last=first+sizes[h]-1
                    require(task['stage']=='production' and first<=task['frame_zero_based']<=last,'reused frame lies outside the selected source stratum')
            else:
                require(choice['k']>=2 and choice['m']>=2,'fresh design must sample at least two strata and two frames per selected stratum')
        attempts=max(0,total-2*len(reuse_list))
        require(_proof_rows_match(r['strata'],rows,('ensemble','stratum','cross_stratum'),'probability') and r['new_paired_state_attempts']==attempts,'sampling design probabilities/cost mismatch')
        return {'design':rows,'new_attempts':attempts}
    if kind=='follow_up_relevance':
        mapping=protocol['follow_up_uncertainty_mapping']; obs=protocol['follow_up_observables']; calc=protocol['follow_up_calculation_mapping']
        require(i['target_uncertainty'] in mapping and i['observable'] in obs and i['target_uncertainty'] in calc
                and i['calculation_class']==calc[i['target_uncertainty']],
                'follow-up observable/calculation class does not match its uncertainty')
        require(i['observable'] in mapping[i['target_uncertainty']],'observable does not address declared uncertainty')
        expected_pairs={
          'finite_population_sampling':('positive_second_order_information','within_stratum_joint_moments'),
          'numerical_setting_error':('bounded_local_error','matched_setting_effects'),
          'MD_time_correlation':('time_dependence_measured','trajectory_time_dependence'),
          'chemical_state_identity':('state_observable_measured','spin_or_local_charge_state'),
          'thermodynamic_transfer':('equilibrium_response_measured','equilibrium_response'),
          'Marcus_gap_distribution':('gap_distribution_measured','same_ensemble_gap_variance')}
        expected={'expected_distinguishing_result':expected_pairs[i['target_uncertainty']][0],
                  'missing_source_quantity':expected_pairs[i['target_uncertainty']][1]}
        require(_proof_close(r,expected),'follow-up typed result mismatch')
        return {'follow_up':expected}
    raise EnvironmentFailure('trusted contract follow-up kind has no evaluator semantics: '+kind)

def _validate_follow_up_details(target,details,rules,plan,tasks,records,pairs):
    ensembles={e['ensemble'] for e in plan['ensembles']}
    if target=='finite_population_sampling':
        return
    if target=='numerical_setting_error':
        geoms={t['geometry_id'] for t in tasks}
        require(isinstance(details['geometry_ids'],list) and details['geometry_ids']
                and len(details['geometry_ids'])==len(set(details['geometry_ids']))
                and set(details['geometry_ids'])<=geoms,
                'numerical follow-up must name unique frozen source geometries')
        already_tight={t['geometry_id'] for t in tasks if t['stage']=='sensitivity'}
        require(set(details['state_labels'])=={'neutral','anion'}
                and details['baseline_setting']=='base'
                and details['new_setting_variants']==['tight']
                and not (set(details['geometry_ids']) & already_tight)
                and num(details['comparison_tolerance_eV']) and details['comparison_tolerance_eV']>0,
                'numerical follow-up must compare declared states against the existing base setting')
        return
    if target=='chemical_state_identity':
        by_id={value['native_id']:(key,value) for key,value in records.items()}
        ids=details['state_record_ids']; require(isinstance(ids,list) and ids and len(ids)==len(set(ids))
            and set(ids)<=set(by_id), 'state-characterization proposal must cite unique source-native state records')
        selected=[by_id[x] for x in ids]
        state_labels={'neutral' if x[0][1]==0 else 'anion' for x in selected}
        require(set(details['state_labels'])==state_labels and bool(state_labels),
            'state-characterization proposal state labels do not match its cited native records')
        require(len({x[1]['task']['geometry_id'] for x in selected})>=1,
            'state-characterization proposal has no source geometry scope')
        require(len(details['initial_moment_protocols'])>=2
                and {'co2_site_initial_moment_0_mu_B','co2_site_initial_moment_1_mu_B'}<=set(details['initial_moment_protocols'])
                and {'spin_magnetization','local_spin_density','local_charge_partition'}<=set(details['diagnostics']),
                'state-characterization proposal must compare two explicit CO2 initial-moment SCF protocols and measure spin/charge observables')
        return
    if target in {'MD_time_correlation','thermodynamic_transfer','Marcus_gap_distribution'}:
        ens=details['ensembles']; require(isinstance(ens,list) and ens and len(ens)==len(set(ens)) and set(ens)<=ensembles,
            'trajectory follow-up names an unknown or empty ensemble set')
        require(type(details['replicas']) is int and details['replicas']>=1
                and type(details['steps']) is int and details['steps']>0,
                'dynamic follow-up needs at least one replica and a positive step count')
        if target=='MD_time_correlation':
            require((details['trajectory_protocol']=='single_extended_trajectory' and details['replicas']==1)
                    or (details['trajectory_protocol']=='independent_replicas' and details['replicas']>=2),
                    'MD trajectory replica count does not match its declared protocol')
            require(type(details['analysis_stride']) is int and details['analysis_stride']>0
                    and details['steps']%details['analysis_stride']==0
                    and {'autocorrelation','block_sensitivity'}<=set(details['diagnostics']),
                    'MD time-correlation proposal lacks executable sampling/diagnostic detail')
        elif target=='thermodynamic_transfer':
            require(len(ens)>=2 and details['reference_convention'] in {'R3_native_E_PBE_TS09','standard_free_energy'}
                    and details['response_observable']=='equilibrium_population_response',
                    'thermodynamic proposal must compare at least two ensembles and identify its response/convention')
        else:
            require(details['gap_convention']=='R3_native_E_PBE_TS09'
                    and {'within_ensemble_variance','equilibration_check','distribution_shape'}<=set(details['distribution_diagnostics']),
                    'Marcus distribution proposal must specify within-ensemble and distribution diagnostics')

def _validate_follow_up_resources(target,resource,details,design_result,records):
    require(isinstance(resource,dict) and set(resource)=={'additional_state_attempts','planned_trajectory_steps',
            'estimated_cpu_hours','estimated_wall_hours','cost_basis'},'follow-up resource estimate schema mismatch')
    if target=='finite_population_sampling':
        require(resource['planned_trajectory_steps'] is None and resource['additional_state_attempts']==design_result['new_attempts'],
                'sampling resource estimate differs from its validated design')
    elif target=='numerical_setting_error':
        expected=len(details['geometry_ids'])*len(details['state_labels'])*len(details['new_setting_variants'])
        require(type(resource['additional_state_attempts']) is int and resource['additional_state_attempts']==expected
                and resource['planned_trajectory_steps'] is None,
                'numerical resource count must equal geometry × states × new setting variants')
    elif target=='chemical_state_identity':
        # Count only the explicitly proposed source geometries, both states, and added protocols.
        geometry_by_record={value['native_id']:value['task']['geometry_id'] for value in records.values()}
        geo_count=len({geometry_by_record[x] for x in details['state_record_ids']})
        expected=geo_count*len(details['state_labels'])*len(details['initial_moment_protocols'])
        require(type(resource['additional_state_attempts']) is int and resource['additional_state_attempts']==expected
                and resource['planned_trajectory_steps'] is None,
                'state-characterization resource count must equal geometry × states × protocol variants')
    else:
        expected=len(details['ensembles'])*details['replicas']*details['steps']
        require(resource['additional_state_attempts'] is None and resource['planned_trajectory_steps']==expected,
                'dynamic trajectory work must report steps × replicas and must not invent state-attempt counts')
    basis=resource['cost_basis']; cpu=resource['estimated_cpu_hours']; wall=resource['estimated_wall_hours']
    if basis=='not_estimated':
        require(cpu is None and wall is None,'unestimated cost must use null, not a zero-cost claim')
    else:
        require(basis=='separate_estimate' and num(cpu) and cpu>0 and num(wall) and wall>0,
                'positive resource estimate must state a separate nonzero estimate')

def _check_claims_and_report(out,data,protocol,proofs,results,assumptions,stats,quantities,plan,tasks,records,pairs):
    claims=data.get('claims'); require(isinstance(claims,list) and claims,'claims must be nonempty')
    topics=protocol['claim_topics']; cids={}; statuses={'supported','conditional','not_established'}
    for c in claims:
        require(isinstance(c,dict) and set(c)=={'id','topic','predicate','scope','status','proof_ids'} and c['id'] not in cids,'invalid/duplicate claim')
        require(c['topic'] in topics and c['predicate'] in topics[c['topic']] and c['status'] in statuses,'claim topic/predicate/status invalid')
        require(isinstance(c['scope'],dict) and set(c['scope'])=={'kind','id'} and c['proof_ids'],'claim scope/proof refs invalid')
        require(all(pid in proofs for pid in c['proof_ids']),'claim references missing proof')
        pred=c['predicate']; expected='not_established' if pred in {'not_identified','not_established_from_state_observables','not_unique_from_convention_diagnostics','no_unique_diabatic_or_free_energy_established'} else 'conditional' if pred.startswith('conditional_') else 'supported'
        require(c['status']==expected,'claim status does not follow its target predicate')
        scope_kind={
          'reconstructed_from_native':'native_ledger','reconstructed_state_pairs':'geometry',
          'not_identified':'finite_population','local_effect_only':'geometry','no_total_error_bound':'geometry_set',
          'source_comparison':'cross_ensemble_contrast','no_source_flip':'cross_ensemble_contrast',
          'conditional_bias_scenario':'cross_ensemble_contrast','conditional_order_under_bounds':'cross_ensemble_contrast',
          'targets_named_uncertainty':'future_design','not_established_from_state_observables':'state_pair_set',
          'no_unique_diabatic_or_free_energy_established':'energy_convention','protocols_distinct':'protocol_record_set'}[pred]
        require(c['scope']['kind']==scope_kind,'claim scope kind does not match its target topic')
        referenced=[proofs[pid] for pid in c['proof_ids']]
        kinds={p['kind'] for p in referenced}
        supported_predicates={
          'reconstructed_from_native':{'source_audit'},'reconstructed_state_pairs':{'source_audit'},
          'not_identified':{'population_moment_nonidentifiability','ranking_nonidentifiability','design_variance_nonidentifiability','marcus_identifiability'},
          'local_effect_only':{'setting_scope'},'no_total_error_bound':{'setting_scope'},
          'source_comparison':{'source_convention_comparison'},'no_source_flip':{'source_convention_comparison'},
          'targets_named_uncertainty':{'follow_up_relevance'},
          'not_established_from_state_observables':{'state_inference_limit'},
          'no_unique_diabatic_or_free_energy_established':{'source_convention_comparison','state_inference_limit'},
          'protocols_distinct':{'protocol_comparison'},'conditional_bias_scenario':{'conditional_differential_bias'},
          'conditional_order_under_bounds':{'ranking_under_bounds'}}
        if pred not in supported_predicates:
            raise ScientificFailure('claim predicate has no implemented proof semantics: '+pred)
        if pred=='not_identified':
            expected_kind={'finite_population_K_water_ranking':{'population_moment_nonidentifiability','ranking_nonidentifiability'},
              'equilibrium_or_thermodynamic_claim':{'design_variance_nonidentifiability'},
              'marcus_parameters_and_barriers':{'marcus_identifiability'}}.get(c['topic'])
            require(expected_kind is not None and expected_kind<=kinds,'not_identified claim is linked to unrelated proof kinds')
            require(_scope_set_matches(c['scope']['id'],stats),'nonidentifiability claim scope must match all four frozen ensembles')
            if c['topic']=='equilibrium_or_thermodynamic_claim':
                linked={proofs[pid]['inputs']['ensemble'] for pid in c['proof_ids'] if proofs[pid]['kind']=='design_variance_nonidentifiability'}
                require(linked==set(stats),'equilibrium nonidentifiability claim must itself link all four design variance proofs')
            elif c['topic']=='marcus_parameters_and_barriers':
                linked=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='marcus_identifiability']
                require(len(linked)==1 and set(linked[0]['inputs']['ensembles'])==set(stats),
                        'Marcus nonidentifiability claim must itself link the all-ensemble prerequisite proof')
            elif c['topic']=='finite_population_K_water_ranking':
                moment=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='population_moment_nonidentifiability']
                ranking=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='ranking_nonidentifiability']
                require(len(moment)==1 and len(ranking)==1 and set(moment[0]['inputs']['ensembles'])==set(stats),
                        'population ranking claim must itself link full-ensemble moment and ranking witnesses')
        else:
            require(supported_predicates[pred]<=kinds,'claim predicate lacks its own required proof kind: '+pred)
        if pred=='reconstructed_from_native':
            audits=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='source_audit']
            require(len(audits)==1 and c['scope']['id']==audits[0]['inputs']['audit_scope'],
                    'native-ledger claim scope must match its linked source-audit record')
        if pred=='reconstructed_state_pairs':
            require(any(q['scope']==c['scope'] for q in quantities.values()),
                    'local state-pair claim scope must have its own source-backed geometry quantity')
        if pred=='conditional_bias_scenario':
            linked=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='conditional_differential_bias']
            used={aid for p in linked for aid in p['inputs']['assumption_ids']}
            require(c['topic']=='energy_convention_ranking_effect' and linked and used and
                    all(assumptions[x]['raw']['kind']=='ensemble_gap_bias' and assumptions[x]['raw']['scope']['kind']=='energy_convention' for x in used),
                    'conditional bias claim lacks its own linked, scoped two-arm bias proof')
            proof_pairs={(x['left_ensemble'],x['right_ensemble']) for p in linked for x in p['inputs']['contrast_pairs']}
            require(proof_pairs and proof_pairs<={('2K_neutral','water_neutral'),('2K_anion','water_anion')} and
                    c['scope']['kind']=='cross_ensemble_contrast' and _scope_set_matches(c['scope']['id'],
                        {f'{left}-minus-{right}' for left,right in proof_pairs}),
                    'conditional bias claim scope does not match its own validated contrast proof')
        if pred=='conditional_order_under_bounds':
            linked=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='ranking_under_bounds']
            used={aid for p in linked for aid in p['inputs']['assumption_ids']}
            require(c['topic']=='finite_population_K_water_ranking' and linked and used and
                    all(assumptions[x]['raw']['kind']=='finite_population_bounds' and assumptions[x]['raw']['scope']['kind']=='finite_population' for x in used),
                    'conditional ranking claim lacks its own linked, scoped bound proof')
            proof_pairs={(x['left_ensemble'],x['right_ensemble']) for p in linked for x in p['inputs']['contrast_pairs']}
            require(proof_pairs and proof_pairs<={('2K_neutral','water_neutral'),('2K_anion','water_anion')} and
                    c['scope']['kind']=='cross_ensemble_contrast' and _scope_set_matches(c['scope']['id'],
                        {f'{left}-minus-{right}' for left,right in proof_pairs}),
                    'conditional ranking claim scope does not match its own validated bounded contrast proof')
        if pred in {'no_source_flip','source_comparison'}:
            linked=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='source_convention_comparison']
            pairs={(x['left_ensemble'],x['right_ensemble']) for p in linked for x in p['inputs']['contrast_pairs']}
            require(linked and pairs=={('2K_neutral','water_neutral'),('2K_anion','water_anion')} and
                    c['scope']['kind']=='cross_ensemble_contrast' and _scope_set_matches(c['scope']['id'],
                        {f'{left}-minus-{right}' for left,right in pairs}),
                    'energy-convention claim scope does not match its two validated same-arm comparisons')
        if pred=='no_source_flip':
            rows=[r for p in referenced if p['kind']=='source_convention_comparison' for r in p['reported']['contrast_pairs']]
            require(len(rows)>=2 and all(x['flip'] is False for x in rows),'source convention comparisons do not establish the claimed absence of ranking reversal')
        if pred in {'local_effect_only','no_total_error_bound'}:
            setting_proofs=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='setting_scope']
            require(setting_proofs,'setting claim lacks matched-geometry proof')
            checked={gid for p in setting_proofs for gid in p['inputs']['geometry_ids']}
            if pred=='local_effect_only': require(c['scope']['id'] in checked,'local-effect claim scope is absent from its linked setting proof')
            else: require(c['scope']['kind']=='geometry_set' and _scope_set_matches(c['scope']['id'],checked),
                          'error-bound claim scope does not match exactly the tested geometries')
        if pred=='targets_named_uncertainty':
            relevance_proofs=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='follow_up_relevance']
            require(len(relevance_proofs)==1 and len(c['proof_ids']) in {1,2},
                    'follow-up claim must link one relevance proof and only an optional sampling design proof')
            target=relevance_proofs[0]['inputs']['target_uncertainty']
            if target=='finite_population_sampling':
                design_proofs=[proofs[pid] for pid in c['proof_ids'] if proofs[pid]['kind']=='design_information_gain']
                require(len(design_proofs)==1 and len(c['proof_ids'])==2,
                        'sampling follow-up claim must link its own design and relevance proofs')
            else:
                require(all(proofs[pid]['kind']=='follow_up_relevance' for pid in c['proof_ids']),
                        'non-sampling follow-up claim cannot cite a sampling design proof')
            require(c['scope']['id']==target,
                    'follow-up claim scope does not match the uncertainty its proofs evaluate')
        if pred=='not_established_from_state_observables':
            expected_targets={'spin_ground_state','radical_identity','global_minimum'} if c['topic']=='chemical_state_identity' else {'unique_physical_energy'} if c['topic']=='physical_energy_interpretation' else set()
            linked_targets={proofs[pid]['inputs']['target_predicate'] for pid in c['proof_ids'] if proofs[pid]['kind']=='state_inference_limit'}
            require(expected_targets and linked_targets==expected_targets,'state-observables claim does not link exactly its target-specific inference limits')
            state_ids={nid for pid in c['proof_ids'] if proofs[pid]['kind']=='state_inference_limit' for nid in proofs[pid]['inputs']['state_record_ids']}
            require(_scope_set_matches(c['scope']['id'],state_ids),'state-pair-set scope does not match its cited native records')
        if pred=='no_unique_diabatic_or_free_energy_established':
            linked_targets={proofs[pid]['inputs']['target_predicate'] for pid in c['proof_ids'] if proofs[pid]['kind']=='state_inference_limit'}
            require(c['topic']=='physical_energy_interpretation' and linked_targets=={'unique_physical_energy'},
                    'physical-energy interpretation must link its own unique-physical-energy inference limit')
            require(any(proofs[pid]['kind']=='source_convention_comparison' for pid in c['proof_ids']),
                    'physical-energy interpretation lacks a linked source convention comparison')
            conventions=[proofs[pid]['inputs'] for pid in c['proof_ids'] if proofs[pid]['kind']=='source_convention_comparison']
            convention_scope={f"{x['base_convention']}-minus-{x['alternative_convention']}" for x in conventions}
            require(_scope_set_matches(c['scope']['id'],convention_scope),'energy-convention scope does not match its linked comparisons')
        if pred=='protocols_distinct':
            rows=[row for pid in c['proof_ids'] if proofs[pid]['kind']=='protocol_comparison' for row in results[pid].get('protocol_comparisons',[])]
            ids={source_id for pid in c['proof_ids'] if proofs[pid]['kind']=='protocol_comparison' for source_id in proofs[pid]['inputs']['protocol_ids']}
            required_ids={*(f'author_md/{e}' for e in ('water_neutral','water_anion','2K_neutral','2K_anion')),
                          'author_vertical/neutral','author_vertical/anion',
                          *(f'revision3/{state}/{setting}' for state in ('neutral','anion') for setting in ('base','tight'))}
            required_fields={'state','spin','energy','sampling'}
            linked_protocols=[proofs[pid]['inputs'] for pid in c['proof_ids'] if proofs[pid]['kind']=='protocol_comparison']
            covered={source_id:set() for source_id in required_ids}
            for item in linked_protocols:
                for source_id in required_ids & set(item['protocol_ids']): covered[source_id].update(item['compared_fields'])
            require(required_ids<=ids and all(required_fields<=covered[source_id] for source_id in required_ids),
                    'protocol distinction omits a required MD, vertical, or R3 record/field')
            require(any(row['different'] is True for row in rows) and any(x.startswith('author_') for x in ids) and any(x.startswith('revision3/') for x in ids),
                    'protocol distinction claim has no verified source-known difference between author and R3 records')
            require(_scope_set_matches(c['scope']['id'],ids),'protocol-record-set scope does not match its linked source protocols')
        cids[c['id']]=c
    follow=data.get('follow_up')
    require(isinstance(follow,dict),'follow_up proposal is missing')
    target=follow.get('target_uncertainty')
    require(target in protocol['follow_up_topics'],'unknown follow-up uncertainty')
    common={'target_uncertainty','observable','calculation_class','proposal_details','missing_prerequisites',
            'distinguishable_outcomes','resource_estimate','proof_ids'}
    expected_fields=common|({'design'} if target=='finite_population_sampling' else set())
    require(set(follow)==expected_fields,'follow-up fields do not match the declared objective')
    rel_ids=[pid for pid in follow['proof_ids'] if pid in proofs and proofs[pid]['kind']=='follow_up_relevance']
    require(len(rel_ids)==1,'follow-up must reference exactly one validated relevance proof')
    rel_id=rel_ids[0]; rel=proofs[rel_id]['inputs']; rel_result=results[rel_id]['follow_up']
    require(target==rel['target_uncertainty'] and follow['observable']==rel['observable']
            and follow['calculation_class']==rel['calculation_class'],
            'follow-up proposal does not match its validated relevance proof')
    require(rel_result['missing_source_quantity'] in follow['missing_prerequisites'],
            'follow-up does not name the source quantity its relevance proof found missing')
    outcomes=protocol['follow_up_distinguishable_outcomes'][target]
    require(isinstance(follow['distinguishable_outcomes'],list) and len(follow['distinguishable_outcomes'])==2
            and len(set(follow['distinguishable_outcomes']))==2
            and set(follow['distinguishable_outcomes'])==set(outcomes),
            'follow-up must state both distinct, objective-specific possible results')
    details=follow['proposal_details']; rules=protocol['follow_up_proposal_details'][target]
    require(isinstance(details,dict) and set(details)==set(rules['required_fields']),
            'follow-up proposal details do not match the objective-specific schema')
    for key in rules.get('string_list_fields',[]):
        value=details.get(key)
        require(isinstance(value,list) and value and all(isinstance(x,str) and x for x in value)
                and len(value)==len(set(value)),'follow-up string list is empty, duplicated, or malformed: '+key)
    for key in rules.get('positive_integer_fields',[]):
        require(type(details.get(key)) is int and details[key]>0,'follow-up count must be a positive integer: '+key)
    for key in rules.get('positive_number_fields',[]):
        require(num(details.get(key)) and details[key]>0,'follow-up measurement must be finite and positive: '+key)
    for key,allowed in rules.get('enum_fields',{}).items():
        require(details.get(key) in allowed,'follow-up proposal detail enum mismatch: '+key)
    for key,allowed in rules.get('enum_list_fields',{}).items():
        value=details.get(key)
        require(isinstance(value,list) and value and len(value)==len(set(value)) and set(value)<=set(allowed),
                'follow-up proposal detail list mismatch: '+key)
    require(isinstance(follow['missing_prerequisites'],list) and follow['missing_prerequisites']
            and len(follow['missing_prerequisites'])==len(set(follow['missing_prerequisites']))
            and set(follow['missing_prerequisites'])<=set(rules['missing_prerequisites']),
            'follow-up missing scientific prerequisites are invalid')
    _validate_follow_up_details(target,details,rules,plan,tasks,records,pairs)
    design_id=None
    if target=='finite_population_sampling':
        design_id=follow['design']['proof_id']
        require(design_id in proofs and proofs[design_id]['kind']=='design_information_gain',
                'sampling follow-up must reference a validated design-information proof')
        require(set(follow['proof_ids'])=={design_id,rel_id},
                'sampling follow-up references must be exactly its design and relevance proofs')
        require(details=={'design_proof_id':design_id},'sampling proposal details must bind the validated design proof')
        require(follow['resource_estimate']['additional_state_attempts']==results[design_id]['new_attempts'],
                'follow-up resource count differs from its validated sampling design')
    else:
        require(set(follow['proof_ids'])=={rel_id},'non-sampling follow-up cannot use a sampling-design proof')
    _validate_follow_up_resources(target,follow['resource_estimate'],details,results.get(design_id,{}),records)
    follow_claims=[c for c in claims if c['predicate']=='targets_named_uncertainty']
    require(len(follow_claims)==1 and set(follow_claims[0]['proof_ids'])==set(follow['proof_ids'])
            and follow_claims[0]['scope']=={'kind':'future_design','id':target},
            'follow-up claim does not bind the validated proposal, objective, and proof references')
    obligation=protocol['claim_obligations']; require(set(topics)<=set({c['topic'] for c in claims}),'required scientific claim topic is missing')
    for topic in topics:
        tc=[c for c in claims if c['topic']==topic]
        require(tc,'missing claim topic '+topic)
        allowed=set(topics[topic]); require(all(c['predicate'] in allowed for c in tc),'invalid topic predicate')
        pks={proofs[pid]['kind'] for c in tc for pid in c['proof_ids']}
        required={'budgeted_numerical_execution':{'source_audit'},'calculated_geometry_local_gaps':{'source_audit'},'finite_population_K_water_ranking':{'population_moment_nonidentifiability','ranking_nonidentifiability'},'equilibrium_or_thermodynamic_claim':{'protocol_comparison','design_variance_nonidentifiability'},'marcus_parameters_and_barriers':{'marcus_identifiability'},'numerical_setting_generalization':{'setting_scope'},'energy_convention_ranking_effect':{'source_convention_comparison'},'follow_up_design':{'follow_up_relevance'},'chemical_state_identity':{'state_inference_limit'},'physical_energy_interpretation':{'source_convention_comparison','protocol_comparison'},'method_protocol_distinction':{'protocol_comparison'}}[topic]
        predset={c['predicate'] for c in tc}
        mandatory={
          'budgeted_numerical_execution':{'reconstructed_from_native'},
          'calculated_geometry_local_gaps':{'reconstructed_state_pairs'},
          'finite_population_K_water_ranking':{'not_identified'},
          'equilibrium_or_thermodynamic_claim':{'not_identified'},
          'marcus_parameters_and_barriers':{'not_identified'},
          'numerical_setting_generalization':{'local_effect_only','no_total_error_bound'},
          'energy_convention_ranking_effect':{'source_comparison'},
          'follow_up_design':{'targets_named_uncertainty'},
          'chemical_state_identity':{'not_established_from_state_observables'},
          'physical_energy_interpretation':{'no_unique_diabatic_or_free_energy_established'},
          'method_protocol_distinction':{'protocols_distinct'}}[topic]
        require(mandatory<=predset,'required scientific predicate missing for topic '+topic)
        if topic=='calculated_geometry_local_gaps':
            for claim in tc:
                require(claim['scope']['kind']=='geometry' and any(q['scope']==claim['scope'] for q in quantities.values()),'local-gap claim has no source-backed quantity in its geometry scope')
        if topic=='finite_population_K_water_ranking' and 'not_identified' in predset:
            require({'population_moment_nonidentifiability','ranking_nonidentifiability'}<=pks,'ranking nonidentifiability lacks completion and moment witnesses')
        if topic=='equilibrium_or_thermodynamic_claim' and 'not_identified' in predset:
            variance_proofs=[p for p in proofs.values() if p['kind']=='design_variance_nonidentifiability']
            require({p['inputs']['ensemble'] for p in variance_proofs}==set(stats),'equilibrium claim must cite all four design-variance limitations')
        if topic=='energy_convention_ranking_effect':
            for claim in tc: require('source_convention_comparison' in {proofs[x]['kind'] for x in claim['proof_ids']},'energy-convention claim lacks same-arm source comparison')
        if topic=='chemical_state_identity' and 'not_established_from_state_observables' in predset:
            targets={proofs[x]['inputs']['target_predicate'] for c in tc for x in c['proof_ids'] if proofs[x]['kind']=='state_inference_limit'}
            require({'spin_ground_state','radical_identity','global_minimum'}<=targets,'chemical-state limit omits identity/ground-state inference boundaries')
        if topic=='physical_energy_interpretation' and 'no_unique_diabatic_or_free_energy_established' in predset:
            targets={proofs[x]['inputs']['target_predicate'] for c in tc for x in c['proof_ids'] if proofs[x]['kind']=='state_inference_limit'}
            require('unique_physical_energy' in targets,'physical-energy claim lacks independent physical-interpretation limit proof')
        if predset & {'not_identified','not_established_from_state_observables','not_unique_from_convention_diagnostics','no_unique_diabatic_or_free_energy_established','no_source_flip'}: require(required & pks,'claim lacks required scientific proof kind: '+topic)
    by_topic={t:[c['status'] for c in claims if c['topic']==t] for t in topics}
    rank={'not_established':0,'conditional':1,'supported':2}
    expected={k:min(by_topic[k],key=rank.get) for k in ('budgeted_numerical_execution','calculated_geometry_local_gaps','finite_population_K_water_ranking','equilibrium_or_thermodynamic_claim','marcus_parameters_and_barriers')}
    expected['chemical_state_and_physical_energy_interpretation']=min(by_topic['chemical_state_identity']+by_topic['physical_energy_interpretation'],key=rank.get)
    require(data.get('status_layers')==expected,'aggregate status_layers do not derive from validated target claims')
    _validate_output_proof_references(out,data,set(proofs))
    report_path=out/'report.md'
    try: lines=report_path.read_text(encoding='utf-8').splitlines()
    except (OSError,UnicodeError) as exc: raise ScientificFailure(f'candidate report is unreadable: {type(exc).__name__}: {exc}') from exc
    allowed_heads={'Overview','Evidence','Methods','Inference','Limitations','Follow-up'}; seen=[]
    for line in lines:
        s=line.strip()
        if not s: continue
        if s.startswith('#'):
            require(s.lstrip('#').strip() in allowed_heads,'report has an unrecognized heading')
        else:
            m=re.fullmatch(r'\{\{claim:([A-Za-z0-9_.:-]+)\}\}',s); require(m is not None,'report contains untyped scientific prose or unsupported formatting')
            cid=m.group(1); require(cid in cids,'report references unknown claim'); seen.append(cid)
    require(set(seen)==set(cids),'report does not reference every validated claim')

def _validate_output_proof_references(out,data,proof_ids):
    fields={'reason','reason_null','warning','limitations','variance_status','accounting_interpretation',
            'interpretation','counting_rule','source_approved_scope','stopping_rule','energy_component_split',
            'inference_limits','definitions','derivation','stratum_partition_rule','marginal_inclusion_formula',
            'joint_inclusion_formula','selection_design','Marcus_conventions_from_inputs_methods_json',
            'decision'}
    proof_map={p['id']:p for p in data['proofs']}
    claim_kinds={
      'variance_status':{'design_variance_nonidentifiability','population_moment_nonidentifiability'},
      'reason_null':{'marcus_identifiability'},
      'energy_component_split':{'setting_scope','source_audit'},
      'Marcus_conventions_from_inputs_methods_json':{'marcus_identifiability'},
      'between_system_point_contrasts.warning':{'ranking_nonidentifiability'},
      'contrast_flip_thresholds.warning':{'setting_scope'},
      'design_probabilities.interpretation':{'design_variance_nonidentifiability'},
      'design_probabilities.per_frame':{'design_variance_nonidentifiability'},
      'design_probabilities.distinct_frames_same_stratum':{'design_variance_nonidentifiability'},
      'design_probabilities.distinct_strata_h_and_k':{'design_variance_nonidentifiability'},
      'definitions.free':{'source_convention_comparison'},
      'definitions.extrapolated':{'source_convention_comparison'},
      'definitions.scope':{'source_convention_comparison'},
      'limitations':{'source_convention_comparison'},
      'derivation':{'source_audit'},
      'stratum_partition_rule':{'design_variance_nonidentifiability'},
      'marginal_inclusion_formula':{'design_variance_nonidentifiability'},
      'joint_inclusion_formula':{'design_variance_nonidentifiability'},
      'selection_design':{'design_variance_nonidentifiability'},
      'counting_rule':{'source_audit'},'source_approved_scope':{'source_audit'},
      'accounting_interpretation':{'source_audit'},'stopping_rule':{'source_audit'},
      'budget-interpretation.json.interpretation':{'source_audit'},
      'decision':{'source_audit','design_variance_nonidentifiability','ranking_nonidentifiability','protocol_comparison','source_convention_comparison'},
      'reason':{'source_audit','design_variance_nonidentifiability','population_moment_nonidentifiability','ranking_nonidentifiability','marcus_identifiability','state_inference_limit','protocol_comparison','source_convention_comparison'},
      'inference_limits':{'source_audit','design_variance_nonidentifiability','ranking_nonidentifiability','marcus_identifiability','state_inference_limit','protocol_comparison','setting_scope'}}
    def check(value,path=(),explanation_key=None):
        key=path[-1] if path else ''
        if key in fields: explanation_key=key
        if explanation_key is not None and isinstance(value,dict):
            require(bool(value),'proof reference field is empty: '+explanation_key)
            for k,v in value.items(): check(v,path+(k,),explanation_key)
            return
        if explanation_key is not None and isinstance(value,list):
            require(bool(value),'proof reference field is empty: '+explanation_key)
            for idx,v in enumerate(value): check(v,path+(idx,),explanation_key)
            return
        if explanation_key is not None:
            require(isinstance(value,str) and re.fullmatch(r'proof:([A-Za-z0-9_.:-]+)',value),'untyped scientific explanation field: '+explanation_key)
            require(value[6:] in proof_ids,'explanation points to an unknown proof: '+explanation_key)
            proof=proof_map[value[6:]]
            full_path='.'.join(str(x) for x in path if not isinstance(x,int))
            semantic_path='.'.join(str(x) for x in path[1:] if not isinstance(x,int))
            allowed=claim_kinds.get(full_path,claim_kinds.get(semantic_path,claim_kinds.get(explanation_key)))
            require(allowed is not None and proof['kind'] in allowed,'proof reference has no validated semantics for explanation field: '+full_path)
            if explanation_key in {'variance_status','selection_design'}:
                ensemble=next((x for x in path if isinstance(x,str) and x in {'water_neutral','water_anion','2K_neutral','2K_anion'}),None)
                inp=proof['inputs']
                require(ensemble is not None and ((proof['kind']=='design_variance_nonidentifiability' and inp.get('ensemble')==ensemble) or
                        (proof['kind']=='population_moment_nonidentifiability' and ensemble in inp.get('ensembles',[]))),
                        'design-status proof does not cover its ensemble')
        elif isinstance(value,dict):
            for k,v in value.items(): check(v,path+(k,))
        elif isinstance(value,list):
            for idx,v in enumerate(value): check(v,path+(idx,))
    for name in ('decision_log.json','marcus.json','budget-interpretation.json','standard-electronic-gap-diagnostics.json','sampling-design-audit.json'):
        check(readj(out/name),(name,))

def check_candidate(out,root,tests,refs,tasks,plan,pairs,records,contract):
    final=Path(out)
    candidate_inventory=_candidate_output_inventory(final)
    required=refs['required_outputs']
    missing=[x for x in required if (not (out/x).exists()) or ((out/x).is_file() and (out/x).stat().st_size==0)]
    require(not missing,'missing output artifact(s): '+', '.join(missing))
    permitted={x.rstrip('/') for x in required}
    extras=[p for p in candidate_inventory if p not in permitted and not p.startswith('native/')]
    require(not extras,'unrecognized candidate attachment(s) are not part of the proof contract: '+', '.join(sorted(extras)[:8]))
    for name in ('sampling_plan.json','decision_log.json','marcus.json','budget-interpretation.json',
                 'scientific-claims.json','standard-electronic-gap-diagnostics.json','sampling-design-audit.json'):
        artifact_schema=contract.get('artifact_schemas',{}).get(name,{}).get('required_fields_and_types')
        if isinstance(artifact_schema,dict): _validate_json_schema(readj(out/name),artifact_schema)
    require(eqtree(readj(out/'sampling_plan.json'),plan),'sampling_plan.json differs from frozen revision-3 plan')
    design=readj(out/'sampling-design-audit.json')
    validate_sampling_design_structure(design,plan)
    for e in plan['ensembles']:
        ens=e['ensemble']; item=design['ensembles'][ens]; N=e['target_population_size']; lo,hi=e['target_population']; q,r=divmod(N,4); cursor=lo
        require(item.get('target_population_bounds_zero_based_inclusive')==[lo,hi] and item.get('target_population_size_N')==N,'sampling-design population bounds/size mismatch')
        require(len(item.get('layers',[]))==4 and len(item.get('distinct_frame_pair_inclusion_probability_matrix',[]))==4,'sampling-design must define four layers and a 4x4 pair-probability matrix')
        require(all(len(row)==4 for row in item['distinct_frame_pair_inclusion_probability_matrix']),
                'sampling-design pair-probability matrix must be 4x4')
        for h,L in enumerate(item['layers']):
            size=q+(h<r); first=cursor;last=cursor+size-1;cursor=last+1
            task=next((t for t in tasks if t['ensemble']==ens and t['stage']=='production' and t['stratum']==h),None)
            require(L.get('stratum')==h and L.get('frame_first_zero_based_inclusive')==first and L.get('frame_last_zero_based_inclusive')==last and L.get('stratum_size_Nh')==size and near(L.get('marginal_pi_i'),1/(2*size),1e-15),'sampling stratum bound, Nh or pi mismatch')
            require(L.get('selected_by_frozen_plan')==(h in plan['selected_strata'][ens]) and L.get('observed_frame_zero_based')==(task['frame_zero_based'] if task else None) and L.get('observed_frame_within_declared_bounds') is bool(task and first<=task['frame_zero_based']<=last),'sampling selected frame mapping mismatch')
            require(task is None or (task['frame_zero_based']>=first and task['frame_zero_based']<=last and task['stratum_size']==size),'frozen task frame is outside reconstructed layer')
            for k,cell in enumerate(item['distinct_frame_pair_inclusion_probability_matrix'][h]):
                other=item['layers'][k]; expected_pi=0.0 if k==h else 1/(6*size*other['stratum_size_Nh'])
                require(cell.get('stratum_pair')==[h,k] and near(cell.get('pi_ij_distinct_frames'),expected_pi,1e-15),'sampling frame-pair inclusion matrix mismatch')
        require(cursor==hi+1,'sampling strata do not partition full target frame range')
    manifest=expected_manifest(root,tasks,plan,refs)
    submitted_manifest=readj(out/'source-manifest.json')
    if isinstance(submitted_manifest,dict) and 'native_files' in submitted_manifest:
        expected_native={rel.split('analysis/revision3/native/',1)[1]:value
                         for rel,value in refs['native_hashes'].items()}
        optional_metadata={'schema':'case04-source-manifest/v1',
                           'archive':'r3-native-raw.tar.gz',
                           'file_count':len(expected_native)}
        require(set(submitted_manifest) <= {'native_files',*optional_metadata},
                'source-manifest has unverified metadata')
        for key,value in optional_metadata.items():
            if key in submitted_manifest:
                require(type(submitted_manifest[key]) is type(value) and submitted_manifest[key]==value,
                        'source-manifest metadata mismatch: '+key)
        require(eqtree(submitted_manifest['native_files'],expected_native),
                'source-manifest native file inventory does not match the pinned raw evidence')
    else:
        require(eqtree(submitted_manifest,manifest),
                'source-manifest does not match pinned source evidence')
    # Candidate native payload must be byte-identical to every pinned native file, with no omissions.
    delivered={x for x in (out/'native').rglob('*') if x.is_file()}
    expected_names={Path(x.split('analysis/revision3/native/',1)[1]) for x in refs['native_hashes'] if x.startswith('analysis/revision3/native/')}
    got_names={p.relative_to(out/'native') for p in delivered}
    require(got_names==expected_names,'native/ file set differs from the frozen 20-attempt evidence')
    for rel in got_names:
        src_rel='analysis/revision3/native/'+str(rel)
        require(digest(out/'native'/rel)==refs['native_hashes'][src_rel],f'delivered native evidence hash mismatch: {rel}')
    csv_path=out/'energy_gaps.csv'
    rows=_candidate_csv_rows(csv_path,{'geometry_id','setting','gap_eV','native_id','converged'})
    energy_headers=list(rows[0]) if rows else None
    require(set(energy_headers or [])==set(expected_rows(pairs)[0]),'energy_gaps.csv contains uncontracted columns')
    require(len(rows)==len(tasks) and all(r.get('geometry_id') and r.get('setting') for r in rows)
            and len({r['geometry_id']+'|'+r['setting'] for r in rows})==len(rows),
            'energy_gaps.csv requires ten unique geometry/setting pairs')
    want=expected_rows(pairs); by={r['geometry_id']+'|'+r['setting']:r for r in want}
    for row in rows:
        key=row['geometry_id']+'|'+row['setting']; ref=by.get(key)
        require(ref is not None,'unexpected geometry/setting in energy_gaps.csv')
        for k,v in ref.items():
            if isinstance(v,bool): require(row.get(k,'').lower()==str(v).lower(),f'{key}: {k} mismatch')
            elif isinstance(v,(int,float)): 
                try: actual=float(row[k])
                except Exception: actual=None
                require(near(actual,float(v),1e-8),f'{key}: {k} mismatch')
            else: require(row.get(k)==str(v),f'{key}: {k} mismatch')
    budget=readj(out/'budget-interpretation.json'); source_budget=readj(root/'inputs/OS_budget.json')
    require(budget.get('approved_attempt_cap')==source_budget.get('max_electronic_state_attempts')==24 and budget.get('ledger_state_attempt_reservations')==20 and budget.get('base_attempts')==16 and budget.get('tight_replay_attempts')==4 and budget.get('unconsumed_reserved_attempts')==4,'budget task-state reservation counts mismatch')
    require(budget.get('source_attempt_accounting_wording')==source_budget.get('attempt_accounting'), 'historical budget source wording must remain exact')
    require_text(budget.get('accounting_interpretation'), 'budget accounting interpretation is missing')
    stats=calc_stats(pairs,plan); marcus=readj(out/'marcus.json')
    _check_ht_ensemble_tree(marcus.get('ensembles'),stats,
                            'marcus.json HT estimates differ from raw-native reconstruction')
    _check_marcus_extensions(marcus,stats,pairs,root)
    require(marcus.get('status')=='not_established','Marcus status must remain not_established')
    for field in ('lambda_I_eV','lambda_F_eV','lambda_eV','deltaA_I_eV','deltaA_F_eV','barrier_eV','barrier_I_eV','barrier_F_eV'):
        require(marcus.get(field) is None,f'marcus.json unsupported parameter {field} must be null')
    for system in ('water','2K'):
        m=marcus.get('marcus_by_system',{}).get(system,{})
        require(m.get('status')=='not_established' and all(m.get(k) is None for k in ('lambda_I_eV','lambda_F_eV','lambda_eV','deltaA_I_eV','deltaA_F_eV','barrier_I_eV','barrier_F_eV')),f'{system}: Marcus outputs must remain null/not_established')
    # Replay candidate analysis only in a disposable tree with the pinned native evidence and task inputs.
    with tempfile.TemporaryDirectory(prefix='case04-replay-') as td:
        tmp=Path(td); a=tmp/'analysis/revision3'; a.mkdir(parents=True)
        (tmp/'inputs').mkdir()
        shutil.copy2(root/'inputs/methods.json',tmp/'inputs/methods.json')
        shutil.copy2(out/'analysis.py',a/'analysis.py')
        shutil.copytree(root/'analysis/revision3/native',a/'native')
        rt=tmp/'runtimes/hpc/case04/review-v3'; rt.mkdir(parents=True)
        shutil.copy2(root/'runtimes/hpc/case04/review-v3/tasks.json',rt/'tasks.json')
        shutil.copy2(root/'runtimes/hpc/case04/review-v3/sampling_plan.json',rt/'sampling_plan.json')
        proc=run_candidate_analysis(a/'analysis.py',tmp)
        require(proc.returncode==0,'analysis.py replay failed: '+proc.stderr[-1200:])
        replay_csv=_candidate_csv_rows(a/'energy_gaps.csv',{'geometry_id','setting','gap_eV','native_id','converged'})
        replay_json=readj(a/'marcus.json')
        require(len(replay_csv)==len(rows),'analysis.py replay returned wrong pair count')
        for row in rows:
            rr=next((x for x in replay_csv if x['geometry_id']==row['geometry_id'] and x['setting']==row['setting']),None)
            require(rr is not None and near(_candidate_float(rr['gap_eV'],'replay gap_eV'),_candidate_float(row['gap_eV'],'delivered gap_eV'),1e-8)
                    and rr.get('native_id')==row.get('native_id')
                    and rr.get('converged','').strip().lower()==row.get('converged','').strip().lower(),
                    f"analysis.py replay mismatch for {row['geometry_id']}")
        require(eqtree(replay_json,marcus,1e-8),'analysis.py replayed marcus.json differs from delivered output')
    # Prove the candidate replay responds to valid native-source perturbations and rejects missing evidence.
    with tempfile.TemporaryDirectory(prefix='case04-source-response-') as td:
        tmp=Path(td); a=tmp/'analysis/revision3'; a.mkdir(parents=True)
        (tmp/'inputs').mkdir()
        shutil.copy2(root/'inputs/methods.json',tmp/'inputs/methods.json')
        shutil.copy2(out/'analysis.py',a/'analysis.py'); shutil.copytree(root/'analysis/revision3/native',a/'native')
        rt=tmp/'runtimes/hpc/case04/review-v3'; rt.mkdir(parents=True)
        shutil.copy2(root/'runtimes/hpc/case04/review-v3/tasks.json',rt/'tasks.json'); shutil.copy2(root/'runtimes/hpc/case04/review-v3/sampling_plan.json',rt/'sampling_plan.json')
        # Change one source state coherently (result energy and its TS09 term); this is an algebraic replay test only.
        target=None
        for rp in sorted((a/'native').glob('attempt-*/result.json')):
            rr=readj(rp)
            if rr.get('task_index')==0 and rr.get('state')==-1: target=rp; break
        require(target is not None,'cannot find perturbation source state')
        rr=readj(target); delta=0.125; rr['TS09_correction_eV']+=delta; rr['E_PBE_TS09_eV']+=delta; target.write_text(json.dumps(rr))
        # Preserve consistency of the redundant native log in this disposable
        # fixture: valid analyses may independently check result/log agreement.
        ts_path=target.parent/'ts09.txt'; ts_text=ts_path.read_text()
        for pattern in (r'(?m)^(vdW correction:\s*)([-+0-9.eE]+)',
                        r'(?m)^(Energy:\s*)([-+0-9.eE]+)'):
            ts_text,count=re.subn(pattern,lambda m:m[1]+format(float(m[2])+delta,'.17g'),ts_text)
            if count!=1:
                raise EnvironmentFailure('perturbation fixture requires exactly one TS09 energy/correction line')
        ts_path.write_text(ts_text)
        p=run_candidate_analysis(a/'analysis.py',tmp)
        require(p.returncode==0,'analysis replay failed to respond to coherent native energy perturbation: '+p.stderr[-800:])
        changed=_candidate_csv_rows(a/'energy_gaps.csv',{'geometry_id','setting','gap_eV','native_id','converged'})
        changed0=next((x for x in changed if x['geometry_id']==pairs[0]['task']['geometry_id'] and x['setting']=='base'),None)
        require(changed0 is not None,'analysis replay omitted the perturbed source geometry')
        require(near(float(changed0['gap_eV']),pairs[0]['gap']+delta,1e-8),'analysis replay is not dynamically dependent on native energy source')
        perturb_marcus=readj(a/'marcus.json'); ens=pairs[0]['task']['ensemble']; pr=pairs[0]['task']['inclusion_probability']; N=next(e['target_population_size'] for e in plan['ensembles'] if e['ensemble']==ens)
        expected_ht=stats[ens]['HT_mean_gap_eV']+delta/(pr*N)
        require(near(perturb_marcus['ensembles'][ens]['HT_mean_gap_eV'],expected_ht,1e-8),'analysis HT replay did not respond quantitatively to perturbed native source')
        missing=a/'native/attempt-001/result.json'; missing.unlink()
        p2=run_candidate_analysis(a/'analysis.py',tmp)
        require(p2.returncode!=0,'analysis replay accepted missing native state evidence')
    decision=readj(out/'decision_log.json'); budget=readj(out/'budget-interpretation.json')
    require(decision.get('budget_revision')==3 and decision.get('attempt_cap')==budget['approved_attempt_cap']==24 and decision.get('attempts_recorded')==budget['ledger_state_attempt_reservations']==20 and decision.get('observed_results')==20 and decision.get('valid_pair_summaries')==10 and decision.get('base_geometries')==8 and decision.get('tight_replays')==2,'decision log attempt counts/scope mismatch')
    require(decision.get('new_calculations_submitted')==0 and isinstance(decision.get('decisions'),list),'decision log count/scope invalid')
    claims=readj(out/'scientific-claims.json')
    require(claims.get('schema')=='case04-scientific-claims/v2.2','scientific-claims schema mismatch')
    diag=readj(out/'standard-electronic-gap-diagnostics.json')
    require(diag.get('schema')=='case04-standard-electronic-gap-diagnostics/v1' and diag.get('printed_SIC_all_zero') is True and diag.get('printed_component_precision_eV')==1e-6,'standard electronic diagnostics omit source precision/SIC checks')
    definitions=diag.get('definitions',{})
    for key in ('scope', 'free', 'extrapolated'):
        require_text(definitions.get(key), 'standard energy diagnostic definition is missing: '+key)
    ea=readj(root/'analysis/revision3/spin-audit/energy-convention-audit.json')
    require(ea.get('all_reconstructed_helpers_match_within_1e-5eV') is True and ea.get('all_printed_SIC_zero') is True and len(ea.get('states',[]))==20,'printed energy source audit incomplete')
    grows=diag.get('rows',[]); require(isinstance(grows,list) and len(grows)==10 and {x.get('task_index') for x in grows if isinstance(x,dict)}==set(range(10)) and len({x.get('task_index') for x in grows if isinstance(x,dict)})==10,'standard electronic gap diagnostics need ten unique task rows')
    diag_csv=_candidate_csv_rows(out/'standard-electronic-gap-diagnostics.csv',{'task_index','geometry_id','stage','ensemble','setting'})
    diag_headers=list(diag_csv[0]) if diag_csv else None
    require(set(diag_headers or [])==set(grows[0]),'standard diagnostics CSV contains uncontracted columns')
    task_indices=[int(_candidate_float(x['task_index'],'standard diagnostics task_index')) for x in diag_csv]
    require(len(diag_csv)==10 and set(task_indices)==set(range(10)),'standard electronic gap CSV task coverage mismatch')
    src={(x['task_index'],x['state']):x for x in ea['states']}
    for gr in grows:
        t=next((z for z in tasks if z['index']==gr.get('task_index')),None); require(t is not None and gr.get('geometry_id')==t['geometry_id'] and gr.get('stage')==t['stage'] and gr.get('ensemble')==t['ensemble'] and gr.get('setting')==t['setting'],'diagnostic row task identity mismatch')
        n=src[(t['index'],0)]; a=src[(t['index'],-1)]
        for pre,field in [('free_minus_external','printed_free_minus_external_eV'),('extrapolated_minus_external','printed_extrapolated_minus_external_eV')]:
            expectedn=n[field]+n['TS09_eV']; expecteda=a[field]+a['TS09_eV']; expected=expecteda-expectedn
            require(near(gr.get(pre+'_neutral_plus_TS09_eV'),expectedn,1e-8) and near(gr.get(pre+'_anion_plus_TS09_eV'),expecteda,1e-8) and near(gr.get(pre+'_gap_plus_state_specific_TS09_eV'),expected,1e-8),'alternative energy convention state energy/gap arithmetic mismatch')
            cr=next((z for z in diag_csv if int(_candidate_float(z['task_index'],'standard diagnostics task_index'))==t['index']),None)
            require(cr is not None and cr.get('ensemble')==t['ensemble'] and cr.get('setting')==t['setting'] and cr.get('geometry_id')==t['geometry_id'] and cr.get('stage')==t['stage'] and near(_candidate_float(cr[pre+'_neutral_plus_TS09_eV'],pre),expectedn,1e-8) and near(_candidate_float(cr[pre+'_anion_plus_TS09_eV'],pre),expecteda,1e-8) and near(_candidate_float(cr[pre+'_gap_plus_state_specific_TS09_eV'],pre),expected,1e-8),'alternative-energy CSV state values differ from source-derived diagnostics')
    expected_diag_ht={}
    for pre,field in [('free_minus_external','free_minus_external_gap_plus_state_specific_TS09_eV'),('extrapolated_minus_external','extrapolated_minus_external_gap_plus_state_specific_TS09_eV')]:
        convention=field
        expected_diag_ht[convention]={}
        for ens in sorted({t['ensemble'] for t in tasks if t['stage']=='production'}):
            selected=[t for t in tasks if t['ensemble']==ens and t['stage']=='production']
            gaps=[next(r for r in grows if r['task_index']==t['index'])[field] for t in selected]
            N=next(e['target_population_size'] for e in plan['ensembles'] if e['ensemble']==ens)
            expected_diag_ht[convention][ens]={'HT_mean_eV':sum(g/t['inclusion_probability'] for g,t in zip(gaps,selected))/N,'observed_gaps_eV':gaps}
    require(eqtree(diag.get('HT_diagnostics'),expected_diag_ht,1e-8),
            'standard electronic diagnostics HT tree differs from source-reconstructed four-ensemble values')
    for field in ('native_ledger_records','unique_task_state_records'):
        require(type(budget.get(field)) is int and budget[field]==len(records),
                'budget native reservation count differs from independently audited records: '+field)
    require(type(budget.get('budget_revision')) is int and budget['budget_revision']==plan['budget_revision'],
            'budget revision differs from pinned plan')
    try:
        argument_result=_validate_scientific_argument(out,root,refs,tasks,plan,pairs,records,stats,diag_rows=grows,energy_audit=ea)
    except ScientificFailure:
        raise
    except (KeyError,TypeError,IndexError,ValueError,OverflowError,RecursionError) as exc:
        raise ScientificFailure(f'candidate scientific argument has an invalid shape/value: {type(exc).__name__}: {exc}') from exc
    final_inventory=_candidate_output_inventory(final)
    if final_inventory!=candidate_inventory:
        raise ScientificFailure('candidate artifact inventory changed during verification')
    return {'status':'PASS','reward':1,'verification_coverage':'COMPLETE',
      'attempts':len(records),'valid_pairs':len(pairs),'production_pairs':8,
      'sensitivity_pairs':2,'new_scientific_calculations':0,
      'population_inference':argument_result['finite_population_K_water_ranking'],
      'marcus':argument_result['marcus_parameters_and_barriers'],
      'scientific_claim_count':argument_result['claim_count'],
      'proof_count':argument_result['proof_count']}

def main():
    if len(sys.argv)!=2:
        print(json.dumps({'status':'ENVIRONMENT_ERROR','error':'usage: case04_verify.py OUTPUT_DIR'},ensure_ascii=False)); return 2
    output_raw=Path(sys.argv[1]); root=Path(os.environ.get('APP','/app')).resolve()
    tests=Path(os.environ.get('TESTS','/tests')).resolve()
    try:
        if output_raw.is_symlink(): raise ScientificFailure('candidate output root cannot be a symlink')
        try:
            out=output_raw.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ScientificFailure('candidate output directory is missing') from exc
        refs_path=tests/'refs.json'
        if refs_path.is_symlink() or not refs_path.is_file():
            raise EnvironmentFailure('trusted refs.json is missing or redirected')
        try: refs=readj(refs_path)
        except Exception as exc: raise EnvironmentFailure(f'trusted refs.json is invalid: {exc}') from exc
        contract_path=_safe_source(root,'assets/output-contract.json')
        if digest(contract_path)!=refs.get('public_contract_sha256'):
            raise EnvironmentFailure('public output contract hash mismatch')
        contract=readj(contract_path)
        if contract.get('scientific_proof_protocol',{}).get('schema')!='case04-scientific-proof-protocol/v2.2':
            raise EnvironmentFailure('unsupported public scientific proof protocol')
        with tempfile.TemporaryDirectory(prefix='case04-trusted-sources-') as work:
            trusted=Path(work)
            materialize_sources(root,tests,refs,trusted)
            try:
                tasks,plan=load_sources(trusted,refs)
                expected=expected_manifest(trusted,tasks,plan,refs)
                records,pairs=audit_native(trusted,tasks,refs)
            except EnvironmentFailure:
                raise
            except Exception as exc:
                raise EnvironmentFailure(f'trusted frozen evidence is damaged or inconsistent: {type(exc).__name__}: {exc}') from exc
            result=check_candidate(out,trusted,tests,refs,tasks,plan,pairs,records,contract)
        print(json.dumps(result,ensure_ascii=False)); return 0
    except EnvironmentFailure as e:
        print(json.dumps({'status':'ENVIRONMENT_ERROR','error':str(e)},ensure_ascii=False)); return 2
    except ScientificFailure as e:
        print(json.dumps({'status':'FAIL','reward':0,'verification_coverage':'COMPLETE','errors':[type(e).__name__+': '+str(e)]},ensure_ascii=False)); return 1
    except Exception as e:
        print(json.dumps({'status':'ENVIRONMENT_ERROR','error':type(e).__name__+': '+str(e)},ensure_ascii=False)); return 2

if __name__=='__main__':
    if sys.argv[1:]==['--grade']:
        raise SystemExit(_grade_entry())
    raise SystemExit(main())
