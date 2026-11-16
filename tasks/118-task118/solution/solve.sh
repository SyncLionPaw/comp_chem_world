#!/usr/bin/env bash
set -euo pipefail
exec python3 - <<'PY'
#!/usr/bin/env python3
"""Independent Oracle for deposited same-composition stacking energies."""
import hashlib, importlib.util, json, math, re, sys
from pathlib import Path
APP=Path('/app'); CFG=json.loads((APP/'environment/assets/configurations.yaml').read_text())
FORM={'TiS2':{'Ti':1,'S':2},'LiTiS2':{'Li':1,'Ti':1,'S':2},'NaTiS2':{'Na':1,'Ti':1,'S':2}}
LIMITATIONS=['Only the three available same-composition P/R pairs are compared.','The deposited KPOINTS files carry the same 4×4×4 grid label, while the cells have different sizes; k-point density convergence is not established.','No Mg or Na0.5TiS2 pair is included.','No formation energies, convex hull, or global stability result is calculated.','Final ionic relaxation completion is checked separately from electronic convergence of every SCF step. NaTiS2-R has an early SCF step that reached NELM=100 without meeting EDIFF; later ionic steps converged.','Therefore this result does not claim that every electronic step converged, nor that either stacking is a global ground state.']
METHODS={'energy_source':'final OUTCAR free energy TOTEN, cross-checked against energy(sigma->0) and final OSZICAR E0','normalization':'one Ti atom equals one TiS2 formula unit; divide by N_Ti','delta_definition':'E_R_per_Ti - E_P_per_Ti','energy_tolerance_eV_per_Ti':1e-5,'delta_tolerance_eV_per_Ti':1e-5,'ordering_dead_zone_eV_per_Ti':1e-3,'tolerance_meaning':'printed-value comparison precision only; not a physical DFT uncertainty'}
def atom_counts(path):
    lines=path.read_text(errors='strict').splitlines(); symbols=lines[5].split(); counts=list(map(int,lines[6].split()))
    if not symbols or len(symbols)!=len(counts): raise RuntimeError(f'invalid species/counts: {path}')
    return dict(zip(symbols,counts)),sum(counts)
def parse_task(c):
    base=APP/'environment/assets/deposited'/c['id']
    for item in c['files'].values():
        p=APP/item['path']
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']: raise RuntimeError(f'deposited source integrity failure: {item["path"]}')
    out=(base/'OUTCAR').read_text(errors='replace'); z=(base/'OSZICAR').read_text(errors='replace')
    number=r'([-+0-9.Ee]+)'; tot=[float(x) for x in re.findall(r'free\s+energy\s+TOTEN\s*=\s*'+number,out,re.I)]; sig=[float(x) for x in re.findall(r'energy\(sigma->0\)\s*=\s*'+number,out)]; e0=[float(x) for x in re.findall(r'^\s*\d+\s+F=.*?\bE0=\s*'+number,z,re.M)]
    if not tot or not sig or not e0: raise RuntimeError(f'final energy record missing: {c["id"]}')
    final=tot[-1]
    if max(abs(final-sig[-1]),abs(final-e0[-1]))>1e-5: raise RuntimeError(f'energy records disagree: {c["id"]}')
    ions=list(map(int,re.findall(r'\bNIONS\s*=\s*(\d+)',out)))
    if not ions: raise RuntimeError(f'NIONS missing: {c["id"]}')
    initial,n0=atom_counts(base/'POSCAR'); relaxed,n1=atom_counts(base/'CONTCAR')
    if initial!=relaxed or n0!=n1 or n1!=ions[-1]: raise RuntimeError(f'atom identity changed: {c["id"]}')
    factor=1 if c['stacking']=='P' else 3; expected={k:v*factor for k,v in FORM[c['formula']].items()}
    if initial!=expected: raise RuntimeError(f'composition mismatch: {c["id"]}')
    nti=initial.get('Ti',0); ed=re.search(r'(?im)^\s*EDIFF\s*=\s*'+number,(base/'INCAR').read_text()); nm=re.search(r'(?im)^\s*NELM\s*=\s*(\d+)',(base/'INCAR').read_text())
    if not ed or not nm: raise RuntimeError(f'INCAR SCF settings missing: {c["id"]}')
    ediff=float(ed.group(1)); nelm=int(nm.group(1)); nout=re.findall(r'(?m)^\s*NELM\s*=\s*(\d+)\b',out); eout=re.search(r'(?im)^\s*EDIFF\s*=\s*'+number,out)
    if not nout or int(nout[-1])!=nelm or not eout or abs(float(eout.group(1))-ediff)>1e-12: raise RuntimeError(f'OUTCAR settings mismatch: {c["id"]}')
    kp=(base/'KPOINTS').read_text().splitlines()
    if len(kp)<4 or kp[2].strip().lower()!='gamma' or kp[3].split()!=['4','4','4']: raise RuntimeError(f'KPOINTS mismatch: {c["id"]}')
    its=[]; des=[]; deps=[]; count=0; de=deps0=None
    for line in z.splitlines():
        m=re.match(r'^\s*(?:DAV|RMM):\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)',line)
        if m: count=int(m.group(1));de=float(m.group(3));deps0=float(m.group(4))
        elif re.match(r'^\s*\d+\s+F=',line):
            if count<=0: raise RuntimeError(f'missing SCF iterations: {c["id"]}')
            its.append(count);des.append(de);deps.append(deps0);count=0
    final_conv=abs(des[-1])<=ediff and abs(deps[-1])<=ediff
    early=any(i>=nelm and (abs(a)>ediff or abs(b)>ediff) for i,a,b in zip(its[:-1],des[:-1],deps[:-1]))
    if 'reached required accuracy' not in out or 'General timing and accounting informations for this job' not in out: raise RuntimeError(f'relaxation did not end normally: {c["id"]}')
    return {'n_atoms':n1,'n_Ti':nti,'n_formula_units':nti,'final_TOTEN_eV':final,'energy_per_formula_unit_eV':final/nti,'final_electronic_converged':final_conv,'ionic_relaxation_complete':True,'normal_end':True,'early_scf_limit_hit':early}
rows={c['id']:parse_task(c) for c in CFG['files']}; pairs={}
for c in CFG['files']: pairs.setdefault(c['formula'],{})[c['stacking']]=rows[c['id']]
outpairs={}
for formula,ends in pairs.items():
    delta=ends['R']['energy_per_formula_unit_eV']-ends['P']['energy_per_formula_unit_eV']; order='within_dead_zone' if abs(delta)<=.001 else ('P_lower' if delta>0 else 'R_lower')
    outpairs[formula]={'P_eV_per_Ti':ends['P']['energy_per_formula_unit_eV'],'R_eV_per_Ti':ends['R']['energy_per_formula_unit_eV'],'delta_R_minus_P_eV_per_Ti':delta,'ordering':order,'early_scf_limit_hit':ends['R']['early_scf_limit_hit']}
r={'all_electronic_steps_converged':False,'hull_or_global_stability_claim':False,'methods':METHODS,'limitations':LIMITATIONS,'configurations':rows,'pairs':outpairs}
(APP/'final').mkdir(exist_ok=True); (APP/'final/stacking.json').write_text(json.dumps(r,indent=2)+'\n')
spec=importlib.util.spec_from_file_location('renderer',APP/'environment/assets/render_report.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);(APP/'final/report.md').write_text(m.render(r))
PY
