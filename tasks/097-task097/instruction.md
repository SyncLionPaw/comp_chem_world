# Task: Pressure coefficients and the S/LB crossover

## Background

The supplied experimental peak series give shear (S) and layer-breathing (LB) frequencies versus pressure for several layer counts. Their pressure slopes and crossover depend on layer number and on how the crossover is defined.

## Task

Determine each available branch’s pressure coefficient, locate the continuous S/LB crossover, identify the first integer layer where their ordering reverses, and assess sensitivity to an alternate pressure window.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, SciPy. Do not install additional packages or fetch dependencies from the network.

Use 1–8 GPa as the primary fit interval and report the actual interval used. Refit alternate-window values from your declared finite, increasing interval. Do not impute the missing N=3 LB series. Declare the continuous-crossover method as `experimental_interpolation` or `mcm`, and provide at least six valid alternate S slopes. Slopes are in cm⁻¹ GPa⁻¹; cover S for N=2–9 and every available LB series. Follow the exact fields and 0.35 cm⁻¹ GPa⁻¹ refit tolerance in `/app/verification.md`.

The slope comparison tolerance is 0.05. The intercept and continuous crossing tolerances are 0.8 in their declared units. The slope-versus-layer-count coefficient must be above 0.02 for S and below −0.02 for LB.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Pressure-dependent shear and layer-breathing series. |
| `/app/verification.md` | Methods and output specification. |

Inputs: `/app/assets/public_s_n1_vs_p.csv`, `/app/assets/public_lb_nnminus1_vs_p.csv`, `/app/assets/data_notes.md`, and `/app/assets/conventions.md`. Submit `/app/final/results.json` and `/app/final/slope_fits.csv` under the public contract.
