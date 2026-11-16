# Bias Reconstruction and Interpretation Limits for Ordinary CHA MetaD

## Background

Reconstruct bias and derivatives from two ordinary CHA metadynamics histories and native observations, examining time alignment, grid resolution and finite-time interpretation.

The two runs include HILLS deposition histories, COLVAR observations and PLUMED kernel and unit settings, together with diagnostic formulas.

## Task

Reconstruct bias and CV derivatives from two ordinary CHA MetaD histories and assess interpretation limits.

## Requirements

Actually parse native HILLS, COLVAR, and PLUMED inputs for two ordinary CHA MetaD runs. Independently reconstruct accumulated bias and CV derivatives, auditing printing/time/grid differences and free-energy interpretation limits.

- Choose increasing s grids covering hill centers and handle each run's independent timeline.
- Reconstruct three cumulative prefixes using acquired source-kernel conventions; check native CV/bias observations and quantify identifiable discrepancy sources.
- Distinguish direct-kernel reconstruction, native-grid interpolation, and finite-time -V curves. Do not infer convergence or unbiased rates without evidence.

This is ordinary MetaD, not WTMetaD. Use stored histories only; run neither PLUMED nor MD. Direct-kernel reconstruction is not bitwise native-grid replay. Self-trained CVs and equilibrium-free-energy solution are outside scope.

Actually recompute from source data without upstream simulation. Distinguish failure/ambiguity/null from numerical zero. Evidence-backed insufficiency may complete diagnosis, but disclaimers do not replace work. Retain author/DOI attribution under CC-BY-NC-SA4.0.

Justify grid spacing relative to the minimum sigma, use a refined grid to support profile and extremum claims, and report spacing-to-sigma diagnostics. Choose a spacing/minimum-width ratio in [0.1,1] and MAE or RMSE for the alignment loss; retain both histories and all three cumulative prefixes per history.

Determine grid range and minimum sigma separately for each prefix.

Reconstruct coarse and twice-refined grids spanning deposited centers and kernel support. Report both extrema, maximum interpolation difference and a global Lipschitz interpolation bound derived from source heights and widths. For each COLVAR row, use printed decimal time intervals to determine guaranteed-before and possible-through hill counts. Reconstruct bias for both orders and report every native-minus-direct residual, counts, aggregate losses, descriptive preferred alignment and residuals unexplained by either order. Do not fit a universal tolerance to erase differences or omit adverse refinement or history discrepancies.

Explain the derivation and sources and retain ordinary MetaD biasf=-1. Finite bias, correlated prefixes and two deposition histories cannot establish equilibrium free-energy surfaces, unbiased kinetics or independent confidence intervals. Keep scientific choices fixed when recomputing original and controlled perturbed data.

Network access is disabled.

- Submit the required results and evidence under `/app/` according to the listed output convention. Use `/app/analysis.py` as the analysis entry point; `/app/code` may contain optional helpers.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Bias histories, trajectory observations and run parameters. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/public/output-contract.yaml` | Required outputs and submission format. |
