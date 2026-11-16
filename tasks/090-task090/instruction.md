# Task: Compute hydration pressure with the variational boundary and frozen roughness average

## Background

The public input `/app/assets/model_constants.json` fixes the kernel, surface polarization, energy density, pressure conversion, and roughness convention. The boundary data are antisymmetric Dirichlet polarization values, and the natural condition at both ends is `P1''=0` — not `P1'=0`. The supplied source’s Eq. 16 surface-bound charge (`P1'=-rho_b`) is not part of this task. Pressure follows from the input `energy_code` as `Pi = -d/dL_A (integral energy_code dz_A) / eps0`, with `z` in Å and polarization in C/m².

## Task

Compute the sharp pressure curve and the task-defined roughness average of it. The roughness uses the task's Gaussian, not the supplied source’s Eq. 19 convention: each surface displacement is supported on `[0,L/2]`, centered at 0, with density `exp(-x^2/(2 sigma^2))` and `sigma=1.25 Å`. The input value `2.5 Å` is `2*sigma`, not the supplied source’s roughness width.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include matplotlib, MDAnalysis, NumPy, pillow, SciPy. Do not install additional packages or fetch dependencies from the network.

- Sharp curve `final/force_sharp.csv` (columns `L_A,Pi_Pa`): 2–20 Å, spacing at most 0.08 Å. Smeared curve `final/force_smeared.csv`: 5–20 Å with the specified `sigma`, spacing at most 0.11 Å. Both need at least 100 finite rows with strictly increasing `L_A`.
- Discard roughness samples with film thickness below `0.40 Å`, renormalize the rest, and evaluate the sharp pressure at each retained separation down to 0.40 Å — do not substitute `Pi(2 Å)`. The public sharp curve starts at 2 Å, but the internal integration table must reach 0.40 Å.
- `final/analysis.json` with finite numeric fields `lambda_d1_A`, `lambda_o_A`, `lambda_d2_A`, `oscillation_period_A`, `sharp_sign_changes_4_20`, `smeared_sign_changes_5_20`, `smeared_sign_changes_10_20`, `film_floor_A` (0.40), `task_two_sigma_A` (2.5), `internal_sharp_start_A` (0.40).
- Sign counts: use the delivered curve samples in the named inclusive interval, drop exact zeros, count sign changes between consecutive remaining samples. `oscillation_period_A`: from the delivered sharp samples with `L_A` in `[4,16] Å`, take interior samples where the product of adjacent pressure differences is negative (no interpolation or fitting, at least three extrema) and report twice the median of successive extremum spacings.
- The `lambda_*_A` values are kernel pole diagnostics implied by the fixed public input: `lambda_d1_A` the decay length of the oscillatory conjugate-pole mode, `lambda_o_A` its wavelength, `lambda_d2_A` the decay length of the monotone pole; here `lambda_d1_A < lambda_d2_A`. Each is checked with an absolute tolerance of 0.08 Å.
- `final/solver.log` reports four diagnostics as `field value` lines, finite and nonnegative: `max_boundary_residual` (at most 1e-8), `pressure_step_relative_change_at_0.40A` and `quadrature_relative_change_at_0.40A` (at most 1e-5 each), and `energy_reproducibility_residual_at_8A`.

The sharp and smeared curves are compared against independently recomputed references over their full ranges, and the pole lengths, sign counts, period, and physical conventions are checked from the delivered data — the log alone is not treated as proof.

### Input and deliverable details

- Input: `/app/assets/model_constants.json`
- Outputs: `final/force_sharp.csv`, `final/force_smeared.csv`, `final/analysis.json`, `final/solver.log`

Across the full grid, the maximum absolute deviation normalized by the reference peak magnitude must not exceed 0.012 for the sharp curve or 0.015 for the smeared curve. Require at least six sign changes for the sharp curve over 4–20 Å, with period 2.10 ± 0.30 Å, and no sign changes for the smeared curve over 10–20 Å.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/model_constants.json` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
