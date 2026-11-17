# Charge-dependent Au adsorbate energies

## Background

The inputs provide the charge grid and transcribed Supplementary Table 6 energy parameters, alongside the source article, supplement and text layer.

## Task

Reconstruct the 16 quadratic charge-energy models at all six charges, compare adsorbates and audit six reference-state corrections.

## Requirements

Retain all 16 rows including dagger rows, applying a_displayed_times_1e-2 and b_displayed_times_1e-4. At −40,−30,−20,−10,0,10 microC/cm2 compute E=E0+a*sigma+b*sigma² and dE/dsigma=a+2*b*sigma: 96 rows, energies 8 decimals and derivatives 10. Compare Au(211),3x3,BEEF-vdW,fitPt. Record six corrections with signs, targets, sources and tri-state inclusion; do not invent total free energies or interpret frozen geometry as relaxed DFT validation. No DFT, NEB, fitting or constant-potential calculation.

Follow the listed output convention for the required fields and scientific criteria.

The output contract specifies unresolved-input entries and permits source-backed limitations in the required structured claim assessments.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Charge grid, energy parameters and source material. |
| `/opt/co2-public/output-contract.md` | Required outputs and submission format. |
| `/app/` | Submitted results and required execution evidence. |
