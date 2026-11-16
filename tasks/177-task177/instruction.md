# Task: Compare total X-ray scattering curves

## Background

`sfac_xray_calc.csv` stores calculated total S(q), with q in nm⁻¹ (divide by 10 for Å⁻¹); `saxs_experiment.dat` gives the experimental trace in Å⁻¹ before vertical alignment. See `units.txt`.

## Task

Compare both curves over 0.5–8.0 Å⁻¹, assess their agreement, and state what the total-S(q) comparison can establish about short Li–Li chains.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Sort each curve by q, average values at duplicate q points, then linearly interpolate. Fit and add a least-squares constant vertical shift to the experimental trace. At 300 equally spaced q points including both endpoints, report the shift within 0.01 and pre- and post-shift RMSE within 0.005 of the computed values. The agreement criterion is shifted RMSE ≤0.10 (dimensionless), an operational cutoff. State the shift and derive the qualitative and structural judgments from the comparison. No plot or particular software is required.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Scattering inputs and experimental reference data. |

Inputs are under `environment/assets/`. Write `/app/final/scattering.json` with numeric `experimental_vertical_shift` (added to the experimental values), `q_min_Ainv`, `q_max_Ainv`, `rmse_unshifted`, and `rmse_shifted`; boolean `qualitative_agreement` and `total_s_uniquely_proves_short_li_chains`; and a concise scientific `rationale` about the comparison and its structural limitation.
