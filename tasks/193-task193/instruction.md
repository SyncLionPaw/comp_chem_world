# Cross-Composition Potential-Energy Error and Reference-Offset Diagnosis

## Background

Compare NNP and ReaxFF energy/force errors across compositions and examine how reference states and relative-energy gauges affect their interpretation.

The inputs include per-configuration energy and force labels, group definitions, relative-energy anchors, method reference states and diagnostic formulas.

## Task

Compute general NNP and ReaxFF errors on the OOD test set from author per-configuration energies/forces. Determine how relative energies can hide composition-dependent reference offsets. Do not run new MD.

## Requirements

Report incomplete input conditions if declared materials are missing; do not invent data. Retain theory level, normalization, and units for all energies/forces.

- Choose comparable formation-reaction and same-composition relative-energy metrics, making denominators explicit.
- Check each method's reference states, force-component aggregation, and group weights.
- Distinguish systematic offsets from configuration-dependent errors; low RMSE does not imply generally unbiased sampling.

Choose formation or relative energy, force components or vector norms, and equal-group, frame or atom aggregation as scientific conventions.

Retain all NNP and REAX group and per-frame results; the DFT zero-error baseline may be included or omitted as a whole. Explain the force RMSE convention and group aggregation and retain sufficient precision; counts must be integers, RMSE nonnegative, and coarse rounding or scientific-notation exponents must not inflate allowed error. For every group and method calculate signed formation and relative-energy means, centered and full MSE, removed anchor offset, RMSE change and force error. Evaluate both energy metrics, all three aggregation rules, weights 0, 0.25, 0.5, 0.75 and 1, and a chosen weight in [0,1]; report denominators, group weights, scores and tied minimizers. RMSE alone cannot establish the sign of an offset.

Use formation and relative errors corrected for each method’s reference state, and distinguish the removed gauge from the raw unreferenced energy difference. GIS differs in topology, composition and temperature; limit comparisons to the evaluated systems and do not identify temperature as the unique cause or certify unseen sampling safety. Explain methods and sources, and keep the scientific choices fixed when recomputing original and controlled perturbed data.

Network access is disabled.

- Submit the required results and evidence under `/app/` according to the listed output convention. Use `/app/analysis.py` as the analysis entry point; `/app/code` may contain optional helpers.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Energy and force labels, groups and reference data. |
| `/app/` | Submitted results and required execution evidence. |
| `/app/public/output-contract.yaml` | Required outputs and submission format. |
