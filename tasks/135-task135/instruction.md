# Task: Rotational Equivariance Check for the TNEP Tensor Model

## Background

Starting from the 200 provided water-monomer configurations and source models, independently design and perform rotational-equivariance experiments for rank-1 dipoles and rank-2 polarizabilities.

## Task

Determine how the tensors should transform, how to construct rotations, how to choose the reference center, and how to analyze numerical errors. The task does not provide tensor-transformation formulas, a rotation-generation algorithm, or example seeds.

Public materials are in `environment/assets/inputs/` (also available at runtime through `/app/inputs/`); the configuration file is `test-positions-h2o-200.xyz`. The model must actually be run on both the original and rotated geometries. Do not generate rotated predictions by transforming only unrotated results, and do not obtain external labels.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

### Coordinate and data-encoding conventions

The following conventions remove ambiguity in matrix direction and file format; they do not prescribe your research plan:

- `R` uses the column-vector convention; in the coordinate file it is represented as `x' = R(x-c)+c`. The center may be declared as `origin` or `com`; the latter uses O=15.999 and H=1.008.
- All 200 `R` matrices must belong to SO(3), with orthogonality and determinant errors each no greater than `1e-10`; the rotation angle for each frame must be at least `0.2 rad`. Rotated coordinates must agree with the declared transformation (maximum deviation `2e-5 Å`). You choose the rotation design, reproducible seed, and distribution.
- Dipole units are e·bohr; polarizability units are bohr³. Nine tensor components use row-major order.

### Numerical accuracy and reproducibility

For double precision, the maximum dipole absolute residual must be at most `1e-6 e·bohr` and maximum polarizability relative residual at most `1e-6` in double precision; for single precision, both must be at most `1e-4`. All data must be finite. Check the four reported summaries against the residuals from the submitted arrays using `rtol=1e-3` and `atol=1e-12`. The RMSE of unrotated predictions must meet the published source’s benchmark-anchor window (absolute log10 ratio no greater than `0.75`).

Run the source model on both original and rotated geometries. Record the actual engine, precision, inputs, predictions and hashes as specified below so the analysis can be reproduced.

Keep native execution records. The numerical checks compare submitted arrays and records without rerunning the inference engine.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/inputs/` | Source material and scientific inputs for this task. |

Submit the following under `/app/final/`:

1. `equivariance.json`, containing:
   - `engine`: `name`, `version`, `precision` (`float32`/`single` or `float64`/`double`), and `log_sha256`.
   - `rotation_protocol`: integer `seed`, non-empty `distribution`, `n_rotations=200`, and `center`.
   - `frames`: numbered in input order from 0–199; each frame provides `frame`, `R` (3×3), `mu_unrotated`/`mu_rotated` (3), and `alpha_unrotated`/`alpha_rotated` (9).
   - `residual_summary`: `max_abs_mu`, `rms_mu`, `max_rel_alpha`, and `rms_alpha`. Let `expected` be the reference tensor obtained from the transformation appropriate to its rank, and `actual` the prediction on the rotated geometry. Use elementwise residuals `abs(expected-actual)` for dipoles and `abs(expected-actual)/(abs(expected)+1e-12)` for polarizabilities. `max_abs_mu`/`rms_mu` and `max_rel_alpha`/`rms_alpha` are the maximum and root-mean-square over all frames and components of their respective residuals. Derive the reference transformation for each tensor rank yourself.
2. `rotated-positions.xyz`: the rotated geometries.
3. `inference-unrotated.xyz` and `inference-rotated.xyz`: 200 frames each, with geometries bound respectively to the original and rotated configurations; comments provide `dipole` and `polarizability` arrays consistent with the JSON. Values may be quoted JSON numeric lists or quoted whitespace-separated numeric tokens. A bracketed JSON numeric list may also be unquoted; unquoted whitespace-separated values are ambiguous and are not accepted.
4. `inference.log`: non-empty and containing `run=unrotated`, `run=rotated`, and the four `key=SHA-256` entries `input_sha256`, `rotated_xyz_sha256`, `inference_unrotated_sha256`, and `inference_rotated_sha256`. `engine.log_sha256` is the hash of this log.
