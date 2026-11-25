# Task: Short-MD Numerical Check and Continue/Stop Decision

## Background

This requires real remote molecular-dynamics execution. The package supplies the G4 B/U systems, topology, template, two safe NVT MDPs capped at 50 ps, and input provenance. Plans, copied/reference trajectories and local analysis are not evidence of a run.

## Task

On the available single-node CPU environment, run B and U at 1 fs and 2 fs (four conditions). Pair 1 fs/2 fs initial velocities within each state, using identical actual velocities or a shared explicit seed; B and U may differ. Compare numerical stability and water geometry, then decide whether to continue or stop.

## Requirements

If using HPC, see `/app/AGENTS.md`: use SSH alias `hpc`, keep remote work under a unique `~/submit-jobs/<task>-<utc>-<rand>/` directory, and validate the scientific result.

Within each paired comparison, the starting TPR coordinates and velocities must match. A shared seed is acceptable only when the actual starting vectors agree.

Each run is at most 50 ps and the total at most 200 ps; use no more than 50,000 steps at 1 fs or 25,000 at 2 fs, 8 CPUs, one node, 8 GiB RAM and a 30-minute target. The cap is not a minimum: a shorter safe probe is valid. Preserve the original 300 K NVT, force field/topology, water/ions/box, PME, all-bonds LINCS constraints and thermostat. Record actual engine/settings, resources, native logs, energy, checkpoint, coordinates and failures. Compare temperature, potential-energy terms, LINCS/NaN/box behavior, warnings and a small set of water geometries.

Cross-check configured duration against actual native final time/step and report sampling coverage separately. If the run cannot complete within budget, stop and document actual progress; do not extend limits. The supplied original NVT MDP is provenance only. Do not use PLUMED/OPES, learned weights or extra production runs. A 50 ps probe cannot establish equilibrium, binding free energy, kinetics, CV generalization or training sufficiency; no universal temperature or energy-drift pass threshold is prescribed.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Public inputs and method resources |
| `/app/environment/assets/output-contract.json` | Submission format, evidence conventions and applicable tolerances |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/submission/input-audit.json` | Input audit |
| `/app/submission/remote-provenance.json` | Remote execution provenance |
| `/app/submission/diagnostics.csv` | Run diagnostics |
| `/app/submission/numerical-comparison.json` | Numerical comparison |
| `/app/submission/continuation-decision.json` | Continuation decision |
| `/app/submission/scientific-rationale.md` | Scientific rationale |

Also retain the four native run directories under `/app/submission/`. Explain omissions caused by an actual early stop.
