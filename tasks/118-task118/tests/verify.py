#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability (including stacking.json, report.md).
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Compare fixed-composition stacking stability from deposited GGA relaxation outputs.
"""Independent verifier for deposited same-composition P/R energies."""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, math, re, sys
from pathlib import Path
REFS=json.loads((Path(__file__).resolve().parent/'refs.json').read_text())
TOL=REFS['tol']; DEAD=REFS['dead_zone']
EXPECTED_FORMULAE=REFS['expected_formulae']
EXPECTED_IDS=set(REFS['expected_ids'])
LIMITATIONS=[
 'Only the three available same-composition P/R pairs are compared.',
 'The deposited KPOINTS files carry the same 4×4×4 grid label, while the cells have different sizes; k-point density convergence is not established.',
 'No Mg or Na0.5TiS2 pair is included.',
 'No formation energies, convex hull, or global stability result is calculated.',
 'Final ionic relaxation completion is checked separately from electronic convergence of every SCF step. NaTiS2-R has an early SCF step that reached NELM=100 without meeting EDIFF; later ionic steps converged.',
 'Therefore this result does not claim that every electronic step converged, nor that either stacking is a global ground state.'
]
METHODS={'energy_source':'final OUTCAR free energy TOTEN, cross-checked against energy(sigma->0) and final OSZICAR E0','normalization':'one Ti atom equals one TiS2 formula unit; divide by N_Ti','delta_definition':'E_R_per_Ti - E_P_per_Ti','energy_tolerance_eV_per_Ti':TOL,'delta_tolerance_eV_per_Ti':TOL,'ordering_dead_zone_eV_per_Ti':DEAD,'tolerance_meaning':'printed-value comparison precision only; not a physical DFT uncertainty'}

def emit(status,message,rc,details=None):
 out={'status':status,'message':message}
 if status!='ERROR':out['reward']=1 if status=='PASS' else 0
 if details:out['details']=details
 print(json.dumps(out,ensure_ascii=False,indent=2));return rc

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def num(x):
 if isinstance(x,bool) or not isinstance(x,(int,float)):return False
 try:return math.isfinite(float(x))
 except (TypeError,ValueError,OverflowError):return False
def parse_poscar(path):
 lines=path.read_text(errors='strict').splitlines()
 syms=lines[5].split(); counts=list(map(int,lines[6].split()))
 if not syms or len(syms)!=len(counts):raise RuntimeError(f'POSCAR species/count parse failed: {path}')
 return dict(zip(syms,counts)),sum(counts)
def parse_outcar_oszicar(pkg,c):
 base=pkg/'environment/assets/deposited'/c['id']; files=c['files']
 for n,meta in files.items():
  p=pkg/meta['path']
  if not p.is_file() or sha(p)!=meta['sha256']:raise RuntimeError(f'input missing/hash mismatch: {meta["path"]}')
 out=(base/'OUTCAR').read_text(errors='replace');z=(base/'OSZICAR').read_text(errors='replace')
 vals=re.findall(r'energy\(sigma->0\)\s*=\s*([-+0-9.Ee]+)',out)
 e0s=re.findall(r'^\s*\d+\s+F=.*?\bE0=\s*([-+0-9.Ee]+)',z,re.M)
 if not vals or not e0s:raise RuntimeError(f'final energy missing: {c["id"]}')
 sigma0=float(vals[-1]);e0=float(e0s[-1])
 totens=re.findall(r'free\s+energy\s+TOTEN\s*=\s*([-+0-9.Ee]+)',out,re.I)
 if not totens:raise RuntimeError(f'final OUTCAR TOTEN missing: {c["id"]}')
 final=float(totens[-1])
 if abs(final-sigma0)>TOL or abs(final-e0)>TOL:raise RuntimeError(f'OUTCAR TOTEN, sigma-zero energy and OSZICAR E0 disagree: {c["id"]}')
 nions=re.findall(r'\bNIONS\s*=\s*(\d+)',out)
 if not nions:raise RuntimeError(f'OUTCAR NIONS missing: {c["id"]}')
 nions=int(nions[-1])
 pos_atoms,npos=parse_poscar(base/'POSCAR');cont_atoms,ncont=parse_poscar(base/'CONTCAR')
 if pos_atoms!=cont_atoms or npos!=ncont or npos!=nions:raise RuntimeError(f'POSCAR/CONTCAR/OUTCAR atom counts disagree: {c["id"]}')
 factor=1 if c['stacking']=='P' else 3
 expected={k:v*factor for k,v in EXPECTED_FORMULAE[c['formula']].items()}
 if pos_atoms!=expected:raise RuntimeError(f'composition/stacking identity mismatch: {c["id"]}')
 n_ti=pos_atoms.get('Ti',0)
 if n_ti<1 or npos % n_ti !=0:raise RuntimeError(f'Ti/f.u. normalization invalid: {c["id"]}')
 ediffmatch=re.search(r'(?im)^\s*EDIFF\s*=\s*([-+0-9.Ee]+)',(base/'INCAR').read_text())
 nelmmatch=re.search(r'(?im)^\s*NELM\s*=\s*(\d+)',(base/'INCAR').read_text())
 if not ediffmatch or not nelmmatch:raise RuntimeError(f'INCAR EDIFF/NELM missing: {c["id"]}')
 ediff=float(ediffmatch.group(1));nelm=int(nelmmatch.group(1))
 if not re.search(r'(?m)^\s*NELM\s*=\s*'+str(nelm)+r'\b',out):raise RuntimeError(f'OUTCAR NELM differs from INCAR: {c["id"]}')
 out_ediff=re.search(r'(?im)^\s*EDIFF\s*=\s*([-+0-9.Ee]+)',out)
 if not out_ediff or abs(float(out_ediff.group(1))-ediff)>1e-12:raise RuntimeError(f'OUTCAR EDIFF differs from INCAR: {c["id"]}')
 kp=(base/'KPOINTS').read_text(errors='replace').splitlines()
 if len(kp)<4 or kp[2].strip().lower()!='gamma' or kp[3].split()!=['4','4','4']:raise RuntimeError(f'deposited KPOINTS grid identity mismatch: {c["id"]}')
 # Read each ionic block's electronic iteration trace from OSZICAR.
 counts=[]; d_e=[]; d_eps=[]; count=0; last_de=last_deps=None
 for line in z.splitlines():
  m=re.match(r'^\s*(?:DAV|RMM):\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)',line)
  if m:
   count=int(m.group(1));last_de=float(m.group(3));last_deps=float(m.group(4))
  elif re.match(r'^\s*\d+\s+F=',line):
   if count<=0:raise RuntimeError(f'OSZICAR ionic record lacks electronic iterations: {c["id"]}')
   counts.append(count);d_e.append(last_de);d_eps.append(last_deps);count=0;last_de=last_deps=None
 if not counts:raise RuntimeError(f'OSZICAR ionic steps missing: {c["id"]}')
 final_electronic=abs(d_e[-1])<=ediff and abs(d_eps[-1])<=ediff
 early_cap=any(n>=nelm and (abs(de)>ediff or abs(deps)>ediff) for n,de,deps in zip(counts[:-1],d_e[:-1],d_eps[:-1]))
 if 'reached required accuracy' not in out:raise RuntimeError(f'final ionic relaxation completion marker missing: {c["id"]}')
 normal_end='General timing and accounting informations for this job' in out
 if not normal_end:raise RuntimeError(f'VASP normal-end marker missing: {c["id"]}')
 return {'n_atoms':npos,'n_Ti':n_ti,'n_formula_units':n_ti,'final_TOTEN_eV':final,'energy_per_formula_unit_eV':final/n_ti,'final_electronic_converged':final_electronic,'ionic_relaxation_complete':True,'normal_end':normal_end,'early_scf_limit_hit':early_cap}

def reference(pkg):
 cfg=json.loads((pkg/'environment/assets/configurations.yaml').read_text())
 expected_ids=EXPECTED_IDS
 if not isinstance(cfg.get('files'),list) or {r.get('id') for r in cfg['files'] if isinstance(r,dict)}!=expected_ids or len(cfg['files'])!=6:raise RuntimeError('configuration manifest must define the six expected structures exactly once')
 structures={c['id']:parse_outcar_oszicar(pkg,c) for c in cfg['files']}
 pairs={}
 for c in cfg['files']:
  pairs.setdefault(c['formula'],{})[c['stacking']]=structures[c['id']]
 for f,row in pairs.items():
  if set(row)!={'P','R'}:raise RuntimeError(f'incomplete pair {f}')
  row['delta']=row['R']['energy_per_formula_unit_eV']-row['P']['energy_per_formula_unit_eV']
 return cfg,structures,pairs

def load_renderer(pkg):
 path=pkg/'environment/assets/render_report.py';spec=importlib.util.spec_from_file_location('task154_renderer',path)
 if spec is None or spec.loader is None:raise RuntimeError('report renderer unavailable')
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module.render

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--package',type=Path,default=Path(__file__).resolve().parent.parent);ap.add_argument('--submission',type=Path,required=True);a=ap.parse_args()
 # Assets and reference integrity are environment state; evaluate them before submission parsing.
 try: cfg,ref,groups=reference(a.package);render=load_renderer(a.package)
 except Exception as e:return emit('ERROR',f'evaluation asset/environment error: {e}',2)
 try:sub=json.loads(a.submission.read_text())
 except Exception as e:return emit('FAIL',f'submission JSON missing or invalid: {e}',1)
 issues=[]
 if not isinstance(sub,dict):return emit('FAIL','submission root must be an object',1)
 if sub.get('all_electronic_steps_converged') is not False:issues.append('all_electronic_steps_converged must be false')
 if sub.get('hull_or_global_stability_claim') is not False:issues.append('unsupported hull/global stability claim')
 if sub.get('methods')!=METHODS:issues.append('methods must state the fixed source, normalization, delta and tolerances')
 if sub.get('limitations')!=LIMITATIONS:issues.append('limitations must exactly cover the defined evidence boundary')
 submitted=sub.get('configurations')
 if not isinstance(submitted,dict) or set(submitted)!=set(ref):issues.append('configurations must include all six deposited structures')
 else:
  for ident,want in ref.items():
   got=submitted[ident]
   if not isinstance(got,dict):issues.append(f'{ident}: configuration must be an object');continue
   for key in ('n_atoms','n_Ti','n_formula_units','final_TOTEN_eV','energy_per_formula_unit_eV'):
    x=got.get(key)
    if key in ('n_atoms','n_Ti','n_formula_units'):
     if isinstance(x,bool) or not isinstance(x,int) or x!=want[key]:issues.append(f'{ident}: {key} incorrect')
    elif not num(x) or abs(float(x)-want[key])>TOL:issues.append(f'{ident}: {key} incorrect')
   for key in ('final_electronic_converged','ionic_relaxation_complete','normal_end','early_scf_limit_hit'):
    if got.get(key) is not want[key]:issues.append(f'{ident}: {key} incorrect')
 pairs=sub.get('pairs')
 if not isinstance(pairs,dict) or set(pairs)!=set(groups):issues.append('pairs must contain exactly TiS2, LiTiS2, NaTiS2')
 else:
  for f,row in groups.items():
   got=pairs[f]
   if not isinstance(got,dict):issues.append(f'{f}: pair must be an object');continue
   vals={'P_eV_per_Ti':row['P']['energy_per_formula_unit_eV'],'R_eV_per_Ti':row['R']['energy_per_formula_unit_eV'],'delta_R_minus_P_eV_per_Ti':row['delta']}
   for key,want in vals.items():
    x=got.get(key)
    if not num(x) or abs(float(x)-want)>TOL:issues.append(f'{f}: {key} incorrect (units/normalization/value)')
   order='within_dead_zone' if abs(row['delta'])<=DEAD else 'P_lower' if row['delta']>0 else 'R_lower'
   if got.get('ordering')!=order:issues.append(f'{f}: ordering incorrect')
   if got.get('early_scf_limit_hit') is not row['R']['early_scf_limit_hit']:issues.append(f'{f}: early_scf_limit_hit incorrect')
 if issues:return emit('FAIL','submission failed scientific checks',1,issues)
 report=a.submission.with_name('report.md')
 if not report.is_file():return emit('FAIL','report.md missing beside stacking.json',1)
 try:actual=report.read_text()
 except (OSError,UnicodeError) as e:return emit('FAIL',f'report unreadable: {e}',1)
 if actual!=render(sub):return emit('FAIL','report.md does not match deterministic renderer',1)
 return emit('PASS','scoped deposited-pair comparison verified',0,{'pair_delta_eV_per_Ti':{f:v['delta'] for f,v in groups.items()},'full_hull_claimed':False,'every_electronic_step_converged_claimed':False})
if __name__=='__main__':sys.exit(main())
