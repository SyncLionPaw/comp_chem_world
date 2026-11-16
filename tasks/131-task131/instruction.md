# Task: Compute reaction enthalpies from consistent species-level calculations

## Background

The enthalpy of a gas-phase reaction follows from the enthalpies of its separated
species. Each species contributes its electronic energy plus a thermal correction
evaluated from its own vibrational analysis, and the molecular symmetry, geometry class
and spin state enter that correction explicitly — molecular oxygen, in particular, is
a triplet whose multiplicity must be passed to the calculator.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

For the reaction CH₄ + 2 O₂ → CO₂ + 2 H₂O, compute the reaction enthalpy at 298.15 K
with GFN2-xTB.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, NumPy, RDKit, SciPy, tblite. Do not install additional packages or fetch dependencies from the network.

- For each of the four species, build the reference geometry with
  `ase.build.molecule(name)`, then optimize it with GFN2-xTB (`tblite`) via ASE `BFGS`
  to `fmax = 0.02` eV/Å.
- Run a vibrational analysis (`ase.vibrations.Vibrations`) and evaluate
  `ase.thermochemistry.IdealGasThermo` from the electronic plus vibrational energies to
  obtain each species' enthalpy at 298.15 K.
- Use these parameters per species: CH₄ (`geometry="nonlinear"`, `symmetrynumber=12`,
  `spin=0`); O₂ (`geometry="linear"`, `symmetrynumber=2`, `spin=1`, triplet — pass
  `multiplicity=3` to the calculator); CO₂ (`geometry="linear"`, `symmetrynumber=2`,
  `spin=0`); H₂O (`geometry="nonlinear"`, `symmetrynumber=2`, `spin=0`).
- Combine the species enthalpies as
  ΔH = [H(CO₂) + 2·H(H₂O)] − [H(CH₄) + 2·H(O₂)].

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/inputs.json` | Packaged molecular or reaction inputs. |

Write the result as JSON to `/app/final/reaction.json`: an object with the single key
  `reaction_enthalpy_eV` whose value is the reaction enthalpy in eV. The absolute error must be below 0.02 eV.
