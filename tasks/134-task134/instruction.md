# Task: TNEP Polarizability and Blind Validation on QM7B

## Background

Use the provided source models and configurations to validate molecular polarizabilities in source Table 2 and dipoles and polarizabilities on QM7B.

## Task

Select the applicable models, identify the physical conventions for the different systems, and organize and implement the inference. Do not obtain validation labels externally.

Public materials are in `environment/assets/inputs/` (also available at runtime through `/app/inputs/`): pretrained models and the following configurations.

| system_id | Configuration file | Frames |
|---|---|---|
| alpha_h2o | test-positions-alpha-h2o.xyz | 500 |
| alpha_h2o_dimer | test-positions-alpha-h2o-dimer.xyz | 500 |
| alpha_h5o2plus | test-positions-alpha-h5o2plus.xyz | 500 |
| qm7b_dipole | test-positions-qm7b-dipole.xyz | 1443 |
| qm7b_polarizability | test-positions-qm7b-polarizability.xyz | 1443 |

 Liquid-water polarizability is not included in this task; do not substitute a tested system or reduce the frame count. The tools, precision, batching, and implementation of physical conventions are yours to determine. The task does not provide an engine route or processing recipe.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

### Accuracy and numerical criteria

Compare each specified molecular and QM7B error term with its published value; must meet `|log10(recomputed / published)| <= 0.5`. Keep the nine-component tensors symmetric: pairwise tolerance is `atol=1e-6 bohr³, rtol=1e-6` in double precision and `atol=1e-4, rtol=1e-4` in single precision. Values must be finite. Select and report a reproducible model-inference route; no correction step is prescribed.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/inputs/` | Source material and scientific inputs for this task. |

Write to `/app/final/`: `results.json`, prediction NPZ files for the five systems, and non-empty `build.log` and `run.log`.

- `engine`: `name`, `version`, `build_command`, and `log_sha256` (the checksums of both logs). Set `precision` to `float32` for single precision or `float64` for double precision. If omitted, comparisons assume double precision.
- `predictions`: a mapping from `system_id` to a relative NPZ path.
- Molecular and QM7B polarizability arrays use key `polarizability`, shape `(n_frames, 9)`, row-major order `xx,xy,xz,yx,yy,yz,zx,zy,zz`, and units bohr³. QM7B dipole arrays use key `dipole`, shape `(n_frames, 3)`, and units e·bohr. Store the model physical quantity for each configuration. Apply the supplied source’s convention when normalizing quantities for comparison with its reported error metrics.
- `conventions` must contain `molecular_polarizability`, `offdiag`, and `qm7b`, respectively explaining your physical-convention judgments and implementation. Explain the physical basis for each convention judgment. For `qm7b`, declare the selected convention for the stored physical quantity using `per-cell`, `per-molecule`, or `per-atom`, and explain how benchmark error metrics are normalized; storage and metric normalization may use different conventions. Use the supplied source’s metric convention when comparing QM7B errors with its reported values. The vocabulary does not determine the correct storage convention.
