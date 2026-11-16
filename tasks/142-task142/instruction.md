# Task: robustness of saddle searches to controlled initial-guess perturbations

## Background

Use the two supplied transition-state proxy geometries (IDs `001` and `162`) on the frozen NewtonNet potential. The source workflow's original starting guesses are unavailable, so conclusions apply to these two geometries and the specified perturbation design.

## Task

Run the ten frozen full-Hessian saddle searches and assess how often the searches meet the first-order-saddle success criterion. Explain convergence and computational cost, and interpret final energy and heavy-atom geometry changes relative to each ID's baseline.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, JAX, matplotlib, NetworkX, NumPy, pandas, pillow, PyTorch, PyYAML, scikit-learn, SciPy, sympy. Do not install additional packages or fetch dependencies from the network.

- Follow `/app/assets/protocol.json` exactly: one baseline per ID and RMS perturbations 0.05 and 0.12 angstrom at seeds 17 and 31, for ten trials. Use the specified PCG64 generator, rigid-motion projection, and scaling.
- Use the frozen Sella 2.5.0 exact-Hessian callback protocol, with at most 16 accepted optimizer steps per trial.
- Scientific success requires optimizer convergence, independently replayed maximum per-atom Euclidean force norm <= 0.04 eV/angstrom, and exactly one projected internal eigenvalue below -1/23.06055 eV/angstrom^2.
- Preserve actual raw evidence for all trials: frozen start geometries and manifest, event sidecars, event records, native trajectories, optimizer logs, protocol snapshot and envelope. Do not synthesize or reconstruct run evidence.
- Stay within the frozen budget of 180 Hessian calls, 640 energy/force evaluations, and 2700 seconds.
- Write `failure_analysis.md` with the observed ten-trial outcomes, convergence and cost, and baseline-relative energy and heavy-atom geometry responses. Keep conclusions within the two proxy geometries and fixed amplitudes/seeds. Energy and RMSD do not certify transition-state identity.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Initial geometries, checkpoint, model specification and protocol. |
| `/app/assets/output-contract.json` | Native run tree and submission format. |

Write `failure_analysis.md` and the complete `runner_output` tree specified by `/app/assets/output-contract.json` to `/app/final`. Derive the reported trial outcomes and numeric diagnostics from the complete raw `runner_output` record; explain the results in `failure_analysis.md` and preserve all native evidence.
