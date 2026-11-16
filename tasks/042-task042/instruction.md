# Audit model errors on a small public DFT training and holdout dataset

## Background

This is a small, visible DFT sample for a 304-atom deep eutectic solvent. The manifest identifies 64 training frames (32 `init`, 32 `extr`) and 16 holdout frames. Holdout labels and four source-model predictions are visible, so this exercise cannot establish blind generalization or production accuracy.

## Task

Train a new DeePMD-kit TensorFlow model on the 64 training frames, predict the 16 holdout frames, compare it with the four supplied models and a training-mean/zero-force baseline, and recommend a route from the evidence.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include h5py, keras, NetworkX, NumPy, pandas, PyTorch, PyYAML, SciPy, sympy, TensorFlow. Do not install additional packages or fetch dependencies from the network.

- Use manifest IDs and order exactly; do not train on holdout data, copy labels or source predictions, or relabel a source model as new.
- Train one final model within a total budget of 20 optimizer steps; additional training runs for hyperparameter selection are outside that budget. Include `training-trace/train.json`, `lcurve.out`, replayable `model.ckpt*`, seed, software version, and native logs. The training system must be `/app/inputs/short-training/train`, with `stop_batch` from 1 to 20. Finish the deliverables inside the run; do not spend the budget on extra experiments.
- Submit a replayable DeePMD TensorFlow graph at `model/graph.pb` and its `type.raw` and `type_map.raw`; other formats are unsupported. The saved graph and checkpoint must reproduce the submitted predictions.
- In `predictions.npz`, preserve holdout order and provide finite energies `(16,)` in eV and forces `(16,304,3)` in eV/Å. In `metrics.json`, use `output-contract.json` for fields and definitions; compare raw and centered energy errors, bias, and Cartesian force-component RMSE for the candidate, all supplied models, and baseline.
- Report the best source for centered energy and force error, `chosen_route` (`candidate`, source ID, or `none`), and an evidence-based reason. Use the `1e-12` tie tolerance and lowest source index on ties. This is a relative comparison on a visible, small sample and cannot establish production accuracy.
- Explain bias versus centered error, rankings, force error, training limits, visible holdout reuse, and the recommendation in `report.md`. Report failed or unstable runs honestly.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Training samples, system definitions and author predictions. |
| `/app/output-contract.json` | Output and evidence conventions. |

Work under `/app/`; input and output paths below are relative to that directory.

Read `inputs/short-training/`, `inputs/sample-manifest.json`, `inputs/system-spec-304.json`, and `inputs/author-predictions/`. Submit `model/`, `predictions.npz`, `metrics.json`, `report.md`, and the required replayable `training-trace/`. See `output-contract.json` for exact output details.
