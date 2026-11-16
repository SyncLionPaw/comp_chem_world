# Propagate the supplied exciton network

## Background

`inputs/benchmark.json` defines a three-state kinetic network (S1, T1, T2), its initial population, rate constants, and observation times. S0 is the population remainder.

## Task

Build the column-population generator (dP/dt=KP) from the supplied rates, with rows/columns ordered S1,T1,T2: K=[[-(isc1+isc2+f+nrS),risc1,risc2],[isc1,-(risc1+ic12+ph1+nr1),ic21],[isc2,ic12,-(risc2+ic21+ph2+nr2)]]. Propagate the initial population stably to each requested time; S0 is the conserved remainder. Calculate infinite-time channel probabilities from integrated state occupancy: fluorescence=f∫S1, phosphorescence_T1=ph1∫T1, phosphorescence_T2=ph2∫T2, and nonradiative=nrS∫S1+nr1∫T1+nr2∫T2. Do not hard-code the supplied trajectory.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include h5py, NumPy, PySCF, SciPy. Do not install additional packages or fetch dependencies from the network.

Report `result.json` with `times_s` in input order, an N×4 `populations` array ordered S1, T1, T2, S0, and exactly five finite dimensionless yields: `fluorescence`, `phosphorescence_T1`, `phosphorescence_T2`, `nonradiative`, `total_PLQY`. Compute S0 by conservation; each row must sum to one. `total_PLQY` is the sum of the three emissive yields; report nonradiative yield separately. The trajectory and all yields must agree with an independent calculation within an absolute difference of 2e−7 + 2e−7 × the absolute reference value.

Write `final/solver.py`, `final/result.json`, and `final/convergence.json`. Run two genuine convergence calculations and record them as `runs`, exactly two entries, each with `method` and its real Python `command` (argv list or command string). The first runs `solver.py`; the second runs `solver.py` or `convergence_solver.py`. They must use different methods, or the same method with positive `rtol` and `atol` on both runs, neither tolerance loosened and at least one strictly tightened. Do not repeat both the baseline source and command. The two trajectories must differ by at most 2e−7 in absolute population. Check probability conservation, the zero-ISC analytic limit, and invariance of populations and yields when all rates are multiplied by 10 and times divided by 10. Distinguish the finite-time excited-state tail from infinite-time yields.

Replay commands run from the application root, read `inputs/benchmark.json`, and may write `result.json` in the working directory or beside the script in `final/`; if both are written, their contents must match. For shell-free command strings or argv, use Python and application paths such as `/app/final/solver.py`. Runtime: 2 CPUs, 2 GiB, 15 minutes; no network access or credentials.

`convergence.json` contains nonempty `solver` and `solver_version` strings and `runs`. Each run has a nonempty `method` and its executed `command`; when the method is the same, each run also records its positive `rtol` and `atol`.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/benchmark.json` | Benchmark parameters and calculation conditions. |

Input: `/app/inputs/benchmark.json`. Required outputs: `/app/final/solver.py`, `/app/final/result.json`, `/app/final/convergence.json`. Optional second source: `/app/final/convergence_solver.py` when used by the second run.
