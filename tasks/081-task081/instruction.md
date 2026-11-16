# Task: Analyze historical excited-state geometry results

## Background

ADMM and simplified response kernels can alter optimized excited-state geometries. The package contains the original public CP2K inputs, outputs and trajectories for 26 method/molecule routes, plus a public route inventory and an output-format contract.

## Task

For formaldehyde (M2), thioformaldehyde (M3), formyl chloride (M14), acetaldehyde (M19) and pyrazine (M29), reconstruct the reference geometry comparisons from the archived native optimizer records and the matching reference geometry data. Assess the 36 non-null excited-state bond targets with the empirical 3.0 pm interval rule; recompute the 13 paired PBE0/ADMM bond differences; and classify the M14 default `aEX=0.2` result from native evidence, separately evaluating its three `aEX=0.25` remedy bonds. Exclude M14 default null targets from numeric comparisons.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, pandas, pillow. Do not install additional packages or fetch dependencies from the network.

Select each optimizer endpoint using native output/trajectory evidence and explain the closure check. Compute matched Cartesian bond distances in pm, averaging symmetry-equivalent bonds; apply the frozen 3.0 pm interval rule to unrounded coordinates with the specified reference-value and coordinate-precision uncertainty. Distinguish physical dissociation from launch, execution, memory and ordinary convergence failures. Do not run CP2K or claim fresh execution, minimum, stationarity or positive curvature.

The public format specification `/app/inputs/case06-v5-agent-historical-results-contract-v1.json` defines exact deliverable fields, row identities, reference mapping, coordinate order, tolerances, classifications and report requirements. `/app/inputs/case06-v5-public-native-source-manifest-v1.json` maps the 26 routes to pinned source files; neither contains results. State that historical launcher, stderr, scheduler and allocation metadata are unavailable, and preserve the frozen manifests.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/public-source/` | Archived optimization records. |
| `/app/inputs/case06-v5-agent-historical-results-contract-v1.json` | Analysis and submission conventions. |

Use original archive members under `/app/inputs/public-source/` and the supplied documentation. Submit `provenance.json`, `comparison.csv`, `scientific-summary.json` and `report.md` under `/app/final/`. The report must cover the 26 routes, 36 comparisons, 13 paired differences, M14 default/remedy findings and historical evidence limits.
