# Task: Convert molecular names into canonical SMILES

## Background

Different cheminformatics tools can write the same molecule in different ways, so
comparing structures across databases requires a canonical form. RDKit defines a
canonical SMILES that is unique for a given molecule.

## Task

Determine the canonical SMILES of 2-acetoxybenzoic acid (aspirin).

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, RDKit. Do not install additional packages or fetch dependencies from the network.

- Obtain the compound's SMILES from the name-to-SMILES lookup table shipped with this
  task; do not rely on a memorized structure.
- Report the SMILES in the canonical form produced by RDKit: parse the string and
  re-serialize it with RDKit's canonical writer.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/name_lookup.json` | Name-to-SMILES lookup table. |

Read the name-to-SMILES lookup table at `/app/environment/assets/name_lookup.json`.

Write the canonical SMILES to `/app/final/smiles.txt`.
