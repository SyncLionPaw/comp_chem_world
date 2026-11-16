#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Identify interlayer modes from a native MoS₂ trajectory.
"""Case05 v4 scorer: candidate-submitted execution provenance, native physics and independent spectra.

Candidate artifacts are untrusted. The verifier cross-checks their execution records,
native manifest, file hashes, rank claims, and raw simulation evidence before it
independently recomputes Fourier projections and cross-spectral checks.
"""
from __future__ import annotations
import json, hashlib, math, os, re, stat, sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
try:
    import numpy as np
    _NUMPY_IMPORT_ERROR=None
except Exception as _e:
    np=None
    _NUMPY_IMPORT_ERROR=_e

HERE=Path(__file__).resolve().parent
ANALYSIS=HERE
sys.path.insert(0,str(ANALYSIS))
try:
    import score_reference as sr
except Exception:
    sr=None

TASK='case05-generic-native-modes-v4'
ARTIFACT_SCHEMA='case05-generic-mode-evidence/v1'
ATOMS_PER_LAYER=3534
KB=8.617333262145e-5
BRANCHES=('S','LB')
PUBLIC_EVIDENCE_REQUIRED={'manifest','input','eqmon','com','thermo_log'}
PROVENANCE_EVIDENCE_REQUIRED={'native_manifest','execution_receipt','scheduler_record','execution_order','batch_script','job_stdout','job_stderr'}
LOCKED_ASSET_MANIFEST_SHA256='23f77f707b9866860c48b487f59802dcde8ec9b78a2df94a29167651a4eb6576'
LOCKED_SELECTION={'N':2,'seed':24101,'atoms':7068}
NATIVE_REQUIRED_ROLES=('manifest','input','data','deletion_map','source','potential_rebomos_source','potential_rebomos_derived','potential_ilp','potential_diagnostics',
    'potential_composite_stdout','potential_rebo_stdout','potential_ilp_stdout','force_baseline_composite','force_baseline_rebo','force_baseline_ilp',
    'force_compressed_composite','force_compressed_rebo','force_compressed_ilp','force_rebo_baseline','force_rebo_compressed','restart_min','restart_equil','restart_final',
    'eqmon','com','thermo_log','stdout')
REQUIRED_EXECUTION_STEPS={'potential_baseline_composite','potential_baseline_rebo','potential_baseline_ilp','potential_rigid_shift_composite',
    'potential_compressed_composite','potential_compressed_rebo','potential_compressed_ilp','minimization','npt_equilibration','nve_production'}
class InfraError(Exception): pass
class ScienceFail(Exception): pass

def sha(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def finite_num(x,label,positive=False):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or (positive and x<=0):
        raise ScienceFail(f'{label} must be a finite '+('positive ' if positive else '')+'number')
    return float(x)

def load_json(path:Path,infra=False):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>32*1024*1024: raise ValueError('missing, symlink, or oversized JSON')
        return json.loads(path.read_text(encoding='utf-8'),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    except Exception as e:
        cls=InfraError if infra else ScienceFail
        raise cls(f'cannot load JSON {path}: {type(e).__name__}: {e}') from e

def _numeric_table(path:Path, columns:int, label:str)->np.ndarray:
    rows=[]
    try:
        for lineno,line in enumerate(path.read_text(encoding='utf-8').splitlines(),1):
            t=line.strip()
            if not t or t.startswith('#'): continue
            vals=[float(x) for x in t.split()]
            if len(vals)!=columns or not all(math.isfinite(x) for x in vals) or not vals[0].is_integer():
                raise ValueError(f'{label}:{lineno}: malformed finite numeric row')
            rows.append(vals)
    except Exception as e: raise ScienceFail(f'{label} parse failed: {e}') from e
    if not rows: raise ScienceFail(f'{label} is empty')
    return np.asarray(rows,dtype=float)

def _data_rows(path:Path)->list[tuple]:
    rows=[]; active=False; ids=set()
    for line in path.read_text(encoding='utf-8',errors='strict').splitlines():
        t=line.strip()
        if t.startswith('Atoms'): active=True; continue
        if not active or not t: continue
        f=t.split()
        if len(f)==7 and f[0].isdigit():
            try: row=(int(f[0]),int(f[1]),int(f[2]),float(f[3]),float(f[4]),float(f[5]),float(f[6]))
            except Exception as e: raise ScienceFail('malformed native Atoms row') from e
            if row[0] in ids or not all(math.isfinite(x) for x in row[3:]): raise ScienceFail('duplicate atom ID or nonfinite atom data')
            ids.add(row[0]); rows.append(row)
        elif rows: break
    if not rows: raise ScienceFail('native data has no parseable Atoms rows')
    return rows

def _data_ids(path:Path)->set[int]: return {r[0] for r in _data_rows(path)}

def _run0(path:Path,style:str,tag:str)->list[float]:
    count=6 if style=='composite' else 4
    rx=re.compile(r'^C05_RESULT\s+'+re.escape(tag)+r'\s+(.+?)\s*$',re.M)
    matches=rx.findall(path.read_text(encoding='utf-8',errors='replace'))
    if len(matches)!=1: raise ScienceFail(f'{path.name}: expected one anchored {tag} record')
    toks=matches[0].split(); num=r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'
    if len(toks)!=count or any(re.fullmatch(num,t) is None for t in toks): raise ScienceFail(f'{path.name}: malformed run0 record')
    out=[float(x) for x in toks]
    if not all(math.isfinite(x) for x in out): raise ScienceFail(f'{path.name}: nonfinite run0 record')
    return out

def _forces(path:Path,ids:set[int])->dict[int,tuple[float,float,float]]:
    lines=path.read_text(encoding='utf-8',errors='replace').splitlines()
    hi=next((i for i,l in enumerate(lines) if l.startswith('ITEM: ATOMS ')),None)
    if hi is None: raise ScienceFail(f'{path.name}: missing force dump header')
    cols=lines[hi].split()[2:]
    try: ix,iy,iz,ii=(cols.index(k) for k in ('fx','fy','fz','id'))
    except ValueError as e: raise ScienceFail(f'{path.name}: force columns missing') from e
    result={}
    for line in lines[hi+1:]:
        if not line.strip(): continue
        f=line.split()
        try: atom=int(f[ii]); vec=(float(f[ix]),float(f[iy]),float(f[iz]))
        except Exception as e: raise ScienceFail(f'{path.name}: malformed force row') from e
        if atom in result or not all(math.isfinite(x) for x in vec): raise ScienceFail(f'{path.name}: duplicate/nonfinite force')
        result[atom]=vec
    if set(result)!=ids: raise ScienceFail(f'{path.name}: force atom-ID set differs from cleaned data')
    return result

def verify_native_inputs_and_preflight(files:dict[str,Path],sel:dict,expected_mpi_ranks:int=10)->dict:
    n=sel['N']; seed=sel['seed']; expected_atoms=sel['atoms']
    required=('manifest','input','data','deletion_map','source','potential_rebomos_source','potential_rebomos_derived','potential_ilp','potential_diagnostics',
      'potential_composite_stdout','potential_rebo_stdout','potential_ilp_stdout','force_baseline_composite','force_baseline_rebo','force_baseline_ilp',
      'force_compressed_composite','force_compressed_rebo','force_compressed_ilp','force_rebo_baseline','force_rebo_compressed','restart_min','restart_equil','restart_final')
    missing=[r for r in required if r not in files]
    if missing: raise InfraError('trusted native protocol roles missing: '+','.join(missing))
    manifest=load_json(files['manifest'],infra=True)
    if manifest.get('N')!=n or manifest.get('seed')!=seed or manifest.get('atoms')!=expected_atoms or manifest.get('protocol',{}).get('timestep_fs')!=1 or manifest.get('protocol',{}).get('equilibration_steps')!=250000 or manifest.get('protocol',{}).get('production_steps')!=50000:
        raise ScienceFail('native manifest selection/count/protocol mismatch')
    fixed=sr.CANDIDATE_HASHES.get((n,seed))
    if fixed is None: raise InfraError('selected N/seed lacks a trusted fixed candidate identity')
    observed={'manifest':sha(files['manifest']),'data':sha(files['data']),'deletion_map':sha(files['deletion_map']),'input':sha(files['input'])}
    if observed!=fixed: raise ScienceFail('native manifest/input/data/deletion-map differ from the fixed reviewed candidate registry')
    if sha(files['source'])!=sr.EXPECTED_SOURCE_SHA256: raise ScienceFail('native source SHA mismatch')
    expected_pots={'MoS.rebomos':sr.POTENTIAL_SHA256['MoS.rebomos'],'MoS.rebomos.rebo-only':sr.POTENTIAL_SHA256['MoS.rebomos.rebo-only'],'TMD.ILP':sr.POTENTIAL_SHA256['TMD.ILP']}
    potpaths={'MoS.rebomos':files['potential_rebomos_source'],'MoS.rebomos.rebo-only':files['potential_rebomos_derived'],'TMD.ILP':files['potential_ilp']}
    for k,path in potpaths.items():
        if sha(path)!=expected_pots[k] or manifest.get('potential_sha256',{}).get(k)!=expected_pots[k]: raise ScienceFail(f'native potential identity mismatch: {k}')
    if sha(files['data'])!=manifest.get('data_sha256') or sha(files['input'])!=manifest.get('input_sha256') or sha(files['deletion_map'])!=manifest.get('duplicate_removal_map_sha256'):
        raise ScienceFail('native manifest does not bind input/data/deletion-map bytes')
    rows=_data_rows(files['data']); ids={r[0] for r in rows}
    if len(ids)!=expected_atoms: raise ScienceFail('native data atom count differs from selected N')
    if any(row[1] not in range(1,n+1) or row[2] not in range(1,7) for row in rows): raise ScienceFail('native molecule/type mapping outside selected stack')
    for layer in range(1,n+1):
        allowed={1,2,3} if layer%2 else {4,5,6}
        layer_rows=[r for r in rows if r[1]==layer]
        if len(layer_rows)!=3534 or {r[2] for r in layer_rows}!=allowed or any(sum(1 for r in layer_rows if r[2]==t)!=1178 for t in allowed):
            raise ScienceFail(f'native molecule/type assignment invalid in layer {layer}')
    zmeans=[float(np.mean([r[6] for r in rows if r[1]==layer])) for layer in range(1,n+1)]
    if not all(a<b for a,b in zip(zmeans,zmeans[1:])): raise ScienceFail('native input layer order is not bottom-to-top')
    txt=files['input'].read_text(encoding='utf-8',errors='strict')
    required_lines=('units           metal','boundary        p p f','timestep        0.001','loop local','pair_style      hybrid/overlay rebomos rebomos ilp/tmd 16.0 1','mass 1 95.95','mass 2 32.065','mass 3 32.065','mass 4 95.95','mass 5 32.065','mass 6 32.065','fix             equil all npt temp 300.0 300.0 0.1 x 0.0 0.0 1.0 y 0.0 0.0 1.0 couple xy','fix             prod all nve')
    if any(x not in txt for x in required_lines) or not re.search(rf'velocity\s+all\s+create\s+300(?:\.0)?\s+{seed}.*loop local',txt): raise ScienceFail('native input does not contain required boundary, timestep, or fixed loop-local seed')
    if len(re.findall(r'^run\s+250000\s*$',txt,re.M))!=1 or len(re.findall(r'^run\s+50000\s*$',txt,re.M))!=1: raise ScienceFail('native input does not encode full 250k+50k stages')
    for role in ('restart_min','restart_equil','restart_final'):
        if not files[role].is_file() or files[role].stat().st_size<128: raise ScienceFail(f'{role}: native restart is absent or truncated')
    if type(expected_mpi_ranks) is not int or not 1 <= expected_mpi_ranks <= 10:
        raise InfraError('trusted actual MPI rank count is outside the host-approved 1..10 range')
    for role in ('potential_composite_stdout','potential_rebo_stdout','potential_ilp_stdout'):
        grid=re.findall(r'^\s*(\d+) by (\d+) by (\d+) MPI processor grid\s*$',files[role].read_text(encoding='utf-8',errors='replace'),re.M)
        if len(grid)!=1 or math.prod(int(x) for x in grid[0])!=expected_mpi_ranks: raise ScienceFail(f'{role}: native MPI grid differs from candidate-reported ranks')
    if 'stdout' not in files: raise InfraError('full-run stdout role missing')
    grids=re.findall(r'^\s*(\d+) by (\d+) by (\d+) MPI processor grid\s*$',files['stdout'].read_text(encoding='utf-8',errors='replace'),re.M)
    if len(grids)!=1 or math.prod(int(x) for x in grids[0])!=expected_mpi_ranks: raise ScienceFail('formal MD native processor grid differs from candidate-reported ranks')
    diag=load_json(files['potential_diagnostics'])
    if not isinstance(diag,dict): raise ScienceFail('potential diagnostics evidence must be a JSON object')
    # Recompute the fixed-geometry checks from anchored scalar records and full ID force dumps.
    rec={style:{tag:_run0(files[f'potential_{style}_stdout'],style,tag) for tag in (('baseline','rigid_shift','compressed') if style=='composite' else ('baseline','compressed'))} for style in ('composite','rebo','ilp')}
    for tag,(pe,odd,even,vdw,rep,_fmax) in rec['composite'].items():
        if abs(pe-odd-even-vdw-rep)>1e-6+1e-8*abs(pe) or vdw>=0 or rep<=0: raise ScienceFail(f'{tag}: run0 energy decomposition/sign gate failed')
    ids=_data_ids(files['data']); add_err={}
    for geom in ('baseline','compressed'):
        c=_forces(files[f'force_{geom}_composite'],ids); r=_forces(files[f'force_{geom}_rebo'],ids); il=_forces(files[f'force_{geom}_ilp'],ids)
        fmax=max(abs(v) for vv in c.values() for v in vv)
        err=max(abs(c[i][a]-r[i][a]-il[i][a]) for i in ids for a in range(3))
        if err>1e-6+1e-8*fmax: raise ScienceFail(f'{geom}: force additivity failed')
        add_err[geom]=err
    rb=_run0(files['potential_rebo_stdout'],'rebo','baseline')[0]; rc=_run0(files['potential_rebo_stdout'],'rebo','compressed')[0]
    ib=_run0(files['potential_ilp_stdout'],'ilp','baseline')[0]; ic=_run0(files['potential_ilp_stdout'],'ilp','compressed')[0]
    for tag in ('baseline','compressed'):
        c=rec['composite'][tag][0]; r=rec['rebo'][tag][0]; il=rec['ilp'][tag][0]
        if abs(c-r-il)>1e-6+1e-8*abs(c): raise ScienceFail(f'{tag}: REBO/ILP energy additivity failed')
    c=rec['composite']['baseline']; d=rec['composite']['rigid_shift']
    if abs(c[1]-d[1])>1e-6 or abs(c[2]-d[2])>1e-6 or abs(c[3]+c[4]-d[3]-d[4])<=1e-10: raise ScienceFail('rigid-layer probe lacks REBO invariance or ILP response')
    if abs(rb-rc)>1e-6+1e-8*abs(rb) or abs(ib-ic)<1e-8: raise ScienceFail('compressed cross-layer REBO isolation/ILP response failed')
    r0=_forces(files['force_rebo_baseline'],ids); r1=_forces(files['force_rebo_compressed'],ids)
    delta=max(abs(r0[i][a]-r1[i][a]) for i in ids for a in range(3))
    if delta>1e-6+1e-8*max(abs(v) for row in r0.values() for v in row): raise ScienceFail('REBO-only cross-layer force isolation failed')
    return {'status':'PASS_RECOMPUTED','atoms':expected_atoms,'run0_force_additivity_eV_A':add_err,'rebo_cross_layer_force_delta_eV_A':delta,'potential_diagnostics_receipt_status':diag.get('status')}

def candidate_path(root:Path,rel:object,label:str)->Path:
    if not isinstance(rel,str) or not rel or '\\' in rel or '\x00' in rel:
        raise ScienceFail(f'{label}: path must be a non-empty relative POSIX path')
    p=PurePosixPath(rel)
    if p.is_absolute() or p.as_posix()!=rel or any(x in {'','.','..'} for x in p.parts):
        raise ScienceFail(f'{label}: path must stay below final/')
    cur=Path(root)
    if cur.is_symlink(): raise ScienceFail(f'{label}: final root may not be a symlink')
    for part in p.parts:
        cur=cur/part
        if cur.is_symlink(): raise ScienceFail(f'{label}: evidence path traverses a symlink')
    if not cur.is_file(): raise ScienceFail(f'{label}: submitted evidence file is missing')
    return cur

def validate_execution_records(receipt:dict,scheduler:dict,order:dict,script:Path,job_stdout:Path,job_stderr:Path,native_manifest:dict,native_manifest_path:Path)->dict:
    if receipt.get('schema')!='case05-execution-receipt/v1' or scheduler.get('schema')!='case05-scheduler-record/v1' or order.get('schema')!='case05-execution-order/v1':
        raise ScienceFail('execution provenance schema mismatch')
    required_receipt={'job_id','request_id','scheduler','allocation_id','resources','wall_seconds','exit_code','batch_script_sha256','stdout_sha256','stderr_sha256','native_manifest_sha256'}
    if not required_receipt.issubset(receipt) or not isinstance(receipt.get('job_id'),str) or not receipt['job_id'].strip() or not isinstance(receipt.get('request_id'),str) or not receipt['request_id'].strip():
        raise ScienceFail('execution receipt is missing job or execution fields')
    if not isinstance(receipt.get('scheduler'),str) or not receipt['scheduler'].strip() or receipt['scheduler'].lower() in {'local','none'}:
        raise ScienceFail('execution receipt must name the HPC scheduler')
    if not isinstance(receipt.get('allocation_id'),str) or not receipt['allocation_id'].strip():
        raise ScienceFail('execution receipt allocation_id is missing')
    if scheduler.get('job_id')!=receipt['job_id'] or scheduler.get('scheduler')!=receipt['scheduler'] or scheduler.get('allocation_id')!=receipt['allocation_id']:
        raise ScienceFail('receipt and scheduler record job/allocation identity differs')
    if type(scheduler.get('array_job')) is not bool or scheduler['array_job'] or scheduler.get('array_task_id') not in (None,''):
        raise ScienceFail('execution must document one non-array allocation')
    resources=receipt.get('resources'); sched_resources=scheduler.get('resources')
    resource_keys={'cpus','memory_gib','walltime_seconds','gpus','mpi_ranks'}
    if not isinstance(resources,dict) or set(resources)!=resource_keys or resources!=sched_resources:
        raise ScienceFail('receipt and scheduler resource records are missing or inconsistent')
    if (type(resources['cpus']) is not int or not 1<=resources['cpus']<=10
        or type(resources['mpi_ranks']) is not int or not 1<=resources['mpi_ranks']<=10 or resources['mpi_ranks']>resources['cpus']
        or type(resources['memory_gib']) is not int or not 1<=resources['memory_gib']<=16
        or type(resources['walltime_seconds']) is not int or not 60<=resources['walltime_seconds']<=21600 or resources['walltime_seconds']%60
        or type(resources['gpus']) is not int or resources['gpus']!=0):
        raise ScienceFail('selected resources exceed the public offline caps')
    if scheduler.get('final_state') not in {'COMPLETED','FAILED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','CANCELLED'}:
        raise ScienceFail('scheduler record does not show a terminal job state')
    if receipt.get('exit_code')!=scheduler.get('exit_code'):
        raise ScienceFail('receipt and scheduler exit codes differ')
    try:
        start=datetime.fromisoformat(scheduler['start_time'].replace('Z','+00:00'))
        end=datetime.fromisoformat(scheduler['end_time'].replace('Z','+00:00'))
        wall=float(receipt['wall_seconds']); scheduler_wall=float(scheduler['wall_seconds'])
    except Exception as e: raise ScienceFail(f'execution timestamps or wall time are malformed: {e}') from e
    span=(end-start).total_seconds()
    if start.tzinfo is None or end.tzinfo is None or not math.isfinite(wall) or not math.isfinite(scheduler_wall) or wall<=0 or span<=0 or abs(wall-scheduler_wall)>1.0 or abs(span-wall)>2.0 or wall>resources['walltime_seconds']+2:
        raise ScienceFail('reported wall time disagrees with scheduler timestamps or limit')
    if sha(script)!=receipt.get('batch_script_sha256') or not re.fullmatch(r'[0-9a-f]{64}',str(receipt.get('batch_script_sha256',''))):
        raise ScienceFail('batch-script hash does not match execution receipt')
    if sha(job_stdout)!=receipt.get('stdout_sha256') or sha(job_stderr)!=receipt.get('stderr_sha256'):
        raise ScienceFail('job stdout/stderr hash does not match execution receipt')
    nm_sha=sha(native_manifest_path)
    if receipt.get('native_manifest_sha256')!=nm_sha or scheduler.get('native_manifest_sha256')!=nm_sha or order.get('native_manifest_sha256')!=nm_sha:
        raise ScienceFail('native manifest hash is not cross-bound by all execution records')
    if order.get('job_id')!=receipt['job_id'] or order.get('allocation_id')!=receipt['allocation_id'] or order.get('batch_script_sha256')!=receipt['batch_script_sha256']:
        raise ScienceFail('execution-order record is not bound to the submitted job and script')
    steps=order.get('ordered_steps')
    if not isinstance(steps,list) or any(not isinstance(x,str) for x in steps) or len(steps)!=len(set(steps)) or not REQUIRED_EXECUTION_STEPS.issubset(steps):
        raise ScienceFail('execution-order record omits or duplicates required protocol arms')
    try:
        if not (steps.index('minimization')<steps.index('npt_equilibration')<steps.index('nve_production')):
            raise ScienceFail('execution-order record does not preserve minimization, NPT, then NVE')
    except ValueError as e: raise ScienceFail('execution-order record omits a required MD stage') from e
    if native_manifest.get('schema')!='case05-native-execution-manifest/v1' or native_manifest.get('job_id')!=receipt['job_id'] or native_manifest.get('allocation_id')!=receipt['allocation_id'] or native_manifest.get('N')!=2 or native_manifest.get('seed')!=24101 or native_manifest.get('atoms')!=7068 or native_manifest.get('mpi_ranks')!=resources['mpi_ranks']:
        raise ScienceFail('native manifest does not match the fixed instance and execution allocation')
    return {'state':scheduler['final_state'],'exit_code':str(scheduler['exit_code']),'job_id':receipt['job_id'],
        'allocation_id':receipt['allocation_id'],'scheduler':receipt['scheduler'],'alloc_cpus':resources['cpus'],
        'mpi_ranks':resources['mpi_ranks'],'cpus':resources['cpus'],'memory_gib':resources['memory_gib'],
        'walltime_limit_seconds':resources['walltime_seconds'],'elapsed_seconds':int(round(wall)),
        'wall_seconds':wall,'start_time':scheduler['start_time'],'end_time':scheduler['end_time'],'array_job':False}

def candidate_context(final_root:Path,asset_root:Path)->tuple[dict,dict[str,Path]]:
    final_root=Path(final_root); asset_root=Path(asset_root)
    asset_manifest=asset_root/'n2-seed24101'/'manifest.json'
    if asset_manifest.is_symlink() or not asset_manifest.is_file(): raise InfraError('locked N2/24101 asset manifest is unavailable')
    if sha(asset_manifest)!=LOCKED_ASSET_MANIFEST_SHA256: raise InfraError('locked N2/24101 asset manifest hash mismatch')
    fixed_manifest=load_json(asset_manifest,infra=True)
    if {k:fixed_manifest.get(k) for k in ('N','seed','atoms')}!=LOCKED_SELECTION:
        raise InfraError('locked asset manifest does not describe N2 seed 24101')
    doc=load_json(final_root/'modes.json')
    if not isinstance(doc,dict) or not isinstance(doc.get('runs'),list) or len(doc['runs'])!=1 or not isinstance(doc['runs'][0],dict):
        raise ScienceFail('one submitted run record is required to resolve candidate evidence')
    run=doc['runs'][0]; evidence=run.get('evidence')
    if not isinstance(evidence,dict): raise ScienceFail('candidate evidence role index is missing')
    expected_proof=set(PROVENANCE_EVIDENCE_REQUIRED)
    proof_paths={role:candidate_path(final_root,evidence.get(role),role) for role in expected_proof}
    native_manifest_path=proof_paths['native_manifest']; native_manifest=load_json(native_manifest_path)
    if not isinstance(native_manifest,dict): raise ScienceFail('native execution manifest must be a JSON object')
    if native_manifest.get('asset_manifest_sha256')!=LOCKED_ASSET_MANIFEST_SHA256:
        raise ScienceFail('native execution manifest does not bind the locked public input instance')
    roles=native_manifest.get('roles')
    if not isinstance(roles,dict) or set(roles)!=set(NATIVE_REQUIRED_ROLES):
        raise ScienceFail('native manifest roles do not cover the required native protocol evidence')
    byrole={}
    for role,row in roles.items():
        if not isinstance(row,dict) or set(row)!={'path','sha256'} or not re.fullmatch(r'[0-9a-f]{64}',str(row.get('sha256',''))):
            raise ScienceFail(f'native manifest role record malformed: {role}')
        if evidence.get(role)!=row['path']: raise ScienceFail(f'modes.json evidence path differs from native manifest role: {role}')
        p=candidate_path(final_root,row['path'],role)
        if sha(p)!=row['sha256']: raise ScienceFail(f'native manifest hash mismatch for submitted role {role}')
        byrole[role]=p
    if set(evidence)!=set(NATIVE_REQUIRED_ROLES)|expected_proof|({'scheduler_log'} if 'scheduler_log' in evidence else set()):
        raise ScienceFail('candidate evidence index has missing or unsupported roles')
    for role,path in proof_paths.items(): byrole[role]=path
    diagnostics=load_json(byrole['potential_diagnostics'])
    if not isinstance(diagnostics,dict): raise ScienceFail('potential diagnostics evidence must be a JSON object')
    receipt=load_json(proof_paths['execution_receipt']); scheduler=load_json(proof_paths['scheduler_record']); order=load_json(proof_paths['execution_order'])
    if not all(isinstance(x,dict) for x in (receipt,scheduler,order)):
        raise ScienceFail('execution receipt, scheduler record, and execution-order record must be JSON objects')
    normalized=validate_execution_records(receipt,scheduler,order,proof_paths['batch_script'],proof_paths['job_stdout'],proof_paths['job_stderr'],native_manifest,native_manifest_path)
    if 'scheduler_log' in evidence:
        log=candidate_path(final_root,evidence['scheduler_log'],'scheduler_log')
        raw=scheduler.get('raw_scheduler_log_path')
        if raw!=evidence['scheduler_log']: raise ScienceFail('scheduler raw-log path differs from execution evidence index')
        if scheduler.get('raw_scheduler_log_sha256')!=sha(log): raise ScienceFail('scheduler raw-log hash mismatch')
        byrole['scheduler_log']=log
    if run.get('request_id')!=receipt.get('request_id') or run.get('job_id')!=receipt.get('job_id'):
        raise ScienceFail('modes.json job/request identifiers differ from candidate receipt')
    if run.get('mpi_ranks')!=native_manifest.get('mpi_ranks'):
        raise ScienceFail('modes.json MPI ranks differ from native manifest')
    ctx={'scope':'AGENT_FORMAL','expected_selection':LOCKED_SELECTION,'request_id':receipt['request_id'],'job_id':receipt['job_id'],
        'mpi_ranks':native_manifest['mpi_ranks'],'scheduler':normalized,
        'files':[{'role':role,'path':evidence[role]} for role in evidence]}
    return ctx,byrole

def validate_artifact(doc:object,ctx:dict)->dict:
    if not isinstance(doc,dict) or set(doc)!={'schema','task_version','runs'} or doc.get('schema')!=ARTIFACT_SCHEMA or doc.get('task_version')!=TASK:
        raise ScienceFail('final/modes.json schema/task_version mismatch')
    runs=doc.get('runs')
    if not isinstance(runs,list) or len(runs)!=1: raise ScienceFail('one trusted selection requires exactly one run record')
    run=runs[0]; sel=ctx['expected_selection']
    base_run_keys={'N','seed','request_id','job_id','evidence','sampling','modes','mpi_ranks'}
    if not isinstance(run,dict) or set(run)!=base_run_keys or type(run.get('N')) is not int or type(run.get('seed')) is not int or run['N']!=sel['N'] or run['seed']!=sel['seed']:
        raise ScienceFail('artifact selection differs from the locked public N2/24101 instance')
    actual_ranks=ctx['scheduler']['mpi_ranks'] if ctx['scope']=='AGENT_FORMAL' else 10
    if type(run.get('mpi_ranks')) is not int or not 1 <= run['mpi_ranks'] <= 10:
        raise ScienceFail('artifact mpi_ranks must be an integer within the public 1..10 rank cap')
    if run['mpi_ranks']!=actual_ranks:
        raise ScienceFail('artifact MPI rank claim differs from candidate execution records')
    if run.get('request_id')!=ctx['request_id'] or run.get('job_id')!=ctx['job_id']:
        raise ScienceFail('artifact request/job identity differs from candidate execution records')
    evidence=run.get('evidence'); sampling=run.get('sampling')
    public_paths={row['role']:row['path'] for row in ctx['files']}
    if (not isinstance(evidence,dict) or not PUBLIC_EVIDENCE_REQUIRED.issubset(evidence)
        or not PROVENANCE_EVIDENCE_REQUIRED.issubset(evidence) or evidence!=public_paths):
        raise ScienceFail('artifact evidence index must list every candidate-submitted native and execution record')
    if sampling!={'native_eqmon_rows':251,'native_com_rows':50001,'dt_fs':1,'canonical_com_rows':50000}:
        raise ScienceFail('artifact sampling contract differs from native fix ave/time mapping')
    n=sel['N']; modes=run.get('modes')
    if not isinstance(modes,list) or len(modes)!=2*(n-1): raise ScienceFail('artifact must cover all 2(N-1) modes')
    expected={(b,j) for b in BRANCHES for j in range(1,n)}; seen=set()
    base_mode_keys={'branch','j','label','status','frequency_cm1','frequency_uncertainty_cm1','frequency_interval_cm1','complex_layer_amplitudes','reliability_metrics','diagnosis','evidence_path'}
    for m in modes:
        if not isinstance(m,dict) or not base_mode_keys.issubset(m) or set(m)-base_mode_keys-{'unresolved_reason'}: raise ScienceFail('mode record has missing or unknown keys')
        b,j=m.get('branch'),m.get('j')
        if b not in BRANCHES or type(j) is not int or not 1<=j<n or (b,j) in seen: raise ScienceFail('invalid/duplicate branch and free-chain index')
        seen.add((b,j)); k=n-j
        expected_label=f'S_{n},{k}' if b=='S' else f'LB_{n},{k}'
        if m.get('label')!=expected_label: raise ScienceFail(f'mode label does not match {b},N={n},j={j}')
        if m.get('status') not in {'DETECTED','UNRESOLVED'}: raise ScienceFail('mode status must be DETECTED or UNRESOLVED')
        amps=m.get('complex_layer_amplitudes')
        if not isinstance(amps,list) or len(amps)!=n: raise ScienceFail('complex amplitudes must cover every physical layer')
        required_axes={'x','y'} if b=='S' else {'z'}
        for li,row in enumerate(amps,1):
            if not isinstance(row,dict) or set(row)!={'layer','components'} or type(row.get('layer')) is not int or row['layer']!=li or not isinstance(row.get('components'),dict) or set(row['components'])!=required_axes:
                raise ScienceFail('layer order or branch component axes invalid')
            for axis,c in row['components'].items():
                if not isinstance(c,dict) or set(c)!={'complex','amplitude_A','phase_rad','phase_reliable','node_mask'} or not isinstance(c.get('complex'),list) or len(c['complex'])!=2:
                    raise ScienceFail('complex coefficient must be [real,imag]')
                re0=finite_num(c['complex'][0],'complex real'); im0=finite_num(c['complex'][1],'complex imag')
                amp=finite_num(c.get('amplitude_A'),'amplitude')
                if amp < 0: raise ScienceFail('amplitude must be nonnegative')
                if not math.isclose(math.hypot(re0,im0),amp,rel_tol=1e-4,abs_tol=1e-10): raise ScienceFail('amplitude differs from complex coefficient')
                node=c.get('node_mask'); phase_ok=c.get('phase_reliable'); phase=c.get('phase_rad')
                if type(node) is not bool or type(phase_ok) is not bool: raise ScienceFail('node_mask and phase_reliable must be booleans')
                if node and phase_ok: raise ScienceFail('node-masked phase cannot be marked reliable')
                if phase_ok:
                    ph=finite_num(phase,'phase')
                    if amp == 0: raise ScienceFail('zero-amplitude component cannot have reliable phase')
                    expected_phase=math.atan2(im0,re0)
                    if abs((ph-expected_phase+math.pi)%(2*math.pi)-math.pi)>0.1:
                        raise ScienceFail('phase_rad is inconsistent with complex coefficient')
                elif phase is not None: raise ScienceFail('unreliable phase must be null')
        if m['status']=='DETECTED':
            if m.get('unresolved_reason') not in (None,''):
                raise ScienceFail('DETECTED mode cannot declare an unresolved reason')
            finite_num(m.get('frequency_cm1'),'frequency',True)
            finite_num(m.get('frequency_uncertainty_cm1'),'frequency uncertainty',True)
            metrics=m.get('reliability_metrics')
            if not isinstance(metrics,dict) or set(metrics)!={'local_power_snr','fft_resolution_cm1','half_window_frequencies_cm1','local_background_bins'} or not isinstance(m.get('diagnosis'),str) or not m['diagnosis'].strip() or not isinstance(m.get('evidence_path'),str) or not m['evidence_path'].strip():
                raise ScienceFail('detected mode requires metrics, diagnosis, and evidence path')
            snr=finite_num(metrics.get('local_power_snr'),'detected reliability_metrics.local_power_snr',True)
            finite_num(metrics.get('fft_resolution_cm1'),'detected reliability_metrics.fft_resolution_cm1',True)
            hfreq=metrics.get('half_window_frequencies_cm1')
            if not isinstance(hfreq,list) or len(hfreq)!=2: raise ScienceFail('detected mode requires two half-window frequencies')
            for x in hfreq: finite_num(x,'half-window frequency',True)
            if type(metrics.get('local_background_bins')) is not int or metrics['local_background_bins']<3: raise ScienceFail('detected mode requires at least three local-background bins')
            interval=m.get('frequency_interval_cm1')
            if not isinstance(interval,list) or len(interval)!=2: raise ScienceFail('frequency_interval_cm1 must be [low,high]')
            lo,hi=(finite_num(x,'frequency interval bound',True) for x in interval)
            if lo>hi or not lo<=m['frequency_cm1']<=hi or not math.isclose(hi-lo,2*m['frequency_uncertainty_cm1'],rel_tol=1e-4,abs_tol=1e-8): raise ScienceFail('frequency interval and uncertainty disagree')
        else:
            if m.get('frequency_cm1') is not None or m.get('frequency_uncertainty_cm1') is not None or m.get('frequency_interval_cm1') is not None:
                raise ScienceFail('unresolved mode frequency/uncertainty must be null')
            if m.get('unresolved_reason') not in {'LOW_LOCAL_SNR','HALF_WINDOW_UNSTABLE','FREQUENCY_SPACE_AMBIGUITY','LOW_PHASE_RELIABILITY'}:
                raise ScienceFail('unresolved mode requires a recognized reason_code')
            metrics=m.get('reliability_metrics')
            if not isinstance(metrics,dict) or set(metrics)!={'local_power_snr','fft_resolution_cm1','half_window_frequencies_cm1','local_background_bins'} or not isinstance(m.get('diagnosis'),str) or not m['diagnosis'].strip() or not isinstance(m.get('evidence_path'),str) or not m['evidence_path'].strip():
                raise ScienceFail('unresolved mode requires quantitative diagnostics and evidence path')
            if metrics.get('local_power_snr') is not None: finite_num(metrics['local_power_snr'],'unresolved local power SNR')
            finite_num(metrics.get('fft_resolution_cm1'),'unresolved FFT resolution',True)
            hfreq=metrics.get('half_window_frequencies_cm1')
            if not isinstance(hfreq,list) or len(hfreq)!=2: raise ScienceFail('unresolved mode requires half-window diagnostic slots')
            for x in hfreq:
                if x is not None: finite_num(x,'unresolved half-window frequency',True)
            if type(metrics.get('local_background_bins')) is not int or metrics['local_background_bins']<0: raise ScienceFail('unresolved local-background count is invalid')
    if seen!=expected: raise ScienceFail('mode branch/index coverage incomplete')
    return run


def validate_evidence_paths(run:dict, final_root:Path)->None:
    """Require each declared evidence path to resolve to a regular file below final/."""
    root=Path(final_root)
    for mode in run.get('modes',[]):
        raw=mode.get('evidence_path')
        if not isinstance(raw,str) or not raw or '\\' in raw or '\x00' in raw:
            raise ScienceFail('mode evidence path must be a non-empty relative POSIX path')
        rel=PurePosixPath(raw)
        if rel.is_absolute() or any(part in ('','.', '..') for part in rel.parts):
            raise ScienceFail('mode evidence path must stay below final/')
        root_abs=root.absolute()
        path=root_abs.joinpath(*rel.parts)
        chain=[root_abs]
        parent=path.parent
        while parent!=root_abs and root_abs in parent.parents:
            chain.append(parent); parent=parent.parent
        chain.append(path)
        # Check every component, including final/ itself, before resolving it.
        if any(item.is_symlink() for item in chain):
            raise ScienceFail('mode evidence path may not traverse symlinks')
        try:
            path.relative_to(root_abs)
        except ValueError:
            raise ScienceFail('mode evidence path escapes final/')
        if not path.is_file():
            raise ScienceFail('declared mode evidence file is missing or not a regular file')

def _detrend(x):
    t=np.linspace(-.5,.5,x.shape[0]); t-=t.mean()
    centered=x-x.mean(axis=0,keepdims=True)
    coef=np.einsum('t,t...->...',t,centered)/np.dot(t,t)
    return centered-t.reshape((-1,)+(1,)*(x.ndim-1))*coef

@lru_cache(maxsize=8)
def _half_window_tapers(half_len):
    from scipy.signal.windows import dpss
    return dpss(half_len,NW=3.5,Kmax=5,sym=False)

def _half_window_support(projection,full_frequency,assigned_full_frequencies,half_channels,
                         half_freq,half_band,full_direction):
    """Require local projected power and a matching data-derived half-window subspace."""
    results=[]; hlen=len(projection)//2; df_half=float(half_freq[1]-half_freq[0])
    center_tolerance=2.0*df_half+1e-10
    tapers=_half_window_tapers(hlen)
    for hi in range(2):
        half_proj=projection[hi*hlen:(hi+1)*hlen]
        window=np.hanning(hlen)
        coeff=np.fft.rfft(half_proj*window[:,None],axis=0)
        power=np.sum(np.abs(coeff)**2,axis=1)
        band_bins=np.flatnonzero(half_band)
        maxima=[int(q) for q in band_bins if q>0 and q<len(power)-1
                and power[q]>=power[q-1] and power[q]>=power[q+1]]
        nearby=[q for q in maxima if abs(float(half_freq[q])-full_frequency)<=center_tolerance]
        pool=nearby if nearby else maxima
        peak=min(pool,key=lambda q:abs(float(half_freq[q])-full_frequency)) if pool else int(band_bins[np.argmax(power[band_bins])])
        peak_frequency=float(half_freq[peak]); peak_in_window=bool(nearby)

        excluded=np.zeros(len(half_freq),dtype=bool)
        excluded[max(0,peak-3):peak+4]=True
        for assigned_frequency in assigned_full_frequencies:
            mapped=int(round(float(assigned_frequency)/df_half))
            excluded[max(0,mapped-3):mapped+4]=True
        initial_ring=(np.abs(half_freq-peak_frequency)<=10.0)&half_band&~excluded
        initial_background_bins=int(np.count_nonzero(initial_ring))
        initial_background=float(np.median(power[initial_ring])) if initial_background_bins>=3 else None
        other_maxima=[q for q in maxima if q!=peak and initial_background is not None
                      and power[q]>=.1*power[peak] and power[q]>=5.0*initial_background
                      and abs(float(half_freq[q])-peak_frequency)<=10.0]
        ring=initial_ring.copy()
        for q in other_maxima: ring[max(0,q-3):q+4]=False
        background_bins=int(np.count_nonzero(ring))
        background=float(np.median(power[ring])) if background_bins>=3 else None
        snr=float(power[peak]/background) if background is not None and background>0 else None

        spatial_overlap=None; supported_rank=0; background_eigenvalue=None; peak_eigenvalue=None
        if full_direction is not None and background_bins>=3:
            taper_spectra=np.asarray([np.fft.rfft(half_channels[hi]*taper[:,None],axis=0) for taper in tapers])
            bg_csd=[]
            for q in np.flatnonzero(ring):
                vectors=taper_spectra[:,q,:]
                bg_csd.append(np.einsum('ki,kj->ij',vectors,vectors.conj(),optimize=False)/len(tapers))
            background_matrix=np.mean(bg_csd,axis=0)
            family_half_bins=[q for q in maxima
                if abs(float(half_freq[q])-full_frequency)<=center_tolerance]
            full_sample=full_direction[0] if isinstance(full_direction,(list,tuple)) else full_direction
            direction_rows,direction_cols=full_sample['layer_shape'] if isinstance(full_sample,dict) else (len(full_sample),np.asarray(full_sample).shape[1])
            half_layer_signal=np.zeros((direction_rows,direction_rows),dtype=np.complex128)
            half_layer_noise=np.zeros_like(half_layer_signal)
            for family_peak in family_half_bins:
                vectors=taper_spectra[:,family_peak,:]
                csd=np.einsum('ki,kj->ij',vectors,vectors.conj(),optimize=False)/len(tapers)
                csd4=csd.reshape(direction_rows,direction_cols,direction_rows,direction_cols)
                half_layer_signal+=np.einsum('lama->lm',csd4,optimize=False)
                bg4=background_matrix.reshape(direction_rows,direction_cols,direction_rows,direction_cols)
                bg_layer=np.einsum('lama->lm',bg4,optimize=False)
                half_layer_noise+=bg_layer
            background_eigenvalue=max(0.0,float(np.linalg.eigvalsh(half_layer_noise).real[-1]))
            half_values,half_vectors=np.linalg.eigh(half_layer_signal)
            peak_eigenvalue=max(0.0,float(half_values[-1].real))
            half_keep=half_values.real>max(5.0*background_eigenvalue,1e-8*peak_eigenvalue,1e-300)
            half_basis=half_vectors[:,half_keep]
            supported_rank=int(half_basis.shape[1])
            if supported_rank:
                # Compare layer-space column ranges, not individual flattened
                # x/y eigenvectors. This permits thermal polarization rotation
                # and degenerate-basis rotation while requiring the half window
                # to retain every full-window layer direction.
                full_dirs=(full_direction if isinstance(full_direction,(list,tuple)) else [full_direction])
                full_layer_signal=np.zeros((direction_rows,direction_rows),dtype=np.complex128)
                full_layer_noise=np.zeros_like(full_layer_signal); used_peaks=set()
                for item in full_dirs:
                    if not isinstance(item,dict) or item['peak'] in used_peaks: continue
                    used_peaks.add(item['peak'])
                    csd4=np.asarray(item['csd']).reshape(direction_rows,direction_cols,direction_rows,direction_cols)
                    bg4=np.asarray(item['background_csd']).reshape(direction_rows,direction_cols,direction_rows,direction_cols)
                    full_layer_signal+=np.einsum('lama->lm',csd4,optimize=False)
                    bg_layer=np.einsum('lama->lm',bg4,optimize=False)
                    full_layer_noise+=bg_layer
                full_noise_max=max(0.0,float(np.linalg.eigvalsh(full_layer_noise).real[-1]))
                full_values,full_vectors=np.linalg.eigh(full_layer_signal)
                full_eigmax=max(0.0,float(full_values[-1].real))
                full_keep=full_values.real>max(10.0*full_noise_max,1e-8*full_eigmax,1e-300)
                full_basis=full_vectors[:,full_keep]
                if full_basis.shape[1] and half_basis.shape[1]>=full_basis.shape[1]:
                    cosines=np.linalg.svd(full_basis.conj().T@half_basis,compute_uv=False)
                    spatial_overlap=float(np.min(cosines[:full_basis.shape[1]])) if len(cosines)>=full_basis.shape[1] else 0.0
        spatial_supported=bool(spatial_overlap is not None and spatial_overlap>=math.cos(math.radians(30)))
        supported=bool(peak_in_window and background_bins>=3 and snr is not None and math.isfinite(snr)
                       and snr>=5.0 and spatial_supported)
        results.append({'frequency_cm1':peak_frequency,'peak_in_full_window':peak_in_window,
            'local_power_snr':snr,'background_bins':background_bins,'spatial_subspace_overlap':spatial_overlap,
            'spatial_subspace_rank':supported_rank,'background_eigenvalue_max':background_eigenvalue,
            'peak_eigenvalue_max':peak_eigenvalue,'spatial_supported':spatial_supported,'supported':supported})
    return results

def cross_spectrum(xyz:np.ndarray,dt_fs:float=1.0)->dict:
    """Independent Hann cross spectrum with one-to-one peak assignment per branch."""
    if xyz.ndim!=3 or xyz.shape[1] not in (2,3,6) or xyz.shape[2]!=3 or not np.isfinite(xyz).all(): raise ScienceFail('invalid layer COM tensor')
    n=xyz.shape[1]; nt=xyz.shape[0]
    if nt<16 or not math.isfinite(dt_fs) or dt_fs<=0: raise ScienceFail('invalid sample count or timestep')
    try:
        from scipy.optimize import linear_sum_assignment
    except Exception as e:
        raise InfraError(f'SciPy peak-assignment dependency unavailable: {type(e).__name__}: {e}') from e
    detr=_detrend(xyz)
    relative=detr-detr.mean(axis=1,keepdims=True)
    relative-=relative.mean(axis=0,keepdims=True)
    freq=np.fft.rfftfreq(nt,d=dt_fs)*1e15/2.99792458e10
    df=float(freq[1]-freq[0]); band=(freq>=5)&(freq<=150)
    win=np.hanning(nt); win_sum=float(win.sum())
    phi={j:np.sqrt(2/n)*np.cos(np.pi*j*(np.arange(n)+.5)/n) for j in range(1,n)}
    output={"frequencies_cm1":freq.tolist(),"bin_spacing_cm1":df,"modes":[]}
    for branch in BRANCHES:
        axes=(0,1) if branch=='S' else (2,)
        projections={j:np.einsum('l,tlc->tc',v,relative[:,:,axes]) for j,v in phi.items()}
        half_len=nt//2
        half_freq=np.fft.rfftfreq(half_len,d=dt_fs*1e-15)/2.99792458e10
        half_band=(half_freq>=5)&(half_freq<=150)
        half_channels=[relative[:half_len,:,axes].reshape(half_len,n*len(axes)),
                       relative[half_len:2*half_len,:,axes].reshape(half_len,n*len(axes))]
        proj_fft={j:np.fft.rfft(x*win[:,None],axis=0)*(2.0/win_sum) for j,x in projections.items()}
        ps_by_j={j:np.sum(np.abs(fx)**2,axis=1) for j,fx in proj_fft.items()}
        # Build a shared peak vocabulary, then assign distinct peaks across j.
        peak_bins=set()
        local_bins=np.flatnonzero(band)
        for j,ps in ps_by_j.items():
            maxima=[q for q in local_bins if q>0 and q<len(ps)-1 and ps[q]>=ps[q-1] and ps[q]>=ps[q+1]]
            maxima=sorted(maxima,key=lambda q:ps[q],reverse=True)
            cutoff=max(float(ps[maxima[0]])*1e-3,1e-300) if maxima else 1e-300
            peak_bins.update(q for q in maxima[:max(12,n*4)] if ps[q]>=cutoff)
        bins=sorted(peak_bins)
        if not bins:
            for j in phi:
                output['modes'].append({'branch':branch,'j':j,'peak_bin':None,'frequency_cm1':None,
                    'peak_power':0.0,'local_noise_floor_power':None,'local_power_snr':None,
                    'half_window_frequencies_cm1':[None,None],'projection_residual':None,'peak_width_cm1':None,
                    'raw_complex_layer_coefficients':[[[0.0,0.0] for _ in axes] for _ in range(n)],
                    'local_noise_floor_A_by_component':[[None for _ in axes] for _ in range(n)],
                    'assigned_peak_unique':False,'resolved_reason_code':'LOW_LOCAL_SNR',
                    'cross_spectral_eigenvalues':[],'cross_spectral_noise_eigenvalue_max':None,
                    'cross_spectral_rank':0,'cross_spectral_subspace':[],'local_noise_bins':0})
            continue
        channels=relative[:,:,axes].reshape(nt,n*len(axes))
        channel_fft=np.fft.rfft(channels*win[:,None],axis=0)*(2.0/win_sum)
        try:
            from scipy.signal.windows import dpss
            tapers=dpss(nt,NW=3.5,Kmax=5,sym=False)
            taper_spectra=np.asarray([np.fft.rfft(channels*taper[:,None],axis=0) for taper in tapers])
        except Exception as e:
            raise InfraError(f'multitaper CSD dependency unavailable: {type(e).__name__}: {e}') from e
        # Build one assignment slot per data-supported spatial eigen-direction,
        # rather than repeating every frequency bin n-1 times. This allows true
        # degenerate independent directions while preventing a rank-one peak
        # from being copied into several mode labels.
        slots=[]
        for q in bins:
            qexcl=np.zeros(len(freq),dtype=bool)
            for qb in bins: qexcl[max(0,qb-3):qb+4]=True
            ring_q=(np.abs(freq-freq[q])<=10)&band&~qexcl
            peak_spectra=taper_spectra[:,q,:]
            csd=np.einsum('ki,kj->ij',peak_spectra,peak_spectra.conj(),optimize=False)/len(tapers)
            bg_mats=[]
            for qb in np.flatnonzero(ring_q):
                xb=taper_spectra[:,qb,:]
                bg_mats.append(np.einsum('ki,kj->ij',xb,xb.conj(),optimize=False)/len(tapers))
            bg_eigmax=0.0
            if bg_mats:
                bg_csd=np.mean(bg_mats,axis=0)
                bgvals=np.linalg.eigvalsh(bg_csd).real
                bg_eigmax=max(0.0,float(bgvals[-1]))
            else:
                bg_csd=np.zeros_like(csd)
            eigvals,eigvecs=np.linalg.eigh(csd); order=np.argsort(eigvals)[::-1]
            eigmax=max(0.0,float(eigvals[order[0]].real))
            eig_threshold=max(10.0*bg_eigmax,1e-8*eigmax,1e-300)
            significant=[int(ix) for ix in order if float(eigvals[ix].real)>eig_threshold]
            for ix in significant:
                vec=eigvecs[:,ix]
                fitted=np.vdot(vec,channel_fft[q])
                amplitude_power=float(abs(fitted)**2)
                scores_by_j={}
                for j,v in phi.items():
                    candidate_vec=vec.reshape(n,len(axes))
                    projection=np.einsum('l,la->a',v,candidate_vec)
                    overlap2=float(np.sum(np.abs(projection)**2)/(np.linalg.norm(candidate_vec)**2+1e-300))
                    # Spatial agreement is primary; Hann projection power is a
                    # weak tie-breaker so a strong unrelated branch cannot win.
                    scores_by_j[j]=math.log(max(overlap2,1e-12))+.1*math.log(max(amplitude_power,1e-300))
                slots.append({'peak':int(q),'direction':ix,'direction_count':len(significant),
                    'vec':vec,'csd':csd,'background_csd':bg_csd,
                    'eigenvalue':float(eigvals[ix].real),'eigvals':eigvals,'order':order,
                    'bg_eigmax':bg_eigmax,'ring':ring_q,'score_by_j':scores_by_j,
                    'noise_bins':int(np.count_nonzero(ring_q))})
        if not slots:
            for j in phi:
                output['modes'].append({'branch':branch,'j':j,'peak_bin':None,'frequency_cm1':None,
                    'peak_power':0.0,'local_noise_floor_power':None,'local_power_snr':None,
                    'half_window_frequencies_cm1':[None,None],'projection_residual':None,'peak_width_cm1':None,
                    'raw_complex_layer_coefficients':[[[0.0,0.0] for _ in axes] for _ in range(n)],
                    'local_noise_floor_A_by_component':[[None for _ in axes] for _ in range(n)],
                    'assigned_peak_unique':False,'resolved_reason_code':'LOW_LOCAL_SNR',
                    'cross_spectral_eigenvalues':[],'cross_spectral_noise_eigenvalue_max':None,
                    'cross_spectral_rank':0,'cross_spectral_subspace':[],'local_noise_bins':0})
            continue
        score=np.asarray([[slot['score_by_j'][j] for slot in slots] for j in phi])
        row_idx,col_idx=linear_sum_assignment(-score)
        assigned={list(phi)[int(r)]:slots[int(c)] for r,c in zip(row_idx,col_idx)}
        assigned_slot_ids={id(slot) for slot in assigned.values()}
        # Estimate model uncertainty from the part of the measured Hann vector
        # not explained by all independently assigned CSD directions at a peak.
        # This is a confidence bound, not background noise: subtract every
        # assigned direction together so a degenerate partner is never treated
        # as uncertainty for the other mode.
        residual_by_peak={}
        for q in {slot['peak'] for slot in assigned.values()}:
            model=np.zeros(channels.shape[1],dtype=np.complex128)
            for slot in assigned.values():
                if slot['peak']!=q: continue
                vec=slot['vec']
                model += vec*np.vdot(vec,channel_fft[q])
            residual_by_peak[q]=(channel_fft[q]-model).reshape(n,len(axes))
        for j,v in phi.items():
            projected=projections[j]; ps=ps_by_j[j]
            slot=assigned.get(j)
            if slot is None:
                # A physical-band projection with no independent CSD direction
                # is an ambiguity diagnosis, not a fabricated second eigvector.
                peak=max(bins,key=lambda q:ps_by_j[j][q]); ps=ps_by_j[j]
                excl=np.zeros(len(freq),dtype=bool); excl[max(0,peak-3):peak+4]=True
                for other in (s['peak'] for s in assigned.values()): excl[max(0,other-3):other+4]=True
                ring=(np.abs(freq-freq[peak])<=10)&band&~excl
                maxima=[q for q in local_bins if q>0 and q<len(ps)-1 and ps[q]>=ps[q-1] and ps[q]>=ps[q+1]
                        and q!=peak and ps[q]>=.1*ps[peak] and abs(freq[q]-freq[peak])<=10]
                for q in maxima: ring[max(0,q-3):q+4]=False
                floor=float(np.median(ps[ring])) if np.count_nonzero(ring)>=3 else None
                snr=float(ps[peak]/floor) if floor is not None and floor>0 else None
                half_support=_half_window_support(projections[j],float(freq[peak]),
                    [float(freq[s['peak']]) for s in assigned.values()],half_channels,
                    half_freq,half_band,None)
                halves=[x['frequency_cm1'] for x in half_support]
                raw_coeff=channel_fft[peak].reshape(n,len(axes))
                channel_floor_flat=np.median(np.abs(channel_fft[ring]),axis=0) if np.count_nonzero(ring)>=3 else np.full(n*len(axes),np.nan)
                channel_floor=channel_floor_flat.reshape(n,len(axes)).astype(float).tolist()
                halfp=ps[peak]/2; lo=peak; hi=peak
                while lo>0 and ps[lo-1]>=halfp: lo-=1
                while hi+1<len(ps) and ps[hi+1]>=halfp: hi+=1
                width=float((hi-lo+1)*df)
                near=[s for s in slots if s['peak']==peak]
                slot=near[0] if near else None
                output['modes'].append({'branch':branch,'j':j,'peak_bin':int(peak),'frequency_cm1':float(freq[peak]),
                    'peak_power':float(ps[peak]),'local_noise_floor_power':floor,'local_power_snr':snr,
                    'half_window_frequencies_cm1':halves,'projection_residual':None,'peak_width_cm1':width,
                    'raw_complex_layer_coefficients':[[[float(z.real),float(z.imag)] for z in row] for row in raw_coeff],
                    'local_noise_floor_A_by_component':channel_floor,'assigned_peak_unique':False,
                    'resolved_reason_code':'FREQUENCY_SPACE_AMBIGUITY',
                    'cross_spectral_eigenvalues':[float(x) for x in slot['eigvals'][slot['order']].real] if slot else [],
                    'cross_spectral_noise_eigenvalue_max':float(slot['bg_eigmax']) if slot else None,
                    'cross_spectral_rank':int(slot['direction_count']) if slot else 0,
                    'cross_spectral_subspace':[[[float(z.real),float(z.imag)] for z in row] for row in slot['vec'].reshape(n,len(axes))] if slot else [],
                    'local_noise_bins':int(np.count_nonzero(ring)),'half_window_support':half_support})
                continue
            peak=slot['peak']
            # Local robust power floor around the chosen peak, excluding this and competing peaks.
            other_assigned=[slot['peak'] for jj,slot in assigned.items() if jj!=j]
            excl=np.zeros(len(freq),dtype=bool)
            excl[max(0,peak-3):peak+4]=True
            for q in other_assigned: excl[max(0,q-3):q+4]=True
            ring=(np.abs(freq-freq[peak])<=10)&band&~excl
            # Exclude any other strong local maximum within this local ring.
            maxima=[q for q in local_bins if q>0 and q<len(ps)-1 and ps[q]>=ps[q-1] and ps[q]>=ps[q+1]]
            maxima=[q for q in maxima if q!=peak and ps[q]>=.1*ps[peak] and abs(freq[q]-freq[peak])<=10]
            for q in maxima: ring[max(0,q-3):q+4]=False
            floor=float(np.median(ps[ring])) if np.count_nonzero(ring)>=3 else None
            snr=float(ps[peak]/floor) if floor is not None and floor>0 else None
            half_support=_half_window_support(projected,float(freq[peak]),
                [float(freq[s['peak']]) for s in assigned.values()],half_channels,
                half_freq,half_band,[{'peak':s['peak'],'vector':s['vec'],'csd':s['csd'],'background_csd':s['background_csd'],
                    'eigenvalue':s['eigenvalue'],'layer_shape':(n,len(axes))} for s in slots
                    if abs(float(freq[s['peak']])-float(freq[peak]))<=2.0*(half_freq[1]-half_freq[0])+1e-10])
            halves=[x['frequency_cm1'] for x in half_support]
            projected_coeff=proj_fft[j][peak]
            # Keep the measured full-channel complex vector. Multiplying the
            # projection by the free-chain template would manufacture an exact
            # eigenvector and make the later shape check circular.
            raw_coeff=channel_fft[peak].reshape(n,len(axes))
            channel_floor_flat=np.median(np.abs(channel_fft[ring]),axis=0) if np.count_nonzero(ring)>=3 else np.full(n*len(axes),np.nan)
            channel_floor=channel_floor_flat.reshape(n,len(axes)).astype(float).tolist()
            model_uncertainty=np.abs(residual_by_peak.get(peak,np.full((n,len(axes)),np.nan+0j))).astype(float)
            eigvals=slot['eigvals']; order=slot['order']; bg_eigmax=slot['bg_eigmax']
            vec=slot['vec'].reshape(n,len(axes))
            fitted=np.vdot(slot['vec'],channel_fft[peak])
            raw_coeff=vec*fitted
            layer_signal=np.linalg.norm(raw_coeff,axis=1)
            confidence_components=2.0*np.asarray(channel_floor,dtype=float)+model_uncertainty
            layer_floor=(np.linalg.norm(confidence_components,axis=1) if branch=='S' else confidence_components[:,0])
            proj=v[:,None]*np.sum(v[:,None]*vec,axis=0,keepdims=True)
            residual=float(np.linalg.norm(vec-proj)/max(np.linalg.norm(vec),1e-300))
            halfp=ps[peak]/2; lo=peak; hi=peak
            while lo>0 and ps[lo-1]>=halfp: lo-=1
            while hi+1<len(ps) and ps[hi+1]>=halfp: hi+=1
            width=float((hi-lo+1)*df)
            # Frequency equality alone is not a collision: the post-pass checks
            # whether close modes have independently supported CSD directions.
            unique=id(slot) in assigned_slot_ids
            half_delta=abs(halves[0]-halves[1])
            if not unique:
                reason_code='FREQUENCY_SPACE_AMBIGUITY'
            elif snr is None or snr<10:
                reason_code='LOW_LOCAL_SNR'
            elif (half_delta>2.67 or width>6.0
                  or any(not x['supported'] for x in half_support)):
                reason_code='HALF_WINDOW_UNSTABLE'
            elif not np.isfinite(channel_floor).all():
                reason_code='LOW_PHASE_RELIABILITY'
            else:
                reason_code=None
            if reason_code is None and int(np.count_nonzero(layer_signal>layer_floor))<min(2,n):
                reason_code='LOW_PHASE_RELIABILITY'
            output['modes'].append({'branch':branch,'j':j,'peak_bin':int(peak),'frequency_cm1':float(freq[peak]),
                'peak_power':float(ps[peak]),'local_noise_floor_power':floor,'local_power_snr':snr,
                'half_window_frequencies_cm1':halves,'projection_residual':residual,'peak_width_cm1':width,
                'raw_complex_layer_coefficients':[[[float(z.real),float(z.imag)] for z in row] for row in raw_coeff],
                'local_noise_floor_A_by_component':channel_floor,
                'refit_model_uncertainty_A_by_component':model_uncertainty.tolist(),
                'assigned_peak_unique':bool(unique),'resolved_reason_code':reason_code,
                'cross_spectral_eigenvalues':[float(x) for x in eigvals[order].real],
                'cross_spectral_noise_eigenvalue_max':float(bg_eigmax),'cross_spectral_rank':int(slot['direction_count']),
                'cross_spectral_subspace':[[[float(z.real),float(z.imag)] for z in row] for row in vec],
                'local_noise_bins':int(np.count_nonzero(ring)),'half_window_support':half_support})
    # A near-frequency pair is distinguishable only when its layer-space vectors
    # are independent. This preserves true degenerate orthogonal modes while
    # marking copied/aliased peaks unresolved.
    for branch in BRANCHES:
        group=[m for m in output['modes'] if m['branch']==branch]
        for ia in range(len(group)):
            for ib in range(ia+1,len(group)):
                a,b=group[ia],group[ib]
                if a['frequency_cm1'] is None or b['frequency_cm1'] is None or a['peak_width_cm1'] is None or b['peak_width_cm1'] is None: continue
                resolution=max(df,0.5*(a['peak_width_cm1']+b['peak_width_cm1']))
                if abs(a['frequency_cm1']-b['frequency_cm1'])>resolution: continue
                ae=np.asarray(a['raw_complex_layer_coefficients'],dtype=np.float64)
                be=np.asarray(b['raw_complex_layer_coefficients'],dtype=np.float64)
                va=ae[...,0]+1j*ae[...,1]; vb=be[...,0]+1j*be[...,1]
                if branch=='LB': overlap=abs(np.vdot(va[:,0],vb[:,0]))/(np.linalg.norm(va[:,0])*np.linalg.norm(vb[:,0])+1e-300)
                else:
                    overlap=0.0
                    for theta in np.linspace(0.0,2*math.pi,361,endpoint=False):
                        rot=np.asarray([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
                        overlap=max(overlap,float(abs(np.vdot(va,vb@rot))/(np.linalg.norm(va)*np.linalg.norm(vb)+1e-300)))
                independent=overlap<math.cos(math.radians(30))
                a['assigned_peak_unique']=bool(a['assigned_peak_unique'] and independent)
                b['assigned_peak_unique']=bool(b['assigned_peak_unique'] and independent)
                if not independent:
                    a['resolved_reason_code']='FREQUENCY_SPACE_AMBIGUITY'
                    b['resolved_reason_code']='FREQUENCY_SPACE_AMBIGUITY'
                a['same_frequency_space_overlap']=float(overlap); b['same_frequency_space_overlap']=float(overlap)
    return output

def compare_controlled_truth(spectral:dict,truth:dict,n:int)->dict:
    """Construction-only comparison; never returns an agent reward."""
    records=truth.get('modes') if isinstance(truth,dict) else None
    if not isinstance(records,list): raise InfraError('controlled signal truth lacks modes list')
    observed={(m['branch'],m['j']):m for m in spectral['modes']}
    wanted={(m.get('branch'),m.get('j')):m for m in records if isinstance(m,dict)}
    expected={(b,j) for b in BRANCHES for j in range(1,n)}
    if set(wanted)!=expected: raise InfraError('controlled signal truth does not cover exact 2(N-1) modes')
    checks=[]
    for key,target in wanted.items():
        f=finite_num(target.get('frequency_cm1'),'controlled target frequency',True)
        got=observed[key]
        err=abs(got['frequency_cm1']-f) if got.get('frequency_cm1') is not None else None
        tol=max(1.5*spectral['bin_spacing_cm1'],finite_num(target.get('tolerance_cm1',1.5*spectral['bin_spacing_cm1']),'controlled tolerance',True))
        checks.append({'branch':key[0],'j':key[1],'expected_cm1':f,'observed_cm1':got['frequency_cm1'],'error_cm1':err,'tolerance_cm1':tol,'pass':err is not None and err<=tol and got['assigned_peak_unique']})
    return {'pass':all(x['pass'] for x in checks),'checks':checks,'source_kind':'CONTROLLED_SIGNAL','reward_eligible':False}

def nve_energy_excursion(rows:list[dict],n_atoms:int)->dict:
    if len(rows)!=51 or n_atoms<=0: raise ScienceFail('NVE energy gate requires 51 native thermo rows and positive atom count')
    energy=np.asarray([finite_num(row.get('toteng'),'NVE total energy') for row in rows],dtype=float)
    thermal=n_atoms*8.617333262145e-5*300.0
    delta=float(energy[-1]-energy[0]); peak_to_peak=float(np.max(energy)-np.min(energy))
    delta_norm=abs(delta)/thermal; p2p_norm=peak_to_peak/thermal
    return {'total_energy_delta_eV':delta,'total_energy_peak_to_peak_eV':peak_to_peak,
            'delta_over_N_kBT':delta_norm,'peak_to_peak_over_N_kBT':p2p_norm,
            'endpoint_drift_lt_0.01':delta_norm<.01,'sampled_peak_to_peak_lt_0.01':p2p_norm<.01,
            'sampling_scope':'51 native thermo samples; does not bound between-sample excursions'}

def physics_diagnostics(native:dict[str,Path],n:int,expected_mpi_ranks:int=10)->dict:
    monitor,_=sr.parse_equilibration_monitor(native['eqmon'],n)
    n_atoms=ATOMS_PER_LAYER*n
    box=re.search(r'^\s*([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+zlo zhi\s*$',native['data'].read_text(encoding='utf-8'),re.M)
    if not box: raise ScienceFail('cleaned data z bounds missing')
    zlo,zhi=map(float,box.groups())
    nmon=_numeric_table(native['eqmon'],n+5,'native equilibration monitor')
    ncom=_numeric_table(native['com'],1+3*n,'native production COM')
    if np.any(nmon[:,1:n+1]<=zlo) or np.any(nmon[:,1:n+1]>=zhi) or np.any(ncom[:,3::3]<=zlo) or np.any(ncom[:,3::3]>=zhi): raise ScienceFail('layer COM touches/exceeds free-z box bounds')
    if n>1 and (np.any(np.diff(nmon[:,1:n+1],axis=1)<=0) or np.any(np.diff(ncom[:,3::3],axis=1)<=0)):
        raise ScienceFail('native monitor/COM shows layer-order crossing')
    if 'Lost atoms' in native['stdout'].read_text(encoding='utf-8',errors='replace'): raise ScienceFail('native LAMMPS reports atom loss')
    eq=sr.summarize_equilibrium(monitor,n,n_atoms)
    stdout=native['stdout'].read_text(encoding='utf-8',errors='replace')
    thermo_text=native['thermo_log'].read_text(encoding='utf-8',errors='replace')
    thermo=sr.parse_thermo_by_stage(stdout,n_atoms)
    thermo_native=sr.parse_thermo_by_stage(thermo_text,n_atoms)
    for stage in ('equilibration','production'):
        if len(thermo[stage])!=len(thermo_native[stage]) or any(set(a)!=set(b) or any(not math.isclose(a[k],b[k],rel_tol=0.0,abs_tol=1e-9) for k in a) for a,b in zip(thermo[stage],thermo_native[stage])):
            raise ScienceFail(f'{stage} thermo stdout differs from native LAMMPS log')
    loops=re.findall(r'^Loop time of ([^ ]+) on (\d+) procs for (\d+) steps with (\d+) atoms\s*$',thermo_text,re.M)
    if len(loops)!=3: raise ScienceFail('native LAMMPS log must contain exactly minimization, NPT, and NVE loop records')
    parsed=[]
    for sec,procs,steps,atoms in loops:
        seconds=float(sec)
        if not math.isfinite(seconds) or seconds<=0 or int(procs)!=expected_mpi_ranks or int(atoms)!=n_atoms:
            raise ScienceFail('native Loop record has invalid elapsed time/ranks/atom count')
        parsed.append((int(steps),seconds))
    if [x[0] for x in parsed[1:]]!=[250000,50000]: raise ScienceFail('native LAMMPS loop counts differ from full protocol')
    drift=sr.summarize_nve_drift(thermo['production'],n_atoms)
    # Proposed public structural/physics envelope; root/Sol may version before dispatch.
    blocks=eq['blocks']; means=[b['means'] for b in blocks]
    temp_ok=all(285<=m['temperature_K']<=315 for m in means)
    area0,area1=means[0]['area_A2'],means[-1]['area_A2']
    area_rel=abs(area1-area0)/abs(area0)
    gap_keys=[k for k in means[0] if k.startswith('layer_gap_')]
    gaps=[]
    for k in gap_keys:
        first,last=means[0][k],means[-1][k]
        gaps.append({'pair':k,'first_A':first,'last_A':last,'delta_A':last-first,'relative_change':abs(last-first)/abs(first)})
    pe0,pe1=means[0]['potential_energy_eV_per_atom'],means[-1]['potential_energy_eV_per_atom']
    thermal=abs(drift['delta_over_N_kBT'])
    excursion=nve_energy_excursion(thermo['production'],n_atoms)
    criteria={'all_block_temperatures_285_315K':temp_ok,'first_last_block_area_change_lt_1pct':area_rel<.01,
       'all_layer_gaps_positive_and_change_lt_2pct_and_0.1A':all(g['first_A']>0 and g['last_A']>0 and g['relative_change']<.02 and abs(g['delta_A'])<.1 for g in gaps),
       'first_last_block_pe_per_atom_change_lt_0.005eV':abs(pe1-pe0)<.005,
       'nve_abs_delta_over_NkBT_lt_0.01':thermal<.01,
       'nve_sampled_peak_to_peak_over_NkBT_lt_0.01':excursion['sampled_peak_to_peak_lt_0.01']}
    return {'equilibrium_diagnostic':eq,'npt_native_thermo_rows':len(thermo['equilibration']),
        'nve_drift':{**drift,**excursion},'physics_metrics':{'area_first_last_relative_change':area_rel,'layer_gaps':gaps,
        'pe_per_atom_first_last_block_change_eV':pe1-pe0,'nve_abs_delta_over_NkBT':thermal},
        'proposed_physics_criteria':criteria,'proposed_physics_pass':all(criteria.values()),
        'criteria_status':'V4_PUBLIC_RULES_FROM_SCORER_DESIGN'}

def _native_science_parse(label:str,callable_,*args,**kwargs):
    """Classify malformed trusted simulation rows as a scientific run failure."""
    try:
        return callable_(*args,**kwargs)
    except getattr(sr,'EvidenceError',()) as e:
        raise ScienceFail(f'native {label} evidence is malformed/incomplete: {e}') from e

def complex_vector_check(claim:dict, truth:dict, branch:str)->dict:
    axes=('x','y') if branch=='S' else ('z',)
    candidate=np.asarray([[complex(*layer['components'][axis]['complex']) for axis in axes]
                          for layer in claim['complex_layer_amplitudes']],dtype=np.complex128)
    enc=np.asarray(truth['raw_complex_layer_coefficients'],dtype=np.float64)
    if enc.ndim!=3 or enc.shape[-1]!=2: raise ScienceFail('trusted complex layer vector encoding malformed')
    ref=enc[...,0]+1j*enc[...,1]
    if candidate.shape!=ref.shape or not np.isfinite(candidate).all(): raise ScienceFail('candidate complex vector has invalid shape or values')
    if branch=='LB':
        a,b=ref[:,0],candidate[:,0]
        overlap=float(abs(np.vdot(a,b))/(np.linalg.norm(a)*np.linalg.norm(b)+1e-300))
        amp_ratio=float(np.linalg.norm(b)/(np.linalg.norm(a)+1e-300)); aligned=b[:,None]
    else:
        best=(-1.0,None,None)
        for theta in np.linspace(0.0,2*math.pi,1441,endpoint=False):
            rot=np.asarray([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
            br=candidate@rot; z=np.vdot(ref,br)
            val=abs(z)/(np.linalg.norm(ref)*np.linalg.norm(br)+1e-300)
            if val>best[0]: best=(float(val),br,theta)
        overlap,aligned,_=best
        amp_ratio=float(np.linalg.norm(candidate)/(np.linalg.norm(ref)+1e-300))
    floors=np.asarray(truth['local_noise_floor_A_by_component'],dtype=float)
    if floors.shape!=ref.shape or not np.isfinite(floors).all(): raise ScienceFail('independent noise floor shape mismatch/nonfinite')
    model_uncertainty=np.asarray(truth.get('refit_model_uncertainty_A_by_component',np.zeros_like(floors)),dtype=float)
    if model_uncertainty.shape!=ref.shape or not np.isfinite(model_uncertainty).all() or np.any(model_uncertainty<0):
        raise ScienceFail('refit model-uncertainty shape mismatch/nonfinite')
    # The public confidence bound is 2× background amplitude floor plus the
    # absolute residual of the assigned CSD refit model.
    confidence_bounds=2.0*floors+model_uncertainty
    floor_layer=np.linalg.norm(confidence_bounds,axis=1) if branch=='S' else confidence_bounds[:,0]
    raw_layer=np.linalg.norm(ref,axis=1)
    claimed_layer=np.linalg.norm(aligned,axis=1)
    masks=[]; phase_checks=[]; floor_consistency=[]
    for li,row in enumerate(claim['complex_layer_amplitudes']):
        for ai,axis in enumerate(axes):
            comp=row['components'][axis]
            amp=float(comp['amplitude_A'])
            # For shear, the axis basis may be globally rotated. Use the
            # rotation-invariant layer floor rather than the unrotated per-axis floor.
            independent_floor=float(floor_layer[li])
            masks.append((not bool(comp['node_mask'])) or amp<=independent_floor+1e-12)
            floor_consistency.append(True)
            # Phase reliability is reported in the candidate's published x/y
            # coordinates.  The aligned vector is used only for shape matching;
            # rotating it back before consulting these flags can turn a legal
            # low-signal candidate axis into a false phase failure.
            candidate_amp=float(abs(candidate[li,ai]))
            if candidate_amp>max(floor_layer[li],1e-12): phase_checks.append(bool(comp['phase_reliable']))
    # A high-signal physical layer cannot be erased by rotating or masking both shear axes.
    layer_nodes=[bool(all(row['components'][ax]['node_mask'] for ax in axes)) for row in claim['complex_layer_amplitudes']]
    node_ok=all((not layer_nodes[i]) if raw_layer[i]>floor_layer[i] else True for i in range(len(raw_layer)))
    expected_signal_layers=int(sum(bool(raw_layer[i]>floor_layer[i]) for i in range(len(raw_layer))))
    reliable_phase_norms=[]
    for li,row in enumerate(claim['complex_layer_amplitudes']):
        reliable_values=[]
        for ai,axis in enumerate(axes):
            component=row['components'][axis]
            if bool(component['phase_reliable']) and not bool(component['node_mask']):
                reliable_values.append(candidate[li,ai])
        reliable_phase_norms.append(float(np.linalg.norm(reliable_values)) if reliable_values else 0.0)
    phase_layers=int(sum(bool(reliable_phase_norms[i]>floor_layer[i]+1e-12)
                         for i in range(len(reliable_phase_norms))))
    # Every trusted signal layer must retain a measurable, reliable phase
    # component.  Summing reliable x/y components makes this invariant to a
    # legitimate in-plane rotation while preventing an epsilon-sized spare
    # axis from rescuing a masked high-signal layer.
    layer_phase_support=all(reliable_phase_norms[i]>floor_layer[i]+1e-12
                            for i in range(len(raw_layer)) if raw_layer[i]>floor_layer[i])
    enough_phase_layers=bool(phase_layers>=min(2,expected_signal_layers))
    amp_ok=.5<=amp_ratio<=2.0
    return {'complex_shape_overlap':float(overlap),'complex_amplitude_norm_ratio':amp_ratio,
            'complex_amplitude_scale_pass':amp_ok,'raw_noise_amplitude_upper_bound_A':floors.tolist(),
            'refit_model_uncertainty_A_by_component':model_uncertainty.tolist(),
            'phase_node_confidence_bound_A_by_component':confidence_bounds.tolist(),
            'node_mask_below_independent_floor':all(masks),
            'all_above_floor_components_phase_reliable':all(phase_checks),'high_signal_layers_not_fully_masked':node_ok,
            'complex_shape_pass':overlap>=math.cos(math.radians(30)),
            'phase_node_pass':bool(all(masks) and all(floor_consistency) and all(phase_checks) and node_ok and enough_phase_layers and layer_phase_support and amp_ok),
            'reliable_phase_layers':int(phase_layers),'trusted_signal_layers':int(expected_signal_layers)}

def grade_mode_credits(mode_credits:list[float],raw:dict,n:int,physics_ok:bool,scheduler_ok:bool)->dict:
    all_unresolved=all(x['resolved_reason_code'] is not None for x in raw.values())
    critical_unresolved=any(x['resolved_reason_code'] is not None for (b,j),x in raw.items()
                            if (b=='S' and j==n-1) or (b=='LB' and j==1))
    mean_credit=sum(mode_credits)/max(1,len(mode_credits))
    if not physics_ok or not scheduler_ok:
        status,reward,substatus='FAIL',0,'PHYSICS_OR_SCHEDULER_FAILURE'
    elif all_unresolved and all(c==.5 for c in mode_credits):
        status,reward,substatus='FAIL',0,'UNJUDGEABLE'
    elif all(c==1.0 for c in mode_credits):
        status,reward,substatus='PASS',1,'FULLY_RESOLVED'
    elif mean_credit>0:
        status='PARTIAL'; reward=min(mean_credit,.5 if critical_unresolved else .99); substatus='PARTIAL_UNRESOLVED_OR_MISMATCH'
    else:
        status,reward,substatus='FAIL',0,'NO_VALID_MODE_CREDIT'
    return {'status':status,'reward':reward,'scientific_substatus':substatus,'mean_mode_credit':mean_credit,
            'critical_mode_unresolved':critical_unresolved}

def nearest_competing_peak(raw:dict,key:tuple[str,int],frequency:float,df:float)->float:
    current=raw.get(key)
    candidates=[]
    for other_key,other in raw.items():
        if other_key[0]!=key[0] or other_key==key or other.get('frequency_cm1') is None:
            continue
        delta=abs(float(other['frequency_cm1'])-frequency)
        if delta<=df: continue
        # Independent layer-space modes are not competing peaks even when
        # their frequencies are close; spatially repeated directions are.
        if current is not None and _raw_spatial_overlap(current,other,key[0])<math.cos(math.radians(30)):
            continue
        candidates.append(float(other['frequency_cm1']))
    return min((abs(x-frequency) for x in candidates),default=6.6666667)

def _raw_spatial_overlap(a:dict,b:dict,branch:str)->float:
    try:
        ea=np.asarray(a['raw_complex_layer_coefficients'],dtype=float)
        eb=np.asarray(b['raw_complex_layer_coefficients'],dtype=float)
        va=ea[...,0]+1j*ea[...,1]; vb=eb[...,0]+1j*eb[...,1]
        if va.shape!=vb.shape or not np.isfinite(va).all() or not np.isfinite(vb).all(): return 1.0
        na=np.linalg.norm(va); nb=np.linalg.norm(vb)
        if na<=1e-300 or nb<=1e-300: return 1.0
        if branch=='LB': return float(abs(np.vdot(va[:,0],vb[:,0]))/(na*nb))
        overlap=0.0
        for theta in np.linspace(0.0,2*math.pi,361,endpoint=False):
            rot=np.asarray([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
            overlap=max(overlap,float(abs(np.vdot(va,vb@rot))/(na*nb)))
        return overlap
    except Exception:
        return 1.0

def reliability_metrics_match(claim:dict,truth:dict,df:float)->dict:
    """Recompute the public Hann/free-chain diagnostic contract from native COM."""
    metrics=claim.get('reliability_metrics',{})
    snr=metrics.get('local_power_snr'); ref_snr=truth.get('local_power_snr')
    if snr is None or ref_snr is None:
        snr_ok=snr is None and ref_snr is None
    else:
        snr_ok=abs(float(snr)-float(ref_snr))<=max(.5,.25*abs(float(ref_snr)))
    fft=metrics.get('fft_resolution_cm1')
    fft_ok=(fft is not None and abs(float(fft)-df)<=max(1e-8,abs(df)*1e-6))
    half=metrics.get('half_window_frequencies_cm1'); ref_half=truth.get('half_window_frequencies_cm1')
    if half==[None,None] or ref_half==[None,None]:
        half_ok=half==[None,None] and ref_half==[None,None]
    else:
        half_ok=(isinstance(half,list) and len(half)==2 and isinstance(ref_half,list) and len(ref_half)==2
                 and all(x is not None for x in half+ref_half)
                 and all(abs(float(half[i])-float(ref_half[i]))<=2*df+1e-8 for i in range(2)))
    bins_ok=(type(metrics.get('local_background_bins')) is int
             and metrics.get('local_background_bins')==truth.get('local_noise_bins'))
    return {'local_power_snr':bool(snr_ok),'fft_resolution_cm1':bool(fft_ok),
            'half_window_frequencies_cm1':bool(half_ok),'local_background_bins':bool(bins_ok),
            'all_match':bool(snr_ok and fft_ok and half_ok and bins_ok),
            'protocol':'Hann projection; +/-10 cm^-1 ring; peak/competitor +/-3 bins excluded; two contiguous half windows'}


def score(ctx:dict,files:dict[str,Path],run:dict)->dict:
    if sr is None: raise InfraError('trusted native parser dependency is unavailable')
    n=ctx['expected_selection']['N']; scope=ctx['scope']
    if scope=='SYNTHETIC_SPECTRAL_FIXTURE':
        n=ctx['expected_selection']['N']
        com=sr.read_numeric_table(files['synthetic_com'],1+3*n,'trusted synthetic COM')
        if len(com)!=50000: raise ScienceFail('controlled signal must have exactly 50000 post-initial rows')
        xyz=com[:,1:].reshape(len(com),n,3)
        spectral=cross_spectrum(xyz)
        truth=load_json(files['analytic_truth'],infra=True)
        verdict=compare_controlled_truth(spectral,truth,n)
        return {'schema':'case05-verification-result/v1','status':'CONSTRUCTION_FIXTURE_PASS' if verdict['pass'] else 'CONSTRUCTION_FIXTURE_FAIL',
          'reward':None,'trust_established':False,'selection':ctx['expected_selection'],'scope':scope,
          'full_instance_replay':False,'scientific_acceptance':'NOT_APPLICABLE_SYNTHETIC_ONLY','cross_spectral_modes':spectral,'fixture_checks':verdict}
    if scope=='AGENT_FORMAL' and (ctx['scheduler'].get('state')!='COMPLETED' or ctx['scheduler'].get('exit_code') not in ('0:0','0')):
        return {'schema':'case05-verification-result/v1','status':'FAIL','reward':0,'selection':ctx['expected_selection'],
          'scope':scope,'slurm':ctx['scheduler'],'reason':'candidate-submitted scheduler record shows an unsuccessful HPC execution'}
    if n not in (2,3,6): raise InfraError('unsupported N')
    native_ranks=ctx['mpi_ranks'] if scope=='AGENT_FORMAL' else 10
    native_preflight=verify_native_inputs_and_preflight(files,ctx['expected_selection'],native_ranks)
    com=_native_science_parse('production COM',sr.parse_layer_com,files['com'],n)
    if len(com)!=50000: raise ScienceFail('trusted post-initial COM rows are not exactly 50000')
    xyz=com[:,1:].reshape(50000,n,3)
    spectral=cross_spectrum(xyz)
    diag=_native_science_parse('trajectory diagnostics',physics_diagnostics,files,n,native_ranks)
    modes={(m['branch'],m['j']):m for m in run['modes']}
    raw={(m['branch'],m['j']):m for m in spectral['modes']}
    mode_results=[]
    mode_passes=0
    mode_credits=[]
    for key,claim in modes.items():
        truth=raw[key]; fref=truth['frequency_cm1']; half=truth['half_window_frequencies_cm1']
        metric_check=reliability_metrics_match(claim,truth,spectral['bin_spacing_cm1'])
        if fref is None:
            unresolved_ok=(claim.get('status')=='UNRESOLVED' and claim.get('unresolved_reason')==truth['resolved_reason_code']=='LOW_LOCAL_SNR'
                           and metric_check['all_match'])
            credit=.5 if unresolved_ok else 0.0
            mode_credits.append(credit)
            mode_results.append({'branch':key[0],'j':key[1],'trusted_frequency_cm1':None,'candidate_frequency_cm1':claim.get('frequency_cm1'),
                'resolved_reason_code':truth['resolved_reason_code'],'resolved_from_trusted_raw':False,'mode_pass':unresolved_ok,
                'mode_credit':credit,'reliability_metric_check':metric_check,
                'reason':'no physical-band signal; matching unresolved diagnosis' if unresolved_ok else 'no-signal diagnosis/metrics mismatch'})
            continue
        half_delta=abs(half[0]-half[1]); df=spectral['bin_spacing_cm1']
        nearest=nearest_competing_peak(raw,key,fref,df)
        tol=min(3.0,.45*nearest,max(2*df,half_delta,.5*truth['peak_width_cm1']))
        uncertainty_floor=max(df,half_delta/2)
        resolved=truth['resolved_reason_code'] is None and uncertainty_floor<=tol
        if truth['resolved_reason_code'] is None and not resolved:
            truth['resolved_reason_code']='FREQUENCY_SPACE_AMBIGUITY'
        claimed=claim.get('frequency_cm1')
        freqerr=abs(finite_num(claim.get('frequency_cm1'),'claimed frequency',True)-fref) if claim.get('status')=='DETECTED' else None
        shape=complex_vector_check(claim,truth,key[0]) if claim.get('status')=='DETECTED' else {'complex_shape_pass':False,'phase_node_pass':False}
        unc=claim.get('frequency_uncertainty_cm1')
        uncertainty_ok=(claim.get('status')=='DETECTED' and unc is not None and math.isfinite(float(unc)) and float(unc)>=uncertainty_floor and float(unc)<=tol)
        detected_ok=bool(claim.get('status')=='DETECTED' and resolved and freqerr<=tol and uncertainty_ok
                         and metric_check['all_match'] and shape['complex_shape_pass'] and shape['phase_node_pass'])
        unresolved_ok=False
        if claim.get('status')=='UNRESOLVED' and not resolved and claim.get('unresolved_reason')==truth['resolved_reason_code']:
            unresolved_ok=metric_check['all_match']
        ok=detected_ok or unresolved_ok
        credit=1.0 if detected_ok else .5 if unresolved_ok else 0.0
        mode_credits.append(credit)
        if detected_ok: mode_passes+=1
        mode_results.append({'branch':key[0],'j':key[1],'trusted_frequency_cm1':fref,
            'candidate_frequency_cm1':claimed,'frequency_error_cm1':freqerr,'frequency_tolerance_cm1':tol,
            'uncertainty_floor_cm1':uncertainty_floor,'nearest_competing_peak_cm1':nearest,
            'half_window_frequencies_cm1':half,'half_window_delta_cm1':half_delta,
            'local_power_snr':truth['local_power_snr'],'peak_width_cm1':truth['peak_width_cm1'],
            'projection_residual_diagnostic':truth['projection_residual'],'resolved_reason_code':truth['resolved_reason_code'],
            'resolved_from_trusted_raw':bool(resolved),'candidate_unresolved_reason':claim.get('unresolved_reason'),
            'complex_vector_check':shape,'reliability_metric_check':metric_check,'mode_pass':ok,'mode_credit':credit,
            'reason':'detected mode checks passed' if detected_ok else 'trusted unresolved diagnosis matched' if unresolved_ok else 'candidate diagnosis or mode evidence did not match trusted raw'})
    mode_freqs={}
    for key, value in raw.items(): mode_freqs.setdefault(key[0], []).append((key, value['frequency_cm1']))
    collisions=[]
    for branch, pairs in mode_freqs.items():
        for i,(ka,fa) in enumerate(pairs):
            for kb,fb in pairs[i+1:]:
                if fa is not None and fb is not None and abs(fa-fb)<=spectral['bin_spacing_cm1']:
                    collisions.append({'branch':branch,'mode_a':ka[1],'mode_b':kb[1],'frequency_a_cm1':fa,'frequency_b_cm1':fb})
    # Close competing peaks remain in the per-mode diagnostics; an aliased/
    # non-independent assignment is unresolved, not a process-level parser error.
    physics_ok=diag['proposed_physics_pass']
    # A candidate-submitted failed allocation is a science failure, not an environment error.
    scheduler_ok=(ctx['scope']=='AUTHOR_REPLAY_N2' or (ctx['scheduler'].get('state')=='COMPLETED' and ctx['scheduler'].get('exit_code') in ('0:0','0')))
    grade=grade_mode_credits(mode_credits,raw,n,physics_ok,scheduler_ok)
    status,reward,substatus=grade['status'],grade['reward'],grade['scientific_substatus']; mean_credit=grade['mean_mode_credit']
    full_replay=(scope=='AUTHOR_REPLAY_N2' and n==2)
    return {'schema':'case05-verification-result/v1','status':status,
       'reward':reward,'scientific_substatus':substatus,'score':{'passed_modes':mode_passes,'total_modes':len(raw),'mode_credits':mode_credits,'mean_mode_credit':mean_credit,'physics_pass':physics_ok},
       'selection':ctx['expected_selection'],'scope':scope,
       'coverage':{'full_instance_replay':full_replay,'selection':ctx['expected_selection'],
                   'multi_layer_production_replay':False if n==2 else None},
       'slurm':ctx['scheduler'],'native_context_scope':'CANDIDATE_SUBMITTED_EVIDENCE_CROSS_CHECKED','scheduler_success':scheduler_ok,
       'physics':diag,'native_preflight':native_preflight,'cross_spectral_modes':spectral,'mode_checks':mode_results,
       'scientific_rules_status':'V4_PUBLIC_RULES_FROZEN_BEFORE_AGENT_RESULT'}

def _emit_result(logs:Path|None, result:dict, message:str)->int:
    """Emit a machine-readable result even when dependencies or LOGS are broken."""
    try:
        serialized=json.dumps(result,indent=2,allow_nan=False)+'\n'
    except Exception as e:
        result={'schema':'case05-verification-result/v1','status':'ERROR',
                'error':f'result serialization failed: {type(e).__name__}: {e}',
                'trust_established':False,'reward':None}
        serialized=json.dumps(result,indent=2,allow_nan=False)+'\n'
        message='ERROR: result serialization failed'
    if logs is not None:
        try:
            (logs/'verification.json').write_text(serialized,encoding='utf-8')
        except Exception as e:
            result={'schema':'case05-verification-result/v1','status':'ERROR',
                    'error':f'{message}; verification report could not be written: {type(e).__name__}: {e}',
                    'trust_established':False,'reward':None}
            serialized=json.dumps(result,indent=2,allow_nan=False)+'\n'
            message=result['error']
            # Best-effort only: the directory may be absent or read-only.
            try: (logs/'verification.json').write_text(serialized,encoding='utf-8')
            except Exception: pass
    print(serialized,end='')
    return 0 if result.get('status')=='PASS' else 1 if result.get('status') in {'FAIL','PARTIAL'} else 2

def verify_refs_pins()->None:
    refs=load_json(HERE/'refs.json',infra=True)
    contract=refs.get('runtime_contract')
    if not isinstance(contract,dict): raise InfraError('public runtime contract is missing from refs.json')
    canonical=json.dumps(contract,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    if hashlib.sha256(canonical).hexdigest()!=refs.get('runtime_contract_sha256'):
        raise InfraError('public runtime contract hash is stale')
    pins=refs.get('files')
    verifier_pin=next((row for row in pins if isinstance(row,dict) and row.get('path')=='tests/verify.py'),None) if isinstance(pins,list) else None
    if verifier_pin is None or verifier_pin.get('sha256')!=sha(HERE/'verify.py') or verifier_pin.get('bytes')!=(HERE/'verify.py').stat().st_size:
        raise InfraError('refs.json verifier source pin is stale')

def main()->int:
    logs=None
    log_error=None
    log_path=Path(os.environ.get('LOGS','/logs/verifier'))
    try:
        log_path.mkdir(parents=True,exist_ok=True)
        logs=log_path
    except Exception as e:
        log_error=f'cannot create verifier log directory: {type(e).__name__}: {e}'
    if log_error is not None:
        return _emit_result(None,{'schema':'case05-verification-result/v1','status':'ERROR',
            'error':log_error,'trust_established':False,'reward':None},log_error)
    if np is None:
        msg=f'NumPy unavailable: {_NUMPY_IMPORT_ERROR}'
        return _emit_result(logs,{'schema':'case05-verification-result/v1','status':'ERROR','error':msg,'trust_established':False,'reward':None},msg)
    if sr is None:
        msg='trusted native evidence parser unavailable'
        return _emit_result(logs,{'schema':'case05-verification-result/v1','status':'ERROR','error':msg,'trust_established':False,'reward':None},msg)
    app=Path(os.environ.get('APP','/app')); final=app/'final'; asset_root=Path(os.environ.get('ASSETS',str(app/'assets')))
    provenance_valid=False
    try:
        verify_refs_pins()
        ctx,files=candidate_context(final,asset_root)
        artifact=load_json(final/'modes.json')
        run=validate_artifact(artifact,ctx)
        validate_evidence_paths(run,final)
        provenance_valid=True
        result=score(ctx,files,run)
        result['native_context_scope']='CANDIDATE_SUBMITTED_EVIDENCE_CROSS_CHECKED'
        result['submission_provenance_valid']=True
        return _emit_result(logs,result,f"{result['status']}: verification completed")
    except InfraError as e:
        out={'schema':'case05-verification-result/v1','status':'ERROR','error':str(e),'trust_established':False,'reward':None}
        return _emit_result(logs,out,f'ERROR: {e}')
    except ScienceFail as e:
        out={'schema':'case05-verification-result/v1','status':'FAIL','error':str(e),'submission_provenance_valid':provenance_valid,'reward':0}
        return _emit_result(logs,out,f'FAIL: {e}')
    except Exception as e:
        out={'schema':'case05-verification-result/v1','status':'ERROR','error':f'verifier internal/dependency failure: {type(e).__name__}: {e}','trust_established':False,'reward':None}
        return _emit_result(logs,out,f'ERROR: {type(e).__name__}: {e}')
if __name__=='__main__': raise SystemExit(main())
