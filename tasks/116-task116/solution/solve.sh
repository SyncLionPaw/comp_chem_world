#!/usr/bin/env bash
set -euo pipefail
exec python3 - <<'PY'
#!/usr/bin/env python3
"""Independent Oracle for Bader basin electron populations."""
import importlib.util,json,sys
from pathlib import Path
ROOT=Path('/app/environment/assets'); IDS=('TiS2_GGA','TiS2_HSE06','LiTiS2_GGA','LiTiS2_HSE06')
def populations(name):
    base=ROOT/name; lines=(base/'POSCAR').read_text().splitlines(); labels=[]
    for el,count in zip(lines[5].split(),map(int,lines[6].split())): labels.extend([el]*count)
    q=[]
    for line in (base/'ACF.dat').read_text(errors='replace').splitlines():
        f=line.split()
        if f and f[0].isdigit() and len(f)>=5: q.append(float(f[4]))
    if len(labels)!=len(q): raise RuntimeError(f'POSCAR/ACF count mismatch: {name}')
    sums={}
    for el,value in zip(labels,q): sums.setdefault(el,[]).append(value)
    return {el:sum(vals)/len(vals) for el,vals in sums.items()}
s={i:populations(i) for i in IDS}; d={}
for method,pristine,lithiated in [('GGA','TiS2_GGA','LiTiS2_GGA'),('HSE06','TiS2_HSE06','LiTiS2_HSE06')]:
    ds=s[lithiated]['S']-s[pristine]['S']; d[method]={'Ti':s[lithiated]['Ti']-s[pristine]['Ti'],'S_mean':ds,'S_total':2*ds}
c={'GGA_S_total_gain_exceeds_Ti':d['GGA']['S_total']>d['GGA']['Ti'],'HSE06_S_total_gain_exceeds_Ti':d['HSE06']['S_total']>d['HSE06']['Ti'],'bader_alone_shows_sulfur_redox_inactive':False}
r={'schema_version':2,'systems':s,'deltas':d,'claims':c,'methods':{'charge_quantity':'bader_basin_electrons','sulfur_aggregation':'mean_and_two_atom_total'}}
spec=importlib.util.spec_from_file_location('renderer',ROOT/'render_report.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
Path('/app/charges.json').write_text(json.dumps(r,indent=2)+'\n');Path('/app/report.md').write_text(m.render(r))
PY
