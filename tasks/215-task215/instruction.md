# Deposited MD protocol: restraint Hamiltonian response and restart dependencies

## Background

Analyse deposited equilibration restraint protocols using static diagnostics.

The deposited archive supplies coordinates, protocols and EVB inputs.

## Task

Analyse deposited equilibration restraint protocols using static diagnostics, and calculate and interpret the quantities specified below and in the public contract.

## Requirements

- Use all five systems and all nine stages, deriving masks, controls and dependencies from deposited topology, coordinates, README and namelists.
- Exclude only WAT and Na+ from solute and use topology masses.
- At a fixed deposited Cartesian reference without wrapping, minimum images or alignment, evaluate all-atom translation (0.10,−0.20,0.05) Å, solute rotation +1° about its mass-centred z axis, and solute translation by full cell vector a.
- Use E=kΣ|r−r_ref|² without 1/2, k in kcal mol⁻¹ Å⁻²; report energy, net force and maximum atom force, plus E(eqnpt)−E(npt4) at identical diagnostic coordinates.
- Unrestrained counts/forces/energies are zero.
- MD duration=nstlim*dt; scheduled writes=floor(nstlim/ntwx).
- This static diagnostic provides no MD convergence or production-readiness claim.
- Finite numbers require absolute or relative agreement 1e-7.
- Do not fetch external scientific data.

- Submit the required artifacts according to the listed output contract.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Structures, calculation records and reference data. |
| `/app/inputs/output-contract.json` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
