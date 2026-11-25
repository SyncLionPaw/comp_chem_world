# Investigate molecular-centre-of-mass diffusion and its identifiability within a finite budget

## Background

The supplied system has 2,432 choline chloride/urea atoms, four source models, structures, and MD templates. This is a finite-budget study of molecular center-of-mass (COM) diffusion and identifiability, not a six-temperature production curve or validation of equilibrium diffusion or activation energy.

## Task

Study diffusion at 353 K and 373 K; add 363 K only if pilot evidence supports it. Assess finite-window behavior, temperature trend, and whether activation energy is identifiable. Before the first run, freeze the model, starting-state source, estimator, excluded time, analysis windows, decision rules, and reserved budget. Then use pilot measurements to compare at least two concrete actions, follow the registered adaptive rule, and test its prediction on fresh confirmation runs. Explain what is supported, unresolved, and the next useful measurement.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

If using HPC computing resources, see `/app/AGENTS.md` and use SSH alias `hpc`.

- Use supplied source models only; no new training or DFT. Stay within 100 ps and 200,000 steps and use a timestep ≤0.5 fs. Count setup, equilibration, branches, controls, failed and unknown attempts. Charge failed/unknown runs their full reservation and completed runs by verified executed steps.
- Run at least two distinct 10-ps pilot seeds at both 353 K and 373 K; then at least 10 ps adaptive sampling and two fresh confirmation seeds of at least 10 ps each. Keep the full study within budget. Before the pilots, freeze the selector: if any pilot-only group violates the registered finite-window diagnostic, extend; if no pilot group triggers, use a fresh velocity seed. Preserve per-group measured values and stable/triggered flags. Stable, mixed, or physical-claim outcomes may require independent review after every execution and numerical gate passes; do not infer a preferred scientific result from the review route.
- Follow the host profile and task run budget; preserve actual resource and throughput evidence from the pilot and report unavailable capabilities without substituting historical output.
- Use fully periodic, orthogonal, fixed-volume NVT trajectories and supplied native atom columns. Reconstruct molecular topology, masses and mapping; calculate COM MSD and VACF with consistent units. Fix at least two analysis windows before results and report temperatures, species, estimates, window sensitivity, and statistical units.
- Apply the public finite-window diagnostics: nonpositive fitted D, endpoint log-slope differing from one by >0.2, or adjacent-window D relative spread >0.25. These are registered triggers, not universal physical convergence thresholds. Use actual pilot quantities to show whether the rule applies; freeze the chosen prediction before fresh-seed confirmation. Compare at least two alternatives by their information value; carry out the action prescribed by the preregistered rule. Do not use confirmation data to choose windows.
- Separate finite-window evidence from equilibrium or converged transport. Discuss shared starts, time origins, correlations, model/finite-size effects, and limits of temperature and Arrhenius claims. Yeh–Hummer correction is conditional on viscosity and box data and cannot prove a plateau. Preserve native inputs, logs, trajectories, restarts, scheduler records, and provenance for every run. Ensemble probes, if any, are limited to 200 frames.
- Explain the limits in `decision.json` and `report.md`. This registered diagnostic protocol addresses finite-window identifiability only: claim non-identifiability only when the numerical evidence supports it. Strong claims about equilibrium properties lie outside what this study protocol can establish.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Initial configurations and execution protocols. |
| `/app/output-contract.json` | Output and evidence conventions. |

Work under `/app/`; input and output paths below are relative to that directory.

Submit `plan.json`, per-attempt native files under `execution/`, `run-ledger.json`, `topology.json`, `msd-vacf.npz`, `results.json`, `decision-trace.json`, `decision.json`, and `report.md`. Follow `output-contract.json`, `inputs/automatic-decision-contract-04.md`, and `inputs/candidate-scheduler-contract.json` for required contents and records. Keep every result traceable to native evidence.
