# Diagnose and recover a failed propagation without changing the underlying physical model

## Background
A molecular model, integrator, last reliable state and failure record are supplied. Diagnose from native evidence without changing the physical model.

## Task
Explain instability, repair the numerical propagation conservatively, and continue 2 ps from saved state.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Relate failure to propagation, last-good state and constraints; assess parameterization, electronic-state, thermostat and restart alternatives. Choose timestep (0,1] fs. Preserve force field, masses, charges, constraints, periodic box and all other integrator/thermostat settings; only additional permitted change is stochastic seed. Report changes; do not re-thermalize/delete particles. Resume at time 0 and run 2 ps; retain ≥11 frames with unchanged mapping/box. Report coordinates/box Å, time ps, energies kcal/mol, temperature K. Check trajectory/steps/energies/temperature/end positions and velocities for consistency; retain actual logs. Numerical recovery is not equilibrium. Read supplied model/integrator/checkpoint/failure evidence; submit repair.json, analysis.md, repair.py/log, system.xml, integrator.xml, restart-before.xml, final-state.xml, recovered.nc, native.csv. Public contract defines field/native-data requirements/tolerances; CLI must recover in a clean directory.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Model and native failure evidence. |
| `/app/output-contract.yaml` | Output format and evidence requirements. |

/app/inputs/: model and failure evidence; /app/output-contract.yaml: schema; /app/final/: recovery artifacts.
