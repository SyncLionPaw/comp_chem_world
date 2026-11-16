# Fine-tuning nonadiabatic couplings without losing physical symmetries

## Background

The supplied PaiNN baseline predicts energies, forces and nonadiabatic couplings (NACs). Test whether a short NAC-head fine-tune improves a selected error stratum without changing energy/force outputs or violating rotation, permutation and analytic origin-term behavior. This experiment does not establish long-time dynamics reliability.

## Task

Diagnose one low-gap or geometry-out-of-distribution stratum from public training/validation data, preregister a directional hypothesis and risk, perform one fixed-template fine-tune, then decide whether to retain the baseline or adopt the tuned model for that stratum.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, h5py, matplotlib, NetworkX, NumPy, pillow, PyTorch, PyYAML, SciPy, sympy. Do not install additional packages or fetch dependencies from the network.

- Use 4,499 training and 500 validation structures. Report baseline NAC MAE for the full validation set and selected stratum in Bohr⁻¹, using whole-tensor alignment over the four physical global gauges. Define low gap by the training p10 of the minimum absolute three-state gap; define geometry OOD by the 50 most distant validation structures in the fixed CC/CH/HH 15-distance descriptor, resolving ties stably.
- Before training, register the hypothesis, expected error direction, scope, risk, stopping condition, public evidence and resource request through the supplied execution interface. Use the supplied CPU target and fixed tensor-only baseline; train only the NAC head once with the reviewed template, `phase_aligned_nac_mae`, four-global-gauge loss and seed 20261007. Select checkpoints using validation data and verify that frozen tensors remain unchanged. Do not use held-out labels for any choice.
- Submit and collect the experiment through `ccb-capture` (`--help` describes the interface), preserving native outputs and exit status. Record actual software and resources. Allocation through final decision is capped at 1,200 s, including limits of 300 s training, 600 s collection, 120 s assessment and 120 s feedback-to-decision; queue time is excluded. Do not submit remote jobs.
- After fixing the outputs, obtain one aggregate for the selected stratum from all 1,000 held-out geometries; each calibrated stratum must contain at least 100 structures. Report baseline-minus-tuned absolute NAC error, its mean and a 95% paired interval from 10,000 geometry resamples with seed 20261007. Treat this interval descriptively for correlated frames. Held-out labels and individual residuals are not deliverables; membership may be inferred from public geometries.
- Assess the transformation results and analytic origin-term residual using the supplied scientific definitions. NAC and smooth-NAC outputs are origin dependent; their raw translated smooth-NAC change is unavailable and must not be quantified. Do not extend this conclusion to energies or forces. Adopt only when the preregistered scope is `COM_centered_only`, the interval lower bound is positive and every guard passes, with validity restricted to COM-centered coordinates; otherwise retain the baseline. Do not generalize to other strata or long-time dynamics.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Training and held-out data, baseline model and output contract. |

Inputs are `/app/inputs/trainval_shifted.db`, `heldout_geometry.db`, `public_asset_manifest.json` and `painn_baseline_state_dict.pt`. Coordinates are COM-centered; energies use the training-only S0 offset −77.97151981751722 Ha. Forces and couplings retain their stored values; `smooth_NAC = NAC*(E_i-E_j)` with C01/C02/C12 axes.

Use the existing `/app/inputs/output-contract.md` for the execution interface, transformation definitions and result formats. Under `/app/outputs/`, submit `hypothesis.json`, generated `strategy_request.json`, `training_report.json`, `model_state_dict.pt` and `final_decision.json`; retain collected execution evidence in `/app/bench25-artifacts/`.
