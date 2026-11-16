# Task: Write an optimised structure to a molecule-specific coordinate file

## Background

Optimized structures are exchanged as coordinate files. This task mirrors the standard
practice of naming each result after the molecule it describes rather than using a
generic file name.

## Task

Optimize the molecular geometry of toluene with GFN2-xTB and save the final structure in
a file named after the molecule.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, NumPy, RDKit, SciPy, tblite. Do not install additional packages or fetch dependencies from the network.

- Obtain the compound's SMILES from the name-to-SMILES lookup table shipped with this
  task.
- Add explicit hydrogens with `Chem.AddHs`, then embed one conformer with
  `AllChem.EmbedMolecule(mol, randomSeed=42)`. Keep the remaining settings at their defaults.
- Pre-optimize with `AllChem.MMFFOptimizeMolecule(mol)` using default settings.
- Optimize with default ASE BFGS settings using the GFN2-xTB calculator (`tblite`) and a force convergence
  criterion of `fmax = 0.02` eV/Å.
- Preserve the atom order and Cartesian frame produced by this workflow in the XYZ file. Coordinates are compared componentwise in Å with
  absolute tolerance 0.001 Å and relative tolerance 0.00001.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/name_lookup.json` | Name-to-SMILES lookup table. |

Read the name-to-SMILES lookup table at `/app/environment/assets/name_lookup.json`.

Write the optimized structure to `/app/final/toluene.xyz` in standard XYZ format.
