#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including results.json).
# L2 Execution: Bind native run evidence to the trusted runner context and capture proof.
# L3 Science: Compare eight same-composition relaxation candidates.
from __future__ import annotations
import json, os, sys
from pathlib import Path

REFS = json.loads(Path(__file__).with_name("refs.json").read_text(encoding="utf-8"))

"""Verify Case03 v4 outputs against the trusted host context and native records."""
import hashlib, itertools, json, math, os, re
from pathlib import Path, PurePosixPath

IDS=tuple(REFS["candidate_ids"])
EXPECTED_PAW=set(REFS["paw_titles"])
ARCHIVE_SHA=REFS["archive_sha256"]
ARCHIVE_ID=REFS["archive_source_id"]
RUNNER_CONTEXT_PATH=Path("/app/.bench16-trusted/runner-context.json")
CAPTURE_PROOF_PATH=Path("/app/.bench16-trusted/capture-proof.json")

def _trusted_context_bytes(path):
    path=Path(path)
    runner_path=os.environ.get('CCB_RUN_CONTEXT_PATH')
    expected=os.environ.get('CCB_RUN_CONTEXT_SHA256')
    if path.is_symlink() or not path.is_file(): raise ContextError('trusted runner context is not a regular file')
    raw=path.read_bytes()
    if runner_path is not None or expected is not None:
        if not runner_path or not expected or str(path)!=runner_path or not re.fullmatch(r'[0-9a-f]{64}',str(expected)):
            raise ContextError('runner context pin is malformed')
        if hashlib.sha256(raw).hexdigest()!=expected: raise ContextError('trusted runner context digest mismatch')
        return raw
    if path != RUNNER_CONTEXT_PATH:
        raise ContextError('runner did not provide a pinned protected context')
    proof_path=CAPTURE_PROOF_PATH
    if proof_path.is_symlink() or not proof_path.is_file():
        raise ContextError('protected capture proof is missing')
    try:
        proof=json.loads(proof_path.read_text(encoding='utf-8'))
        context=json.loads(raw.decode('utf-8'))
    except Exception as exc:
        raise ContextError('protected context or capture proof is malformed') from exc
    if (not isinstance(proof,dict) or proof.get('schema')!='compchembench.bench16-capture-proof/v1'
            or proof.get('context_sha256')!=hashlib.sha256(raw).hexdigest()
            or proof.get('attempt_id')!=context.get('attempt_id')
            or proof.get('task')!=context.get('task')
            or proof.get('case_id')!=context.get('case_id')
            or proof.get('execution_mode')!=context.get('execution_mode')):
        raise ContextError('protected capture proof does not bind this context')
    return raw

"""Native eight-candidate relaxation parser and comparison builder."""
import bz2, hashlib, itertools, math, re
from pathlib import Path
NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
NORMAL = "General timing and accounting informations for this job:"
class ScienceError(ValueError): pass
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def det(a): return a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])-a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])+a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0])
def volume(cell): return abs(det(cell))
def inv(a):
 d=det(a)
 if abs(d)<1e-12: raise ScienceError('singular cell')
 return [[(a[1][1]*a[2][2]-a[1][2]*a[2][1])/d,(a[0][2]*a[2][1]-a[0][1]*a[2][2])/d,(a[0][1]*a[1][2]-a[0][2]*a[1][1])/d],[(a[1][2]*a[2][0]-a[1][0]*a[2][2])/d,(a[0][0]*a[2][2]-a[0][2]*a[2][0])/d,(a[0][2]*a[1][0]-a[0][0]*a[1][2])/d],[(a[1][0]*a[2][1]-a[1][1]*a[2][0])/d,(a[0][1]*a[2][0]-a[0][0]*a[2][1])/d,(a[0][0]*a[1][1]-a[0][1]*a[1][0])/d]]
def mul(v,m): return [sum(v[i]*m[i][j] for i in range(3)) for j in range(3)]
def parse_poscar(path):
 rows=Path(path).read_text(errors='replace').splitlines()
 if len(rows)<8: raise ScienceError(f'truncated POSCAR {path}')
 scale=float(rows[1].split()[0]); raw=[[float(x) for x in rows[i].split()[:3]] for i in (2,3,4)]
 if scale<0: scale=(abs(scale)/abs(det(raw)))**(1/3)
 cell=[[x*scale for x in row] for row in raw]; species=rows[5].split(); counts=[int(x) for x in rows[6].split()]
 if len(species)!=len(counts): raise ScienceError('POSCAR species/count mismatch')
 idx=7
 if rows[idx].strip().lower().startswith('s'): idx+=1
 direct=rows[idx].strip().lower().startswith('d'); idx+=1; coords=[]; symbols=[]
 for s,n in zip(species,counts):
  for line in rows[idx:idx+n]: coords.append([float(x) for x in line.split()[:3]]); symbols.append(s)
  idx+=n
 if direct: coords=[mul(v,cell) for v in coords]
 if len(coords)!=sum(counts): raise ScienceError('truncated coordinate rows')
 return {'cell_A':cell,'positions_cartesian_A':coords,'symbols':symbols,'counts':dict(zip(species,counts))}
def _outcar_text(path):
 raw=Path(path).read_bytes()
 if Path(path).suffix=='.bz2': raw=bz2.decompress(raw)
 return raw.decode('latin1','replace')
def parse_incar(path):
 values={}
 for line in Path(path).read_text().splitlines():
  line=line.split('#',1)[0].split('!',1)[0]
  if '=' not in line: continue
  key,value=line.split('=',1); key=key.strip().upper(); value=value.strip().split()[0] if value.strip() else ''
  if key and value: values[key]=value
 return values
def _outcar_setting(text,name):
 patterns={
  'ENCUT':r'(?im)^\s*ENCUT\s*=\s*('+NUM+r')\s+eV',
  'EDIFF':r'(?im)^\s*EDIFF\s*=\s*('+NUM+r')\s+stopping-criterion',
  'EDIFFG':r'(?im)^\s*EDIFFG\s*=\s*('+NUM+r')\s+stopping-criterion',
  'ISIF':r'(?im)^\s*ISIF\s*=\s*(\d+)',
  'ISPIN':r'(?im)^\s*ISPIN\s*=\s*(\d+)',
  'NSW':r'(?im)^\s*NSW\s*=\s*(\d+)',
  'IBRION':r'(?im)^\s*IBRION\s*=\s*(-?\d+)',
 }
 found=re.findall(patterns[name],text)
 return found[-1] if found else None
def _last_ionic_block(text):
 markers=list(re.finditer(r'(?m)^\s*-+\s*Iteration\s+(\d+)\(\s*1\s*\)\s*-+',text))
 if not markers: raise ScienceError('missing native ionic-step boundary')
 return markers[-1].start(), text[markers[-1].start():]
def _last_lattice(text):
 matches=list(re.finditer(r'(?m)^\s*direct lattice vectors\s+reciprocal lattice vectors\s*$',text))
 if not matches: raise ScienceError('missing native final lattice block')
 lines=text[matches[-1].end():].splitlines(); rows=[]
 for line in lines:
  parts=line.split()
  if len(parts)<3: continue
  try: rows.append([float(x) for x in parts[:3]])
  except ValueError: break
  if len(rows)==3: return rows
 raise ScienceError('truncated native final lattice block')
def parse_outcar(path,natoms=REFS["atom_count"]):
 text=_outcar_text(path); boundary,final_ionic_text=_last_ionic_block(text); toten=re.findall(r'free\s+energy\s+TOTEN\s*=\s*('+NUM+r')',final_ionic_text,re.I); sigma=re.findall(r'energy\(sigma->0\)\s*=\s*('+NUM+r')',final_ionic_text,re.I)
 if not toten or not sigma: raise ScienceError(f'missing native energy pair: {path}')
 blocks=[]; lines=final_ionic_text.splitlines()
 for i,line in enumerate(lines):
  if re.search(r'POSITION\s+TOTAL-FORCE',line):
   rows=[]
   for row in lines[i+2:i+2+natoms]:
    parts=row.split()
    if len(parts)<6: break
    try: vals=[float(x) for x in parts[:6]]
    except ValueError: break
    rows.append(vals)
   if len(rows)==natoms: blocks.append(rows)
 if not blocks: raise ScienceError(f'missing complete native force block: {path}')
 forces=[r[3:] for r in blocks[-1]]; fmax=max(math.sqrt(sum(x*x for x in row)) for row in forces)
 ion_markers=list(re.finditer(r'(?m)^\s*-+\s*Iteration\s+(\d+)\(\s*1\s*\)\s*-+',text)); ion_steps=[int(x.group(1)) for x in ion_markers]
 version=re.search(r'vasp\.([0-9][^\s]*)',text); paw=[re.sub(r'\s+',' ',x).strip() for x in re.findall(r'(?im)^\s*TITEL\s*=\s*(.+?)\s*$',text)]
 return {'toten_eV':float(toten[-1]),'sigma0_eV':float(sigma[-1]),'physical_forces_eV_A':forces,'max_force_eV_A':fmax,'ionic_steps':len(ion_steps),'normal_termination':NORMAL in text,'electronic_convergence_marker':'aborting loop because EDIFF is reached' in final_ionic_text.split('POSITION',1)[0],'force_accuracy_marker':'reached required accuracy - stopping structural energy minimisation' in final_ionic_text,'actual_ibrion':_outcar_setting(text,'IBRION'),'actual_ediffg':_outcar_setting(text,'EDIFFG'),'outcar_settings':{k:_outcar_setting(text,k) for k in ('ENCUT','EDIFF','EDIFFG','ISIF','ISPIN','NSW','IBRION')},'final_outcar_cell_A':_last_lattice(text),'final_outcar_positions_cartesian_A':[[x[0],x[1],x[2]] for x in blocks[-1]],'native_version':version.group(1) if version else None,'paw_titles':paw,'raw_bytes':len(text.encode('latin1')),'sha256':sha(path)}
def mic_frac(d): return [x-round(x) for x in d]

def pair_geometry(a,b):
 ca,cb=a['final_cell_A'],b['final_cell_A']; avg=[[(ca[i][j]+cb[i][j])/2 for j in range(3)] for i in range(3)]
 fa=[mul(x,inv(ca)) for x in a['final_positions_cartesian_A']]; fb=[mul(x,inv(cb)) for x in b['final_positions_cartesian_A']]
 if a['species_order']!=b['species_order']: raise ScienceError('species/index order changed between relaxed structures')
 diffs=[[fb[i][k]-fa[i][k] for k in range(3)] for i in range(len(fa))]; best=None
 for shift in diffs:
  ds=[mul(mic_frac([d[k]-shift[k] for k in range(3)]),avg) for d in diffs]; rms=math.sqrt(sum(sum(x*x for x in d) for d in ds)/len(ds))
  if best is None or rms<best[0]: best=(rms,shift)
 return {'metric_id':REFS["geometry_metric_id"],'periodic_rmsd_A':best[0],'comparison_cell_A':avg,'max_cell_component_delta_A':max(abs(ca[i][j]-cb[i][j]) for i in range(3) for j in range(3)),'volume_delta_A3':volume(ca)-volume(cb),'mapping':{'method':'fixed atom index within identical Li/Ti/O species ordering; common global translation selected by enumerating corresponding-atom offsets; componentwise fractional minimum-image convention under arithmetic-mean cell','species_preserved':True,'atom_count':len(fa),'atom_map_zero_based':[[i,i] for i in range(len(fa))],'global_translation_fractional_subtracted_from_fractional_delta':best[1]}}
def build_result(root,context,asset_root):
 root=Path(root); asset_root=Path(asset_root); candidates={}; frozen_settings=parse_incar(asset_root/'method.INCAR')
 if frozen_settings.get('NPAR')!='2': raise ScienceError('frozen method INCAR must specify NPAR=2')
 expected_outcar={'ENCUT':('ENCUT',float),'EDIFFG':('EDIFFG',float),'ISIF':('ISIF',int),'ISPIN':('ISPIN',int),'NSW':('NSW',int)}
 for cid in IDS:
  d=root/'candidates'/cid; native=parse_outcar(d/'OUTCAR'); final=parse_poscar(d/'CONTCAR'); start=parse_poscar(asset_root/'candidates'/cid/'POSCAR')
  if len(native['physical_forces_eV_A'])!=REFS["atom_count"] or final['counts']!=REFS["composition"] or start['counts']!=final['counts']: raise ScienceError(f'composition or atom count mismatch in {cid}')
  input_settings=parse_incar(d/'INCAR')
  if input_settings!=frozen_settings: raise ScienceError(f'native INCAR settings differ from the frozen method in {cid}')
  for tag,(key,convert) in expected_outcar.items():
   observed=native['outcar_settings'][tag]
   if observed is None or not math.isclose(convert(observed),convert(frozen_settings[key]),rel_tol=0,abs_tol=1e-10): raise ScienceError(f'OUTCAR {tag} differs from the frozen native INCAR in {cid}')
  if native['actual_ibrion'] not in ('1','2') or (context.get('execution_mode')=='FRESH_HPC' and native['actual_ibrion']!='1'): raise ScienceError(f'OUTCAR optimizer is invalid for execution mode in {cid}')
  if context.get('execution_mode')=='FRESH_HPC' and not math.isclose(float(native['outcar_settings']['EDIFF']),float(frozen_settings['EDIFF']),rel_tol=0,abs_tol=1e-15): raise ScienceError(f'fresh OUTCAR EDIFF differs from the frozen 1e-6 method in {cid}')
  if any(abs(final['cell_A'][i][j]-native['final_outcar_cell_A'][i][j])>2e-5 for i in range(3) for j in range(3)): raise ScienceError(f'CONTCAR cell differs from final OUTCAR ionic-step cell in {cid}')
  final_frac=[mul(x,inv(final['cell_A'])) for x in final['positions_cartesian_A']]
  outcar_frac=[mul(x,inv(native['final_outcar_cell_A'])) for x in native['final_outcar_positions_cartesian_A']]
  if any(math.sqrt(sum(x*x for x in mul(mic_frac([final_frac[i][k]-outcar_frac[i][k] for k in range(3)]),final['cell_A'])))>2e-5 for i in range(REFS["atom_count"])): raise ScienceError(f'CONTCAR positions differ from final OUTCAR force block modulo periodic images in {cid}')
  hashes={n:sha(d/n) for n in ('INCAR','KPOINTS','POSCAR','CONTCAR','OSZICAR','OUTCAR')}
  candidates[cid]={**native,'native_incar_settings':input_settings,'final_cell_A':final['cell_A'],'final_positions_cartesian_A':final['positions_cartesian_A'],'species_order':final['symbols'],'start_cell_A':start['cell_A'],'start_sha256':sha(asset_root/'candidates'/cid/'POSCAR'),'native_hashes':hashes,'composition':final['counts'],'volume_A3':volume(final['cell_A']),'force_converged_at_EDIFFG':native['max_force_eV_A']<=REFS["force_threshold_eV_A"],'settings':{**input_settings,'IBRION_OUTCAR':native['actual_ibrion'],'EDIFFG_OUTCAR':native['actual_ediffg']}}
 method_hash=sha(asset_root/'method.INCAR'); k_hash=sha(asset_root/'method.KPOINTS')
 if any(c['native_hashes']['INCAR']!=method_hash for c in candidates.values()): raise ScienceError('native INCAR differs from the frozen common author input')
 if any(c['native_hashes']['KPOINTS']!=k_hash for c in candidates.values()): raise ScienceError('native KPOINTS differs from the frozen common author input')
 ids=list(candidates); comparisons=[]
 for i,j in itertools.combinations(ids,2):
  a,b=candidates[i],candidates[j]; comparisons.append({'candidate_a':i,'candidate_b':j,'delta_toten_eV':a['toten_eV']-b['toten_eV'],'delta_sigma0_eV':a['sigma0_eV']-b['sigma0_eV'],**pair_geometry(a,b)})
 order_t=sorted(ids,key=lambda x:candidates[x]['toten_eV']); order_s=sorted(ids,key=lambda x:candidates[x]['sigma0_eV']); gaps=sorted(abs(x['delta_sigma0_eV']) for x in comparisons)
 historical_settings={cid:c['outcar_settings'] for cid,c in candidates.items()}
 result = {'schema':'case03-author-relax-v4-results/v1','case_id':REFS["case_id"],'source':{k:context.get(k) for k in ('execution_mode','source_is_historical','archive_source_id','archive_sha256','source_job_id','source_terminal_state','resource_budget_ok','accepted_plan','accepted_plan_sha256','job_ids','actual_accounting')},'source_native_manifest':context.get('native_manifest'),'method':{'archived_input_sha256':method_hash,'kpoints_sha256':k_hash,'historical_optimizer_values':sorted({c['actual_ibrion'] for c in candidates.values()}),'historical_outcar_settings':historical_settings,'fresh_IBRION':1,'fresh_NPAR':2,'optimizer_provenance_note':'All candidates share the archived raw INCAR (including NPAR=2). Native OUTCAR records IBRION=1 or 2 and EDIFF=1e-6 or 1e-5 for hop4-final; these observed values are disclosed per candidate. Fresh runs are fixed to IBRION=1 and NPAR=2.','paw_titles':sorted(set(t for c in candidates.values() for t in c['paw_titles'])),'potcar_content_public':False},'candidates':candidates,'pairwise_comparisons':comparisons,'analysis':{'toten_order_low_to_high':order_t,'sigma0_order_low_to_high':order_s,'rankings_agree':order_t==order_s,'minimum_absolute_pairwise_sigma0_gap_eV':min(gaps),'energy_precision_eV':'Native printed precision (typically 1e-8 eV) is numerical representation, not physical uncertainty.','uncertainty_and_scope':'No ensemble or method uncertainty is quantified. Compare the two convention-specific finite-sample orders and report their sensitivity; provenance includes multiple native optimizer values, EDIFF settings, and VASP versions. These eight same-composition relaxations do not establish cross-stoichiometry stability or a global ground state.','claims':{'scope':'finite_same_composition_candidate_set','physical_or_method_uncertainty_quantified':False,'global_ground_state_established':False,'cross_stoichiometry_claimed':False},'geometry_scope':'The fixed_species_index_pbc_mean_cell_v1 metric uses a bijective species-preserving map, fractional positions in the arithmetic-mean cell, componentwise wrapping to [-0.5, 0.5), and the common translation minimizing RMS among mapped-atom offsets. This is one reproducible convention, not a claim of a unique structural minimum.'}}
 if context.get('execution_mode')=='FRESH_HPC':
  inventory=context.get('software_inventory',[]); pair=context.get('accepted_plan',{})
  qualified=next(x for x in inventory if x.get('qualified') is True and x.get('vasp_path')==pair.get('vasp_path') and x.get('mpi_path')==pair.get('mpi_path'))
  result['method']['paw_policy']=qualified['paw_identity'].get('policy','exact_author_archive')
  paw=qualified['paw_identity']
  display={k:paw[k] for k in ('policy','source_id','titles','combined_sha256','compressed_sha256','archive_sha256','archive_member') if k in paw}
  if isinstance(paw.get('components'),list):
   display['components']=[{k:row[k] for k in ('element','title','sha256','source_path','component_index') if k in row} for row in paw['components']]
  result['method']['paw_identity']=display
 return result


class ContextError(ValueError): pass
class CandidateError(ValueError): pass

def _sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _native_rows(context):
    rows=context.get('native_manifest')
    if not isinstance(rows,list) or not rows: raise ContextError('protected native manifest is missing')
    result={}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('path'),str) or not re.fullmatch(r'[0-9a-f]{64}',str(row.get('sha256',''))) or type(row.get('bytes')) is not int or row['bytes']<0 or row['path'] in result: raise ContextError('protected native manifest is malformed or duplicated')
        result[row['path']]=(row['sha256'],row['bytes'])
    return result

def _validate_fresh(context,rows):
    if context.get('source_is_historical') is not False or context.get('resource_budget_ok') is not True: raise ContextError('fresh host execution or resource budget is untrusted')
    job=context.get('source_job_id')
    if not isinstance(job,str) or not job.isdigit() or context.get('source_terminal_state')!='COMPLETED': raise ContextError('fresh source job is not a completed host-observed run')
    plan=context.get('accepted_plan'); fields={'ntasks','memory_gib','walltime_seconds','concurrent_runs','ranks_per_run','vasp_path','mpi_path'}
    if not isinstance(plan,dict) or set(plan)!=fields: raise ContextError('fresh accepted plan is missing or malformed')
    ints=('ntasks','memory_gib','walltime_seconds','concurrent_runs','ranks_per_run')
    if any(type(plan[k]) is not int for k in ints): raise ContextError('fresh accepted plan resource fields are not integers')
    if not (1<=plan['ntasks']<=REFS['resource_limits']['max_cpus'] and 1<=plan['memory_gib']<=REFS['resource_limits']['max_memory_gib'] and 0<plan['walltime_seconds']<=REFS['resource_limits']['max_walltime_seconds'] and plan['walltime_seconds']%60==0 and 1<=plan['concurrent_runs']<=REFS['max_concurrent_runs'] and plan['ranks_per_run']>0 and plan['ranks_per_run']%REFS['ranks_per_run_multiple']==0 and plan['concurrent_runs']*plan['ranks_per_run']<=plan['ntasks']): raise ContextError('fresh accepted plan exceeds authorized allocation or rank policy')
    if plan['ntasks']*plan['walltime_seconds']>REFS['resource_limits']['max_core_hours']*3600: raise ContextError('fresh requested allocation exceeds 160 core-hours')
    digest=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if context.get('accepted_plan_sha256')!=digest: raise ContextError('fresh accepted-plan hash is invalid')
    inventory=context.get('software_inventory'); facts=context.get('execution_facts')
    qualified=next((x for x in inventory if isinstance(x,dict) and x.get('qualified') is True and x.get('vasp_path')==plan['vasp_path'] and x.get('mpi_path')==plan['mpi_path']),None) if isinstance(inventory,list) else None
    if qualified is None: raise ContextError('accepted software pair is absent from host inventory')
    paw=qualified.get('paw_identity')
    if not isinstance(paw,dict) or paw.get('titles')!=REFS["paw_titles"] or paw.get('host_source_verified') is not True or paw.get('private_payload') is not True:
        raise ContextError('fresh software inventory does not bind a host-qualified standard PAW source')
    policy=paw.get('policy','exact_author_archive')
    if policy=='exact_author_archive':
        if (paw.get('source_id')!=REFS["paw_source_id"] or paw.get('compressed_sha256')!=REFS["compressed_paw_sha256"] or paw.get('combined_sha256')!=REFS["combined_paw_sha256"]): raise ContextError('exact-author PAW provenance differs from the frozen source')
    elif policy==REFS.get('qualified_hpc_paw',{}).get('policy'):
        expected=REFS['qualified_hpc_paw']
        if paw.get('source_id')!=expected['source_id'] or paw.get('combined_sha256')!=expected['combined_sha256']:
            raise ContextError('installed PAW source identity differs from the frozen host inventory')
        components=paw.get('components')
        if not isinstance(components,list) or len(components)!=3:
            raise ContextError('installed PAW component inventory is incomplete')
        paw_root = PurePosixPath(plan["vasp_path"]).parent.parent / "testsuite" / "POTCARS"
        for got,want in zip(components,expected['components']):
            want = {**want, "source_path": str(paw_root / PurePosixPath(want["source_path"]).name)}
            if not isinstance(got,dict) or any(got.get(k)!=want.get(k) for k in ('element','title','sha256','source_path','component_index')):
                raise ContextError('installed PAW component identity or order differs from the frozen host inventory')
        run_pots=paw.get('run_potcar_observations')
        expected_paths={f'{cid}/POTCAR' for cid in IDS}
        if not isinstance(run_pots,list) or {x.get('path') for x in run_pots if isinstance(x,dict)}!=expected_paths:
            raise ContextError('host PAW observation does not cover all eight fresh candidate POTCARs')
        expected_run_components=[{'title':x['title'],'sha256':x['sha256']} for x in expected['components']]
        for row in run_pots:
            if (row.get('sha256')!=expected['combined_sha256'] or row.get('titles')!=REFS['paw_titles']
                    or row.get('components')!=expected_run_components):
                raise ContextError('a fresh candidate POTCAR differs from the sealed qualified components')
    else:
        raise ContextError('fresh PAW policy is unsupported')
    inv_sha=hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if context.get('software_inventory_sha256')!=inv_sha: raise ContextError('host software inventory hash is invalid')
    site=context.get('site_profile')
    if not isinstance(site,dict) or set(site)!={'account','partition','job_root','vasp_path','mpi_path'}: raise ContextError('fresh operator site profile is missing or malformed')
    expected_exec=site['vasp_path']; expected_mpi=site['mpi_path']
    if (not isinstance(facts,dict) or facts.get('accepted_plan')!=plan or facts.get('accepted_plan_sha256')!=digest or facts.get('executable_path')!=expected_exec or plan['vasp_path']!=expected_exec or facts.get('mpi_path')!=expected_mpi or plan['mpi_path']!=expected_mpi or not re.fullmatch(r'[0-9a-f]{64}',str(facts.get('executable_sha256',''))) or not re.fullmatch(r'[0-9a-f]{64}',str(facts.get('mpi_sha256',''))) or not re.fullmatch(r'[0-9a-f]{64}',str(facts.get('script_sha256','')))):
        raise ContextError('fresh execution facts do not bind the accepted VASP/MPI pair')
    if facts.get('executable_sha256')!=REFS["vasp_sha256"] or facts.get('mpi_sha256')!=REFS["mpi_sha256"]: raise ContextError('fresh executable digest differs from the authorized inventory')
    accounting=context.get('resource_accounting')
    if not isinstance(accounting,dict): raise ContextError('fresh Slurm accounting is missing')
    sched=accounting.get('scheduler_rows')
    if not isinstance(sched,list): raise ContextError('fresh parent scheduler row is missing')
    parent=next((x for x in sched if isinstance(x,dict) and str(x.get('JobIDRaw'))==job),None)
    if parent is None: raise ContextError('fresh parent scheduler row is missing')
    try:
        cpus=int(parent.get('AllocCPUS',0)); elapsed=int(parent.get('ElapsedRaw',-1)); requested=int(str(parent.get('ReqMem','')).removesuffix('Gn').removesuffix('G')); limit=_slurm_seconds(parent.get('Timelimit'))
    except Exception as exc: raise ContextError('fresh scheduler resource fields are malformed') from exc
    charged=cpus*elapsed/3600
    if cpus!=plan['ntasks'] or requested!=plan['memory_gib'] or limit!=plan['walltime_seconds'] or not 0<=elapsed<=REFS['resource_limits']['max_walltime_seconds'] or charged>REFS['resource_limits']['max_core_hours']: raise ContextError('fresh scheduler allocation differs from plan or authorized cap')
    if accounting.get('allocated_cpus')!=cpus or accounting.get('elapsed_raw_seconds')!=elapsed or not math.isclose(float(accounting.get('allocated_core_hours_charged',-1)),charged,rel_tol=0,abs_tol=1e-6): raise ContextError('fresh ledger core-hour charge does not match AllocCPUS × ElapsedRaw')
    if (accounting.get('requested_memory')!=parent.get('ReqMem') or _slurm_seconds(accounting.get('time_limit'))!=limit or accounting.get('workdir')!=parent.get('WorkDir') or parent.get('WorkDir')!=context.get('workdir') or accounting.get('account')!=parent.get('Account') or accounting.get('partition')!=parent.get('Partition')): raise ContextError('fresh scheduler accounting and host ledger disagree')
    site=context.get('site_profile'); attempt=context.get('attempt_id')
    if not isinstance(site,dict) or set(site)!={'account','partition','job_root','vasp_path','mpi_path'} or not isinstance(attempt,str) or not re.fullmatch(r'[0-9a-f]{32}',attempt): raise ContextError('fresh operator site profile is missing or malformed')
    site_sha=hashlib.sha256(json.dumps(site,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    job_root=site.get('job_root'); posix_root=PurePosixPath(job_root) if isinstance(job_root,str) else PurePosixPath('.')
    if (not re.fullmatch(r'[A-Za-z0-9_.-]+',str(site.get('account',''))) or not re.fullmatch(r'[A-Za-z0-9_.-]+',str(site.get('partition','')))
            or not posix_root.is_absolute() or job_root in {'/','//'} or job_root.startswith('//') or '..' in posix_root.parts or job_root!=posix_root.as_posix()
            or context.get('site_profile_sha256')!=site_sha): raise ContextError('fresh operator site profile is not normalized or hash bound')
    expected_workdir=f"{job_root.rstrip('/')}/bench16/case03-author-v4/runs/{attempt}"
    if context.get('workdir')!=expected_workdir or parent.get('Account')!=site['account'] or parent.get('Partition')!=site['partition'] or accounting.get('actual_resource_budget_ok') is not True: raise ContextError('fresh host ledger differs from the operator site allocation')
    prefix=f'case03-author-v4/{job}'
    script_path=f'{prefix}/submit.slurm'; script_row=rows.get(script_path)
    if not script_row or script_row[0]!=facts['script_sha256']: raise ContextError('host-collected submit script is not bound to the execution facts')
    return prefix

def _slurm_seconds(value):
    if not isinstance(value,str) or not value: raise ContextError('scheduler time value is missing')
    days=0
    if '-' in value: d,value=value.split('-',1);days=int(d)
    parts=[int(x) for x in value.split(':')]
    if len(parts)==2: h,m=parts;s=0
    elif len(parts)==3: h,m,s=parts
    else: raise ContextError('scheduler time value is malformed')
    return days*86400+h*3600+m*60+s

def _close(a,b,tol=REFS["comparison_tolerance"]): return isinstance(a,(int,float)) and not isinstance(a,bool) and math.isfinite(float(a)) and abs(float(a)-float(b))<=tol
def _check_geometry_pair(row,candidates,where):
    try:
        i,j=row['candidate_a'],row['candidate_b']; a,b=candidates[i],candidates[j]; mapping=row['mapping']; atom_map=mapping['atom_map_zero_based']; shift=mapping['global_translation_fractional_subtracted_from_fractional_delta']; cell=row['comparison_cell_A']
        if row.get('metric_id')!=REFS["geometry_metric_id"] or mapping.get('species_preserved') is not True or not isinstance(mapping.get('method'),str) or not mapping['method'].strip() or len(atom_map)!=REFS["atom_count"] or len(shift)!=3 or len(cell)!=3: raise ValueError('unsupported geometry metric or invalid mapping')
        fa=[mul(x,inv(a['final_cell_A'])) for x in a['final_positions_cartesian_A']]; fb=[mul(x,inv(b['final_cell_A'])) for x in b['final_positions_cartesian_A']]
        mean_cell=[[(a['final_cell_A'][x][y]+b['final_cell_A'][x][y])/2 for y in range(3)] for x in range(3)]
        if len(cell)!=3 or any(len(row_cell)!=3 for row_cell in cell) or any(not _close(cell[x][y],mean_cell[x][y]) for x in range(3) for y in range(3)): raise ValueError('comparison cell is not the declared arithmetic mean')
        pairs=[];deltas=[];seen_a=set();seen_b=set()
        for pair in atom_map:
            if not isinstance(pair,list) or len(pair)!=2 or any(type(q)is not int or not 0<=q<REFS["atom_count"] for q in pair): raise ValueError('atom map index invalid')
            ia,ib=pair
            if ia in seen_a or ib in seen_b or a['species_order'][ia]!=b['species_order'][ib]: raise ValueError('atom mapping is not a species-preserving bijection')
            seen_a.add(ia);seen_b.add(ib);deltas.append([fb[ib][k]-fa[ia][k] for k in range(3)])
        if len(seen_a)!=REFS["atom_count"] or len(seen_b)!=REFS["atom_count"]: raise ValueError('atom mapping omits atoms')
        if any(not isinstance(x,(int,float)) or isinstance(x,bool) or not math.isfinite(float(x)) for x in shift): raise ValueError('global translation is malformed')
        for delta in deltas:
            frac=[delta[k]-shift[k]-round(delta[k]-shift[k]) for k in range(3)];pairs.append(mul(frac,cell))
        rms=math.sqrt(sum(sum(x*x for x in d) for d in pairs)/REFS["atom_count"])
        best_rms=float('inf')
        for candidate_shift in deltas:
            residuals=[]
            for delta in deltas:
                frac=[delta[k]-candidate_shift[k]-round(delta[k]-candidate_shift[k]) for k in range(3)];cart=mul(frac,cell);residuals.append(cart)
            candidate_rms=math.sqrt(sum(sum(x*x for x in d) for d in residuals)/REFS["atom_count"])
            best_rms=min(best_rms,candidate_rms)
        if rms>best_rms+REFS["comparison_tolerance"]: raise ValueError('global translation is not a minimum under the declared mapping')
        if not _close(row.get('periodic_rmsd_A'),rms) or not _close(row.get('max_cell_component_delta_A'),max(abs(a['final_cell_A'][x][y]-b['final_cell_A'][x][y]) for x in range(3) for y in range(3))) or not _close(row.get('volume_delta_A3'),a['volume_A3']-b['volume_A3']): raise ValueError('geometry residuals differ from the declared mapping')
    except CandidateError: raise
    except Exception as exc: raise CandidateError(f'{where}: invalid or unverifiable species-preserving geometry mapping: {exc}') from exc


def _readonly_security_context_valid(audit):
    if not isinstance(audit,dict) or audit.get('passed') is not True or audit.get('agent_uid') in (None,0): return False
    if audit.get('ssh_auth_socket_env_empty') is not True: return False
    protected=audit.get('protected_paths')
    if not isinstance(protected,dict): return False
    if protected.get('/root/.ssh',{}).get('read') is not False: return False
    if protected.get('/run/bench16/profile.json',{}).get('write') is not False: return False
    if protected.get('/run/bench16/ikkem.toml',{}).get('read') is not False: return False
    if protected.get('/app/assets/bench16_runtime.py',{}).get('write') is not False: return False
    clients=audit.get('remote_clients')
    expected={'ssh','scp','sftp','dbclient','plink'}
    if not isinstance(clients,dict) or set(clients)!=expected: return False
    if any(not isinstance(rows,list) or any(not isinstance(row,dict) or row.get('nonroot_execution_denied') is not True for row in rows) for rows in clients.values()): return False
    helpers=audit.get('setuid_helpers_present')
    if not isinstance(helpers,dict) or any(helpers.values()): return False
    if audit.get('setuid_files_remaining') != 0: return False
    return True

def _candidate_evidence_absent_valid(context, final_dir):
    tasks = {"case-03-author-relax-v4": "task 106", "case-04-author-neb-v3": "task 107"}
    attempt = context.get('attempt_id')
    site = context.get('site_profile')
    if not isinstance(site,dict): raise ContextError('operator Slurm site profile is missing')
    root = site.get('job_root','').rstrip('/') + '/bench16/' + ('case03-author-v4' if context.get('case_id')=='case-03-author-relax-v4' else 'case04-author') + '/runs'
    digest=hashlib.sha256(json.dumps(site,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if (context.get('schema') != 'compchembench.bench16-task-root-context/v1'
            or context.get('execution_mode') != 'NORMAL'
            or context.get('authority') != 'task_root_observed'
            or context.get('candidate_evidence_status') != 'NOT_DEMONSTRATED'
            or context.get('science_status') != 'NOT_DEMONSTRATED'
            or context.get('source_is_historical') is not False
            or context.get('case_id') not in tasks
            or context.get('task') != tasks.get(context.get('case_id'))
            or not isinstance(attempt, str) or not re.fullmatch(r'[0-9a-f]{32}', attempt)
            or context.get('run_id') != attempt
            or context.get('workdir') != root + '/' + str(attempt)
            or context.get('site_profile_sha256') != digest
            or context.get('jobs') != [] or context.get('remote_files_created') != []
            or any(key in context for key in ('accepted_plan', 'native_manifest', 'source_job_id', 'job_ids', 'actual_accounting'))):
        raise ContextError('candidate-absence context identity or claim set is invalid')
    for field in ('task_input_manifest_sha256', 'runtime_sha256', 'snapshot_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}', str(context.get(field, ''))):
            raise ContextError(f'candidate-absence context {field} is invalid')
    snapshot = context.get('snapshot')
    if (not isinstance(snapshot, dict) or snapshot.get('status') != 'OBSERVED'
            or snapshot.get('software_matches_reviewed_identity') is not True
            or snapshot.get('paw_matches_reviewed_identity') is not True
            or context.get('startup_probe_sha256') != hashlib.sha256(
                json.dumps(snapshot, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
            ).hexdigest()):
        raise ContextError('candidate-absence startup snapshot binding is invalid')
    observation = context.get('candidate_evidence_observation')
    if not isinstance(observation, dict) or set(observation) != {'sacct', 'squeue', 'attempt_workdir'}:
        raise ContextError('candidate-absence source observations are missing')
    empty_sha = hashlib.sha256(b'').hexdigest()
    absent_sha = hashlib.sha256(b'absent').hexdigest()
    sacct, squeue, workdir = observation['sacct'], observation['squeue'], observation['attempt_workdir']
    if (not isinstance(sacct, dict) or set(sacct) != {'query_return_code', 'query_name', 'query_workdir', 'matching_parent_rows', 'stdout_sha256'}
            or type(sacct.get('query_return_code')) is not int or sacct['query_return_code'] != 0
            or sacct.get('query_name') != attempt or sacct.get('query_workdir') != context['workdir']
            or type(sacct.get('matching_parent_rows')) is not int or sacct['matching_parent_rows'] != 0
            or sacct.get('stdout_sha256') != empty_sha):
        raise ContextError('candidate-absence accounting observation is invalid')
    if (not isinstance(squeue, dict) or set(squeue) != {'query_return_code', 'query_name', 'matching_jobs', 'stdout_sha256'}
            or type(squeue.get('query_return_code')) is not int or squeue['query_return_code'] != 0
            or squeue.get('query_name') != attempt
            or type(squeue.get('matching_jobs')) is not int or squeue['matching_jobs'] != 0
            or squeue.get('stdout_sha256') != empty_sha):
        raise ContextError('candidate-absence queue observation is invalid')
    if (not isinstance(workdir, dict) or set(workdir) != {'query_return_code', 'path', 'exists', 'stdout_sha256'}
            or type(workdir.get('query_return_code')) is not int or workdir['query_return_code'] != 0
            or workdir.get('path') != context['workdir']
            or workdir.get('exists') is not False or workdir.get('stdout_sha256') != absent_sha):
        raise ContextError('candidate-absence workdir observation is invalid')
    result_path = Path(final_dir) / 'results.json'
    if result_path.is_symlink() or result_path.exists():
        raise ContextError('candidate results exist despite the absent-evidence claim')
    evidence = Path(final_dir) / 'evidence'
    if evidence.is_symlink() or (evidence.exists() and any(path.is_file() for path in evidence.rglob('*'))):
        raise ContextError('candidate evidence files exist despite the absent-evidence claim')
    return True

def verify(final_dir,context_path=None,asset_root=None):
    final_dir=Path(final_dir);context_path=Path(context_path or os.environ.get('CCB_RUN_CONTEXT_PATH','/app/.bench16-trusted/runner-context.json'));asset_root=Path(asset_root or os.environ.get('APP','/app')+'/assets')
    try:
        context=json.loads(_trusted_context_bytes(context_path).decode('utf-8'))
        mode=context.get('execution_mode')
        if mode == 'NO_HPC_JOB':
            if (context.get('schema') != 'compchembench.bench16-task-root-context/v1'
                    or context.get('authority') != 'task_root_observed'
                    or context.get('case_id') != REFS["case_id"]):
                raise ContextError('invalid trusted scheduler selection record')
            return {'schema':'compchembench.verification/v1','status':'FAIL','score':0,
                    'execution_mode':mode,'science_status':'NOT_DEMONSTRATED',
                    'checked_claims':['no qualifying HPC job was available for trusted collection']}

        if context.get('candidate_evidence_status') == 'NOT_DEMONSTRATED':
            _candidate_evidence_absent_valid(context, final_dir)
            return {'schema':'compchembench.verification/v1','status':'FAIL','score':0,
                    'execution_mode':'NORMAL','science_status':'NOT_DEMONSTRATED',
                    'checked_claims':['source returned successful empty Slurm accounting and queue observations for this exact protected attempt',
                                      'the protected attempt workdir is absent; no qualifying completed candidate evidence is demonstrated']}
        if mode=='READONLY_MVP':
            if (context.get('authority')!='task_root_observed' or context.get('case_id')!=REFS["case_id"]
                    or context.get('science_status')!='NOT_RUN' or context.get('jobs')!=[]
                    or context.get('remote_files_created')!=[] or context.get('submission_disabled') is not True
                    or context.get('remote_mutation_disabled') is not True
                    or not _readonly_security_context_valid(context.get('security_audit'))
                    or not re.fullmatch(r'[0-9a-f]{64}',str(context.get('runtime_sha256','')))
                    or not re.fullmatch(r'[0-9a-f]{64}',str(context.get('snapshot_sha256','')))):
                raise ContextError('read-only MVP trusted context is malformed')
            return {'schema':'compchembench.verification/v1','status':'FAIL','score':0,
                    'execution_mode':'READONLY_MVP','science_status':'NOT_RUN',
                    'checked_claims':['read-only profile recorded by task-root collector',
                                      'zero submitted jobs and zero remote files created',
                                      'scientific analysis was not run']}
        if context.get('case_id')!=REFS["case_id"]: raise ContextError('protected task context identity is invalid')
        if mode=='FRESH_HPC':
            if context.get('authority') not in ('runner_host_observed','task_root_observed'): raise ContextError('fresh task-root context authority is invalid')
        elif context.get('authority')!='runner_host_observed': raise ContextError('historical archive context authority is invalid')
        rows=_native_rows(context)
        if mode=='HOST_AUTHORIZED_AUTHOR_ARCHIVE_REPLAY':
            if context.get('source_is_historical') is not True or context.get('source_job_id') is not None or context.get('archive_source_id')!=ARCHIVE_ID or context.get('archive_sha256')!=ARCHIVE_SHA: raise ContextError('historical archive source binding is invalid')
            if context.get('native_prefix')!='case03-author-v4' or not isinstance(context.get('archive_member_manifest'),list) or len(context['archive_member_manifest'])!=48: raise ContextError('historical archive context is incomplete')
            prefix='case03-author-v4'
        elif mode=='FRESH_HPC':
            prefix=_validate_fresh(context,rows)
        else: raise ContextError('unsupported trusted execution mode')
    except Exception as exc:
        return {'schema':'compchembench.verification/v1','status':'ERROR','score':None,'error':str(exc),'checked_claims':[]}
    try:
        actual=json.loads((final_dir/'results.json').read_text(encoding='utf-8'))
        if actual.get('schema')!='case03-author-relax-v4-results/v1' or actual.get('case_id')!=REFS["case_id"]: raise CandidateError('result schema or case id mismatch')
        evidence=final_dir/'evidence'
        expected_native_paths=set()
        for cid in IDS:
            native=evidence/'candidates'/cid
            for name in ('INCAR','KPOINTS','POSCAR','CONTCAR','OSZICAR','OUTCAR'):
                path=native/name; source=f'{prefix}/{cid}/{name}'; expected_native_paths.add(source)
                if not path.is_file(): raise CandidateError(f'missing native evidence {cid}/{name}')
                if rows.get(source)!=(_sha(path),path.stat().st_size): raise CandidateError(f'native bytes differ from protected host manifest: {source}')
        if mode=='FRESH_HPC':
            for cid in IDS:
                for name in ('vasp.stdout','vasp.stderr'):
                    path=evidence/'candidates'/cid/name; source=f'{prefix}/{cid}/{name}'; expected_native_paths.add(source)
                    if not path.is_file() or rows.get(source)!=(_sha(path),path.stat().st_size): raise CandidateError(f'missing or unbound native log {cid}/{name}')
            host=evidence/'host'
            for name in ('submit.slurm','software.txt','input_manifest.json'):
                path=host/name; source=f'{prefix}/{name}'; expected_native_paths.add(source)
                if not path.is_file() or rows.get(source)!=(_sha(path),path.stat().st_size): raise CandidateError(f'missing or unbound host evidence {name}')
        if set(rows)!=expected_native_paths: raise CandidateError('protected native manifest has unexpected or missing paths')
        if actual.get('source_native_manifest')!=context.get('native_manifest'): raise CandidateError('result does not preserve the host-observed native manifest')
        for cid in IDS:
            start=asset_root/'candidates'/cid/'POSCAR'; native=evidence/'candidates'/cid/'POSCAR'
            if not start.is_file() or _sha(start)!=_sha(native): raise CandidateError(f'{cid} does not preserve its supplied starting POSCAR')
        if _sha(asset_root/'method.INCAR')!=_sha(evidence/'candidates'/IDS[0]/'INCAR') or _sha(asset_root/'method.KPOINTS')!=_sha(evidence/'candidates'/IDS[0]/'KPOINTS'): raise CandidateError('frozen author INCAR/KPOINTS are not present as native inputs')
        expected=build_result(evidence,context,asset_root)
        if set(actual.get('candidates',{}))!=set(IDS): raise CandidateError('all eight candidate records are required')
        for cid in IDS:
            a=actual['candidates'][cid];e=expected['candidates'][cid]
            required=('toten_eV','sigma0_eV','physical_forces_eV_A','max_force_eV_A','ionic_steps','normal_termination','electronic_convergence_marker','force_accuracy_marker','actual_ibrion','actual_ediffg','outcar_settings','native_incar_settings','final_outcar_cell_A','final_outcar_positions_cartesian_A','native_version','paw_titles','native_hashes','final_cell_A','final_positions_cartesian_A','species_order','composition','volume_A3','force_converged_at_EDIFFG')
            for key in required:
                if key not in a: raise CandidateError(f'{cid} missing required native field {key}')
                _compare(a[key],e[key],f'candidates.{cid}.{key}')
            if a['normal_termination'] is not True or a['electronic_convergence_marker'] is not True or a['force_accuracy_marker'] is not True: raise CandidateError(f'{cid} lacks normal final SCF and structural-accuracy termination evidence')
            try: actual_ediffg=float(a['actual_ediffg'])
            except (TypeError,ValueError): actual_ediffg=float('nan')
            if a['actual_ibrion'] not in ('1','2') or not _close(actual_ediffg,REFS["ediffg"],1e-10): raise CandidateError(f'{cid} actual optimizer or EDIFFG differs from historical native record')
            if not a['force_converged_at_EDIFFG'] or a['max_force_eV_A']>REFS["force_threshold_eV_A"]: raise CandidateError(f'{cid} final physical force exceeds 0.02 eV/A')
            if set(a['paw_titles'])!=EXPECTED_PAW: raise CandidateError(f'{cid} does not identify the author standard-Ti PAW set')
        source=actual.get('source')
        if not isinstance(source,dict) or any(source.get(k)!=context.get(k) for k in ('execution_mode','source_is_historical','archive_source_id','archive_sha256','source_job_id','source_terminal_state','resource_budget_ok','accepted_plan','accepted_plan_sha256','job_ids','actual_accounting')):
            raise CandidateError('result source fields differ from host-observed context')
        expected_method=expected['method'];method=actual.get('method')
        core_method=('archived_input_sha256','kpoints_sha256','fresh_IBRION','fresh_NPAR','historical_optimizer_values','historical_outcar_settings','optimizer_provenance_note','paw_titles','potcar_content_public')
        if not isinstance(method,dict) or any(method.get(k)!=expected_method.get(k) for k in core_method): raise CandidateError('method, optimizer, PAW, or fresh-method provenance is inconsistent')
        for field in ('paw_policy','paw_identity'):
            if field in expected_method:
                if field not in method: raise CandidateError(f'fresh method omits sealed {field}')
                _compare(method[field],expected_method[field],f'method.{field}')
        if set(actual['analysis'].get('claims',{}))!=set(expected['analysis']['claims']) or actual['analysis']['claims']!=expected['analysis']['claims']: raise CandidateError('analysis scope claims are invalid')
        for field in ('energy_precision_eV','uncertainty_and_scope','geometry_scope'):
            if not isinstance(actual['analysis'].get(field),str) or not actual['analysis'][field].strip(): raise CandidateError(f'analysis requires a non-empty {field} statement')
        pairs=actual.get('pairwise_comparisons')
        if not isinstance(pairs,list) or len(pairs)!=28: raise CandidateError('all 28 pairwise comparisons are required')
        seen=set()
        for row in pairs:
            if not isinstance(row,dict) or row.get('candidate_a') not in IDS or row.get('candidate_b') not in IDS or row['candidate_a']==row['candidate_b']: raise CandidateError('pairwise comparison identity is invalid')
            key=frozenset((row['candidate_a'],row['candidate_b']))
            if key in seen: raise CandidateError('duplicate pairwise comparison')
            seen.add(key);a=expected['candidates'][row['candidate_a']];b=expected['candidates'][row['candidate_b']]
            if not _close(row.get('delta_toten_eV'),a['toten_eV']-b['toten_eV']) or not _close(row.get('delta_sigma0_eV'),a['sigma0_eV']-b['sigma0_eV']): raise CandidateError('pairwise signed energy difference is incorrect')
            _check_geometry_pair(row,expected['candidates'],f"{row['candidate_a']} vs {row['candidate_b']}")
        for field,energies in (('toten_order_low_to_high',{k:v['toten_eV'] for k,v in expected['candidates'].items()}),('sigma0_order_low_to_high',{k:v['sigma0_eV'] for k,v in expected['candidates'].items()})):
            order=actual['analysis'].get(field)
            if not isinstance(order,list) or len(order)!=8 or set(order)!=set(IDS): raise CandidateError(f'{field} must list all candidates exactly once')
            if any(energies[order[i]]>energies[order[i+1]]+REFS["comparison_tolerance"] for i in range(7)): raise CandidateError(f'{field} disagrees with native energies')
        agrees=actual['analysis']['toten_order_low_to_high']==actual['analysis']['sigma0_order_low_to_high']
        if actual['analysis'].get('rankings_agree') is not agrees or not _close(actual['analysis'].get('minimum_absolute_pairwise_sigma0_gap_eV'),min(abs(x['delta_sigma0_eV']) for x in expected['pairwise_comparisons'])): raise CandidateError('cross-convention ranking or reported energy separation is inconsistent')
        return {'schema':'compchembench.verification/v1','status':'PASS','score':1,'execution_mode':mode,'checked_claims':['all eight host-bound native variable-cell relaxations','same input method, separate observed optimizer/version and standard-Ti PAW evidence','final native electronic and structural convergence and physical force threshold','both energy conventions and all signed pairwise differences','species-preserving periodic mappings with independently recomputed residuals','uncertainty and finite same-composition scope claims']}
    except Exception as exc:
        return {'schema':'compchembench.verification/v1','status':'FAIL','score':0,'execution_mode':mode,'error':str(exc),'checked_claims':[]}
def _compare(a,b,path='$',tol=REFS["comparison_tolerance"]):
    if isinstance(b,bool):
        if type(a)is not bool or a is not b: raise CandidateError(path+': boolean differs from native reconstruction')
    elif isinstance(b,(int,float)) and not isinstance(b,bool):
        if not _close(a,b,tol): raise CandidateError(path+': numeric differs from native reconstruction')
    elif isinstance(b,dict):
        if not isinstance(a,dict) or set(a)!=set(b): raise CandidateError(path+': fields differ from native reconstruction')
        for k in b:_compare(a[k],b[k],path+'.'+k,tol)
    elif isinstance(b,list):
        if not isinstance(a,list) or len(a)!=len(b):raise CandidateError(path+': list differs from native reconstruction')
        for i,(x,y) in enumerate(zip(a,b)):_compare(x,y,f'{path}[{i}]',tol)
    elif a!=b: raise CandidateError(path+': value differs from native reconstruction')
def main():
    app=Path(os.environ.get('APP','/app'));logs=Path(os.environ.get('LOGS','/logs/verifier'));logs.mkdir(parents=True,exist_ok=True)
    result=verify(app/'final',Path(os.environ.get('CCB_RUN_CONTEXT_PATH','/app/.bench16-trusted/runner-context.json')),app/'assets')
    (logs/'verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    if result['status']=='PASS': (logs/'reward.txt').write_text('1.0\n');return 0
    if result['status']=='FAIL': (logs/'reward.txt').write_text('0.0\n');return 1
    return 2

def test_output_main():
    app=Path(os.environ.get('APP','/app')); asset=app/'assets'
    if not asset.is_dir(): asset=Path(__file__).resolve().parents[1]/'environment/assets'
    context=Path(os.environ.get('CCB_RUN_CONTEXT_PATH','/app/.bench16-trusted/runner-context.json'))
    report=verify(app/'final',context,asset)
    print(json.dumps(report,sort_keys=True))
    return 0 if report['status']=='PASS' else 2 if report['status']=='ERROR' else 1

if __name__ == "__main__":
    raise SystemExit(test_output_main() if "--test-output" in sys.argv[1:] else main())
