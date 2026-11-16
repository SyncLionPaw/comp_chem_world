#!/usr/bin/env bash
set -euo pipefail
exec python3 - <<'PY'
#!/usr/bin/env python3
"""Independent Oracle for deposited CI-NEB energies."""
import importlib.util,json,sys
from pathlib import Path
ROOT=Path('/app/environment/assets'); IDS=('O1_Li','O1_Mg','O1_Na','Li05_Li','Li05_Mg','O3_Na','O3_Mg_PATH1','O3_Mg_PATH2','P3_Na','P3_Mg')
def last_f(path):
    values=[]
    for line in path.read_text(errors='replace').splitlines():
        tokens=line.split()
        if 'F=' in tokens and tokens.index('F=')+1<len(tokens): values.append(float(tokens[tokens.index('F=')+1]))
    if not values: raise ValueError(f'missing ionic free energy: {path}')
    return values[-1]
def analyze(pid):
    root=ROOT/'neb'/pid; images=sorted((x for x in root.iterdir() if x.is_dir() and x.name.isdigit()),key=lambda x:int(x.name))
    energy=[last_f(x/'OSZICAR') for x in images]; relative=[x-energy[0] for x in energy]; ix=max(range(len(relative)),key=relative.__getitem__)
    return {'n_images':len(images),'energies_rel_eV':relative,'barrier_eV':relative[ix],'barrier_image':int(images[ix].name),'endpoint_rel_eV':relative[-1],'interior_saddle':ix not in (0,len(relative)-1)}
p={key:analyze(key) for key in IDS}
c={'O1_Mg_slower_than_O1_Li':p['O1_Mg']['barrier_eV']>p['O1_Li']['barrier_eV']+.05,'O1_Na_interior_saddle':p['O1_Na']['interior_saddle'],'Li05_lowers_Mg_barrier':p['Li05_Mg']['barrier_eV']<p['O1_Mg']['barrier_eV']-.05,'Li05_lowers_Li_barrier':p['Li05_Li']['barrier_eV']<p['O1_Li']['barrier_eV']-.05,'P3_Na_below_O3_Na':p['P3_Na']['barrier_eV']<p['O3_Na']['barrier_eV']-.05,'P3_Mg_below_both_O3_paths':p['P3_Mg']['barrier_eV']<p['O3_Mg_PATH1']['barrier_eV']-.05 and p['P3_Mg']['barrier_eV']<p['O3_Mg_PATH2']['barrier_eV']-.05,'low_P3_barrier_explains_poor_Mg_Na_storage':p['P3_Na']['barrier_eV']>p['O3_Na']['barrier_eV']+.05 and p['P3_Mg']['barrier_eV']>p['O3_Mg_PATH1']['barrier_eV']+.05 and p['P3_Mg']['barrier_eV']>p['O3_Mg_PATH2']['barrier_eV']+.05}
r={'schema_version':2,'paths':p,'claims':c,'delta_Mg_O1_minus_Li05_eV':p['O1_Mg']['barrier_eV']-p['Li05_Mg']['barrier_eV'],'methods':{'energy_source':'last_ionic_F'}}
spec=importlib.util.spec_from_file_location('renderer',ROOT/'render_report.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
Path('/app/barriers.json').write_text(json.dumps(r,indent=2)+'\n'); Path('/app/report.md').write_text(m.render(r))
PY
