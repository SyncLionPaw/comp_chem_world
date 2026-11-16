# Task: Compute molecular thermochemistry with consistent symmetry and spin conventions

## Background

The Gibbs free energy of a molecule combines its electronic energy with the
translational, rotational and vibrational contributions of an ideal gas. `ase`'s
`IdealGasThermo` evaluates those contributions from a vibrational analysis and the
molecular symmetry, so the geometry class, symmetry number and spin state must be
supplied explicitly.

## Task

Compute the Gibbs free energy of ammonia at 298.15 K and 1 atm with GFN2-xTB.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, NumPy, RDKit, SciPy, tblite. Do not install additional packages or fetch dependencies from the network.

- Obtain the compound's SMILES from the name-to-SMILES lookup table shipped with this
  task.
- Optimize the geometry first: add explicit hydrogens in RDKit, embed with random seed 42, then use MMFF pre-optimization,
  followed by GFN2-xTB (`tblite`) minimization via ASE `BFGS` to `fmax = 0.02` eV/Å.
- Run a vibrational analysis (`ase.vibrations.Vibrations`), then evaluate
  `ase.thermochemistry.IdealGasThermo` at 298.15 K and 101325 Pa from the electronic energy and the vibrational
  energies with `geometry="nonlinear"`, `symmetrynumber=3`, `spin=0`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/name_lookup.json` | Name-to-SMILES lookup table. |

Read the name-to-SMILES lookup table at `/app/environment/assets/name_lookup.json`.

Write the result as JSON to `/app/final/thermo.json`, in eV, using the key
  `gibbs_free_energy_eV`. The absolute error must be below 0.01 eV.
