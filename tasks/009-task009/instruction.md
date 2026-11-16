# Hydrogen-induced stacking-fault response and finite-area uncertainty

## Background

Supplied unstable stacking-fault data give 18 mean/spread anchors for six alloys at three H coverages, from nine SQS configurations at 108 Å². Raw configurations, the source ddof convention and cross-coverage covariance are unavailable.

## Task

Quantify coverage response and uncertainty, transfer physical fluctuations to finite nucleation areas, and assess which hardening, curvature and alloy-ranking conclusions follow under stated assumptions.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

- For every alloy calculate three coverage increments and curvature. Preserve both ddof interpretations, assume/state n=9, and calculate contrast variance `aᵀCov a`, including independent and admissible PSD covariance bounds.
- Separate ensemble spread, mean-estimation SE and ±0.5 mJ/m² source precision. Give conditional normal 95% intervals, not exact finite-sample guarantees. Do not invent raw samples or bootstrap replicates.
- At each coverage assess five adjacent ranks and all 15 alloy pairs under both ddof conventions. Separate descriptive mean ranking from signs robust to worst-case covariance and rounding; missing covariance does not automatically make every pair undecidable.
- Transfer physical spread—not mean-estimation uncertainty—to 30/50/70/108 Å² with `sigma_A=sigma_108*sqrt(108/A)`. Report Gaussian 5th/50th/95th quantiles and nonpositive probabilities without clipping negative tails. This is conditional model extrapolation, not new DFT evidence.
- Distinguish SQS configurations from displacement-path images and mJ/m² from J/m². Execute and document the analysis.
- Use `/app/assets/gamma_usf_fig2c_parameters.csv`, its source record and `task09_task_spec.json`. In `/app/final/`, provide the specified `response.csv`, `area_transport.csv`, `ranking.csv`, `inference.json`, executable `calculation_source.py` and run metadata. Preserve 48 response, 72 area, 30 adjacent-rank and 90 all-pair entries; report assumptions and uncertainties in your own words. Keep existing schema/provenance records and unit conventions.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Alloy data, source records and task conventions. |

Inputs and full grid/output contract are under `/app/assets/`; results go in `/app/final/`.
