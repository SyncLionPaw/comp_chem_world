# Task: Assess Water-CV Validation

## Background

The package provides one complete archived G4 scalar trace and its public provenance, plus 64 legacy descriptor rows, the exported Deep-LDA weights and method. The three networks are evaluated on one biased record; they are not independent simulations.

## Task

Decide whether the water-aware collective variable can be accepted, deferred pending validation, or rejected. Recompute the three models' outputs and descriptor gradients, compare them with every native scalar column, and design the smallest held-out validation that would address generalization.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Use the public model graph and weights. Compare all three model outputs against `node0`, `node1`, `node2`, `sw`, `swb` and `swc` on all 64 descriptor frames using the specified affine fits and residuals; do not infer model/native identity from filenames or correlation. Report all d(sw)/d(d1…d12) summaries using the specified signed-gradient and absolute-quantile conventions. Join descriptor times only to their exact or unique nearest native time within 0.01 ps; do not interpolate.

Report the trace provenance, duplicate-column audit policy and limits: duplicate columns are absent from the converted NPZ and cannot be re-audited there. Describe run-level or contiguous-block holdouts that prevent leakage between adjacent frames. The archived record is biased and cannot establish independent B/U generalization; keep unsupported mappings and claims unresolved.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Public inputs and method resources |
| `/app/environment/assets/output-contract.json` | Submission format, evidence conventions and applicable tolerances |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/cv-audit.csv` | Collective-variable audit |
| `/app/validation-plan.json` | Validation design |
| `/app/decision.json` | Research decision |
| `/app/rationale.md` | Scientific rationale |
| `/app/model-output-audit.csv` | Model output checks |
| `/app/model-gradient-audit.csv` | Model gradient checks |
