# Dynamical Regimes from Mean-Squared Displacement

## Background

The supplied `msd.csv` contains mean MSD versus scaled time \(t/t_D\) for PD, the A0/A1/A2 acidic tracts, and rpL5, with \(t_D=100\) ps and MSD in Å². The curves are averages over molecules; they do not provide independent replicate uncertainty or per-molecule distributions.

## Task

Estimate early- and late-time power laws for each species, determine whether the mean curves support distinct dynamical regimes, and test how fit-window and objective choices affect the exponents.

## Requirements

State and justify the early/late fit windows, the objective, and the crossover or regime choice. Use unweighted ordinary least squares in natural-log space: \(\ln \mathrm{MSD} = \ln A + n\ln(t/t_D)\), with `exponent = n`, `amplitude_A2 = A`, and `log_residual_sse` the sum of squared log residuals. Each window must contain at least three positive-MSD points. Provide alternate-window sensitivity fits. Distinguish temporal changes in the mean curve from molecule-level heterogeneity; do not infer independent replicate errors, bimodality, or a unique microscopic mechanism from averaged MSD.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/msd.csv` | Mean-square displacement data. |

Input is `/app/environment/assets/msd.csv`. Write these deliverables under `/app/final/`:

- `exponents.json`: `t_D_ps = 100`, `msd_unit = "angstrom_squared"`, and a `species` object for exactly `PD`, `A0`, `A1`, `A2`, `rpL5`. Each species has exactly `early` and `late`. Each primary fit declares `objective` (`log_ols` or a justified alternative), an ordered `window_t_over_tD=[low,high]`, `exponent`, `amplitude_A2` (Å²), `log_residual_sse`, and a nonempty `sensitivity` list of alternate fits with `window_t_over_tD`, `exponent`, `amplitude_A2`, `log_residual_sse`.
- `fits.csv`: columns `species,t_over_tD,observed_MSD,fitted_MSD,regime`; one row for every positive-MSD input bin inside each primary window, for all five species and both regimes. `observed_MSD` is the raw mean; `fitted_MSD = amplitude_A2*(t/t_D)^exponent`.
- `report.md`: data convention, method, primary and alternate windows, regime interpretation, window sensitivity, and the distinction between mean-curve behavior and per-molecule heterogeneity or replicate uncertainty.
- `analysis.py`: deterministic, reproducible analysis. It must accept `--input-dir` and `--output-dir`, read `msd.csv` from the input directory, write the other outputs, and document methods, windows and uncertainty.

Use full precision; avoid NaN/Infinity. Place only these four files in `/app/final/`.

`analysis.py` must run under the container's provided Python using only its preinstalled packages (NumPy, SciPy, matplotlib). The analysis must be self-contained and require no additional packages, network access, or alternative interpreter.
