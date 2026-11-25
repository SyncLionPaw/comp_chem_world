# Investigate conductivity estimates with consistent temperature, units, and sampling evidence

## Background

The supplied 2,432-atom choline chloride/urea system, four source models, and templates support a bounded study at nominal 363 K. The supplied start/restart input uses 363.15 K. Freeze one actual target, either 363.0 or 363.15 K, in the existing `plan.json` `protocol.ensemble` description; keep that choice consistent in every ledger row, native thermostat input, and `results.json` `T_K`. Use the actual frozen temperature in the conductivity conversion. The task examines short-time neighbor-shell signals, collective-current correlations, Green–Kubo integration, and gamma; it does not establish equilibrium dc conductivity.

## Task

Plan and run a finite-budget study of (1) the shell signal, (2) whether the GK integral has a supported plateau, and (3) what gamma means for the sampled correlations. Freeze model, starting state, statistical unit, excluded time, observables, windows, decision rules, seeds, and reserved budget before the first run. Use pilot evidence for adaptive sampling, compare paired control branches, and test a prediction on a fresh seed. Separate finite-window observations from equilibrium transport or association claims.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

If using HPC computing resources, see `/app/AGENTS.md` and use SSH alias `hpc`.

- Use supplied source models only; no new training or DFT. Limit the study to 50 ps and 100,000 steps, with a timestep ≤0.5 fs. Count preparation, equilibration, controls, branches, failed and unknown attempts; charge failed/unknown runs their full reservation and completed runs by verified steps.
- At the single frozen actual temperature (363.0 or 363.15 K; both are nominally 363 K), run two distinct pilot seeds of at least 5 ps including preparation; from a common checkpoint run two control branches of at least 3 ps with different thermostat or control settings; then run at least 5 ps adaptive sampling and one fresh confirmation seed of at least 10 ps. Record positive integer seeds for stochastic initialization or thermostats. A null seed is permitted only for a deterministic NVT intervention that reads a completed pilot restart whose hash matches `parent_checkpoint_sha256`, with no random velocity initialization or stochastic thermostat in the hashed input. Pilot and confirmation seeds must be positive integers and match a seed in their hashed native input; confirmation must remain fresh.
- Follow the host profile and task run budget; preserve actual resource, software-stack and throughput evidence from the pilot. Use unique attempt roots and explicit stage work directories. If configuration is unavailable, report it rather than substituting historical output.
- Keep each remote file ≤512 MiB and the collection ≤4 GiB. Retain native trajectories with positions, velocities, and boxes; summaries cannot replace them. Reconstruct topology from periodic geometry and composition. Build ionic current from molecular charges and COM velocities (urea is neutral); state charges and normalization.
- For each time origin, define its neighbor shell at that origin and keep it fixed across lag; also compare refreshed shells. Report shell counts, self/distinct terms, total-current consistency, finite-window GK integrals across at least two windows, and ordered species-pair reciprocal counts using population sizes. Exclude same-particle pairs where appropriate.
- Explain shared starts, correlated time origins, and uncertainty; do not treat atoms, origins, or resamples as independent trajectories. Interpret gamma only for the defined sampled correlation: a peak or truncated integral does not establish equilibrium transport or ion-pair fraction. State uncertainty, limits, and the next informative measurement.
- Ensemble frame probes, if any, are limited to 200 frames.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Simulation inputs and sampling references. |
| `/app/output-contract.json` | Output and evidence conventions. |

Work under `/app/`; input and output paths below are relative to that directory.

Submit `plan.json`, native per-attempt files under `execution/`, `run-ledger.json`, `topology.json`, `correlations.npz`, `results.json`, `decision-trace.json`, `decision.json`, and `report.md`. Follow `output-contract.json` for contents, units, and execution provenance. Keep reported results traceable to native evidence.
