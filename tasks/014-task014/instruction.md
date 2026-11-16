# Fit RESP charges for a naphthalene radical cation from supplied geometry and ESP grids

## Background
RESP fits atom-centred charges to an electrostatic potential. Fit the supplied naphthalene radical-cation geometry and ESP grid; no new electronic-structure calculation is needed.

## Task
Fit and validate RESP charges.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Use charge +1 and doublet multiplicity. Confirm the ESP coordinates match the XYZ order (ten C, then eight H). ESP coordinates are bohr and potentials hartree/e. Minimize J(q)=Σk[(Aq)k−Vk]²+0.0005Σi=0..9(√(qi²+0.1²)−0.1), Aki=1/rki, subject to Σqi=1; restrain only carbon. Document optimizer/convergence, state, units and mapping. Preserve atom order, charge to 1e-6 e, and recompute objective/RMSE. Read supplied XYZ/ESP; write charges.json, fit-input.json, actual fit.log, runnable fit.py and analysis.md in /app/final/. Public /app/output-contract.yaml defines fields/units/tolerances. CLI must reproduce the fit in a clean directory using only supplied inputs, code and installed libraries.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Geometry and electrostatic potential data. |
| `/app/output-contract.yaml` | Output format and evidence requirements. |

| Path | Contents |
| --- | --- |
| `/app/final/charges.json` | Fitted charges |
| `/app/final/fit-input.json` | Fit inputs and settings |
| `/app/final/fit.log` | Native fit log |
| `/app/final/fit.py` | Runnable fit code |
| `/app/final/analysis.md` | Analysis report |
