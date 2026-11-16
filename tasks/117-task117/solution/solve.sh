#!/usr/bin/env bash
set -euo pipefail
exec python3 - <<'PY'
#!/usr/bin/env python3
"""Independent Oracle for first-grid VASP charge-density differences."""
import importlib.util,sys
from pathlib import Path
import numpy as np
ROOT=Path('/app/environment/assets'); IONS=('Li','Mg')
def read_grid(path):
    with path.open(errors='replace') as f:
        f.readline(); scale=float(f.readline().split()[0]); vectors=np.array([[float(x)*scale for x in f.readline().split()[:3]] for _ in range(3)])
        if not np.isfinite(vectors).all(): raise ValueError(f'non-finite cell: {path}')
        species=f.readline().split(); counts=list(map(int,f.readline().split())); n=sum(counts); mode=f.readline()
        if mode.strip().lower().startswith('s'): mode=f.readline()
        for _ in range(n): f.readline()
        while True:
            line=f.readline()
            if not line: raise ValueError(f'grid missing: {path}')
            if line.strip(): break
        shape=tuple(map(int,line.split()[:3])); need=int(np.prod(shape)); vals=[]
        while len(vals)<need:
            row=f.readline()
            if not row: raise ValueError(f'truncated grid: {path}')
            vals.extend(map(float,row.split()))
    volume=abs(float(np.linalg.det(vectors)))
    return np.asarray(vals[:need]),shape,volume,vectors

def structure(path):
    a=path.read_text(errors='replace').splitlines(); scale=float(a[1].split()[0]); lat=np.array([[float(x)*scale for x in a[i].split()[:3]] for i in (2,3,4)]); labels=[]
    for e,n in zip(a[5].split(),map(int,a[6].split())): labels.extend([e]*n)
    pos=7
    if a[pos].strip().lower().startswith('s'): pos+=1
    cart=a[pos].strip().lower().startswith(('c','k')); pos+=1; coords=np.array([[float(v) for v in a[pos+i].split()[:3]] for i in range(len(labels))])
    frac=coords*scale@np.linalg.inv(lat) if cart else coords
    if not np.isfinite(frac).all() or not np.isfinite(lat).all(): raise ValueError(f'non-finite structure: {path}')
    return labels,frac,lat

def close_geometry(directory,ion):
    labels,frac,lat=structure(directory/'host_ion'/'CONTCAR'); hl,hf,lh=structure(directory/'host'/'CONTCAR'); il,iff,li=structure(directory/'ion'/'CONTCAR')
    if not np.allclose(lat,lh,atol=1e-4,rtol=0) or not np.allclose(lat,li,atol=1e-4,rtol=0): return False
    def match(a,fa,b,fb):
        used=set()
        for lab,coord in zip(a,fa):
            candidates=[j for j,x in enumerate(b) if j not in used and x==lab]
            if not candidates:return False
            distances=[np.linalg.norm(((coord-fb[j])-np.round(coord-fb[j]))@lat) for j in candidates]
            j=candidates[int(np.argmin(distances))]
            if min(distances)>.01:return False
            used.add(j)
        return len(used)==len(b)
    host=[(x,y) for x,y in zip(labels,frac) if x!=ion]; mobile=[(x,y) for x,y in zip(labels,frac) if x==ion]
    return all(x==ion for x in il) and match(hl,hf,[x for x,y in host],[y for x,y in host]) and match(il,iff,[x for x,y in mobile],[y for x,y in mobile])
def metrics(ion):
    directory=ROOT/ion; vals=[]; shapes=[]; volumes=[]; lattices=[]
    for role in ('host_ion','host','ion'):
        v,s,vol,lat=read_grid(directory/role/'CHGCAR'); vals.append(v);shapes.append(s);volumes.append(vol);lattices.append(lat)
    if shapes[0]!=shapes[1] or shapes[0]!=shapes[2] or not all(np.allclose(lattices[0],x,atol=1e-4,rtol=0) for x in lattices[1:]) or max(abs(volumes[0]-v) for v in volumes[1:])>1e-4: raise ValueError('incompatible density grids or cells')
    rho=vals[0]/volumes[0]-vals[1]/volumes[1]-vals[2]/volumes[2]
    return {'grid':list(shapes[0]),'cell_volume_A3':volumes[0],'integral_delta_e':float(rho.sum()*volumes[0]/rho.size),'max_abs_delta_e_per_A3':float(np.max(np.abs(rho))),'volume_fraction_abs_gt_0.004':float(np.mean(np.abs(rho)>.004)),'geometry_match':close_geometry(directory,ion)}
ions={i:metrics(i) for i in IONS}; compatible=all(row['grid']==ions['Li']['grid'] for row in ions.values()) and all(abs(row['cell_volume_A3']-ions['Li']['cell_volume_A3'])<=1e-4 for row in ions.values()); closed=all(abs(row['integral_delta_e'])<1e-4 for row in ions.values())
r={'schema_version':2,**ions,'checks':{'cells_and_grids_compatible':compatible,'geometry_matches':all(x['geometry_match'] for x in ions.values()),'electron_count_closed':closed},'interpretation':{'observable':'first_grid_total_density_difference','valence_order_status':'insufficient_evidence','reason':'no_defined_valence_polarization_metric'}}
spec=importlib.util.spec_from_file_location('renderer',ROOT/'render_report.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
Path('/app/polarization.json').write_text(__import__('json').dumps(r,indent=2)+'\n');Path('/app/report.md').write_text(m.render(r))
PY
