# Recovery Kinetics after Acidic-Region Enhancement

## Background

FRAP recovery was measured for WT and +A2, with 12 replicate curves per condition. The Methods recovery model is rational, \(I(t)=(I_0+I_\infty t/t_{1/2})/(1+t/t_{1/2})\); its parameter is the half-time \(t_{1/2}\), not an exponential time constant \(\tau\). Baseline, plateau, weighting, fit window and model choice all affect the inferred timescale and immobile fraction.

## Task

Fit WT and +A2 independently, compare their recovery kinetics with replicate-based uncertainty, and assess how model and fit-window choices affect the comparison.

## Requirements

Use the replicate curves to characterize between-replicate variability, separately from curve-fit covariance and any published error. Do not treat time points as independent replicates. State the recovery model and equation, baseline/plateau handling, weighting, fit window, and identifiability limits. A single FRAP model does not uniquely determine microscopic diffusivity or an immobile fraction.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | FRAP summary and replicate observations. |

Inputs are in `/app/environment/assets/` (`frap.csv`, `frap_replicates.csv`). Write these deliverables under `/app/final/`:

- `fits.json`: exactly the top-level objects `WT` and `plusA2`. Each declares `family` (`rational` or `exponential`), `equation`, finite `baseline` and `plateau`, positive `timescale_s`, `time_parameter` (`t_half` for rational, `tau` for exponential), an ordered `window_s=[low,high]` containing at least four summary points, `weighting`, `unweighted_sse`, and a nonempty `uncertainty` describing replicate and model uncertainty. `unweighted_sse` is the unweighted squared residual of the summary means over the declared window.
- `fitted_curves.csv`: columns `time_s,WT_observed,WT_fitted,plusA2_observed,plusA2_fitted`; one row per input summary time; observed values are the input means; fitted values follow the declared model at every time, including times outside the fit window.
- `report.md`: recovery times with uncertainty; rational \(t_{1/2}\) versus exponential \(\tau\) (with \(t_{1/2}=\ln 2\,\tau\)); model, baseline and identifiability limits; between-replicate versus curve-fit versus published uncertainty.
- `analysis.py`: deterministic, reproducible analysis. It must accept `--input-dir` and `--output-dir`, read the two CSVs from the input directory, write the other outputs, and document methods, windows and uncertainty.

`analysis.py` must run under the container's provided Python using only its preinstalled packages (NumPy, SciPy, matplotlib). The analysis must be self-contained and require no additional packages, network access, or alternative interpreter.

Avoid NaN/Infinity and place only these four files in `/app/final/`.
