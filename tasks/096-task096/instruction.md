# Task: Fit ambient MCM interlayer force constants

## Background

The supplied ambient Raman series for few-layer MoS₂ follow `ω_N = ω_bulk sin[(N−1)π/(2N)]`. The target branches are the highest shear mode (`S_N1`) and highest layer-breathing mode (`LB_highest`).

## Task

Fit each branch’s bulk-limit frequency from the labeled layer series and convert it to an interlayer force constant using the supplied areal reduced mass.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, SciPy. Do not install additional packages or fetch dependencies from the network.

Use frequencies in cm⁻¹ and `alpha` in 10¹⁹ N m⁻³. Each fit must reproduce its series with RMS error ≤1.5 cm⁻¹; Both fitted constants must be positive and satisfy the frequency–mass identity within 4%; compare their magnitudes. The N=16 bulk-shear reference is optional. Follow the exact fields and fit-table coverage in `/app/verification.md`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Ambient-pressure shear and layer-breathing series. |
| `/app/verification.md` | Methods and output specification. |

Inputs: `/app/assets/ambient_s_lb_series.csv` and `/app/assets/conventions.md` (branch definitions, mass and units). Submit `/app/final/results.json` and `/app/final/fit_table.csv` as specified in the public contract.
