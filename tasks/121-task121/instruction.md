# Task: Generate reproducible three-dimensional structures from molecular names

## Background

A SMILES string fixes connectivity but not geometry. Generating a three-dimensional
structure is the starting point for any subsequent energy or property calculation, and a
fixed embedding seed makes the resulting conformer reproducible.

## Task

Generate the three-dimensional atomic coordinates of ethanol and save the structure in
standard XYZ format.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, NumPy, RDKit. Do not install additional packages or fetch dependencies from the network.

- Obtain the compound's SMILES from the name-to-SMILES lookup table shipped with this
  task.
- Add explicit hydrogens with `Chem.AddHs`, then embed one conformer with
  `AllChem.EmbedMolecule(mol, randomSeed=42)`. Keep the remaining settings at their defaults.
- Do not run any further geometry optimization on the embedded structure.
- Preserve the atom order and Cartesian frame produced by this workflow in the XYZ file. Coordinates are compared componentwise in Å with
  absolute tolerance 0.001 Å and relative tolerance 0.00001.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/name_lookup.json` | Name-to-SMILES lookup table. |

Read the name-to-SMILES lookup table at `/app/environment/assets/name_lookup.json`.

Write the structure to `/app/final/out.xyz` in standard XYZ format.
