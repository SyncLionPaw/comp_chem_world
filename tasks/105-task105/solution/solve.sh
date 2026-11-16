#!/usr/bin/env bash
set -euo pipefail
: "${APP:=/app}"
REF="${BENCH16_REFERENCE_ROOT:-/run/compchembench/reference}/case03-author-v4"
CTX="${CCB_RUN_CONTEXT_PATH:-/app/.bench16-trusted/runner-context.json}"
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 - "$REF" "$CTX" "$APP/final" "$HERE" "$APP/assets" <<'PY'
from __future__ import annotations
import json, shutil, sys
from pathlib import Path
ref, context_path, out, solution, assets = map(Path,sys.argv[1:])
"""Native eight-candidate relaxation parser and comparison builder."""
import bz2, hashlib, itertools, math, re
from pathlib import Path
IDS = ["hop1-initial"] + [f"hop{i}-final" for i in range(1, 8)]
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
def parse_outcar(path,natoms=177):
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
 return {'metric_id':'fixed_species_index_pbc_mean_cell_v1','periodic_rmsd_A':best[0],'comparison_cell_A':avg,'max_cell_component_delta_A':max(abs(ca[i][j]-cb[i][j]) for i in range(3) for j in range(3)),'volume_delta_A3':volume(ca)-volume(cb),'mapping':{'method':'fixed atom index within identical Li/Ti/O species ordering; common global translation selected by enumerating corresponding-atom offsets; componentwise fractional minimum-image convention under arithmetic-mean cell','species_preserved':True,'atom_count':len(fa),'atom_map_zero_based':[[i,i] for i in range(len(fa))],'global_translation_fractional_subtracted_from_fractional_delta':best[1]}}
def build_result(root,context,asset_root):
 root=Path(root); asset_root=Path(asset_root); candidates={}; frozen_settings=parse_incar(asset_root/'method.INCAR')
 if frozen_settings.get('NPAR')!='2': raise ScienceError('frozen method INCAR must specify NPAR=2')
 expected_outcar={'ENCUT':('ENCUT',float),'EDIFFG':('EDIFFG',float),'ISIF':('ISIF',int),'ISPIN':('ISPIN',int),'NSW':('NSW',int)}
 for cid in IDS:
  d=root/'candidates'/cid; native=parse_outcar(d/'OUTCAR'); final=parse_poscar(d/'CONTCAR'); start=parse_poscar(asset_root/'candidates'/cid/'POSCAR')
  if len(native['physical_forces_eV_A'])!=177 or final['counts']!={'Li':41,'Ti':40,'O':96} or start['counts']!=final['counts']: raise ScienceError(f'composition or atom count mismatch in {cid}')
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
  if any(math.sqrt(sum(x*x for x in mul(mic_frac([final_frac[i][k]-outcar_frac[i][k] for k in range(3)]),final['cell_A'])))>2e-5 for i in range(177)): raise ScienceError(f'CONTCAR positions differ from final OUTCAR force block modulo periodic images in {cid}')
  hashes={n:sha(d/n) for n in ('INCAR','KPOINTS','POSCAR','CONTCAR','OSZICAR','OUTCAR')}
  candidates[cid]={**native,'native_incar_settings':input_settings,'final_cell_A':final['cell_A'],'final_positions_cartesian_A':final['positions_cartesian_A'],'species_order':final['symbols'],'start_cell_A':start['cell_A'],'start_sha256':sha(asset_root/'candidates'/cid/'POSCAR'),'native_hashes':hashes,'composition':final['counts'],'volume_A3':volume(final['cell_A']),'force_converged_at_EDIFFG':native['max_force_eV_A']<=0.0200005,'settings':{**input_settings,'IBRION_OUTCAR':native['actual_ibrion'],'EDIFFG_OUTCAR':native['actual_ediffg']}}
 method_hash=sha(asset_root/'method.INCAR'); k_hash=sha(asset_root/'method.KPOINTS')
 if any(c['native_hashes']['INCAR']!=method_hash for c in candidates.values()): raise ScienceError('native INCAR differs from the frozen common author input')
 if any(c['native_hashes']['KPOINTS']!=k_hash for c in candidates.values()): raise ScienceError('native KPOINTS differs from the frozen common author input')
 ids=list(candidates); comparisons=[]
 for i,j in itertools.combinations(ids,2):
  a,b=candidates[i],candidates[j]; comparisons.append({'candidate_a':i,'candidate_b':j,'delta_toten_eV':a['toten_eV']-b['toten_eV'],'delta_sigma0_eV':a['sigma0_eV']-b['sigma0_eV'],**pair_geometry(a,b)})
 order_t=sorted(ids,key=lambda x:candidates[x]['toten_eV']); order_s=sorted(ids,key=lambda x:candidates[x]['sigma0_eV']); gaps=sorted(abs(x['delta_sigma0_eV']) for x in comparisons)
 historical_settings={cid:c['outcar_settings'] for cid,c in candidates.items()}
 return {'schema':'case03-author-relax-v4-results/v1','case_id':'case-03-author-relax-v4','source':{k:context.get(k) for k in ('execution_mode','source_is_historical','archive_source_id','archive_sha256','source_job_id','source_terminal_state','resource_budget_ok','accepted_plan','accepted_plan_sha256','job_ids','actual_accounting')},'source_native_manifest':context.get('native_manifest'),'method':{'archived_input_sha256':method_hash,'kpoints_sha256':k_hash,'historical_optimizer_values':sorted({c['actual_ibrion'] for c in candidates.values()}),'historical_outcar_settings':historical_settings,'fresh_IBRION':1,'fresh_NPAR':2,'optimizer_provenance_note':'All candidates share the archived raw INCAR (including NPAR=2). Native OUTCAR records IBRION=1 or 2 and EDIFF=1e-6 or 1e-5 for hop4-final; these observed values are disclosed per candidate. Fresh runs are fixed to IBRION=1 and NPAR=2.','paw_titles':sorted(set(t for c in candidates.values() for t in c['paw_titles'])),'potcar_content_public':False},'candidates':candidates,'pairwise_comparisons':comparisons,'analysis':{'toten_order_low_to_high':order_t,'sigma0_order_low_to_high':order_s,'rankings_agree':order_t==order_s,'minimum_absolute_pairwise_sigma0_gap_eV':min(gaps),'energy_precision_eV':'Native printed precision (typically 1e-8 eV) is numerical representation, not physical uncertainty.','uncertainty_and_scope':'No ensemble or method uncertainty is quantified. Compare the two convention-specific finite-sample orders and report their sensitivity; provenance includes multiple native optimizer values, EDIFF settings, and VASP versions. These eight same-composition relaxations do not establish cross-stoichiometry stability or a global ground state.','claims':{'scope':'finite_same_composition_candidate_set','physical_or_method_uncertainty_quantified':False,'global_ground_state_established':False,'cross_stoichiometry_claimed':False},'geometry_scope':'The fixed_species_index_pbc_mean_cell_v1 metric uses a bijective species-preserving map, fractional positions in the arithmetic-mean cell, componentwise wrapping to [-0.5, 0.5), and the common translation minimizing RMS among mapped-atom offsets. This is one reproducible convention, not a claim of a unique structural minimum.'}}

ctx=json.loads(context_path.read_text())
if (ctx.get('authority')!='runner_host_observed' or ctx.get('case_id')!='case-03-author-relax-v4' or ctx.get('execution_mode')!='HOST_AUTHORIZED_AUTHOR_ARCHIVE_REPLAY' or ctx.get('source_is_historical') is not True or ctx.get('source_job_id') is not None or ctx.get('archive_source_id')!='author-neb-relax-eight-archive' or ctx.get('archive_sha256')!='7bdcd8aa4e6e12d388af5193ac8b24ddaedf49e33c8e5f9eb49ca9e1ca6ae404'):
    raise SystemExit('Oracle requires the host-protected eight-record author archive replay context')
for cid in IDS:
    src=ref/cid; dst=out/'evidence'/'candidates'/cid; dst.mkdir(parents=True,exist_ok=True)
    for name in ('INCAR','KPOINTS','POSCAR','CONTCAR','OSZICAR','OUTCAR'):
        if not (src/name).is_file(): raise SystemExit(f'missing protected native output {cid}/{name}')
        shutil.copyfile(src/name,dst/name)
result=build_result(out/'evidence',ctx,assets)
out.mkdir(parents=True,exist_ok=True)
(out/'results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
PY
