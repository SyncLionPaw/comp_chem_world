#!/bin/sh
set -eu
app=${APP:-/app}
input=${INPUT_DIR:-$app/inputs}
output=$app/final
mkdir -p "$output"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
cat > "$work/repair.py" <<'ORACLE_PY'
"""Independent real repair/reference execution; no evaluator import."""
from pathlib import Path
import argparse,json,csv,shutil
import numpy as np,openmm as mm
from openmm import app,unit
from scipy.io import netcdf_file
p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path);p.add_argument('--output-dir',type=Path);a=p.parse_args();out=a.output_dir;out.mkdir(parents=True,exist_ok=True)
system=mm.XmlSerializer.deserialize((a.input_dir/'faulty-system.xml').read_text())
integrator=mm.XmlSerializer.deserialize((a.input_dir/'faulty-integrator.xml').read_text());original_dt=integrator.getStepSize().value_in_unit(unit.femtosecond)
trace=json.loads((a.input_dir/'failed-trace.json').read_text())['records'][-1]
assert system.getNumConstraints()==0 and original_dt>5 and abs(trace['potential_kcal_mol'])>1e12,'Inspect different failure before applying this reference repair'
integrator.setStepSize(.001*unit.picoseconds)
context=mm.Context(system,integrator,mm.Platform.getPlatformByName('CPU'),{'Threads':'4'})
initial=mm.XmlSerializer.deserialize((a.input_dir/'last-good-state.xml').read_text());context.setState(initial)
(out/'restart-before.xml').write_text(mm.XmlSerializer.serialize(context.getState(getPositions=True,getVelocities=True,getEnergy=True)))
(out/'system.xml').write_text(mm.XmlSerializer.serialize(system));(out/'integrator.xml').write_text(mm.XmlSerializer.serialize(integrator))
diagnosis={'failure_class':'numerical_integration','unstable_parameter':'timestep_fs','unconstrained_hydrogen_motion':system.getNumConstraints()==0,'failure_step':trace['step'],'failure_time_ps':trace['time_ps'],'failure_potential_kcal_mol':trace['potential_kcal_mol'],'last_good_potential_kcal_mol':initial.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole),'rejected_alternatives':[{'category':'parameterization','evidence':'The same complete force field and saved state have finite native potential energy before propagation; no parameter replacement is needed.'},{'category':'electronic_structure','evidence':'Native System and Langevin integrator describe classical force-field dynamics; no SCF or quantum electronic solve occurs in this failed propagation.'}]}
(out/'repair.json').write_text(json.dumps({'diagnosis':diagnosis,'equilibrium_claim':False,'validation_scope':'numerical_recovery_only','root_causes':['An oversized timestep resolves unconstrained hydrogen stretches inadequately and produces rapid energy divergence.'],'original_timestep_fs':original_dt,'corrected_timestep_fs':1,'constraints':'none','allowed_changes':['timestep_fs'],'resume_time_ps':0,'production_ps':2,'method':'resume saved positions/velocities with stable timestep; no rethermalization'},indent=2)+'\n')
f=netcdf_file(str(out/'recovered.nc'),'w')
for d,n in [('frame',None),('atom',system.getNumParticles()),('spatial',3),('cell_spatial',3)]:f.createDimension(d,n)
x=f.createVariable('coordinates','f',('frame','atom','spatial'));x.units='angstrom';t=f.createVariable('time','d',('frame',));t.units='picosecond';box=f.createVariable('cell_lengths','d',('frame','cell_spatial'));box.units='angstrom'
log=(out/'native.csv').open('w');writer=csv.DictWriter(log,fieldnames=['step','time_ps','potential_kcal_mol','kinetic_kcal_mol','temperature_K']);writer.writeheader();dof=3*system.getNumParticles()-system.getNumConstraints()-3
for i in range(11):
 if i:integrator.step(200)
 state=context.getState(getPositions=True,getVelocities=True,getEnergy=True);potential=state.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole);kinetic=state.getKineticEnergy().value_in_unit(unit.kilocalorie_per_mole)
 assert np.isfinite(potential+kinetic) and abs(potential)<1e10
 x[i]=state.getPositions(asNumpy=True).value_in_unit(unit.angstrom);t[i]=state.getTime().value_in_unit(unit.picosecond);box[i]=np.diag(np.asarray(state.getPeriodicBoxVectors().value_in_unit(unit.angstrom)))
 writer.writerow({'step':i*200,'time_ps':float(t[i]),'potential_kcal_mol':potential,'kinetic_kcal_mol':kinetic,'temperature_K':2*kinetic/(dof*.00198720425864083)});log.flush();f.flush()
f.close();log.close();(out/'final-state.xml').write_text(mm.XmlSerializer.serialize(state));(out/'repair.log').write_text('OpenMM 8.6.1 native real recovery: 2000 steps of 1 fs completed; finite energy/positions/velocities.\n')
(out/'analysis.md').write_text('原故障为无氢键约束条件下使用 20 fs 步长；仅将步长改为 1 fs，从已保存位置和速度续跑 2 ps。短恢复验证不能证明平衡采样。\n')
shutil.copyfile(__file__,out/'repair.py')
print('Real recovery complete: 2 ps from last saved state.')
ORACLE_PY
cp "$work/repair.py" "$output/repair.py"
python3 "$work/repair.py" --input-dir "$input" --output-dir "$output"
