# Task: Choose a Nonlocal Water Descriptor

## Background

The package contains 64 time-uniform frames from one biased OAMe–G4 trajectory and coordination data for those frames. The coordinates are sparse samples, not equilibrium observations. `environment/assets/geometry-method.md` defines the coordinate frame, PBC, atom IDs, switching functions, normalization and units; `training-design.json` summarizes the reported B/U training design.

## Task

Choose and justify a low-dimensional candidate set from ligand-adjacent points L1–L4 and cavity-axis points V1–V8. Compare it with coordinate-defined z/r-matched samples, quantify feature variation and redundancy, and state what independent B/U evidence is still needed before training or approving the descriptor as a collective variable.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy. Do not install additional packages or fetch dependencies from the network.

Recompute the coordinate-defined features using the public geometry method. Include closed-form and lattice-translation checks, and identify a bound-like frame pair matched within 0.02 nm in both z and radius whose V1–V8 coordination differs. Feature subsets are your decision; support them with the observed feature families and alternatives.

Describe how the reported design (five 4 ns B trajectories and five 4 ns U trajectories, descriptor stride 0.25 ps) differs from this single biased excerpt. Do not infer equilibrium frequencies, causality, CV optimality or generalization from these frames. State the independent, held-out evidence required to resolve those limits.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/environment/assets/` | Public inputs and method resources |
| `/app/environment/assets/output-contract.json` | Submission format, evidence conventions and applicable tolerances |

**Deliverables**

| Path | Contents |
| --- | --- |
| `/app/feature-audit.csv` | Feature audit |
| `/app/geometry-check.json` | Geometry checks |
| `/app/decision.json` | Research decision |
| `/app/research-rationale.md` | Scientific rationale |
