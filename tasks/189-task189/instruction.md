# Multicomponent transferability

## Background

Assessing transferability of a fixed interatomic potential requires actual predictions and controlled comparisons on distinct calibration and challenge structures.

The inputs include the full sixteen-species NEP4/ZBL model, 43 labeled calibration frames and 91 unlabeled challenge geometries. `request.json` specifies the scientific scope, units and controls.

## Task

Run the full UNEP-v1 model on the 43 labeled calibration frames and 91 unlabeled challenge frames. Diagnose forces and same-stoichiometry relative energies, and produce calibration error analysis and predictions for all challenge structures without inventing challenge labels.

## Requirements

- Execute the required scientific calculations locally in the task environment. Preserve the actual commands, inputs, native outputs and reproducible execution records.
- Apply the complete supplied sixteen-species NEP4/ZBL potential to all 43 calibration and 91 challenge frames. Preserve every frame's atom identities, order, geometry and split; do not substitute labels for computed predictions or obtain withheld challenge labels.
- Calculate calibration force RMSE by the supplied strata and relative-energy errors only between frames with identical elemental counts. Retain non-comparable singleton groups without treating their zero differences as measured errors. The challenge set has no supplied labels and cannot support a measured challenge error.
- Keep all scientific settings, units, grouping and output conventions in `request.json`. Select a compatible inference implementation and preserve inputs, reproducible code, native energies/forces, logs and failed or stopped attempts. No reference answer is supplied.

- Submit the required results and evidence under `/app/results/` according to the listed output convention.

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Potential model, calibration data and challenge structures. |
| `/app/results/` | Submitted results and required execution evidence. |
| `/app/assets/output-contract.json` | Required outputs and submission format. |
