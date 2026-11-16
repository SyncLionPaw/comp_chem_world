# Task: Calculate vibrational frequencies for SMILES-specified molecules

## Background

Vibrational frequencies follow from the curvature of the potential energy surface at a
minimum. A numerical Hessian evaluated at an optimized geometry gives the normal-mode
frequencies, of which a nonlinear molecule has 3N-6 genuine vibrational modes.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Compute the vibrational frequencies of formaldehyde, whose SMILES is `C=O`, with
GFN2-xTB.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, NumPy, RDKit, SciPy, tblite. Do not install additional packages or fetch dependencies from the network.

- Optimize the geometry first: add explicit hydrogens in RDKit, embed with random seed 42, then use MMFF pre-optimization,
  followed by GFN2-xTB (`tblite`) minimization via ASE `BFGS` to `fmax = 0.02` eV/Å.
- Run a numerical Hessian (`ase.vibrations.Vibrations`) at the optimized geometry.
- Report only the genuine vibrational modes (3N-6 = 6 for formaldehyde), in cm⁻¹,
  sorted from lowest to highest.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/inputs.json` | Packaged molecular or reaction inputs. |

Write the frequencies as a JSON list to `/app/final/frequencies.json`. Each frequency must agree within 5 cm⁻¹.
