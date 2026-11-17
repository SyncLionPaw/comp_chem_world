# Proton-hop path calculations under the supplied NNP

## Background

Proton-transfer barriers depend on endpoint relaxation and path discretization. The supplied O1 and O4 endpoint structures and SiAlOH1 neural-network potential support a proton-transfer calculation in dry FAU zeolite.

## Task

Compute the O1-to-O4 proton-hop path with the supplied NNP. Independently optimize both endpoints, execute CI-NEB and its tightening and image-refinement calculations, and determine forward/reverse barriers and reaction energy with consistent endpoint gauges. Evaluate connectivity and numerical changes from the actual calculated records.

## Requirements

- Execute the required scientific calculations locally in the task environment. Preserve the actual commands, inputs, native outputs and reproducible execution records.
- Use the designated SiAlOH1 model and 6 Å neighborhood. Preserve source isotope masses, composition, atom mapping, periodicity and the fixed cell; state energy and force units.
- Independently optimize O1 and O4 endpoints under the same model, fixed cell and physical constraints. Retain raw forces, stopping thresholds, termination, tightening checks and identities; band endpoints must match the optimized endpoints.
- Choose periodic unwrapping, interpolation, images, tangent, springs, climb, constraints/preconditioning and optimizer settings. Preserve actual optimizer-projected residuals; raw atomic forces or perpendicular forces alone cannot replace the optimizer stopping quantity.
- Optimize the initial band, then reoptimize with a tighter force threshold using the same endpoints, model, image count and constraints. Increase images or justify redistribution and reoptimize again. Scientifically equivalent schemes must separate stopping and discretization errors; interpolated plots are not reoptimization.
- Record native execution, independent energy-force derivatives, step-size checks and numerical changes. Report optimizer termination and residual checks as calculated results. Preserve step-limit stops, drift, new extrema, branches and failures; do not hide them with an arbitrary universal tolerance.
- Record framework/proton connectivity, shared-proton geometry and comparison results as calculated data. Use the initial endpoint for forward barriers and the final endpoint for reverse barriers, with consistent reaction-energy direction. SCAN barrier accuracy, global minimum paths, global reaction networks and free energies are outside scope.

- Submit native trajectories, optimization histories, model settings and derivative samples to record the calculations.
- Submit the required results and evidence under `/app/` according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Endpoint structures and the designated neural-network potential. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/public/output-contract.yaml` | Required outputs and submission format. |
