#!/usr/bin/env bash
set -euo pipefail
exec python3 - <<'PY'
#!/usr/bin/env python3
"""Independent Oracle for deposited TiS2 lattice metrics."""
import importlib.util, json, math, sys
from pathlib import Path
ROOT=Path('/app/environment/assets')
IDS=('TiS2_P-3m1','TiS2_R-3m','TiS2_R3m','LiTiS2_P-3m1','LiTiS2_R-3m','NaTiS2_P-3m1','NaTiS2_R-3m')
def cell(path):
    lines=path.read_text().splitlines(); scale=float(lines[1].split()[0])
    vectors=[[float(x)*scale for x in lines[i].split()[:3]] for i in (2,3,4)]
    lengths=[math.sqrt(sum(x*x for x in row)) for row in vectors]
    n_ti=sum(int(n) for e,n in zip(lines[5].split(),lines[6].split()) if e=='Ti')
    spacing=lengths[2]/n_ti if abs(lengths[0]-lengths[1])<=.01 and lengths[0]<4.5 and n_ti in (1,3) else None
    return {'a_A':lengths[0],'b_A':lengths[1],'c_A':lengths[2],'n_Ti':n_ti,'interlayer_A':spacing}
s={key:cell(ROOT/key/'CONTCAR') for key in IDS}
t,l,n=s['TiS2_P-3m1']['interlayer_A'],s['LiTiS2_P-3m1']['interlayer_A'],s['NaTiS2_P-3m1']['interlayer_A']
r={'schema_version':2,'structures':s,'claims':{'O1_lithiation_expands_interlayer':l>t+.05,'O1_sodiation_expands_interlayer_more_than_lithiation':n-t>l-t+.05,'deposited_GGA_set_contains_MgTiS2':False,'R3m_TiS2_is_primitive_monolayer_cell':s['TiS2_R3m']['interlayer_A'] is not None},'methods':{'interlayer_rule':'c_over_nTi_if_a_b_hexagonal_and_nTi_1_or_3'}}
spec=importlib.util.spec_from_file_location('renderer',ROOT/'render_report.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
Path('/app/lattice.json').write_text(json.dumps(r,indent=2)+'\n'); Path('/app/report.md').write_text(m.render(r))
PY
