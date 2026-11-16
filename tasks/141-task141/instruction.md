# Task: full-Hessian against quasi-Newton saddle searches

## Background

Compare two transition-state search arms on the frozen NewtonNet potential for reaction IDs `001` (10 atoms) and `079` (11 atoms): analytic Hessian at every optimizer step versus native quasi-Newton curvature. Both arms start from the supplied initial guesses and use the frozen protocol.

## Task

Run the four paired trials, determine which runs satisfy the protocol’s first-order-saddle success criterion, and compare convergence and computational cost between the two methods. Interpret only these observed systems and this single repeat per arm.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, JAX, matplotlib, NetworkX, NumPy, pandas, pillow, PyTorch, PyYAML, scikit-learn, SciPy, sympy. Do not install additional packages or fetch dependencies from the network.

- Follow `/app/assets/protocol.json` exactly, including the 24-step limit per trial. Keep all four trials in the denominator.
- Scientific success requires optimizer convergence, independently replayed maximum per-atom Euclidean force norm ≤ 0.04 eV/angstrom, and exactly one projected internal eigenvalue below −1/23.06055 eV/angstrom².
- Record the selected curvature at each accepted optimizer step so the two search strategies can be independently audited.
- Preserve the actual native execution evidence and settings for all four trials. Do not synthesize or reconstruct run evidence.
- Stay within 24 optimizer steps per trial, 120 Hessian calls and 500 energy/force evaluations overall.
- Submit a concise `report.md` explaining the observed paired success outcomes, convergence/cost tradeoffs and limits of inference. Explain the scientific method and parameter choices there; do not make broad claims from two IDs and one repeat.

Use the raw run records to report success outcomes, per-arm steps, model-call totals, active time and paired trial results. Explain the observed convergence and cost in `report.md`; base conclusions on the four recorded trials and retain their native evidence.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Initial geometries, checkpoint, model specification and protocol. |
| `/app/assets/output-contract.json` | Native run tree and submission format. |

Inputs are under `/app/assets`: initial guesses, checkpoint, model specification, frozen `protocol.json` and this `output-contract.json`. Write `/app/final/report.md` and the complete native run tree described by `runner_output.required_tree` in the contract. The native tree must include the envelope, protocol snapshot, four trial records, evaluation event streams, native trajectories and optimizer logs. The report must accurately interpret those raw records.
