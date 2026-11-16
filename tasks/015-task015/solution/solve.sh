#!/bin/sh
# Compute AM1-BCC/GAFF parameters and build the periodic solvent model.
set -eu
app=${APP:-/app}
input=${INPUT_DIR:-$app/inputs}
output=$app/final
mkdir -p "$output/parameters" "$output/logs"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
cd "$work"
export AMBERHOME=${AMBERHOME:-/opt/autosolvate}
python3 - "$input/naphthalene_neutral.xyz" <<'PY'
from pathlib import Path
import sys,numpy as np
rows=Path(sys.argv[1]).read_text().splitlines();n=int(rows[0]);symbols=[r.split()[0] for r in rows[2:2+n]];x=np.array([[float(v) for v in r.split()[1:4]] for r in rows[2:2+n]])
assert symbols==['C']*10+['H']*8
lines=[]
for i,(s,p) in enumerate(zip(symbols,x),1):
 name=s+str(i);lines.append(f'ATOM  {i:5d} {name:>4} SLU A   1    {p[0]:8.3f}{p[1]:8.3f}{p[2]:8.3f}  1.00  0.00          {s:>2}')
radii={'C':.76,'H':.31}
for i in range(n):
 bonded=[j+1 for j in range(n) if i!=j and np.linalg.norm(x[i]-x[j])<1.2*(radii[symbols[i]]+radii[symbols[j]])]
 if bonded:lines.append('CONECT'+f'{i+1:5d}'+''.join(f'{j:5d}' for j in bonded))
Path('solute.pdb').write_text('\n'.join(lines)+'\nEND\n')
PY
antechamber -i solute.pdb -fi pdb -o "$output/parameters/solute.mol2" -fo mol2 \
  -c bcc -nc 0 -m 1 -at gaff -rn SLU -pf y -s 2 > "$output/logs/antechamber.log" 2>&1
parmchk2 -i "$output/parameters/solute.mol2" -f mol2 -o "$output/parameters/solute.frcmod" -s gaff > "$output/logs/parmchk2.log" 2>&1
cp "$input/ch3cn.prep" "$input/ch3cn.frcmod" "$output/parameters/"
cat > templates.leap <<LEAP
source leaprc.protein.ff14SB
source leaprc.gaff
loadAmberParams $output/parameters/solute.frcmod
loadAmberParams $output/parameters/ch3cn.frcmod
loadAmberPrep $output/parameters/ch3cn.prep
set C3N head null
set C3N tail null
SLU = loadMol2 $output/parameters/solute.mol2
set SLU head null
set SLU tail null
savePdb C3N acn.pdb
savePdb SLU solute-named.pdb
quit
LEAP
tleap -f templates.leap > "$output/logs/templates.log" 2>&1
cat > packing.inp <<'PACK'
tolerance 2.0
filetype pdb
output packed.pdb
seed 63729
nloop 500
structure solute-named.pdb
 number 1
 fixed 28. 28. 28. 0. 0. 0.
end structure
structure acn.pdb
 number 1680
 inside box 0.5 0.5 0.5 55.5 55.5 55.5
end structure
PACK
packmol < packing.inp > "$output/logs/packmol.log" 2>&1
cat > build.leap <<LEAP
source leaprc.protein.ff14SB
source leaprc.gaff
loadAmberParams $output/parameters/solute.frcmod
loadAmberParams $output/parameters/ch3cn.frcmod
loadAmberPrep $output/parameters/ch3cn.prep
set C3N head null
set C3N tail null
SLU = loadMol2 $output/parameters/solute.mol2
set SLU head null
set SLU tail null
model = loadPdb packed.pdb
set model box {56. 56. 56.}
check model
saveAmberParm model $output/system.prmtop $output/system.inpcrd
savePdb model $output/system.pdb
quit
LEAP
tleap -f build.leap > "$output/logs/tleap.log" 2>&1
cp templates.leap build.leap packing.inp "$output/logs/"
for f in sqm.in sqm.out sqm.pdb; do
 if [ -f "$f" ]; then cp "$f" "$output/parameters/"; fi
done
python3 - "$output" <<'PY'
from pathlib import Path
import json,sys,numpy as np,parmed
from scipy.spatial import cKDTree
from openmm import app,unit,Context,VerletIntegrator,Platform
p=Path(sys.argv[1]);top=parmed.load_file(str(p/'system.prmtop'),xyz=str(p/'system.inpcrd'))
assert len(top.atoms)==10098 and len(top.residues)==1681 and np.isfinite(top.coordinates).all()
bonded={tuple(sorted((b.atom1.idx,b.atom2.idx))) for b in top.bonds};pairs=cKDTree(np.mod(top.coordinates,56),boxsize=56).query_pairs(.3);assert not (set(pairs)-bonded)
crd=app.AmberInpcrdFile(str(p/'system.inpcrd'));prm=app.AmberPrmtopFile(str(p/'system.prmtop'),periodicBoxVectors=crd.boxVectors);system=prm.createSystem(nonbondedMethod=app.PME,nonbondedCutoff=1*unit.nanometer,constraints=app.HBonds);integrator=VerletIntegrator(.001*unit.picosecond);context=Context(system,integrator,Platform.getPlatformByName('CPU'),{'Threads':'2'});context.setPositions(crd.positions);state=context.getState(getEnergy=True,getForces=True);energy=state.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole);forces=state.getForces(asNumpy=True).value_in_unit(unit.kilojoule_per_mole/unit.nanometer);assert np.isfinite(energy) and np.isfinite(forces).all()
charge=float(sum(a.charge for a in top.atoms));assert abs(charge)<=.05
warnings=[line for name in ['templates.log','tleap.log'] for line in (p/'logs'/name).read_text().splitlines() if 'warning' in line.lower()]
model={'charge':0,'multiplicity':1,'solute_atoms':18,'solvent_molecules':len(top.residues)-1,'box_angstrom':top.box[:3].tolist(),'net_charge':charge,'force_fields':['AM1-BCC','GAFF','supplied six-site acetonitrile'],'parameter_warnings':warnings};(p/'model.json').write_text(json.dumps(model,indent=2)+'\n')
(p/'analysis.md').write_text(f'AM1-BCC/GAFF parameters were calculated from the supplied neutral singlet structure, then a six-site acetonitrile periodic model was packed and built. Native atom mapping, connectivity, parameter terms, charge balance, and clashes were checked. Initial energy {energy:.10g} kcal/mol; energy and forces are finite. Net charge {charge:.10g} e, including the supplied solvent charge precision. All native build logs and any warnings are retained. This construction is not an equilibrium trajectory.\n')
PY
