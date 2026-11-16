# Task: Optimise SMILES-specified molecular structures with GFN2-xTB

## Background

GFN2-xTB is a tight-binding semi-empirical method that gives molecular geometries close
to DFT at a small fraction of the cost, which makes it a standard first step for
structure preparation. A geometry is considered converged once the largest atomic force
norm falls below a chosen threshold.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Optimize the molecular geometry of phenol, whose SMILES is `OC1=CC=CC=C1`, with
GFN2-xTB and save the final structure.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, NumPy, RDKit, SciPy, tblite. Do not install additional packages or fetch dependencies from the network.

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
| `/app/environment/assets/inputs.json` | Packaged molecular or reaction inputs. |

Write the optimized structure to `/app/final/out.xyz` in standard XYZ format.
