#!/usr/bin/env bash
set -euo pipefail
APP_ROOT=${APP:-$(pwd -P)}
mkdir -p "$APP_ROOT/final"
cat > "$APP_ROOT/final/generate_water.py" <<'PY'
#!/usr/bin/env python3
"""Generate a deterministic near-equilibrium isolated H2O geometry."""
import argparse,math,pathlib
p=argparse.ArgumentParser(); p.add_argument('--output',type=pathlib.Path,default=pathlib.Path('water.xyz')); a=p.parse_args()
# A transparent first-pass construction from generic chemical geometry:
# sum of single-bond covalent radii, and the ideal tetrahedral angle.
r=0.66+0.31
angle=math.acos(-1.0/3.0)
rows=[('O',0.0,0.0,0.0),('H',r,0.0,0.0),('H',r*math.cos(angle),r*math.sin(angle),0.0)]
a.output.parent.mkdir(parents=True,exist_ok=True)
with a.output.open('w') as f:
 f.write('3\nGenerated neutral isolated H2O; coordinates in angstrom\n')
 for sym,x,y,z in rows: f.write(f'{sym} {x:.10f} {y:.10f} {z:.10f}\n')
PY
chmod 755 "$APP_ROOT/final/generate_water.py"
(cd "$APP_ROOT/final" && python3 generate_water.py)
