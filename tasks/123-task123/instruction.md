# Task: Calculate molecular vibrational frequencies from a Hessian

## Background

Vibrational frequencies follow from the curvature of the potential energy surface at a
minimum. A numerical Hessian evaluated at an optimized geometry gives the normal-mode
frequencies, of which a nonlinear molecule has 3N-6 genuine vibrational modes.

## Task

Compute the vibrational frequencies of water with GFN2-xTB.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, NumPy, RDKit, SciPy, tblite. Do not install additional packages or fetch dependencies from the network.

- Obtain the compound's SMILES from the name-to-SMILES lookup table shipped with this
  task.
- Optimize the geometry first: add explicit hydrogens in RDKit, embed with random seed 42, then use MMFF pre-optimization,
  followed by GFN2-xTB (`tblite`) minimization via ASE `BFGS` to `fmax = 0.02` eV/Å.
- Run a numerical Hessian (`ase.vibrations.Vibrations`) at the optimized geometry.
- Report only the genuine vibrational modes (3N-6 for water), in cm⁻¹, sorted from
  lowest to highest.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/name_lookup.json` | Name-to-SMILES lookup table. |

Read the name-to-SMILES lookup table at `/app/environment/assets/name_lookup.json`.

Write the frequencies as a JSON list to `/app/final/frequencies.json`. Each frequency must agree within 5 cm⁻¹.
