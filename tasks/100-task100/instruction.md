# Task: Identify interlayer modes from a native MoS₂ trajectory

## Background

The public manifest fixes the instance to bilayer MoS₂ (`N=2`, seed `24101`). Identify both interlayer modes—shear (S) and layer breathing (LB)—from a complete native molecular-dynamics trajectory. The specified run uses the full in-plane cell, `p p f` boundaries, REBO-only plus ILP, 300 K zero-target-stress NPT for 250 ps, then fixed-cell NVE for 50 ps. Experimental frequencies or synthetic signals cannot replace candidate trajectory evidence.

## Task

Run the supplied instance and protocol, then determine mode frequencies, uncertainty and reliability from the native trajectory. Provide evidence permitting independent checks of the run and each assignment.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include NumPy, SciPy. Do not install additional packages or fetch dependencies from the network.

If using HPC, follow the `ikkem-slurm` workflow: probe the authorized target, submit, wait for a terminal state, collect native outputs, and validate the scientific result.

Retain actual MPI ranks and candidate-submitted execution records. Include native inputs, outputs, potential checks and stage evidence required by `/app/verification.md`. Apply its frequency, stability, phase, uncertainty, provenance and resource criteria without substituting synthetic data.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Simulation structures, potential files and manifest. |
| `/app/verification.md` | Methods and output specification. |

Inputs: `/app/assets/n2-seed24101/manifest.json` and its bound data, deduplication map and potentials, plus `/app/verification.md`. Submit `/app/final/modes.json`, `/app/final/md_inputs/`, `/app/final/equilibrium.md` and `/app/final/mode_evidence/` under the public contract.
