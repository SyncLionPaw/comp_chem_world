# Task: Compare catalytic geometry across assembly and ligand/protonation conditions

## Background

Inputs are `/app/assets/Fig_9a.dat` and `/app/assets/data_dictionary.md`. The data contain per-frame δ/γ measurements for WT and V72I under the single-ring S, D-AspAsh, and D-ADP-Pi conditions. In D-ADP-Pi, Asp397 is protonated and ATP is replaced by ADP and HPO₄²⁻. Follow the dictionary exactly for mapping systems, columns, and units; in the final panel, column 11 is γ and column 12 is δ, opposite to the column order in the other panels.

The data are pooled frame measurements without replicate labels or a time axis. Describe the empirical distributions and their limitations; do not treat frames as independent replicates or make unsupported claims of statistical significance.

## Task

Compare the distributions of δ (Å) and γ (degrees) for WT and V72I under all three conditions to characterize catalytic-pocket geometry and apical-domain motion after ATP cleavage. Use the data to determine the direction and magnitude of changes; the task does not presuppose the direction of pocket or apical-domain changes.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas. Do not install additional packages or fetch dependencies from the network.

The report must explain the structured comparison, pocket-distance and apical-angle changes, distance relative to S, and the uncertainty and sampling limitations of pooled-frame data. Use the data dictionary for units and panel/column mappings.

### Input and deliverable details

`findings.json` must strictly use `post-hydrolysis/v1`, with top-level keys only `schema_version,summary_statistics,statistical_methods,comparisons,return_toward_S,uncertainty`. `summary_statistics` must contain exactly 12 condition × variant × observable records, each containing only `condition,variant,observable,n,mean,std,median,q25,q75`; `std` is the sample standard deviation. `statistical_methods` must be a non-empty array of strings.

`comparisons` must contain exactly four WT/V72I × δ/γ comparisons, each containing only `variant,observable,baseline,target,location_statistic,effect,units,conclusion`. `baseline` is `D-AspAsh`; `target` is `D-ADP-Pi`; `location_statistic` may be `mean` or `median`; `effect` is target minus baseline; units are `angstrom` and `degree`, respectively. If the effect is greater than 2e-6, `conclusion` must be `increased`; if less than -2e-6, it must be `decreased`; otherwise it must be `inconclusive`.

`return_toward_S` must contain exactly one item each for WT and V72I, with each item containing only `variant,location_statistic,baseline_condition,target_condition,reference_condition,before_distance,after_distance,units,closer_to_S`. The conditions are respectively `D-AspAsh`, `D-ADP-Pi`, and `S`; units are `angstrom`; `location_statistic` must match that variant's δ comparison. The two distances are the absolute differences between the δ statistic for each condition and the δ statistic for S. `closer_to_S` is `true` only when `after_distance < before_distance`. These definitions do not presuppose the result.

`uncertainty` must contain only `approach,independent_sampling_claim,series_spread,applicability,limitations`. For descriptive analysis, use `approach: descriptive`, `independent_sampling_claim: false`, and `applicability: pooled_empirical_data`. `series_spread` must contain exactly 12 items, each with only `condition,variant,observable,q25,q75`. `limitations` must be a non-empty string or non-empty array of strings that explicitly discloses the absence of independent replicate labels/identifiers and a time axis. Interquartile ranges describe per-frame empirical distributions; they are not confidence intervals. If an inferential method is used, its results require human review; do not treat the frame count as the number of independent samples. Calculate machine-readable values from unrounded data and retain full precision; the report may round moderately for readability.

Submit `findings.json` and `report.md` in `final/`. The JSON must fully satisfy the fields, record counts, comparison definitions, and data limitations above; the report must explain the numerical results rather than substitute prose for structured conclusions.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/Fig_9a.dat` | Supplied scientific input or resource; see the task requirements for format and units. |
| `/app/assets/data_dictionary.md` | Supplied data, parameters or method documentation; see the task requirements. |

| Path | Contents |
| --- | --- |
| `/app/final/findings.json` | Matched comparisons and descriptive statistics |
| `/app/final/report.md` | Scientific interpretation |
