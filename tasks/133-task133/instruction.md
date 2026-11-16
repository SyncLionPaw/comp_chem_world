# Task: Blind Validation of the TNEP Dipole Model (Source Table 1)

## Background

Use the provided source models to predict dipoles for the four water systems and report the physical conventions used in source Table 1.

## Task

Determine the mapping between models and systems, the reference points, and the normalization treatment, then design and implement the inference workflow. The task provides neither operating steps nor preselected scientific conventions.

Public materials are in `environment/assets/inputs/`: pretrained models and the following validation sets, which contain only coordinates, elements, and lattice data. The same layout is also available at runtime through `/app/inputs/`.

| system_id | Configuration file | Atoms per frame |
|---|---|---|
| h2o | test-positions-h2o.xyz | 3 |
| h2o_dimer | test-positions-h2o-dimer.xyz | 6 |
| h5o2plus | test-positions-h5o2plus.xyz | 7 |
| liquid_water | test-positions-liquid-water.xyz | 96 |

There are 500 frames per system.  Labels are not provided; do not obtain validation-set labels externally or construct predictions from them. Choose and record your tools, execution method, and precision. Predictions must correspond to the configurations in this package.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

### Accuracy and evidence

Use the published RMSE as the accuracy reference for each system; must meet `|log10(RMSE / published_RMSE)| <= 0.5`. Values must be finite, and array shapes, conventions, and hashes must be consistent. Generate predictions by running the selected model on the packaged configurations.

The engine and implementation route are your choice. Record the actual tool and version, build process, and inference run in the files specified below.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/inputs/` | Source material and scientific inputs for this task. |

Write to `/app/final/`:

- `results.json`, containing `engine`, `conventions`, and `predictions`.
- One NPZ per system, with key `dipole`, shape `(500, 3)`, units e·bohr, and unchanged frame order. The physical reference point and normalization must follow the supplied source’s Table 1 convention for that system.
- Non-empty `build.log` and `run.log`, matching the hashes in `engine.log_sha256`.

`engine` provides `name`, `version`, `build_command`, and the checksums of both log files. `predictions` maps each `system_id` to a relative file path within the submission.

`conventions` must state your judgments. To avoid ambiguity in free-text parsing, use the following interface vocabulary; the task does not choose for you:

- `h5o2plus`: `absolute-origin` or `relative-to-COM`.
- `liquid_water`: `per-cell`, `per-molecule`, or `per-atom`.

Use only the selected token in each `conventions` field. Put the source-based explanation in a separate descriptive field, outside `conventions`.
